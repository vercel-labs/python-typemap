"""Decompile __annotate__ bytecode back into AST expression nodes.

Python 3.14 (PEP 649) generates __annotate__ methods for functions and classes
that construct annotation dicts from bytecode.  This module walks the bytecode
with a virtual stack and reconstructs equivalent ast.expr trees.

Two dict-building patterns exist:

  Function annotations:
    LOAD_CONST 'key1'  <expr1>  ...  BUILD_MAP N  RETURN_VALUE

  Class annotations:
    BUILD_MAP 0  <expr> COPY 2 LOAD_CONST 'key' STORE_SUBSCR ...

Either pattern may contain if-expressions (control flow):

  Inline (non-last annotation):
    TO_BOOL POP_JUMP_IF_FALSE <true> JUMP_FORWARD <false>

  Tail-position (last annotation):
    TO_BOOL POP_JUMP_IF_FALSE <true+return> <false+return>

For tail-position if-expressions, the compiler duplicates surrounding context
into both branches.  Source position info on bytecode instructions distinguishes
shared structure (same source span → factor into inner IfExp) from independent
structure (different span → wrap with outer IfExp).
"""

from __future__ import annotations

import ast
import dis
import types
from typing import Any, Union


# BINARY_OP arg constants (from dis._nb_ops)
_NB_OR = 7  # |
_NB_SUBSCR = 26  # []

# Stack sentinels (compared by identity)
_CLASSDICT: ast.expr = ast.Name(id="__classdict__")
_MAP: ast.expr = ast.Name(id="__map__")


class DecompileError(Exception):
    """Raised when we encounter bytecode we can't handle."""


def _const_to_ast(value: Any) -> ast.expr:
    """Convert a Python constant to an AST node.

    Tuples become ast.Tuple of their elements (recursively).
    Everything else becomes ast.Constant.
    """
    if isinstance(value, tuple):
        return ast.Tuple(elts=[_const_to_ast(v) for v in value], ctx=ast.Load())
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


def _decompile_bytecode(
    code: types.CodeType,
) -> dict[str, ast.expr]:
    """Walk __annotate__ bytecode and return {name: ast_expr}."""
    instructions = list(dis.get_instructions(code))

    # Build offset → index map for jump resolution
    offset_to_idx: dict[int, int] = {}
    for idx, instr in enumerate(instructions):
        offset_to_idx[instr.offset] = idx

    # Skip preamble up through RAISE_VARARGS
    start = 0
    for i, instr in enumerate(instructions):
        if instr.opname == "RAISE_VARARGS":
            start = i + 1
            break

    result: dict[str, ast.expr] = {}
    _run(instructions, offset_to_idx, start, [], result)
    return result


