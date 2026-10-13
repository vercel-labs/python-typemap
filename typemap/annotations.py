"""Decompile __annotate__ bytecode back into AST expression nodes.

WARNING: Higher slop percentage here than I normally aim for.

Python 3.14/3.15 (PEP 649) generates __annotate__ functions for
functions and classes that construct annotation dicts from bytecode,
and evaluate_* functions for type alias values, TypeVar bounds, etc.
This module runs the bytecode on a virtual stack of ast.expr nodes to
reconstruct the source expressions.

Two dict-building patterns exist:

  Function annotations:
    LOAD_CONST 'key1'  <expr1>  ...  BUILD_MAP N  RETURN_VALUE

  Class annotations:
    BUILD_MAP 0  <expr> COPY 2 LOAD_CONST 'key' STORE_SUBSCR ...

Conditional jumps (from if-expressions, ``and``, ``or``, and ``not``) are
handled by running both branches up to where they meet and merging their
stacks into if-expressions (see _fork); _simplify then recovers boolean
operators.  For an if-expression in tail position, the compiler duplicates
the rest of the code into both branches, which then never meet.  Source
positions distinguish the duplicated structure, which is factored out of the
if-expression, from independent structure (see _merge_values).

"""

from __future__ import annotations

import ast
import collections.abc
import copy
import dataclasses
import dis
import inspect
import math
import types
from typing import Any, Callable

__all__ = (
    "AnnotateInfo",
    "BindingEnvironment",
    "BindingNamespace",
    "DecompileError",
    "get_annotate_ast",
    "get_annotations_ast",
)


# BINARY_OP arg constants (from dis._nb_ops)
_NB_OR = 7  # |
_NB_SUBSCR = 26  # []

# CALL_INTRINSIC_1 arg constants
_INTRINSIC_LIST_TO_TUPLE = 6

# SET_FUNCTION_ATTRIBUTE arg constants
_FUNC_DEFAULTS = 1
_FUNC_KWDEFAULTS = 2

_CMP_OPS: dict[str, type[ast.cmpop]] = {
    "<": ast.Lt,
    "<=": ast.LtE,
    "==": ast.Eq,
    "!=": ast.NotEq,
    ">": ast.Gt,
    ">=": ast.GtE,
}

# Stack sentinels (compared by identity)
_CLASSDICT: ast.expr = ast.Name(id="__classdict__")
_CONDITIONAL: ast.expr = ast.Name(id="__conditional_annotations__")

# Result keys for the bare value returned by an evaluate_* function, and
# for the element of a comprehension
_VALUE_KEY = "<value>"
_ELT_KEY = "<elt>"
# A comprehension element that is skipped (by a filter)
_SKIP: ast.expr = ast.Name(id="<skip>")


class DecompileError(Exception):
    """Raised when we encounter bytecode we can't handle."""


def _const_to_ast(value: Any) -> ast.expr:
    """Convert a Python constant to an AST node.

    Tuples become ast.Tuple of their elements (recursively), and
    negative numbers (which the compiler folds) become negations.
    Everything else becomes ast.Constant.
    """
    if isinstance(value, tuple):
        return ast.Tuple(elts=[_const_to_ast(v) for v in value], ctx=ast.Load())
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.copysign(1, value) < 0
    ):
        return ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=-value))
    return ast.Constant(value=value)


def _set_pos(node: ast.expr, instr: dis.Instruction) -> ast.expr:
    """Copy source positions from a bytecode instruction onto an AST node."""
    pos = instr.positions
    if pos and pos.lineno is not None and pos.col_offset is not None:
        node.lineno = pos.lineno
        node.col_offset = pos.col_offset
        node.end_lineno = pos.end_lineno
        node.end_col_offset = pos.end_col_offset
    return node


def _get_span(
    node: ast.expr,
) -> tuple[int | None, int | None, int | None, int | None]:
    """Extract the source span from an AST node."""
    return (
        getattr(node, "lineno", None),
        getattr(node, "col_offset", None),
        getattr(node, "end_lineno", None),
        getattr(node, "end_col_offset", None),
    )


def _same_span(a: ast.expr, b: ast.expr) -> bool:
    """Check whether two AST nodes have the same source span.

    Returns True if either node lacks position info (conservative:
    assume shared).
    """
    sa = _get_span(a)
    sb = _get_span(b)
    if None in sa or None in sb:
        return True  # can't distinguish → assume shared
    return sa == sb


# ---------------------------------------------------------------------------
# Shared opcode interpreter
# ---------------------------------------------------------------------------


def _get_instructions(
    code: types.CodeType,
) -> tuple[list[dis.Instruction], dict[int, int]]:
    """Return the instructions of `code` and a map from offsets to indices
    (for resolving jumps).

    EXTENDED_ARGs are dropped (dis folds them into the following
    instruction's arg); jumps to one resolve to that instruction.
    """
    instructions: list[dis.Instruction] = []
    offset_to_idx: dict[int, int] = {}
    pending: list[int] = []
    for instr in dis.get_instructions(code):
        pending.append(instr.offset)
        if instr.opname == "EXTENDED_ARG":
            continue
        for offset in pending:
            offset_to_idx[offset] = len(instructions)
        pending.clear()
        instructions.append(instr)
    return instructions, offset_to_idx


def _not(expr: ast.expr) -> ast.expr:
    return ast.UnaryOp(op=ast.Not(), operand=expr)


def _is_bool_expr(expr: ast.expr) -> bool:
    return isinstance(expr, ast.Compare) or (
        isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not)
    )


def _strip_not_not(expr: ast.expr) -> ast.expr:
    if (
        isinstance(expr, ast.UnaryOp)
        and isinstance(expr.op, ast.Not)
        and isinstance(expr.operand, ast.UnaryOp)
        and isinstance(expr.operand.op, ast.Not)
    ):
        return expr.operand.operand
    return expr


def _code_of(node: ast.expr) -> types.CodeType | None:
    if isinstance(node, ast.Constant) and isinstance(
        node.value, types.CodeType
    ):
        return node.value
    return None


