from __future__ import annotations

import ast
import textwrap

from types import NoneType

from typing import Literal, TypeVar

import pytest

from typemap.annotations import (
    BindingEnvironment,
    BindingNamespace,
    get_annotate_ast,
)
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
            dict[int, None],
            dict[str, None],
            dict[float, None],
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


def _class_env(**classdict):
    return BindingEnvironment(
        globals={**globals(), "X": str, "Ts": tuple[int]},
        closure={},
        classdict=classdict,
    )


def test_type_ast_class_scope_01():
    env = _class_env(X=int, Ts=tuple[bool])
    assert type_ast_to_type("list[X]", env=env) == list[int]

    # Lambda bodies can't see the class namespace, but defaults can
    assert type_ast_to_type("(lambda: X)", env=env)() is str
    assert type_ast_to_type("(lambda x=X: x)", env=env)() is int

    # Only the outermost iterable of a comprehension can see it
    src = "tuple[*[tuple[t, X] for t in Iter[Ts]]]"
    assert (
        eval_typing(type_ast_to_type(src, env=env)) == tuple[tuple[bool, str]]
    )


def test_type_ast_class_scope_02():
    # Names declared global bypass the class namespace
    env = _class_env(X=int)
    ns = BindingNamespace(
        class_name="C", global_names=("X",), mangled_names=None
    )
    assert type_ast_to_type("X", env=env, namespace=ns) is str


def test_type_ast_class_scope_03():
    # any and all are syntax, even if the class has its own
    env = _class_env(any=None, Ts=tuple[str, bool])
    src = "int if any(IsAssignable[t, int] for t in Iter[Ts]) else str"
    assert eval_typing(type_ast_to_type(src, env=env)) is int


class Mangled:
    _C__y = bool


def test_type_ast_mangling_01():
    ns = BindingNamespace(class_name="_C", global_names=(), mangled_names=None)
    env = BindingEnvironment(
        globals={"_C__X": int, "Mangled": Mangled}, closure={}, classdict=None
    )
    assert type_ast_to_type("list[__X]", env=env, namespace=ns) == list[int]
    assert type_ast_to_type("Mangled.__y", env=env, namespace=ns) is bool
    assert (
        type_ast_to_type("(lambda __x: __x)(__X)", env=env, namespace=ns) is int
    )
    assert (
        type_ast_to_type("__X__", globals={"__X__": str}, namespace=ns) is str
    )

    # Like for the bounds of a generic class's type params, where only
    # some names are mangled
    ns = BindingNamespace(
        class_name="C", global_names=(), mangled_names=("__X",)
    )
    env = BindingEnvironment(
        globals={"_C__X": int, "__Y": str}, closure={}, classdict=None
    )
    assert (
        type_ast_to_type("tuple[__X, __Y]", env=env, namespace=ns)
        == tuple[int, str]
    )


_SCOPING_SRC = """
X = int

class C:
    X = str
    __Y = bool
    a: X
    b: lambda: X
    c: lambda x=X: x
    d: __Y

g = "global"

def outer():
    g = "nonlocal"
    class D:
        global g
        ann: g
    D.g = "class"
    return D

D = outer()
"""


def test_type_ast_decompiled_scoping_01():
    # Evaluating decompiled annotations matches evaluating them for real.
    # (dont_inherit, so as not to get this file's __future__ import.)
    ns: dict = {}
    exec(compile(_SCOPING_SRC, "<scoping>", "exec", dont_inherit=True), ns)

    def conv(cls):
        annos, info = get_annotate_ast(cls.__annotate__)
        assert isinstance(annos, dict)
        return {
            k: type_ast_to_type(v, env=info.env, namespace=info.namespace)
            for k, v in annos.items()
        }

    res = conv(ns["C"])
    real = ns["C"].__annotations__
    assert res["a"] is real["a"] is str
    assert res["b"]() is real["b"]() is int
    assert res["c"]() is real["c"]() is str
    assert res["d"] is real["d"] is bool

    assert conv(ns["D"]) == ns["D"].__annotations__ == {"ann": "global"}