def _run(
    instructions: list[dis.Instruction],
    offset_to_idx: dict[int, int],
    pc: int,
    stack: list[ast.expr],
    result: dict[str, ast.expr],
) -> None:
    """Execute bytecode from `pc`, mutating `stack` and `result`.

    For inline if-expressions (JUMP_FORWARD after true branch), this
    constructs an ast.IfExp and continues linearly.

    For tail-position if-expressions (each branch has its own BUILD_MAP +
    RETURN_VALUE), this recursively processes both branches, merging their
    results with IfExp wrappers for any keys whose values differ.
    """
    while pc < len(instructions):
        instr = instructions[pc]
        op = instr.opname
        arg = instr.arg
        argval = instr.argval
        pc += 1

        if op == "LOAD_CONST":
            stack.append(_set_pos(_const_to_ast(argval), instr))

        elif op == "LOAD_SMALL_INT":
            stack.append(_set_pos(ast.Constant(value=argval), instr))

        elif op in ("LOAD_GLOBAL", "LOAD_NAME"):
            stack.append(_set_pos(ast.Name(id=argval, ctx=ast.Load()), instr))

        elif op == "LOAD_DEREF":
            if argval == "__classdict__":
                stack.append(_CLASSDICT)
            else:
                stack.append(
                    _set_pos(ast.Name(id=argval, ctx=ast.Load()), instr)
                )

        elif op in ("LOAD_FROM_DICT_OR_GLOBALS", "LOAD_FROM_DICT_OR_DEREF"):
            if stack and stack[-1] is _CLASSDICT:
                stack.pop()
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

        elif op == "BUILD_TUPLE":
            n = argval
            if n:
                elts = stack[-n:]
                del stack[-n:]
            else:
                elts = []
            stack.append(_set_pos(ast.Tuple(elts=elts, ctx=ast.Load()), instr))

        elif op == "BUILD_LIST":
            n = argval
            if n:
                elts = stack[-n:]
                del stack[-n:]
            else:
                elts = []
            stack.append(_set_pos(ast.List(elts=elts, ctx=ast.Load()), instr))

        elif op == "BUILD_MAP":
            n = argval
            if n == 0:
                stack.append(_MAP)
            else:
                items = stack[-n * 2 :]
                del stack[-n * 2 :]
                for i in range(0, len(items), 2):
                    key_node = items[i]
                    val_node = items[i + 1]
                    assert isinstance(key_node, ast.Constant)
                    assert isinstance(key_node.value, str)
                    result[key_node.value] = val_node

        elif op == "COPY":
            stack.append(stack[-argval])

        elif op == "STORE_SUBSCR":
            key_node = stack.pop()
            stack.pop()  # __map__ copy
            val_node = stack.pop()
            assert isinstance(key_node, ast.Constant)
            assert isinstance(key_node.value, str)
            result[key_node.value] = val_node

        elif op == "MAKE_FUNCTION":
            stack.pop()
            stack.append(_set_pos(ast.Constant(value="<function>"), instr))

        elif op == "TO_BOOL":
            # The test expression is on top of stack.  The next meaningful
            # instruction is POP_JUMP_IF_FALSE (skip NOT_TAKEN).
            test_node = stack.pop()

            # Advance past NOT_TAKEN to POP_JUMP_IF_FALSE
            while pc < len(instructions) and instructions[pc].opname in (
                "NOT_TAKEN",
            ):
                pc += 1
            assert (
                pc < len(instructions)
                and instructions[pc].opname == "POP_JUMP_IF_FALSE"
            ), (
                "Expected POP_JUMP_IF_FALSE after TO_BOOL, "
                f"got {instructions[pc].opname}"
            )
            jump_instr = instructions[pc]
            else_idx = offset_to_idx[jump_instr.argval]
            pc += 1  # skip POP_JUMP_IF_FALSE

            # Skip NOT_TAKEN after POP_JUMP_IF_FALSE
            while (
                pc < len(instructions)
                and instructions[pc].opname == "NOT_TAKEN"
            ):
                pc += 1

            # Check whether this is inline (true branch ends with
            # JUMP_FORWARD) or tail-position (true branch ends with
            # RETURN_VALUE).
            if _is_inline_ifexp(instructions, pc, else_idx):
                # Inline: true_branch JUMP_FORWARD(join) false_branch join
                true_val, pc = _run_expr(
                    instructions, offset_to_idx, pc, list(stack)
                )
                # pc now points at JUMP_FORWARD
                assert instructions[pc].opname == "JUMP_FORWARD"
                join_idx = offset_to_idx[instructions[pc].argval]
                false_val, _ = _run_expr(
                    instructions,
                    offset_to_idx,
                    else_idx,
                    list(stack),
                    end=join_idx,
                )
                stack.append(
                    ast.IfExp(test=test_node, body=true_val, orelse=false_val)
                )
                pc = join_idx  # continue after the join point
            else:
                # Tail-position: each branch independently finishes the
                # annotation dict and returns.  Run both branches to
                # completion and merge with IfExp.
                #
                true_result: dict[str, ast.expr] = {}
                _run(
                    instructions,
                    offset_to_idx,
                    pc,
                    list(stack),
                    true_result,
                )
                false_result: dict[str, ast.expr] = {}
                _run(
                    instructions,
                    offset_to_idx,
                    else_idx,
                    list(stack),
                    false_result,
                )
                _merge_branch_results(
                    result, true_result, false_result, test_node
                )
                return  # both branches returned; we're done

        elif op == "RETURN_VALUE":
            return

        elif op in (
            "RESUME",
            "COPY_FREE_VARS",
            "NOT_TAKEN",
            "POP_JUMP_IF_FALSE",
            "LOAD_FAST_BORROW",
            "COMPARE_OP",
            "LOAD_COMMON_CONSTANT",
            "RAISE_VARARGS",
            "PUSH_NULL",
        ):
            pass

        else:
            raise DecompileError(
                f"Unsupported opcode: {op} (arg={arg}, argval={argval!r})"
            )