def _pop_n(stack: list[ast.expr], n: int) -> list[ast.expr]:
    items = stack[len(stack) - n :]
    del stack[len(stack) - n :]
    return items


def _exec_stack_op(instr: dis.Instruction, stack: list[ast.expr]) -> bool:
    """Execute an opcode that only operates on the stack.

    Returns True if the opcode was handled, False otherwise.
    """
    op = instr.opname
    arg = instr.arg
    argval = instr.argval

    if op == "LOAD_CONST":
        stack.append(_set_pos(_const_to_ast(argval), instr))

    elif op == "LOAD_SMALL_INT":
        stack.append(_set_pos(ast.Constant(value=argval), instr))

    elif argval == "__conditional_annotations__" and op in (
        "LOAD_GLOBAL",
        "LOAD_DEREF",
    ):
        stack.append(_CONDITIONAL)

    elif op in ("LOAD_GLOBAL", "LOAD_NAME", "LOAD_FAST", "LOAD_FAST_BORROW"):
        stack.append(_set_pos(ast.Name(id=argval, ctx=ast.Load()), instr))

    elif op == "LOAD_DEREF":
        if argval == "__classdict__":
            stack.append(_CLASSDICT)
        else:
            stack.append(_set_pos(ast.Name(id=argval, ctx=ast.Load()), instr))

    elif op in ("LOAD_FROM_DICT_OR_GLOBALS", "LOAD_FROM_DICT_OR_DEREF"):
        if stack.pop() is not _CLASSDICT:
            raise DecompileError(f"{op} from something besides __classdict__")
        stack.append(_set_pos(ast.Name(id=argval, ctx=ast.Load()), instr))

    elif op == "LOAD_ATTR":
        obj = stack.pop()
        stack.append(
            _set_pos(
                ast.Attribute(value=obj, attr=argval, ctx=ast.Load()),
                instr,
            )
        )

    elif op == "BINARY_OP":
        if arg == _NB_SUBSCR:
            slice_node = stack.pop()
            value_node = stack.pop()
            stack.append(
                _set_pos(
                    ast.Subscript(
                        value=value_node, slice=slice_node, ctx=ast.Load()
                    ),
                    instr,
                )
            )
        elif arg == _NB_OR:
            right = stack.pop()
            left = stack.pop()
            stack.append(
                _set_pos(
                    ast.BinOp(left=left, op=ast.BitOr(), right=right),
                    instr,
                )
            )
        else:
            raise DecompileError(f"Unsupported BINARY_OP arg {arg}")

    elif op == "BUILD_MAP":
        items = _pop_n(stack, 2 * argval)
        keys: list[ast.expr | None] = [*items[::2]]
        stack.append(_set_pos(ast.Dict(keys=keys, values=items[1::2]), instr))

    elif op == "BUILD_TUPLE":
        elts = _pop_n(stack, argval)
        stack.append(_set_pos(ast.Tuple(elts=elts, ctx=ast.Load()), instr))

    elif op == "BUILD_LIST":
        elts = _pop_n(stack, argval)
        stack.append(_set_pos(ast.List(elts=elts, ctx=ast.Load()), instr))

    elif op == "MAKE_FUNCTION":
        top = stack.pop()
        # Keep comprehension code objects for CALL
        code = _code_of(top)
        if code and code.co_name in ("<listcomp>", "<genexpr>"):
            stack.append(top)
        elif code and code.co_name == "<lambda>":
            stack.append(_decompile_lambda(code))
        else:
            raise DecompileError("Unsupported MAKE_FUNCTION")

    elif op in ("LIST_EXTEND", "LIST_APPEND"):
        item = stack.pop()
        if op == "LIST_EXTEND":
            item = ast.Starred(value=item, ctx=ast.Load())
        # Copy rather than mutate the list, since it may be shared with
        # another branch's stack.
        target = copy.copy(stack[-argval])
        assert isinstance(target, ast.List)
        target.elts = [*target.elts, item]
        stack[-argval] = target

    elif (
        op == "CALL"
        and argval == 0
        and len(stack) >= 2
        and (code := _code_of(stack[-2]))
    ):
        # A comprehension compiled as its own code object (see
        # _decompile_comp_code), called with its iterable.
        iterable = stack.pop()
        stack.pop()
        stack.append(_decompile_comp_code(code, iterable))

    elif op == "CALL":
        args = _pop_n(stack, argval)
        func = stack.pop()
        stack.append(
            _set_pos(ast.Call(func=func, args=args, keywords=[]), instr)
        )

    elif op == "CALL_KW":
        names = stack.pop()
        assert isinstance(names, ast.Tuple)
        args = _pop_n(stack, argval)
        nargs = len(args) - len(names.elts)
        keywords = []
        for name, value in zip(names.elts, args[nargs:], strict=True):
            assert isinstance(name, ast.Constant)
            assert isinstance(name.value, str)
            keywords.append(ast.keyword(arg=name.value, value=value))
        func = stack.pop()
        stack.append(
            _set_pos(
                ast.Call(func=func, args=args[:nargs], keywords=keywords),
                instr,
            )
        )

    elif op == "LOAD_COMMON_CONSTANT" and (
        argval is None or isinstance(argval, (bool, int, float, str))
    ):
        # Since 3.15, used for some ordinary constants
        stack.append(_set_pos(_const_to_ast(argval), instr))

    elif op == "CALL_INTRINSIC_1":
        if arg == _INTRINSIC_LIST_TO_TUPLE:
            list_node = stack.pop()
            assert isinstance(list_node, ast.List)
            stack.append(ast.Tuple(elts=list_node.elts, ctx=ast.Load()))
        else:
            raise DecompileError(f"Unsupported CALL_INTRINSIC_1 arg {arg}")

    elif op == "SET_FUNCTION_ATTRIBUTE":
        func_node = stack.pop()
        value = stack.pop()
        if argval == _FUNC_DEFAULTS:
            assert isinstance(func_node, ast.Lambda)
            assert isinstance(value, ast.Tuple)
            func_node = copy.copy(func_node)
            func_node.args = copy.copy(func_node.args)
            func_node.args.defaults = value.elts
        elif argval == _FUNC_KWDEFAULTS:
            assert isinstance(func_node, ast.Lambda)
            assert isinstance(value, ast.Dict)
            defaults = {
                key.value: val
                for key, val in zip(value.keys, value.values, strict=True)
                if isinstance(key, ast.Constant)
            }
            func_node = copy.copy(func_node)
            func_node.args = copy.copy(func_node.args)
            func_node.args.kw_defaults = [
                defaults.get(arg.arg) for arg in func_node.args.kwonlyargs
            ]
        # Otherwise it is the closure, which we don't need.
        stack.append(func_node)

    elif op == "UNPACK_SEQUENCE":
        # `*x` in a subscript or a `*args` annotation
        if argval != 1:
            raise DecompileError(f"Unsupported UNPACK_SEQUENCE arg {argval}")
        top = stack.pop()
        stack.append(ast.Starred(value=top, ctx=ast.Load()))

    elif op == "TO_BOOL":
        # Usually this feeds a jump or UNARY_NOT, but on its own it is
        # what `not not x` compiles to.  Jumps strip it (see _fork).
        operand = stack.pop()
        if not _is_bool_expr(operand):
            operand = _not(_not(operand))
        stack.append(operand)

    elif op == "UNARY_NOT":
        operand = stack.pop()
        stack.append(_not(_strip_not_not(operand)))

    elif op in ("IS_OP", "CONTAINS_OP", "COMPARE_OP"):
        right = stack.pop()
        left = stack.pop()
        cmp: ast.cmpop
        if op == "IS_OP":
            cmp = ast.IsNot() if arg else ast.Is()
        elif op == "CONTAINS_OP":
            cmp = ast.NotIn() if arg else ast.In()
        else:
            assert arg is not None
            cmp = _CMP_OPS[dis.cmp_op[arg >> 5]]()
        stack.append(ast.Compare(left=left, ops=[cmp], comparators=[right]))

    elif op == "STORE_SUBSCR":
        # Adding a class annotation to the dict
        key_node = stack.pop()
        old = stack.pop()
        val_node = stack.pop()
        if not isinstance(old, ast.Dict):
            raise DecompileError("STORE_SUBSCR into a non-dict")
        # Copy rather than mutate the dict, since it may be shared with
        # another branch's stack.
        new = copy.copy(old)
        new.keys = [*old.keys, key_node]
        new.values = [*old.values, val_node]
        stack[:] = [new if v is old else v for v in stack]

    elif op == "COPY":
        stack.append(stack[-argval])

    elif op == "POP_TOP":
        stack.pop()

    elif op in (
        "NOT_TAKEN",
        "PUSH_NULL",
        "RESUME",
        "COPY_FREE_VARS",
        "MAKE_CELL",
    ):
        pass

    else:
        return False

    return True


