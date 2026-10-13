from __future__ import annotations

import ast
import textwrap

from types import NoneType

from typing import Literal, TypeVar

import pytest

from typemap.type_eval import eval_typing, type_ast_to_type
from typemap.typing import _Cond, _GetAssociated

from typemap_extensions import (
    Attrs,  # noqa: F401
    IsAssignable,
    Iter,
    Member,
)


def _conv(src, **locals):
    return type_ast_to_type(
        ast.parse(textwrap.dedent(src).strip(), mode="eval"),
        globals(),
        locals,
    )


def _eval(src, **locals):
    return eval_typing(_conv(src, **locals))


def test_type_ast_plain_01():
    assert _conv("dict[str, list[T]]", T=int) == dict[str, list[int]]


def test_type_ast_cond_01():
    src = "list[T] if IsAssignable[T, int] else set[T]"
    assert (
        _conv(src, T=int) == _Cond[IsAssignable[int, int], list[int], set[int]]
    )
    assert _eval(src, T=int) == list[int]
    assert _eval(src, T=str) == set[str]


def test_type_ast_bool_ops_01():
    src = "int if IsAssignable[T, int] and not IsAssignable[T, bool] else str"
    assert _eval(src, T=int) is int
    assert _eval(src, T=bool) is str
    assert _eval(src, T=float) is str

    src = "int if IsAssignable[T, int] or IsAssignable[T, str] else None"
    assert _eval(src, T=bool) is int
    assert _eval(src, T=str) is int
    assert _eval(src, T=float) is NoneType

    src = "IsAssignable[T, int] and IsAssignable[T, bool]"
    assert _eval(src, T=bool) == Literal[True]
    assert _eval(src, T=int) == Literal[False]


def test_type_ast_comprehension_01():
    src = "tuple[*[list[t] for t in Iter[Ts] if IsAssignable[t, int]]]"
    assert _eval(src, Ts=tuple[int, str, bool]) == tuple[list[int], list[bool]]
    assert _eval(src, Ts=tuple[()]) == tuple[()]

    src = "tuple[str, *[list[t] for t in Iter[Ts]], str]"
    assert (
        _eval(src, Ts=tuple[int, bool])
        == tuple[str, list[int], list[bool], str]
    )


def test_type_ast_comprehension_02():
    src = """
    tuple[
        *[
            dict[a, b]
            for a in Iter[As]
            if not IsAssignable[a, bool]
            for b in Iter[tuple[a, None]]
            if IsAssignable[a, int] or IsAssignable[b, None]
        ]
    ]
    """
    assert (
        _eval(src, As=tuple[int, bool, str, float])
        == tuple[
            dict[int, int],
            dict[int, NoneType],
            dict[str, NoneType],
            dict[float, NoneType],
        ]
    )


def test_type_ast_comprehension_03():
    src = "tuple[*[*[t for t in Iter[Ts]]]]"
    assert _eval(src, Ts=tuple[int]) == tuple[int]


def test_type_ast_comprehension_04():
    # The inner t shadows the outer one, which it iterates over
    src = "tuple[*[list[t] for t in Iter[Ts] for t in Iter[t]]]"
    assert (
        _eval(src, Ts=tuple[tuple[int, str], tuple[bool]])
        == tuple[list[int], list[str], list[bool]]
    )

    res = _conv("tuple[*[list[t] for t in Iter[Ts]]]", Ts=tuple[int])
    unpack_map = res.__args__[0]
    ts, tv, body, cond = unpack_map.__args__
    assert isinstance(tv, TypeVar) and tv.__name__ == "t"
    assert body == list[tv]
    assert cond == Literal[True]


class Point:
    x: int
    y: str


def test_type_ast_member_access_01():
    src = "tuple[*[Member[m.name, set[m.type]] for m in Iter[Attrs[C]]]]"
    assert (
        _eval(src, C=Point)
        == tuple[
            Member[Literal["x"], set[int]],
            Member[Literal["y"], set[str]],
        ]
    )


def test_type_ast_member_access_02():
    def f[M](): ...

    (M,) = f.__type_params__
    assert _conv("M.name", M=M) == _GetAssociated[M, Literal["name"]]


def test_type_ast_any_all_01():
    src = "int if any(IsAssignable[t, int] for t in Iter[Ts]) else str"
    assert _eval(src, Ts=tuple[str, bool]) is int
    assert _eval(src, Ts=tuple[str, float]) is str
    assert _eval(src, Ts=tuple[()]) is str

    src = "int if all(IsAssignable[t, int] for t in Iter[Ts]) else str"
    assert _eval(src, Ts=tuple[int, bool]) is int
    assert _eval(src, Ts=tuple[int, str]) is str
    assert _eval(src, Ts=tuple[()]) is int

    src = """
    all(
        IsAssignable[a, b]
        for a in Iter[As]
        if IsAssignable[a, int]
        for b in Iter[tuple[int, a]]
    )
    """
    assert _eval(src, As=tuple[int, bool, str]) == Literal[True]
    assert _eval(src, As=tuple[int, float]) == Literal[True]
    assert _eval(src, As=tuple[bool, int]) == Literal[True]


def test_type_ast_errors_01():
    with pytest.raises(SyntaxError, match="unpacked lists"):
        _conv("tuple[[t for t in Iter[Ts]]]", Ts=tuple[int])
    with pytest.raises(SyntaxError, match="single variable"):
        _conv("tuple[*[a for a, b in Iter[Ts]]]", Ts=tuple[int])
    with pytest.raises(TypeError, match="Iter"):
        _conv("tuple[*[t for t in Ts]]", Ts=tuple[int])


def g[T](
    x: T,
) -> tuple[*[list[t] if IsAssignable[t, int] else t for t in Iter[T]]]:
    raise NotImplementedError


def test_type_ast_future_annotations_01():
    tree = ast.parse(g.__annotations__["return"], mode="eval")
    (T,) = g.__type_params__
    assert (
        eval_typing(type_ast_to_type(tree, globals(), {"T": tuple[int, str]}))
        == tuple[list[int], str]
    )

    # With the unbound type variable, it is just an unevaluated type
    res = type_ast_to_type(tree, globals(), {"T": T})
    assert res.__origin__ is tuple


def test_type_ast_namespace_01():
    # A lambda written in the annotation can see locals, and sees
    # globals live
    ns: dict = {}
    res = type_ast_to_type(
        ast.parse("(lambda: (X, Y))", mode="eval"), ns, {"X": int}
    )
    ns["Y"] = str
    assert res() == (int, str)