def _is_inline_ifexp(
    instructions: list[dis.Instruction], true_start: int, else_idx: int
) -> bool:
    """Check if the true branch ends with JUMP_FORWARD (inline)
    vs RETURN_VALUE (tail)."""
    for i in range(true_start, else_idx):
        if instructions[i].opname == "JUMP_FORWARD":
            return True
        if instructions[i].opname == "RETURN_VALUE":
            return False
    return False


def _run_expr(
    instructions: list[dis.Instruction],
    offset_to_idx: dict[int, int],
    pc: int,
    stack: list[ast.expr],
    end: int | None = None,
) -> tuple[ast.expr, int]:
    """Run bytecode for a single expression, returning the value and new pc.

    Used for inline if-expression branches that produce exactly one value
    on top of the initial stack.  Stops at JUMP_FORWARD, RETURN_VALUE,
    or when reaching the `end` instruction index.
    """
    initial_depth = len(stack)
    while pc < len(instructions):
        if end is not None and pc >= end:
            break
        instr = instructions[pc]
        op = instr.opname

        # Stop when we hit branch-ending instructions
        if op == "JUMP_FORWARD":
            break
        if op == "RETURN_VALUE":
            break

        # For nested inline if-expressions, handle TO_BOOL recursively
        if op == "TO_BOOL":
            test_node = stack.pop()
            pc += 1
            while (
                pc < len(instructions)
                and instructions[pc].opname == "NOT_TAKEN"
            ):
                pc += 1
            assert instructions[pc].opname == "POP_JUMP_IF_FALSE"
            jump_instr = instructions[pc]
            else_idx = offset_to_idx[jump_instr.argval]
            pc += 1
            while (
                pc < len(instructions)
                and instructions[pc].opname == "NOT_TAKEN"
            ):
                pc += 1

            if _is_inline_ifexp(instructions, pc, else_idx):
                true_val, pc = _run_expr(
                    instructions, offset_to_idx, pc, list(stack)
                )
                assert instructions[pc].opname == "JUMP_FORWARD"
                join_idx = offset_to_idx[instructions[pc].argval]
                false_val, _ = _run_expr(
                    instructions, offset_to_idx, else_idx, list(stack)
                )
                stack.append(
                    ast.IfExp(test=test_node, body=true_val, orelse=false_val)
                )
                pc = join_idx
            else:
                raise DecompileError(
                    "Nested tail-position if-expression in expression context"
                )
            continue

        # Reuse the same opcode handling as _run
        arg = instr.arg
        argval = instr.argval
        pc += 1

        if op == "LOAD_CONST":
            stack.append(_set_pos(_const_to_ast(argval), instr))
        elif op == "LOAD_SMALL_INT":
            stack.append(_set_pos(ast.Constant(value=argval), instr))
        elif op in ("LOAD_GLOBAL", "LOAD_NAME"):
            stack.append(_set_pos(ast.Name(id=argval, ctx=ast.Load()), instr))
        elif op == "LOAD_DEREF":
            if argval == "__classdict__":
                stack.append(_CLASSDICT)
            else:
                stack.append(
                    _set_pos(ast.Name(id=argval, ctx=ast.Load()), instr)
                )
        elif op in ("LOAD_FROM_DICT_OR_GLOBALS", "LOAD_FROM_DICT_OR_DEREF"):
            if stack and stack[-1] is _CLASSDICT:
                stack.pop()
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
                s = stack.pop()
                v = stack.pop()
                stack.append(
                    _set_pos(
                        ast.Subscript(value=v, slice=s, ctx=ast.Load()),
                        instr,
                    )
                )
            elif arg == _NB_OR:
                r = stack.pop()
                l = stack.pop()  # noqa: E741
                stack.append(
                    _set_pos(
                        ast.BinOp(left=l, op=ast.BitOr(), right=r),
                        instr,
                    )
                )
            else:
                raise DecompileError(f"Unsupported BINARY_OP arg {arg}")
        elif op == "BUILD_TUPLE":
            n = argval
            if n:
                elts = stack[-n:]
                del stack[-n:]
            else:
                elts = []
            stack.append(_set_pos(ast.Tuple(elts=elts, ctx=ast.Load()), instr))
        elif op == "BUILD_LIST":
            n = argval
            if n:
                elts = stack[-n:]
                del stack[-n:]
            else:
                elts = []
            stack.append(_set_pos(ast.List(elts=elts, ctx=ast.Load()), instr))
        elif op == "MAKE_FUNCTION":
            stack.pop()
            stack.append(_set_pos(ast.Constant(value="<function>"), instr))
        elif op in ("NOT_TAKEN", "PUSH_NULL"):
            pass
        else:
            raise DecompileError(
                f"Unsupported opcode in expr: {op} "
                f"(arg={arg}, argval={argval!r})"
            )

    assert len(stack) == initial_depth + 1, (
        f"Expression branch should produce exactly one value, "
        f"got {len(stack) - initial_depth}"
    )
    return stack.pop(), pc