@dataclasses.dataclass
class _Code:
    """Instructions of a code object, with control flow information."""

    instructions: list[dis.Instruction]
    offset_to_idx: dict[int, int]
    is_annotate: bool = False
    """Whether this is an __annotate__ function, which returns a dict of
    annotations, rather than e.g. an evaluate_* function."""
    ipdom: list[int | None] = dataclasses.field(init=False)
    """The immediate post-dominator of each instruction: the first one that
    every path from it reaches (or None if paths exit separately)."""
    memo: dict[Any, Any] = dataclasses.field(default_factory=dict)
    """Results of running branches; see _fork."""

    def __post_init__(self) -> None:
        # All jumps are forward except JUMP_BACKWARD, which only closes
        # comprehension loops.  Treat it as an exit, and a loop as going
        # straight from its FOR_ITER to the end, so that we can work
        # backwards.
        self.ipdom = [None] * len(self.instructions)
        for i in reversed(range(len(self.instructions))):
            instr = self.instructions[i]
            op = instr.opname
            if op in _EXITS:
                continue
            if op in ("FOR_ITER", "JUMP_FORWARD"):
                self.ipdom[i] = self.target(instr)
            elif op in _COND_JUMPS:
                self.ipdom[i] = self.join(self.target(instr), i + 1)
            elif i + 1 < len(self.instructions):
                self.ipdom[i] = i + 1

    def target(self, instr: dis.Instruction) -> int:
        return self.offset_to_idx[instr.argval]

    def join(self, a: int | None, b: int | None) -> int | None:
        """Return the first instruction every path from both `a` and `b`
        reaches, or None if there isn't one."""
        while a is not None and b is not None and a != b:
            if a < b:
                a = self.ipdom[a]
            else:
                b = self.ipdom[b]
        return a if a == b else None


_EXITS = frozenset(
    {"RETURN_VALUE", "RAISE_VARARGS", "RERAISE", "JUMP_BACKWARD"}
)

_COND_JUMPS = frozenset(
    {
        "POP_JUMP_IF_FALSE",
        "POP_JUMP_IF_TRUE",
        "POP_JUMP_IF_NONE",
        "POP_JUMP_IF_NOT_NONE",
    }
)


def _builtin_guard_at(bc: _Code, pc: int) -> int | None:
    """Match ``COPY 1; LOAD_COMMON_CONSTANT; IS_OP 0; POP_JUMP_IF_FALSE``.

    The compiler inlines calls like ``any(<genexpr>)``, guarded by a
    check that the name still refers to the builtin; otherwise it jumps
    to code for the plain call.  Returns the index of that code.
    """
    instrs = bc.instructions[pc : pc + 4]
    ops = [i.opname for i in instrs]
    if ops != ["COPY", "LOAD_COMMON_CONSTANT", "IS_OP", "POP_JUMP_IF_FALSE"]:
        return None
    if instrs[0].arg != 1 or instrs[2].arg != 0:
        return None
    return bc.target(instrs[3])


# ---------------------------------------------------------------------------
# Comprehension decompilation
# ---------------------------------------------------------------------------

