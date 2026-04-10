"""Decompile __annotate__ bytecode back into AST expression nodes.

Python 3.14 (PEP 649) generates __annotate__ methods for functions and classes
that construct annotation dicts from bytecode.  This module walks the bytecode
with a virtual stack and reconstructs equivalent ast.expr trees.

Two code patterns exist:

  Function annotations:
    LOAD_CONST 'key1'  <expr1>  LOAD_CONST 'key2'  <expr2> ... BUILD_MAP N  RETURN_VALUE

  Class annotations:
    BUILD_MAP 0  <expr> COPY 2 LOAD_CONST 'key' STORE_SUBSCR  ...  RETURN_VALUE
"""

from __future__ import annotations

import ast
import dis
import types
from typing import Any, Union


# BINARY_OP arg constants (from dis._nb_ops)
_NB_OR = 7  # |
_NB_SUBSCR = 26  # []


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


def _decompile_bytecode(
    code: types.CodeType,
) -> dict[str, ast.expr]:
    """Walk __annotate__ bytecode and return {name: ast_expr}."""
    instructions = list(dis.get_instructions(code))

    stack: list[ast.expr | str] = []
    result: dict[str, ast.expr] = {}

    # Skip preamble: COPY_FREE_VARS, RESUME, and the format>2 guard block.
    # The guard is: LOAD_FAST format / LOAD_SMALL_INT 2 / COMPARE_OP > /
    #               POP_JUMP_IF_FALSE / NOT_TAKEN / LOAD_COMMON_CONSTANT / RAISE_VARARGS
    # We find the RAISE_VARARGS and start after it.
    start = 0
    for i, instr in enumerate(instructions):
        if instr.opname == "RAISE_VARARGS":
            start = i + 1
            break

    for instr in instructions[start:]:
        op = instr.opname
        arg = instr.arg
        argval = instr.argval

        if op == "LOAD_CONST":
            stack.append(_const_to_ast(argval))

        elif op == "LOAD_SMALL_INT":
            stack.append(ast.Constant(value=argval))

        elif op in ("LOAD_GLOBAL", "LOAD_NAME"):
            stack.append(ast.Name(id=argval, ctx=ast.Load()))

        elif op == "LOAD_DEREF":
            # Free variable — type param (T, U, P, Ts) or __classdict__
            if argval == "__classdict__":
                # Push a sentinel; LOAD_FROM_DICT_OR_* will consume it
                stack.append("__classdict__")
            else:
                stack.append(ast.Name(id=argval, ctx=ast.Load()))

        elif op in ("LOAD_FROM_DICT_OR_GLOBALS", "LOAD_FROM_DICT_OR_DEREF"):
            # Pops the __classdict__ sentinel, pushes a Name
            if stack and stack[-1] == "__classdict__":
                stack.pop()
            stack.append(ast.Name(id=argval, ctx=ast.Load()))

        elif op == "LOAD_ATTR":
            obj = stack.pop()
            stack.append(
                ast.Attribute(value=obj, attr=argval, ctx=ast.Load())
            )

        elif op == "BINARY_OP":
            if arg == _NB_SUBSCR:
                # X[Y] — top is slice, next is value
                slice_node = stack.pop()
                value_node = stack.pop()
                stack.append(
                    ast.Subscript(
                        value=value_node, slice=slice_node, ctx=ast.Load()
                    )
                )
            elif arg == _NB_OR:
                # X | Y
                right = stack.pop()
                left = stack.pop()
                stack.append(
                    ast.BinOp(left=left, op=ast.BitOr(), right=right)
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
            stack.append(ast.Tuple(elts=elts, ctx=ast.Load()))

        elif op == "BUILD_LIST":
            n = argval
            if n:
                elts = stack[-n:]
                del stack[-n:]
            else:
                elts = []
            stack.append(ast.List(elts=elts, ctx=ast.Load()))

        elif op == "BUILD_MAP":
            n = argval
            if n == 0:
                # Class annotation pattern: empty dict, then STORE_SUBSCR
                stack.append("__map__")
            else:
                # Function annotation pattern: stack has key, val pairs
                # Stack layout: key1, val1, key2, val2, ...
                items = stack[-n * 2 :]
                del stack[-n * 2 :]
                for i in range(0, len(items), 2):
                    key_node = items[i]
                    val_node = items[i + 1]
                    assert isinstance(key_node, ast.Constant)
                    result[key_node.value] = val_node

        elif op == "COPY":
            # COPY n: push a copy of stack[-n]
            stack.append(stack[-argval])

        elif op == "STORE_SUBSCR":
            # Class pattern: STORE_SUBSCR does TOS1[TOS] = TOS2
            # Stack: [..., __map__, value, __map__(copy), key]
            # After: [..., __map__]
            key_node = stack.pop()
            stack.pop()  # __map__ copy
            val_node = stack.pop()
            assert isinstance(key_node, ast.Constant)
            result[key_node.value] = val_node

        elif op == "MAKE_FUNCTION":
            # Lambda or nested function in Annotated metadata.
            # The code object was pushed by LOAD_CONST; replace with
            # a placeholder since we can't decompile arbitrary code.
            stack.pop()
            stack.append(ast.Constant(value="<function>"))

        elif op == "RETURN_VALUE":
            break

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

    return result


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