def _merge_values(
    true_val: ast.expr,
    false_val: ast.expr,
    test: ast.expr,
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

    if not _same_span(true_val, false_val):
        return ast.IfExp(test=test, body=true_val, orelse=false_val)

    # Same span — shared structure.  Recurse into matching node types.

    if isinstance(true_val, ast.Subscript) and isinstance(
        false_val, ast.Subscript
    ):
        return ast.Subscript(
            value=_merge_values(true_val.value, false_val.value, test),
            slice=_merge_values(true_val.slice, false_val.slice, test),
            ctx=ast.Load(),
        )

    if (
        isinstance(true_val, ast.Tuple)
        and isinstance(false_val, ast.Tuple)
        and len(true_val.elts) == len(false_val.elts)
    ):
        elts = [
            _merge_values(t, f, test)
            for t, f in zip(true_val.elts, false_val.elts, strict=True)
        ]
        return ast.Tuple(elts=elts, ctx=ast.Load())

    if (
        isinstance(true_val, ast.BinOp)
        and isinstance(false_val, ast.BinOp)
        and type(true_val.op) is type(false_val.op)
    ):
        left = _merge_values(true_val.left, false_val.left, test)
        right = _merge_values(true_val.right, false_val.right, test)
        return ast.BinOp(left=left, op=true_val.op, right=right)

    if (
        isinstance(true_val, ast.Attribute)
        and isinstance(false_val, ast.Attribute)
        and true_val.attr == false_val.attr
    ):
        return ast.Attribute(
            value=_merge_values(true_val.value, false_val.value, test),
            attr=true_val.attr,
            ctx=ast.Load(),
        )

    return ast.IfExp(test=test, body=true_val, orelse=false_val)


def _merge_branch_results(
    result: dict[str, ast.expr],
    true_branch: dict[str, ast.expr],
    false_branch: dict[str, ast.expr],
    test: ast.expr,
) -> None:
    """Merge results from two tail-position if-expression branches."""
    all_keys = list(true_branch.keys())
    for k in false_branch:
        if k not in true_branch:
            all_keys.append(k)

    for key in all_keys:
        true_val = true_branch.get(key)
        false_val = false_branch.get(key)

        if true_val is not None and false_val is not None:
            result[key] = _merge_values(true_val, false_val, test)
        elif true_val is not None:
            result[key] = true_val
        elif false_val is not None:
            result[key] = false_val


def decompile_annotations(
    obj: Union[types.FunctionType, type],
) -> dict[str, ast.expr]:
    """Decompile the __annotate__ method of a function or class into AST nodes.

    Returns a dict mapping annotation names to ast.expr nodes.
    For functions, keys are parameter names and 'return'.
    For classes, keys are attribute names.
    """
    annotate = getattr(obj, "__annotate__", None)
    if annotate is None:
        return {}
    code = annotate.__code__
    return _decompile_bytecode(code)