# A comprehension like ``[a for a in B if P]`` comes in two forms.
#
# Generator expressions, and list comprehensions in class scopes, are
# compiled as their own code object, which is called with the iterable:
#
#     LOAD_CONST <code <listcomp>>  MAKE_FUNCTION
#     LOAD B  GET_ITER  CALL 0        (3.15: no GET_ITER here)
#
# and whose code is
#
#     <preamble>                      BUILD_LIST 0 / RETURN_GENERATOR, etc.
#   L1: FOR_ITER L3
#     STORE_FAST a
#     <body>
#   L3: END_FOR  POP_ITER  RETURN_VALUE
#
# Other list comprehensions are inlined, saving and restoring the loop
# variable around the loop:
#
#     LOAD B  GET_ITER                (3.15: GET_ITER is after the SWAPs)
#     LOAD_FAST_AND_CLEAR a  SWAP 2  BUILD_LIST 0  SWAP 2
#   L1: FOR_ITER L3
#     STORE_FAST a
#     <body>
#   L3: END_FOR  POP_ITER  SWAP 2  STORE_FAST a
#
# The body is ordinary expression code that ends each path either by
# producing the element, or by skipping it (for a filter):
#
#     LOAD P  TO_BOOL  POP_JUMP_IF_TRUE L2
#     JUMP_BACKWARD L1                skip
#   L2: LOAD a  LIST_APPEND n  JUMP_BACKWARD L1
#
# For a genexpr, YIELD_VALUE takes the place of LIST_APPEND.  The loop
# variable is stored with STORE_DEREF if a nested scope captures it, and
# STORE_FAST a; LOAD a may be fused into STORE_FAST_LOAD_FAST.


def _decompile_loop(
    bc: _Code, pc: int
) -> tuple[ast.Name, ast.expr, list[ast.expr], int]:
    """Decompile a comprehension's loop, starting from somewhere before its
    FOR_ITER.  Returns (target, element, filters, index of FOR_ITER).

    The body is run like any other code (see _run), except that it ends
    either by appending an element or by skipping to the next iteration.
    """
    while bc.instructions[pc].opname != "FOR_ITER":
        pc += 1
    for_iter = pc

    stack: list[ast.expr] = []
    store = bc.instructions[pc + 1]
    # The loop variable is a cell if a nested scope captures it.
    if store.opname in ("STORE_FAST", "STORE_DEREF"):
        var_name = store.argval
    elif store.opname == "STORE_FAST_LOAD_FAST":
        var_name = store.argval[0]
        stack.append(ast.Name(id=store.argval[1], ctx=ast.Load()))
    else:
        raise DecompileError(f"Unsupported loop variable store {store.opname}")
    result: dict[str, ast.expr] = {}
    _run(bc, pc + 2, stack, result, None, in_comp=True)

    elt = _simplify(result[_ELT_KEY])
    filters: list[ast.expr] = []
    while isinstance(elt, ast.IfExp):
        if elt.orelse is _SKIP:
            filters.append(elt.test)
            elt = elt.body
        elif elt.body is _SKIP:
            filters.append(_negate(elt.test))
            elt = elt.orelse
        else:
            break
    if any(node is _SKIP for node in ast.walk(elt)):
        # The skips are mixed in with if-expressions.  If those all pick
        # the same element, they're really just a complicated filter.
        kept = [leaf for leaf in _ifexp_leaves(elt) if leaf is not _SKIP]
        if not kept or any(
            ast.dump(leaf) != ast.dump(kept[0]) for leaf in kept
        ):
            raise DecompileError("Unsupported filter in comprehension")
        cond = _filter_condition(elt)
        assert isinstance(cond, ast.expr)
        filters.append(cond)
        elt = kept[0]
    target = ast.Name(id=var_name, ctx=ast.Store())
    return target, elt, filters, for_iter


def _ifexp_leaves(expr: ast.expr) -> list[ast.expr]:
    if isinstance(expr, ast.IfExp):
        return _ifexp_leaves(expr.body) + _ifexp_leaves(expr.orelse)
    return [expr]


def _filter_condition(expr: ast.expr) -> ast.expr | bool:
    """Turn an if-expression tree whose leaves are an element or _SKIP into
    the condition for keeping the element."""
    if not isinstance(expr, ast.IfExp):
        return expr is not _SKIP
    test = expr.test
    body = _filter_condition(expr.body)
    orelse = _filter_condition(expr.orelse)
    if isinstance(body, bool):
        if isinstance(orelse, bool):
            if body == orelse:
                return body
            return test if body else _negate(test)
        return _or(test, orelse) if body else _and(_negate(test), orelse)
    if isinstance(orelse, bool):
        return _or(_negate(test), body) if orelse else _and(test, body)
    return ast.IfExp(test=test, body=body, orelse=orelse)


def _decompile_lambda(code: types.CodeType) -> ast.Lambda:
    names = code.co_varnames
    posonly = code.co_posonlyargcount
    nargs = code.co_argcount
    nkwonly = code.co_kwonlyargcount
    i = nargs + nkwonly
    vararg = kwarg = None
    if code.co_flags & inspect.CO_VARARGS:
        vararg = ast.arg(arg=names[i])
        i += 1
    if code.co_flags & inspect.CO_VARKEYWORDS:
        kwarg = ast.arg(arg=names[i])
    args = ast.arguments(
        posonlyargs=[ast.arg(arg=name) for name in names[:posonly]],
        args=[ast.arg(arg=name) for name in names[posonly:nargs]],
        vararg=vararg,
        kwonlyargs=[
            ast.arg(arg=name) for name in names[nargs : nargs + nkwonly]
        ],
        kw_defaults=[None] * nkwonly,
        kwarg=kwarg,
        defaults=[],
    )
    result: dict[str, ast.expr] = {}
    _run(_Code(*_get_instructions(code)), 0, [], result, None)
    return ast.Lambda(args=args, body=result[_VALUE_KEY])


def _decompile_comp_code(
    code: types.CodeType,
    iterable: ast.expr,
) -> ast.ListComp | ast.GeneratorExp:
    """Decompile a separate <listcomp> or <genexpr> code object.

    Used for generator expressions, and for list comprehensions in class
    scopes, which aren't inlined.
    """
    target, elt, filters, _ = _decompile_loop(
        _Code(*_get_instructions(code)), 0
    )
    generators = [ast.comprehension(target, iterable, filters, is_async=0)]
    if code.co_name == "<genexpr>":
        return ast.GeneratorExp(elt=elt, generators=generators)
    return ast.ListComp(elt=elt, generators=generators)


def _decompile_inline_comp(
    bc: _Code,
    pc: int,
    iterable: ast.expr,
) -> tuple[ast.ListComp, int]:
    """Decompile an inlined list comprehension starting at `pc`.

    Returns the comprehension and the index of the instruction after it.
    """
    target, elt, filters, for_iter = _decompile_loop(bc, pc)
    # Skip the cleanup, which restores the saved loop variable
    pc = bc.target(bc.instructions[for_iter])
    cleanup = {"END_FOR", "POP_ITER", "SWAP", "STORE_FAST"}
    while bc.instructions[pc].opname in cleanup:
        pc += 1
    generators = [ast.comprehension(target, iterable, filters, is_async=0)]
    return ast.ListComp(elt=elt, generators=generators), pc


# ---------------------------------------------------------------------------
# Main bytecode drivers
# ---------------------------------------------------------------------------


def _decompile_bytecode(
    code: types.CodeType,
    conditional: collections.abc.Container[int] | None = None,
) -> dict[str, ast.expr]:
    """Run an __annotate__ or evaluate_* function's bytecode, returning
    {name: annotation} or {_VALUE_KEY: value}.

    `conditional` is the value of ``__conditional_annotations__``: the
    indices of the conditionally defined annotations that were executed.
    """
    bc = _Code(
        *_get_instructions(code), is_annotate=code.co_name == "__annotate__"
    )

    # Skip preamble up through RAISE_VARARGS
    start = 0
    for i, instr in enumerate(bc.instructions):
        if instr.opname == "RAISE_VARARGS":
            start = i + 1
            break

    result: dict[str, ast.expr] = {}
    _run(bc, start, [], result, conditional)
    return {key: _simplify(value) for key, value in result.items()}


def _run(
    bc: _Code,
    pc: int,
    stack: list[ast.expr],
    result: dict[str, ast.expr],
    conditional: collections.abc.Container[int] | None,
    stop: int | None = None,
    in_comp: bool = False,
) -> None:
    """Execute bytecode from `pc`, mutating `stack` and `result`.

    Runs until reaching `stop`, or until the code finishes: by returning,
    or in a comprehension body (if `in_comp`), by appending an element or
    skipping to the next iteration.  Results go in `result`: annotations
    under their names, a returned value under _VALUE_KEY, and a
    comprehension element (or _SKIP) under _ELT_KEY.
    """
    while pc != stop:
        instr = bc.instructions[pc]
        op = instr.opname
        argval = instr.argval

        if op == "CONTAINS_OP" and stack[-1] is _CONDITIONAL:
            # `<index> in __conditional_annotations__`, guarding an
            # annotation that was defined under an if/for/etc.  Follow
            # the path that was actually taken.
            stack.pop()
            index_node = stack.pop()
            assert isinstance(index_node, ast.Constant)
            jump_instr = bc.instructions[pc + 1]
            assert jump_instr.opname == "POP_JUMP_IF_FALSE"
            if conditional is None:
                raise DecompileError(
                    "__conditional_annotations__ is not available"
                )
            if index_node.value in conditional:
                pc += 2
            else:
                pc = bc.target(jump_instr)

        elif in_comp and (
            op == "YIELD_VALUE" or (op == "LIST_APPEND" and len(stack) < argval)
        ):
            # Appending to the comprehension's list, which is below the
            # part of the stack we track.
            result[_ELT_KEY] = stack.pop()
            return

        elif in_comp and op == "JUMP_BACKWARD":
            result[_ELT_KEY] = _SKIP
            return

        elif (target := _builtin_guard_at(bc, pc)) is not None:
            # Follow the plain call path rather than the inlined builtin.
            pc = target

        # HACK: The iterator detection seems a little too ad-hoc...
        elif op == "GET_ITER" and len(stack) >= 2 and _code_of(stack[-2]):
            # The iterable for a comprehension's code object, which CALL
            # handles.  (Since 3.15, there is no GET_ITER here.)
            pc += 1

        elif op in ("GET_ITER", "LOAD_FAST_AND_CLEAR"):
            # An inlined comprehension starts with GET_ITER, or since 3.15
            # (which moves GET_ITER later), by saving the loop variable.
            iterable = stack.pop()
            comp, pc = _decompile_inline_comp(bc, pc + 1, iterable)
            stack.append(comp)

        elif _exec_stack_op(instr, stack):
            pc += 1

        elif op in _COND_JUMPS:
            new_pc = _fork(bc, pc, stack, result, conditional, in_comp)
            if new_pc is None:
                return
            pc = new_pc

        elif op == "JUMP_FORWARD":
            pc = bc.target(instr)

        elif op == "RETURN_VALUE":
            value = stack.pop()
            if not bc.is_annotate:
                result[_VALUE_KEY] = value
                return
            if not isinstance(value, ast.Dict):
                raise DecompileError("__annotate__ returned a non-dict")
            for key_node, val_node in zip(
                value.keys, value.values, strict=True
            ):
                if not (
                    isinstance(key_node, ast.Constant)
                    and isinstance(key_node.value, str)
                ):
                    raise DecompileError("Non-string annotation name")
                result[key_node.value] = val_node
            return

        else:
            raise DecompileError(
                f"Unsupported opcode: {op} (arg={instr.arg}, argval={argval!r})"
            )


def _fork(
    bc: _Code,
    pc: int,
    stack: list[ast.expr],
    result: dict[str, ast.expr],
    conditional: collections.abc.Container[int] | None,
    in_comp: bool,
) -> int | None:
    """Handle the conditional jump at `pc` by running both branches.

    If the branches meet again, merge their stacks with if-expressions and
    return where they meet.  Otherwise (e.g. if each branch returns), run
    both to the end, merge their results, and return None.

    This turns ``and``, ``or``, and ``not`` into nested if-expressions;
    _simplify turns common cases back.
    """
    jump = bc.instructions[pc]
    test = _strip_not_not(stack.pop())
    if jump.opname in ("POP_JUMP_IF_NONE", "POP_JUMP_IF_NOT_NONE"):
        test = ast.Compare(
            left=test, ops=[ast.Is()], comparators=[ast.Constant(value=None)]
        )
    jumps_if_true = jump.opname in ("POP_JUMP_IF_TRUE", "POP_JUMP_IF_NONE")
    branches = (bc.target(jump), pc + 1)
    if not jumps_if_true:
        branches = branches[::-1]

    def make(if_true: ast.expr, if_false: ast.expr) -> ast.expr:
        return _Fork(test, if_true, if_false, flip=jumps_if_true)

    join = bc.join(*branches)
    stacks: list[list[ast.expr]] = []
    results: list[dict[str, ast.expr]] = []
    for branch in branches:
        # Different paths often reach the same code with the same stack
        # (e.g. each value of an `or` can jump to the same place), and
        # running it once per path would be exponential.
        key = (branch, join, tuple(map(id, stack)))
        if key not in bc.memo:
            branch_stack = list(stack)
            branch_result: dict[str, ast.expr] = {}
            _run(
                bc,
                branch,
                branch_stack,
                branch_result,
                conditional,
                join,
                in_comp,
            )
            # Keep the stack alive so that the ids in the key stay valid.
            bc.memo[key] = (list(stack), branch_stack, branch_result)
        _, branch_stack, branch_result = bc.memo[key]
        stacks.append(list(branch_stack))
        results.append(dict(branch_result))

    if join is None:
        _merge_branch_results(result, results[0], results[1], make)
        return None

    assert not any(results), "Branches of an expression set results"
    assert len(stacks[0]) == len(stacks[1])
    stack[:] = [
        a if a is b else make(a, b) for a, b in zip(*stacks, strict=True)
    ]
    return join


class _Fork(ast.IfExp):
    """An if-expression made from a conditional jump, before _simplify.

    It can also be written as ``orelse if not test else body``, which is
    preferred if `flip` (when the jump skips the source's true branch).
    """

    def __init__(
        self,
        test: ast.expr,
        body: ast.expr,
        orelse: ast.expr,
        flip: bool,
    ) -> None:
        super().__init__(test=test, body=body, orelse=orelse)
        self.flip = flip


def _orientations(
    node: ast.IfExp,
) -> list[tuple[ast.expr, ast.expr, ast.expr]]:
    """The ways to write `node` as (test, body, orelse), best first."""
    plain = (node.test, node.body, node.orelse)
    if not isinstance(node, _Fork):
        return [plain]
    flipped = (_negate(node.test), node.orelse, node.body)
    return [flipped, plain] if node.flip else [plain, flipped]


def _simplify(expr: ast.expr) -> ast.expr:
    """Turn the nested if-expressions from _fork back into ``and``, ``or``,
    and ``not`` where they have the shapes those compile to.

    Works top-down, since for a chain of conditions, the outer one needs to
    combine with its raw branches before they are simplified on their own.
    """
    cache: dict[int, tuple[ast.AST, ast.AST]] = {}

    def same(a: ast.expr, b: ast.expr) -> bool:
        return a is b or ast.dump(a) == ast.dump(b)

    def simp(node: ast.AST) -> Any:
        # Branches share subtrees (see _fork), so cache by identity.
        if id(node) not in cache:
            cache[id(node)] = (node, simp_uncached(node))
        return cache[id(node)][1]

    def simp_uncached(node: ast.AST) -> ast.AST:
        if not isinstance(node, ast.IfExp):
            changes = {}
            for field, value in ast.iter_fields(node):
                if isinstance(value, ast.AST):
                    new_value: Any = simp(value)
                elif isinstance(value, list):
                    new_value = [
                        simp(v) if isinstance(v, ast.AST) else v for v in value
                    ]
                else:
                    continue
                if new_value != value:
                    changes[field] = new_value
            if not changes:
                return node
            new = copy.copy(node)
            for field, new_value in changes.items():
                setattr(new, field, new_value)
            return new

        options = _orientations(node)
        # `a or b` and `a and b` as values (but not a comprehension
        # filter, where one branch skips the element)
        if not any(n is _SKIP for n in ast.walk(node)):
            for test, body, orelse in options:
                if same(test, body):
                    return _or(simp(test), simp(orelse))
                if same(test, orelse):
                    return _and(simp(test), simp(body))
        # `x if a and b else y`
        for test, body, orelse in options:
            if isinstance(body, ast.IfExp):
                for b_test, b_body, b_orelse in _orientations(body):
                    if same(b_orelse, orelse):
                        return simp(
                            ast.IfExp(
                                test=_and(test, b_test),
                                body=b_body,
                                orelse=orelse,
                            )
                        )
        # `x if a or b else y`
        for test, body, orelse in options:
            new_orelse = simp(orelse)
            if isinstance(new_orelse, ast.IfExp) and same(
                new_orelse.body, simp(body)
            ):
                return ast.IfExp(
                    test=_or(simp(test), new_orelse.test),
                    body=new_orelse.body,
                    orelse=new_orelse.orelse,
                )
        test, body, orelse = options[0]
        return ast.IfExp(test=simp(test), body=simp(body), orelse=simp(orelse))

    return simp(expr)


def _and(a: ast.expr, b: ast.expr) -> ast.expr:
    return _boolop(ast.And(), a, b)


def _or(a: ast.expr, b: ast.expr) -> ast.expr:
    return _boolop(ast.Or(), a, b)


def _boolop(op: ast.boolop, a: ast.expr, b: ast.expr) -> ast.expr:
    values = []
    for v in (a, b):
        if isinstance(v, ast.BoolOp) and type(v.op) is type(op):
            values.extend(v.values)
        else:
            values.append(v)
    return ast.BoolOp(op=op, values=values)


def _negate(expr: ast.expr) -> ast.expr:
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        return expr.operand
    if (
        isinstance(expr, ast.Compare)
        and len(expr.ops) == 1
        and isinstance(expr.ops[0], (ast.Is, ast.IsNot))
        and isinstance(expr.comparators[0], ast.Constant)
        and expr.comparators[0].value is None
    ):
        flipped = ast.IsNot() if isinstance(expr.ops[0], ast.Is) else ast.Is()
        return ast.Compare(
            left=expr.left, ops=[flipped], comparators=expr.comparators
        )
    return _not(expr)


# ---------------------------------------------------------------------------
# IfExp branch merging (position-aware)
# ---------------------------------------------------------------------------


def _merge_values(
    true_val: ast.expr,
    false_val: ast.expr,
    make: Callable[[ast.expr, ast.expr], ast.expr],
) -> ast.expr:
    """Merge two branch values, using source positions to decide factoring.

    When the compiler duplicates surrounding context into both branches of
    a tail-position if-expression, the duplicated instructions share the
    same source span.  If two branch result nodes have the same span, we
    recurse into their children to find the point of divergence.  If they
    have different spans, they represent independent structure and we wrap
    with a plain IfExp.

    Example — ``list[int if T else str]``::

        Both branches produce Subscript(list, int) and Subscript(list, str).
        The Subscript nodes share the same source span (the whole
        ``list[...]`` expression) → recurse.  The slices ``int`` vs ``str``
        have different spans → IfExp there.
        Result: Subscript(list, IfExp(T, int, str))

    Example — ``list[int] if T else list[str]``::

        Both branches again produce Subscript(list, int) and
        Subscript(list, str), but now the Subscript nodes have *different*
        spans (``list[int]`` vs ``list[str]``) → stop, IfExp at top level.
        Result: IfExp(T, Subscript(list, int), Subscript(list, str))
    """
    if ast.dump(true_val) == ast.dump(false_val):
        return true_val

    # An if-expression can't produce a starred item, so the star must be
    # outside it.
    if isinstance(true_val, ast.Starred) and isinstance(false_val, ast.Starred):
        return ast.Starred(
            value=_merge_values(true_val.value, false_val.value, make),
            ctx=ast.Load(),
        )

    if (
        type(true_val) is not type(false_val)
        or isinstance(true_val, ast.IfExp)
        or not _same_span(true_val, false_val)
    ):
        return make(true_val, false_val)

    # Same span: shared structure, so merge the children.
    merged = _merge_children(true_val, false_val, make)
    return make(true_val, false_val) if merged is None else merged


def _merge_children[N: ast.AST](
    true_node: N,
    false_node: N,
    make: Callable[[ast.expr, ast.expr], ast.expr],
) -> N | None:
    """Merge the fields of two nodes of the same type, or return None if
    they differ somewhere that an if-expression can't go."""
    fields: dict[str, Any] = {}
    for name, t in ast.iter_fields(true_node):
        f = getattr(false_node, name)
        if isinstance(t, list) and isinstance(f, list) and len(t) == len(f):
            items = [
                _merge_child(te, fe, make) for te, fe in zip(t, f, strict=True)
            ]
            if None in items:
                return None
            fields[name] = items
        else:
            fields[name] = _merge_child(t, f, make)
            if fields[name] is None and t is not None:
                return None
    return ast.copy_location(type(true_node)(**fields), true_node)


def _merge_child(
    t: Any, f: Any, make: Callable[[ast.expr, ast.expr], ast.expr]
) -> Any:
    if _equal(t, f):
        return t
    if isinstance(t, ast.expr) and isinstance(f, ast.expr):
        return _merge_values(t, f, make)
    # Something like an ast.keyword, which can't be made an if-expression,
    # but might contain one.
    if isinstance(t, ast.AST) and type(t) is type(f):
        return _merge_children(t, f, make)
    return None


def _equal(a: object, b: object) -> bool:
    if isinstance(a, list):
        return (
            isinstance(b, list)
            and len(a) == len(b)
            and all(map(_equal, a, b, strict=True))
        )
    if isinstance(a, ast.AST):
        return isinstance(b, ast.AST) and ast.dump(a) == ast.dump(b)
    return a == b


def _merge_branch_results(
    result: dict[str, ast.expr],
    true_branch: dict[str, ast.expr],
    false_branch: dict[str, ast.expr],
    make: Callable[[ast.expr, ast.expr], ast.expr],
) -> None:
    """Merge results from two tail-position if-expression branches, using
    `make` to make if-expressions."""
    for key in {**true_branch, **false_branch}:
        if key in true_branch and key in false_branch:
            result[key] = _merge_values(
                true_branch[key], false_branch[key], make
            )
        else:
            result[key] = true_branch.get(key) or false_branch[key]


# ---------------------------------------------------------------------------
# Binding information
# ---------------------------------------------------------------------------


class _CellMapping(collections.abc.Mapping[str, Any]):
    """A mapping that holds cells and dereferences them on access."""

    __slots__ = ("closure",)

    def __init__(self, closure: dict[str, types.CellType]) -> None:
        self.closure = closure

    def __getitem__(self, key: str) -> Any:
        cell = self.closure[key]
        try:
            return cell.cell_contents
        except ValueError:
            raise NameError(
                f"cannot access free variable {key!r} where it is not "
                "associated with a value in enclosing scope",
                name=key,
            )

    def __iter__(self) -> collections.abc.Iterator[str]:
        return iter(self.closure)

    def __len__(self) -> int:
        return len(self.closure)


@dataclasses.dataclass
class BindingNamespace:
    """How names in an annotate function are bound."""

    class_name: str | None
    """The enclosing class name, for name mangling purposes."""
    global_names: tuple[str, ...]
    """Names known to be declared global."""
    mangled_names: tuple[str, ...] | None
    """If not None, only these private names are mangled.

    Mirrors ``ste_mangled_names`` in CPython's symtable, which is set for
    scopes (like generic class type params) where only some ``__`` names
    get mangled.  Names are stored unmangled.
    """

    def mangle(self, name: str) -> str:
        """Mangle *name* the way the compiler would in this scope."""
        if self.class_name is None or not _is_private_name(name):
            return name
        if self.mangled_names is not None and name not in self.mangled_names:
            return name
        class_name = self.class_name.lstrip("_")
        if not class_name:
            return name
        return f"_{class_name}{name}"


@dataclasses.dataclass
class BindingEnvironment:
    """The namespaces that names in an annotate function resolve in."""

    globals: dict[str, Any]
    closure: collections.abc.Mapping[str, Any]
    """Free variables, excluding __classdict__ and
    __conditional_annotations__."""
    classdict: collections.abc.Mapping[str, Any] | None
    """The class namespace, for annotations in class scope."""


@dataclasses.dataclass
class AnnotateInfo:
    """What is needed to resolve the names in a decompiled annotate
    function."""

    namespace: BindingNamespace
    env: BindingEnvironment


_NAME_OPS = frozenset(dis.hasname + dis.haslocal + dis.hasfree)


def _collect_names(
    code: types.CodeType,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Find (global names, all names) used, including in nested code objects.

    In a class-scoped annotate function, ordinary names are loaded with
    LOAD_FROM_DICT_OR_GLOBALS, so LOAD_GLOBAL indicates a ``global``
    declaration.  Nested scopes (lambdas and comprehensions) can't see
    the class namespace, so they use LOAD_GLOBAL regardless, and only
    contribute to all names.
    """
    global_names: dict[str, None] = {}
    all_names: dict[str, None] = {}

    def visit(code: types.CodeType, nested: bool) -> None:
        for instr in dis.get_instructions(code):
            if instr.opcode not in _NAME_OPS:
                continue
            if (
                not nested
                and instr.opname == "LOAD_GLOBAL"
                and instr.argval != "__conditional_annotations__"
            ):
                global_names[instr.argval] = None
            vals = instr.argval
            for name in vals if isinstance(vals, tuple) else (vals,):
                all_names[name] = None
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                visit(const, True)

    visit(code, False)
    return tuple(global_names), tuple(all_names)


def _is_private_name(name: str) -> bool:
    return name.startswith("__") and not name.endswith("__") and "." not in name


def _find_mangled_names(
    names: tuple[str, ...], class_name: str | None
) -> tuple[str, ...] | None:
    if class_name is None or not class_name.lstrip("_"):
        return None
    if not any(_is_private_name(name) for name in names):
        return None
    prefix = "_" + class_name.lstrip("_")
    return tuple(
        name.removeprefix(prefix)
        for name in names
        if name.startswith(prefix)
        and _is_private_name(name.removeprefix(prefix))
    )


def _enclosing_class_name(fn: types.FunctionType) -> str | None:
    # An annotate/evaluate function's qualname is that of its enclosing
    # scope plus one final component.  In the rest, a component followed
    # by "<locals>" is a function; any other component is a class.
    parts = fn.__qualname__.split(".")[:-1]
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] != "<locals>" and (
            i + 1 == len(parts) or parts[i + 1] != "<locals>"
        ):
            return parts[i]
    return None


def _get_cells(fn: types.FunctionType) -> dict[str, types.CellType]:
    return dict(zip(fn.__code__.co_freevars, fn.__closure__ or (), strict=True))


def _get_conditional(fn: types.FunctionType) -> Any:
    # Class scopes close over __conditional_annotations__; module scopes
    # keep it in globals.
    cell = _get_cells(fn).get("__conditional_annotations__")
    if cell is None:
        return fn.__globals__.get("__conditional_annotations__")
    try:
        return cell.cell_contents
    except ValueError:
        return None


def _get_environment(fn: types.FunctionType) -> BindingEnvironment:
    cells = _get_cells(fn)
    classdict = None
    if "__classdict__" in cells:
        try:
            classdict = cells["__classdict__"].cell_contents
        except ValueError:
            pass
    closure = _CellMapping(
        {
            name: cell
            for name, cell in cells.items()
            if name not in ("__classdict__", "__conditional_annotations__")
        }
    )
    return BindingEnvironment(
        globals=fn.__globals__, closure=closure, classdict=classdict
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_annotate_ast(
    fn: types.FunctionType,
    class_name: str | None = None,
) -> tuple[dict[str, ast.expr] | ast.expr, AnnotateInfo]:
    """Decompile an __annotate__ or evaluate_* function into AST nodes.

    For an __annotate__ function, returns a dict mapping annotation names
    to ast.expr nodes.  For an evaluate_* function (type alias values,
    TypeVar bounds, etc.), returns the single ast.expr it evaluates.
    Also returns the namespace and environment needed to resolve names
    in them.

    The class used for name mangling is derived from ``fn``'s qualname,
    which is wrong for the type params of a generic class: those are
    mangled with the generic class itself, but their qualnames only name
    the enclosing scope.  Callers can pass ``class_name`` to override it.
    """
    code = fn.__code__
    if class_name is None:
        class_name = _enclosing_class_name(fn)
    global_names, all_names = _collect_names(code)
    namespace = BindingNamespace(
        class_name=class_name,
        global_names=global_names,
        mangled_names=_find_mangled_names(all_names, class_name),
    )
    info = AnnotateInfo(namespace=namespace, env=_get_environment(fn))
    result = _decompile_bytecode(code, _get_conditional(fn))
    if _VALUE_KEY in result:
        return result[_VALUE_KEY], info
    return result, info


def get_annotations_ast(
    obj: types.FunctionType | type | types.ModuleType,
) -> dict[str, ast.expr]:
    """Decompile the __annotate__ function of a function, class, or module
    into AST nodes.

    Returns a dict mapping annotation names to ast.expr nodes.
    For functions, keys are parameter names and 'return'.
    For classes and modules, keys are attribute names.
    """
    annotate = getattr(obj, "__annotate__", None)
    if annotate is None:
        return {}
    result, _ = get_annotate_ast(annotate)
    assert isinstance(result, dict)
    return result
