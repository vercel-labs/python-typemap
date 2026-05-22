# SKIP MYPY

from __future__ import annotations

import collections
import textwrap
import unittest
from typing import (
    Annotated,
    Any,
    Callable,
    Generic,
    List,
    Literal,
    Never,
    Self,
    Tuple,
    TypeVar,
    Union,
    get_args,
    overload,
)

import pytest

from typemap.type_eval import _ensure_context, eval_typing
from typemap.type_eval._eval_operators import TypeMapError
from typemap.typing import _BoolLiteral

from typemap_extensions import (
    Attrs,
    Bool,
    FromUnion,
    GenericCallable,
    GetArg,
    GetArgs,
    GetMember,
    GetMemberType,
    GetSpecialAttr,
    GetAnnotations,
    IsAssignable,
    Iter,
    Length,
    IsEquivalent,
    Member,
    Members,
    NewProtocol,
    Overloaded,
    Param,
    Params,
    Slice,
    SpecialFormEllipsis,
    Concat,
    UpdateClass,
    Uppercase,
)

from typemap.type_eval import format_helper

type A[T] = T | None | Literal[False]
type B = A[int]

type OrGotcha[K] = K | Literal["gotcha!"]


class F[T]:
    fff: T


class F_int(F[int]):
    pass


type ConcatTuples[A, B] = tuple[
    *[x for x in Iter[A]],
    *[x for x in Iter[B]],
]

type MapRecursive[A] = NewProtocol[
    *[
        (
            Member[p.name, OrGotcha[p.type]]
            if not IsAssignable[p.type, A]
            else Member[p.name, OrGotcha[MapRecursive[A]]]
        )
        for p in Iter[tuple[*Attrs[A], *Attrs[F_int]]]
    ],
    Member[Literal["control"], float],
]


class Recursive:
    n: int
    m: str
    t: Literal[False]
    a: Recursive


def test_eval_types_1():
    assert str(eval_typing(B)) == "int | None | typing.Literal[False]"


def test_eval_types_2():
    evaled = eval_typing(MapRecursive[Recursive])

    # FIXME, or think about: this doesn't work, we currently evaluate it to an
    # *unexpanded* type alias.
    # # Validate that recursion worked properly and "Recursive" was only walked once
    # assert evaled.__annotations__["a"].__args__[0] is evaled

    # XXX: I don't have a good intuition about whether the inner MapRecursive ought to expand or not.
    #
    # Currently there are two test implementations for flatten_class
    # and the canonical one does not expand it and the
    # NewProtocol-based one does.
    #
    # I don't really think they ought to differ; something funny is
    # going on with recursively alias handling.
    res = format_helper.format_class(evaled)
    res = res.replace('tests.test_type_eval.MapRecursive', 'MapRecursive')

    assert res == textwrap.dedent("""\
        class MapRecursive[tests.test_type_eval.Recursive]:
            n: int | typing.Literal['gotcha!']
            m: str | typing.Literal['gotcha!']
            t: typing.Literal[False] | typing.Literal['gotcha!']
            a: MapRecursive[tests.test_type_eval.Recursive] | typing.Literal['gotcha!']
            fff: int | typing.Literal['gotcha!']
            control: float
        """)


# XXX: should this work???
# probably not?
@unittest.skip
def test_eval_types_3():
    evaled = eval_typing(F[bool])

    assert format_helper.format_class(evaled) == textwrap.dedent("""\
        class F[bool]:
            fff: bool
        """)


type UnlabeledTree = list[UnlabeledTree]
type IntTree = int | list[IntTree]
type GenericTree[T] = T | list[GenericTree[T]]
type XNode[X, Y] = X | list[YNode[X, Y]]
type YNode[X, Y] = Y | list[XNode[X, Y]]
type XYTree[X, Y] = XNode[X, Y] | YNode[X, Y]
type NestedTree = str | list[NestedTree] | list[IntTree]


def test_eval_types_4():
    d = eval_typing(
        Callable[
            [
                Param[Literal["a"], int, Literal["positional"]],
                Param[Literal["b"], int],
                Param[Literal["c"], int, Literal["positional_or_keyword"], int],
                Param[None, int, Literal["*"]],
                Param[Literal["d"], int, Literal["keyword"]],
                Param[Literal["e"], int, Literal["keyword"], int],
                Param[None, int, Literal["**"]],
            ],
            int,
        ]
    )
    assert (
        d
        == Callable[
            [
                Param[Literal["a"], int, Literal["positional"]],
                Param[Literal["b"], int],
                Param[Literal["c"], int, Literal["positional_or_keyword"], int],
                Param[None, int, Literal["*"]],
                Param[Literal["d"], int, Literal["keyword"]],
                Param[Literal["e"], int, Literal["keyword"], int],
                Param[None, int, Literal["**"]],
            ],
            int,
        ]
    )


class TA:
    x: int
    y: list[float]
    z: TB


class TB:
    x: str
    y: list[object]


type GetA1[A, B] = A
type GetA2[B, A] = A


def test_eval_arg_order():
    d = eval_typing(GetA1[int, str])
    assert d is int
    d = eval_typing(GetA2[str, int])
    assert d is int


def test_type_getattr_union_1():
    d = eval_typing(GetMemberType[TA | TB, Literal["x"]])
    assert d == int | str


def test_type_getattr_union_2():
    d = eval_typing(GetMemberType[TA, Literal["x"] | Literal["y"]])
    assert d == int | list[float]


def test_type_getattr_union_3():
    d = eval_typing(GetMemberType[TA | TB, Literal["x"] | Literal["y"]])
    assert d == int | list[float] | str | list[object]


def test_type_getattr_union_4():
    d = eval_typing(GetMemberType[TA, Literal["x", "y"]])
    assert d == int | list[float]


def test_type_getattr_union_5():
    d = eval_typing(GetMemberType[TA, Literal["x", "y"] | Literal["z"]])
    assert d == int | list[float] | TB


def test_getmembertype_classmethod_01():
    class C:
        @classmethod
        def f(cls, x: int) -> int: ...
        @classmethod
        def g(cls: type[C], x: int) -> int: ...
        @classmethod
        def h(cls: type[Self], x: int) -> int: ...

    d = eval_typing(GetMemberType[C, Literal["f"]])
    assert d == classmethod[C, Params[Param[Literal["x"], int]], int]
    d = eval_typing(GetMemberType[C, Literal["g"]])
    assert d == classmethod[C, Params[Param[Literal["x"], int]], int]
    d = eval_typing(GetMemberType[C, Literal["h"]])
    assert d == classmethod[Self, Params[Param[Literal["x"], int]], int]


def test_type_strings_1():
    d = eval_typing(Uppercase[Literal["foo"]])
    assert d == Literal["FOO"]


def test_type_strings_2():
    d = eval_typing(Uppercase[Literal["foo", "bar"]])
    assert d == Literal["FOO"] | Literal["BAR"]


def test_type_strings_3():
    d = eval_typing(Concat[Literal["foo"], Literal["bar"]])
    assert d == Literal["foobar"]


def test_type_strings_4():
    d = eval_typing(Concat[Literal["a", "b"], Literal["c", "d"]])
    assert d == Literal["ac"] | Literal["ad"] | Literal["bc"] | Literal["bd"]


def test_type_strings_5():
    d = eval_typing(Slice[Literal["abcd"], Literal[0], Literal[1]])
    assert d == Literal["a"]


def test_type_strings_6():
    d = eval_typing(Slice[Literal["abcd"], Literal[1], Literal[None]])
    assert d == Literal["bcd"]


def _is_generic_permutation(t1, t2):
    return t1.__origin__ == t2.__origin__ and collections.Counter(
        t1.__args__
    ) == collections.Counter(t2.__args__)


def test_type_from_union_01():
    d = eval_typing(FromUnion[int | bool])
    arg = FromUnion[int | str]
    d = eval_typing(arg)
    assert _is_generic_permutation(d, tuple[int, str])


def test_type_from_union_02():
    d = eval_typing(FromUnion[UnlabeledTree])
    assert _is_generic_permutation(d, tuple[list[UnlabeledTree]])

    d = eval_typing(GetArg[d, tuple, Literal[0]])
    assert d == list[UnlabeledTree]
    d = eval_typing(GetArg[d, list, Literal[0]])
    assert d == list[UnlabeledTree]
    d = eval_typing(FromUnion[d])
    assert _is_generic_permutation(d, tuple[list[UnlabeledTree]])


def test_type_from_union_03():
    d = eval_typing(FromUnion[IntTree])
    assert _is_generic_permutation(d, tuple[int, list[IntTree]])

    d = eval_typing(GetArg[d, tuple, Literal[1]])
    assert d == list[IntTree]
    d = eval_typing(GetArg[d, list, Literal[0]])
    assert d == int | list[IntTree]
    d = eval_typing(FromUnion[d])
    assert _is_generic_permutation(d, tuple[int, list[IntTree]])


def test_type_from_union_04():
    d = eval_typing(FromUnion[GenericTree[str]])
    assert _is_generic_permutation(d, tuple[str, list[GenericTree[str]]])

    d = eval_typing(GetArg[d, tuple, Literal[1]])
    assert d == list[GenericTree[str]]
    d = eval_typing(GetArg[d, list, Literal[0]])
    assert d == str | list[GenericTree[str]]
    d = eval_typing(FromUnion[d])
    assert _is_generic_permutation(d, tuple[str, list[GenericTree[str]]])


def test_type_from_union_05():
    d = eval_typing(FromUnion[XYTree[int, str]])
    assert _is_generic_permutation(
        d,
        tuple[XNode[int, str], YNode[int, str]],
    )

    x = eval_typing(GetArg[d, tuple, Literal[0]])
    assert x == int | list[str | list[XNode[int, str]]]

    x = eval_typing(FromUnion[x])
    assert _is_generic_permutation(
        x, tuple[int, list[str | list[XNode[int, str]]]]
    )
    x = eval_typing(GetArg[x, tuple, Literal[1]])
    assert x == list[str | list[XNode[int, str]]]
    x = eval_typing(GetArg[x, list, Literal[0]])
    assert x == str | list[XNode[int, str]]
    x = eval_typing(FromUnion[x])
    assert _is_generic_permutation(x, tuple[str, list[XNode[int, str]]])
    x = eval_typing(GetArg[x, tuple, Literal[1]])
    assert x == list[XNode[int, str]]
    x = eval_typing(GetArg[x, list, Literal[0]])
    assert x == int | list[str | list[XNode[int, str]]]

    y = eval_typing(GetArg[d, tuple, Literal[1]])
    assert y == str | list[int | list[YNode[int, str]]]

    y = eval_typing(FromUnion[y])
    assert _is_generic_permutation(
        y, tuple[str, list[int | list[YNode[int, str]]]]
    )
    y = eval_typing(GetArg[y, tuple, Literal[1]])
    assert y == list[int | list[YNode[int, str]]]
    y = eval_typing(GetArg[y, list, Literal[0]])
    assert y == int | list[YNode[int, str]]
    y = eval_typing(FromUnion[y])
    assert _is_generic_permutation(y, tuple[int, list[YNode[int, str]]])
    y = eval_typing(GetArg[y, tuple, Literal[1]])
    assert y == list[YNode[int, str]]
    y = eval_typing(GetArg[y, list, Literal[0]])
    assert y == str | list[int | list[YNode[int, str]]]


def test_type_from_union_06():
    d = eval_typing(FromUnion[NestedTree])
    assert _is_generic_permutation(
        d,
        tuple[str, list[NestedTree], list[IntTree]],
    )

    n = eval_typing(GetArg[d, tuple, Literal[1]])
    assert n == list[NestedTree]
    n = eval_typing(GetArg[n, list, Literal[0]])
    assert n == str | list[NestedTree] | list[IntTree]
    n = eval_typing(FromUnion[n])
    assert _is_generic_permutation(
        n, tuple[str, list[NestedTree], list[IntTree]]
    )

    n = eval_typing(
        FromUnion[GetArg[GetArg[n, tuple, Literal[1]], list, Literal[0]]]
    )
    assert _is_generic_permutation(
        n, tuple[str, list[NestedTree], list[IntTree]]
    )

    i = eval_typing(GetArg[d, tuple, Literal[2]])
    assert i == list[IntTree]
    i = eval_typing(GetArg[i, list, Literal[0]])
    assert i == int | list[IntTree]

    n = eval_typing(
        FromUnion[GetArg[GetArg[d, tuple, Literal[2]], list, Literal[0]]]
    )
    assert _is_generic_permutation(n, tuple[int, list[IntTree]])


def test_getmember_01():
    d = eval_typing(GetMember[TA, Literal["x"]])
    assert d == Member[Literal["x"], int, Never, Never, TA]
    d = eval_typing(GetMemberType[TA, Literal["a"]])
    assert d == Never

    d = eval_typing(GetMember[TA | TB, Literal["x"]])
    assert d == (
        Member[Literal["x"], int, Never, Never, TA]
        | Member[Literal["x"], str, Never, Never, TB]
    )
    with pytest.raises(TypeMapError):
        eval_typing(GetMember[TA | TB, Literal[""]])


type OnlyIntToSet[T] = set[T] if IsAssignable[T, int] else T


def test_getmember_02():
    class C:
        def f[TX](self, x: TX) -> OnlyIntToSet[TX]: ...

    m = eval_typing(GetMember[C, Literal["f"]])
    assert eval_typing(m.name) == Literal["f"]
    assert eval_typing(m.quals) == Literal["ClassVar"]
    assert eval_typing(m.definer) == C

    t = eval_typing(m.type)
    Vs = get_args(get_args(t)[0])
    L = get_args(t)[1]
    f = L(*Vs)
    assert (
        f
        == Callable[
            Params[Param[Literal["self"], C], Param[Literal["x"], Vs[0]]],
            OnlyIntToSet[Vs[0]],
        ]
    )


def test_getmember_03():
    class C:
        def f[T](self, x: T) -> OnlyIntToSet[T]: ...

    type P = IndirectProtocol[C]

    m = eval_typing(GetMember[P, Literal["f"]])
    assert eval_typing(m.name) == Literal["f"]
    assert eval_typing(m.quals) == Literal["ClassVar"]
    assert eval_typing(m.definer) != C  # eval typing generates a new class

    t = eval_typing(m.type)
    Vs = get_args(get_args(t)[0])
    L = get_args(t)[1]
    f = L(*Vs)
    assert (
        f
        == Callable[
            Params[
                Param[Literal["self"], Self],
                Param[Literal["x"], Vs[0]],
            ],
            OnlyIntToSet[Vs[0]],
        ]
    )


def test_getmember_04():
    class C:
        @overload
        def f(self, x: int) -> set[int]: ...

        @overload
        def f[T](self, x: T) -> T: ...

        def f(self, x): ...

    m = eval_typing(GetMember[C, Literal["f"]])
    mt = eval_typing(m.type)
    assert mt.__origin__ is Overloaded
    assert len(mt.__args__) == 2

    # Non-generic overload
    assert (
        eval_typing(IsAssignable[GetArg[mt, Overloaded, Literal[0]], Callable])
        == _BoolLiteral[True]
    )
    assert (
        mt.__args__[0]
        == Callable[
            Params[Param[Literal["self"], C], Param[Literal["x"], int]],
            set[int],
        ]
    )

    # Generic overload
    assert (
        eval_typing(
            IsAssignable[GetArg[mt, Overloaded, Literal[1]], GenericCallable]
        )
        == _BoolLiteral[True]
    )
    assert (
        eval_typing(mt.__args__[1].__args__[1](int))
        == Callable[
            Params[Param[Literal["self"], C], Param[Literal["x"], int]], int
        ]
    )


def test_getmember_05():
    # member method, generic self, complex return type
    class A:
        def member_method[T](self: T) -> GetMemberType[T, Literal["x"]]: ...

    class B(A):
        x: int

    class C(A):
        x: str

    m = eval_typing(GetMember[A, Literal["member_method"]])
    assert eval_typing(m.name) == Literal["member_method"]
    assert eval_typing(IsAssignable[m.type, GenericCallable])
    assert eval_typing(m.quals) == Literal["ClassVar"]
    assert eval_typing(m.definer) == A

    ft = m.__args__[1].__args__[1]
    with _ensure_context():
        assert (
            eval_typing(ft(A))
            == Callable[Params[Param[Literal["self"], A]], Never]
        )
        assert (
            eval_typing(ft(B))
            == Callable[Params[Param[Literal["self"], B]], int]
        )
        assert (
            eval_typing(ft(C))
            == Callable[Params[Param[Literal["self"], C]], str]
        )


def test_getmember_06():
    # member method, generic self, complex param type
    class A:
        def member_method[T](
            self: T, x: GetMemberType[T, Literal["x"]]
        ) -> None: ...

    class B(A):
        x: int

    class C(A):
        x: str

    m = eval_typing(GetMember[A, Literal["member_method"]])
    assert eval_typing(m.name) == Literal["member_method"]
    assert eval_typing(IsAssignable[m.type, GenericCallable])
    assert eval_typing(m.quals) == Literal["ClassVar"]
    assert eval_typing(m.definer) == A

    ft = m.__args__[1].__args__[1]
    with _ensure_context():
        assert (
            eval_typing(ft(A))
            == Callable[
                Params[Param[Literal["self"], A], Param[Literal["x"], Never]],
                None,
            ]
        )
        assert (
            eval_typing(ft(B))
            == Callable[
                Params[Param[Literal["self"], B], Param[Literal["x"], int]],
                None,
            ]
        )
        assert (
            eval_typing(ft(C))
            == Callable[
                Params[Param[Literal["self"], C], Param[Literal["x"], str]],
                None,
            ]
        )


def test_getmember_07():
    # class method, generic self, complex return type
    class A:
        @classmethod
        def class_method[T](cls: type[T]) -> GetMemberType[T, Literal["x"]]: ...

    class B(A):
        x: int

    class C(A):
        x: str

    m = eval_typing(GetMember[A, Literal["class_method"]])
    assert eval_typing(m.name) == Literal["class_method"]
    assert eval_typing(IsAssignable[m.type, GenericCallable])
    assert eval_typing(m.quals) == Literal["ClassVar"]
    assert eval_typing(m.definer) == A

    ft = m.__args__[1].__args__[1]
    with _ensure_context():
        assert eval_typing(ft(A)) == classmethod[A, Params[()], Never]
        assert eval_typing(ft(B)) == classmethod[B, Params[()], int]
        assert eval_typing(ft(C)) == classmethod[C, Params[()], str]


def test_getmember_08():
    # class method, generic self, complex param type
    class A:
        @classmethod
        def class_method[T](
            cls: type[T], x: GetMemberType[T, Literal["x"]]
        ) -> None: ...

    class B(A):
        x: int

    class C(A):
        x: str

    m = eval_typing(GetMember[A, Literal["class_method"]])
    assert eval_typing(m.name) == Literal["class_method"]
    assert eval_typing(IsAssignable[m.type, GenericCallable])
    assert eval_typing(m.quals) == Literal["ClassVar"]
    assert eval_typing(m.definer) == A

    ft = m.__args__[1].__args__[1]
    with _ensure_context():
        assert (
            eval_typing(ft(A))
            == classmethod[A, Params[Param[Literal["x"], Never]], None]
        )
        assert (
            eval_typing(ft(B))
            == classmethod[B, Params[Param[Literal["x"], int]], None]
        )
        assert (
            eval_typing(ft(C))
            == classmethod[C, Params[Param[Literal["x"], str]], None]
        )


def test_getmember_09():
    # member method, generic self, iterating over members
    class A:
        def f[T](
            self: T,
        ) -> tuple[
            *[
                m.type
                for m in Iter[Attrs[T]]
                if not IsAssignable[
                    Slice[m.name, None, Literal[1]], Literal["_"]
                ]
            ]
        ]: ...

    class B(A):
        a: bool
        b: str
        _c: int
        _d: float

    m = eval_typing(GetMember[A, Literal["f"]])
    assert eval_typing(m.name) == Literal["f"]
    assert eval_typing(IsAssignable[m.type, GenericCallable])
    assert eval_typing(m.quals) == Literal["ClassVar"]
    assert eval_typing(m.definer) == A

    ft = m.__args__[1].__args__[1]
    with _ensure_context():
        assert (
            eval_typing(ft(A))
            == Callable[Params[Param[Literal["self"], A]], tuple[()]]
        )
        assert (
            eval_typing(ft(B))
            == Callable[Params[Param[Literal["self"], B]], tuple[bool, str]]
        )


def test_getmember_10():
    # class method, generic self, iterating over members
    class A:
        @classmethod
        def f[T](
            cls: type[T],
        ) -> tuple[
            *[
                m.type
                for m in Iter[Attrs[T]]
                if not IsAssignable[
                    Slice[m.name, None, Literal[1]], Literal["_"]
                ]
            ]
        ]: ...

    class B(A):
        a: bool
        b: str
        _x: int
        _y: float

    m = eval_typing(GetMember[B, Literal["f"]])
    assert eval_typing(m.name) == Literal["f"]
    assert eval_typing(IsAssignable[m.type, GenericCallable])
    assert eval_typing(m.quals) == Literal["ClassVar"]
    assert eval_typing(m.definer) == A

    ft = m.__args__[1].__args__[1]
    with _ensure_context():
        assert eval_typing(ft(A)) == classmethod[A, Params[()], tuple[()]]
        assert (
            eval_typing(ft(B)) == classmethod[B, Params[()], tuple[bool, str]]
        )


def test_getarg_never():
    # Never decomposes to an empty union, so the operator never runs
    # and _mk_union returns Never
    d = eval_typing(GetArg[Never, object, Literal[0]])
    assert d is Never


def test_eval_getargs():
    t = dict[int, str]
    args = eval_typing(GetArgs[t, dict])
    assert args == tuple[int, str]

    t = dict
    args = eval_typing(GetArgs[t, dict])
    assert args == tuple[Any, Any]


@unittest.skip
def test_eval_getarg_callable_old():
    # oh hmmmmmmm -- yeah maybe callable could be fully bespoke if we
    # disallowed putting Callable here...!
    t = Callable[[int, str], str]
    args = eval_typing(GetArg[t, Callable, 0])
    assert args == tuple[int, str]

    t = Callable[int, str]
    args = eval_typing(GetArg[t, Callable, 0])
    assert args == tuple[int]

    t = Callable[[], str]
    args = eval_typing(GetArg[t, Callable, 0])
    assert args == tuple[()]

    t = Callable[..., str]
    args = eval_typing(GetArg[t, Callable, 0])
    assert (
        args
        == Params[
            Param[Literal[None], Any, Literal["*"]],
            Param[Literal[None], Any, Literal["**"]],
        ]
    )

    t = Callable
    args = eval_typing(GetArg[t, Callable, 0])
    assert (
        args
        == Params[
            Param[Literal[None], Any, Literal["*"]],
            Param[Literal[None], Any, Literal["**"]],
        ]
    )

    t = Callable
    args = eval_typing(GetArg[t, Callable, 1])
    assert args == Any


def test_eval_getarg_callable_01():
    t = Callable[[int, str], str]
    args = eval_typing(GetArg[t, Callable, Literal[0]])
    assert args == Params[Param[Literal[None], int], Param[Literal[None], str]]

    t = Callable[int, str]
    args = eval_typing(GetArg[t, Callable, Literal[0]])
    assert args == Params[Param[Literal[None], int]]

    t = Callable[[], str]
    args = eval_typing(GetArg[t, Callable, Literal[0]])
    assert args == Params[()]

    # ... becomes *args: Any, **kwargs: Any
    t = Callable[..., str]
    args = eval_typing(GetArg[t, Callable, Literal[0]])
    assert (
        args
        == Params[
            Param[Literal[None], Any, Literal["*"]],
            Param[Literal[None], Any, Literal["**"]],
        ]
    )

    t = Callable
    args = eval_typing(GetArg[t, Callable, Literal[0]])
    assert (
        args
        == Params[
            Param[Literal[None], Any, Literal["*"]],
            Param[Literal[None], Any, Literal["**"]],
        ]
    )

    t = Callable
    args = eval_typing(GetArg[t, Callable, Literal[1]])
    assert args == Any


def test_eval_getarg_callable_02():
    # GenericCallable
    T = TypeVar("T")

    # Params not wrapped
    f = Callable[[T], T]
    gc = GenericCallable[tuple[T], f]
    t = eval_typing(GetArg[gc, GenericCallable, Literal[0]])
    assert t == tuple[T]
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[gc, GenericCallable, Literal[1]])

    # Params wrapped
    f = Callable[
        [
            Param[Literal[None], T, Literal["positional"]],
            Param[Literal["y"], T],
            Param[Literal["z"], T, Literal["keyword"]],
        ],
        T,
    ]
    gc = GenericCallable[
        tuple[T],
        f,
    ]
    t = eval_typing(GetArg[gc, GenericCallable, Literal[0]])
    assert t == tuple[T]
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[gc, GenericCallable, Literal[1]])


type IndirectProtocol[T] = NewProtocol[*[m for m in Iter[Members[T]]],]
type GetMethodLike[T, Name] = GetArg[
    tuple[
        *[
            p.type
            for p in Iter[Members[T]]
            if (
                IsAssignable[p.type, Callable]
                or IsAssignable[p.type, staticmethod]
                or IsAssignable[p.type, classmethod]
                or IsAssignable[p.type, GenericCallable]
            )
            and IsAssignable[Name, p.name]
        ],
    ],
    tuple,
    Literal[0],
]


def test_eval_getarg_callable_03():
    # member function
    class C:
        def f(self, x: int, /, y: int, *, z: int) -> int: ...

    f = eval_typing(GetMethodLike[C, Literal["f"]])
    t = eval_typing(GetArg[f, Callable, Literal[0]])
    assert (
        t
        == Params[
            Param[Literal["self"], C, Literal["positional"]],
            Param[Literal["x"], int, Literal["positional"]],
            Param[Literal["y"], int],
            Param[Literal["z"], int, Literal["keyword"]],
        ]
    )
    t = eval_typing(GetArg[f, Callable, Literal[1]])
    assert t is int

    f = eval_typing(GetMethodLike[IndirectProtocol[C], Literal["f"]])
    t = eval_typing(GetArg[f, Callable, Literal[0]])
    assert (
        t
        == Params[
            Param[Literal["self"], Self, Literal["positional"]],
            Param[Literal["x"], int, Literal["positional"]],
            Param[Literal["y"], int],
            Param[Literal["z"], int, Literal["keyword"]],
        ]
    )
    t = eval_typing(GetArg[f, Callable, Literal[1]])
    assert t is int


def test_eval_getarg_callable_04():
    # classmethod
    class C:
        @classmethod
        def f(cls, x: int, /, y: int, *, z: int) -> int: ...

    f = eval_typing(GetMethodLike[C, Literal["f"]])
    t = eval_typing(GetArg[f, classmethod, Literal[0]])
    assert t == C
    t = eval_typing(GetArg[f, classmethod, Literal[1]])
    assert (
        t
        == Params[
            Param[Literal["x"], int, Literal["positional"]],
            Param[Literal["y"], int],
            Param[Literal["z"], int, Literal["keyword"]],
        ]
    )
    t = eval_typing(GetArg[f, classmethod, Literal[2]])
    assert t is int

    f = eval_typing(GetMethodLike[IndirectProtocol[C], Literal["f"]])
    t = eval_typing(GetArg[f, classmethod, Literal[0]])
    t = eval_typing(GetArg[f, classmethod, Literal[1]])
    assert (
        t
        == Params[
            Param[Literal["x"], int, Literal["positional"]],
            Param[Literal["y"], int],
            Param[Literal["z"], int, Literal["keyword"]],
        ]
    )
    t = eval_typing(GetArg[f, classmethod, Literal[2]])
    assert t is int


def test_eval_getarg_callable_05():
    # staticmethod
    class C:
        @staticmethod
        def f(x: int, /, y: int, *, z: int) -> int: ...

    f = eval_typing(GetMethodLike[C, Literal["f"]])
    t = eval_typing(GetArg[f, staticmethod, Literal[0]])
    assert (
        t
        == Params[
            Param[Literal["x"], int, Literal["positional"]],
            Param[Literal["y"], int],
            Param[Literal["z"], int, Literal["keyword"]],
        ]
    )
    t = eval_typing(GetArg[f, staticmethod, Literal[1]])
    assert t is int

    f = eval_typing(GetMethodLike[IndirectProtocol[C], Literal["f"]])
    t = eval_typing(GetArg[f, staticmethod, Literal[0]])
    assert (
        t
        == Params[
            Param[Literal["x"], int, Literal["positional"]],
            Param[Literal["y"], int],
            Param[Literal["z"], int, Literal["keyword"]],
        ]
    )
    t = eval_typing(GetArg[f, staticmethod, Literal[1]])
    assert t is int


def test_eval_getarg_callable_06():
    # member callable attr
    class C:
        f: Callable[[int], int]

    f = eval_typing(GetMethodLike[IndirectProtocol[C], Literal["f"]])
    t = eval_typing(GetArg[f, Callable, Literal[0]])
    assert t == Params[Param[Literal[None], int]]
    t = eval_typing(GetArg[f, Callable, Literal[1]])
    assert t is int


def test_eval_getarg_callable_07():
    # generic member function
    class C:
        def f[T](self, x: T, /, y: T, *, z: T) -> T: ...

    gc = eval_typing(GetMethodLike[C, Literal["f"]])
    _T = eval_typing(
        GetArg[GetArg[gc, GenericCallable, Literal[0]], tuple, Literal[0]]
    )
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[gc, GenericCallable, Literal[1]])


def test_eval_getarg_callable_08():
    # generic classmethod
    class C:
        @classmethod
        def f[T](cls, x: T, /, y: T, *, z: T) -> T: ...

    gc = eval_typing(GetMethodLike[C, Literal["f"]])
    _T = eval_typing(
        GetArg[GetArg[gc, GenericCallable, Literal[0]], tuple, Literal[0]]
    )
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[gc, GenericCallable, Literal[1]])


def test_eval_getarg_callable_09():
    # generic staticmethod
    class C:
        @staticmethod
        def f[T](x: T, /, y: T, *, z: T) -> T: ...

    gc = eval_typing(GetMethodLike[C, Literal["f"]])
    _T = eval_typing(
        GetArg[GetArg[gc, GenericCallable, Literal[0]], tuple, Literal[0]]
    )
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[gc, GenericCallable, Literal[1]])


def test_eval_getarg_tuple():
    t = tuple[int, ...]
    args = eval_typing(GetArg[t, tuple, Literal[1]])
    assert args == SpecialFormEllipsis

    t = tuple
    args = eval_typing(GetArg[t, tuple, Literal[0]])
    assert args == Any

    args = eval_typing(GetArg[t, tuple, Literal[1]])
    assert args == SpecialFormEllipsis


def test_eval_getarg_list():
    t = list[int]
    arg = eval_typing(GetArg[t, list, Literal[0]])
    assert arg is int

    t = List[int]
    arg = eval_typing(GetArg[t, list, Literal[0]])
    assert arg is int

    t = list
    arg = eval_typing(GetArg[t, list, Literal[0]])
    assert arg == Any

    t = List
    arg = eval_typing(GetArg[t, list, Literal[0]])
    assert arg == Any

    t = list[int]
    arg = eval_typing(GetArg[t, List, Literal[0]])
    assert arg is int

    t = List[int]
    arg = eval_typing(GetArg[t, List, Literal[0]])
    assert arg is int

    t = list
    arg = eval_typing(GetArg[t, List, Literal[0]])
    assert arg == Any

    t = List
    arg = eval_typing(GetArg[t, List, Literal[0]])
    assert arg == Any

    # indexing with -1 equivalent to 0
    t = list[int]
    arg = eval_typing(GetArg[t, list, Literal[-1]])
    assert arg is int

    t = List[int]
    arg = eval_typing(GetArg[t, list, Literal[-1]])
    assert arg is int

    t = list
    arg = eval_typing(GetArg[t, list, Literal[-1]])
    assert arg == Any

    t = List
    arg = eval_typing(GetArg[t, list, Literal[-1]])
    assert arg == Any

    t = list[int]
    arg = eval_typing(GetArg[t, List, Literal[-1]])
    assert arg is int

    t = List[int]
    arg = eval_typing(GetArg[t, List, Literal[-1]])
    assert arg is int

    t = list
    arg = eval_typing(GetArg[t, List, Literal[-1]])
    assert arg == Any

    t = List
    arg = eval_typing(GetArg[t, List, Literal[-1]])
    assert arg == Any

    # indexing with 1 always fails
    for t in [list[int], List[int], list, List]:
        for base in [list, List]:
            with pytest.raises(TypeMapError):
                eval_typing(GetArg[t, base, Literal[1]])


@pytest.mark.xfail(reason="Should this work?")
def test_eval_getarg_union_01():
    arg = eval_typing(GetArg[int | str, Union, Literal[0]])
    assert arg is int


@pytest.mark.xfail(reason="Should this work?")
def test_eval_getarg_union_02():
    arg = eval_typing(GetArg[GenericTree[int], GenericTree, Literal[0]])
    assert arg is int


def test_eval_getarg_custom_01():
    class A[T]:
        pass

    t = A[int]
    assert eval_typing(GetArg[t, A, Literal[0]]) is int
    assert eval_typing(GetArg[t, A, Literal[-1]]) is int
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, A, Literal[1]])

    t = A
    assert eval_typing(GetArg[t, A, Literal[0]]) == Any
    assert eval_typing(GetArg[t, A, Literal[-1]]) == Any
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, A, Literal[1]])


def test_eval_getarg_custom_02():
    T = TypeVar("T")

    class A(Generic[T]):
        pass

    t = A[int]
    assert eval_typing(GetArg[t, A, Literal[0]]) is int
    assert eval_typing(GetArg[t, A, Literal[-1]]) is int
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, A, Literal[1]])

    t = A
    assert eval_typing(GetArg[t, A, Literal[0]]) == Any
    assert eval_typing(GetArg[t, A, Literal[-1]]) == Any
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, A, Literal[1]])


def test_eval_getarg_custom_03():
    class A[T = str]:
        pass

    t = A[int]
    assert eval_typing(GetArg[t, A, Literal[0]]) is int
    assert eval_typing(GetArg[t, A, Literal[-1]]) is int
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, A, Literal[1]])

    t = A
    assert eval_typing(GetArg[t, A, Literal[0]]) is str
    assert eval_typing(GetArg[t, A, Literal[-1]]) is str
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, A, Literal[1]])


def test_eval_getarg_custom_04():
    T = TypeVar("T", default=str)

    class A(Generic[T]):
        pass

    t = A[int]
    assert eval_typing(GetArg[t, A, Literal[0]]) is int
    assert eval_typing(GetArg[t, A, Literal[-1]]) is int
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, A, Literal[1]])

    t = A
    assert eval_typing(GetArg[t, A, Literal[0]]) is str
    assert eval_typing(GetArg[t, A, Literal[-1]]) is str
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, A, Literal[1]])


TestTypeVar = TypeVar("TestTypeVar")


def test_eval_getarg_custom_05():
    # TypeVar declared outside of scope of class
    class ATree(Generic[TestTypeVar]):
        val: list[ATree[TestTypeVar]]

    t = ATree[int]
    assert eval_typing(GetArg[t, ATree, Literal[0]]) is int
    assert eval_typing(GetArg[t, ATree, Literal[-1]]) is int
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, ATree, Literal[1]])

    t = ATree
    assert eval_typing(GetArg[t, ATree, Literal[0]]) is Any
    assert eval_typing(GetArg[t, ATree, Literal[-1]]) is Any
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, ATree, Literal[1]])


def test_eval_getarg_custom_06():
    # TypeVar declared inside scope of class
    A = TypeVar("A")

    class ATree(Generic[A]):
        val: A | list[ATree[A]]

    t = ATree[int]
    assert eval_typing(GetArg[t, ATree, Literal[0]]) is int
    assert eval_typing(GetArg[t, ATree, Literal[-1]]) is int
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, ATree, Literal[1]])

    t = ATree
    assert eval_typing(GetArg[t, ATree, Literal[0]]) is Any
    assert eval_typing(GetArg[t, ATree, Literal[-1]]) is Any
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, ATree, Literal[1]])


# Doubly recursive generic types
NA = TypeVar("NA")
NB = TypeVar("NB")


class ANode(Generic[NA, NB]):
    val: NA | list[BNode[NA, NB]]


class BNode(Generic[NA, NB]):
    val: NB | list[ANode[NA, NB]]


class ABTree(Generic[NA, NB]):
    root: ANode[NA, NB] | BNode[NA, NB]


def test_eval_getarg_custom_07():
    t = ABTree[int, str]
    assert eval_typing(GetArg[t, ABTree, Literal[0]]) is int
    assert eval_typing(GetArg[t, ABTree, Literal[1]]) is str
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, ABTree, Literal[2]])

    t = ABTree
    assert eval_typing(GetArg[t, ABTree, Literal[0]]) is Any
    assert eval_typing(GetArg[t, ABTree, Literal[1]]) is Any
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, ABTree, Literal[2]])


T = TypeVar("T")


class Container(Generic[T]):
    data: list[T]

    def get[T](self, index: int, default: T) -> int | T: ...
    def map[U](self, func: Callable[[int], U]) -> list[U]: ...
    def convert[T](self, func: Callable[[int], T]) -> Container2[T]: ...


class Container2[T]: ...


def test_eval_getarg_custom_08():
    # Generic class with generic methods
    t = Container[int]
    assert eval_typing(GetArg[t, Container, Literal[0]]) is int
    assert eval_typing(GetArg[t, Container, Literal[-1]]) is int
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, Container, Literal[1]])

    t = Container
    assert eval_typing(GetArg[t, Container, Literal[0]]) is Any
    assert eval_typing(GetArg[t, Container, Literal[-1]]) is Any
    with pytest.raises(TypeMapError):
        eval_typing(GetArg[t, Container, Literal[1]])


def test_eval_getargs_generic_callable_01():
    T = TypeVar("T")
    t = GenericCallable[
        tuple[T], lambda T: Callable[Params[Param[Literal["x"], T]], int]
    ]
    args = eval_typing(GetArgs[t, GenericCallable])
    assert args == tuple[tuple[T]]


class OuterType:
    class InnerType:
        pass


def test_eval_typename_01():
    d = eval_typing(GetSpecialAttr[int, Literal["__name__"]])
    assert d == Literal["int"]
    d = eval_typing(GetSpecialAttr[str, Literal["__name__"]])
    assert d == Literal["str"]
    d = eval_typing(GetSpecialAttr[list[int], Literal["__name__"]])
    assert d == Literal["list"]
    d = eval_typing(GetSpecialAttr[list[str], Literal["__name__"]])
    assert d == Literal["list"]

    class C:
        pass

    d = eval_typing(GetSpecialAttr[OuterType, Literal["__name__"]])
    assert d == Literal["OuterType"]
    d = eval_typing(GetSpecialAttr[OuterType.InnerType, Literal["__name__"]])
    assert d == Literal["InnerType"]
    d = eval_typing(GetSpecialAttr[C, Literal["__name__"]])
    assert d == Literal["C"]

    d = eval_typing(GetSpecialAttr[GetA1[int, str], Literal["__name__"]])
    assert d == Literal["int"]


def test_eval_typename_02():
    d = eval_typing(GetSpecialAttr[int, Literal["__module__"]])
    assert d == Literal["builtins"]
    d = eval_typing(GetSpecialAttr[str, Literal["__module__"]])
    assert d == Literal["builtins"]
    d = eval_typing(GetSpecialAttr[list[int], Literal["__module__"]])
    assert d == Literal["builtins"]
    d = eval_typing(GetSpecialAttr[list[str], Literal["__module__"]])
    assert d == Literal["builtins"]

    class C:
        pass

    d = eval_typing(GetSpecialAttr[OuterType, Literal["__module__"]])
    assert d == Literal["tests.test_type_eval"]
    d = eval_typing(GetSpecialAttr[OuterType.InnerType, Literal["__module__"]])
    assert d == Literal["tests.test_type_eval"]
    d = eval_typing(GetSpecialAttr[C, Literal["__module__"]])
    assert d == Literal["tests.test_type_eval"]

    d = eval_typing(GetSpecialAttr[GetA1[int, str], Literal["__module__"]])
    assert d == Literal["builtins"]


def test_eval_typename_03():
    d = eval_typing(GetSpecialAttr[int, Literal["__qualname__"]])
    assert d == Literal["int"]
    d = eval_typing(GetSpecialAttr[str, Literal["__qualname__"]])
    assert d == Literal["str"]
    d = eval_typing(GetSpecialAttr[list[int], Literal["__qualname__"]])
    assert d == Literal["list"]
    d = eval_typing(GetSpecialAttr[list[str], Literal["__qualname__"]])
    assert d == Literal["list"]

    class C:
        pass

    d = eval_typing(GetSpecialAttr[OuterType, Literal["__qualname__"]])
    assert d == Literal["OuterType"]
    d = eval_typing(
        GetSpecialAttr[OuterType.InnerType, Literal["__qualname__"]]
    )
    assert d == Literal["OuterType.InnerType"]
    d = eval_typing(GetSpecialAttr[C, Literal["__qualname__"]])
    assert d == Literal["test_eval_typename_03.<locals>.C"]

    d = eval_typing(GetSpecialAttr[GetA1[int, str], Literal["__qualname__"]])
    assert d == Literal["int"]


type _Works[Ts, I] = Literal[True]
type Works[Ts] = _Works[Ts, Length[Ts]]

type _Fails[Ts, I] = Literal[False]
type Fails[Ts] = _Fails[Ts, Literal[0]]


def test_consistency_01():
    t = eval_typing(Works[tuple[int, str]])
    assert t == Literal[True]

    t = eval_typing(Fails[tuple[int, str]])
    assert t == Literal[False]


def test_uppercase_never():
    d = eval_typing(Uppercase[Never])
    assert d is Never


def test_never_is():
    d = eval_typing(IsAssignable[Never, Never])
    assert d == _BoolLiteral[True]


def test_eval_list_is_sub_01():
    d = eval_typing(list[IsAssignable[int, str]])
    assert d == list[_BoolLiteral[False]]
    d = eval_typing(list[not IsAssignable[int, str]])
    assert d == list[_BoolLiteral[True]]


def test_matches_01():
    d = eval_typing(IsEquivalent[int, int])
    assert d == _BoolLiteral[True]

    d = eval_typing(IsEquivalent[int, str])
    assert d == _BoolLiteral[False]

    d = eval_typing(IsEquivalent[str, int])
    assert d == _BoolLiteral[False]


def test_matches_02():
    class A:
        pass

    class B(A):
        pass

    class C(B):
        pass

    class D(A):
        pass

    class X:
        pass

    d = eval_typing(IsEquivalent[A, A])
    assert d == _BoolLiteral[True]

    d = eval_typing(IsEquivalent[A, B])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[B, A])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[B, C])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[C, B])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[C, D])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[D, C])
    assert d == _BoolLiteral[False]

    d = eval_typing(IsEquivalent[A, X])
    assert d == _BoolLiteral[False]


def test_matches_03():
    class A[T]:
        pass

    class B[T](A[T]):
        pass

    class C(B[int]):
        pass

    class D(A[str]):
        pass

    class X:
        pass

    d = eval_typing(IsEquivalent[A[int], A[int]])
    assert d == _BoolLiteral[True]
    d = eval_typing(IsEquivalent[A[int], A[str]])
    assert d == _BoolLiteral[True]

    d = eval_typing(IsEquivalent[A[int], B[int]])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[B[int], A[int]])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[A[int], B[str]])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[B[str], A[int]])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[B[int], C])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[C, B[int]])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[B[str], C])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[C, B[str]])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[C, D])
    assert d == _BoolLiteral[False]
    d = eval_typing(IsEquivalent[D, C])
    assert d == _BoolLiteral[False]

    d = eval_typing(IsEquivalent[A[int], X])
    assert d == _BoolLiteral[False]


def test_eval_iter_01():
    d = eval_typing(Iter[tuple[int, str]])
    assert tuple(d) == (int, str)

    d = eval_typing(Iter[Tuple[int, str]])
    assert tuple(d) == (int, str)

    d = eval_typing(Iter[tuple[(int, str)]])
    assert tuple(d) == (int, str)

    d = eval_typing(Iter[tuple[()]])
    assert tuple(d) == ()


type DuplicateTuple[T] = tuple[*[x for x in Iter[T]], *[x for x in Iter[T]]]
type ConcatTupleWithSelf[T] = ConcatTuples[T, T]


def test_eval_iter_02():
    # ensure iterating duplicate tuples can be iterated multiple times
    d = eval_typing(ConcatTuples[tuple[int, str], tuple[int, str]])
    assert d == tuple[int, str, int, str]

    d = eval_typing(DuplicateTuple[tuple[int, str]])
    assert d == tuple[int, str, int, str]

    d = eval_typing(ConcatTupleWithSelf[tuple[int, str]])
    assert d == tuple[int, str, int, str]


type NotLiteralGeneric[T] = not T
type AndLiteralGeneric[L, R] = L and R
type OrLiteralGeneric[L, R] = L or R
type LiteralGenericToLiteral[T] = Literal[True] if T else Literal[False]
type NotLiteralGenericToLiteral[T] = Literal[True] if not T else Literal[False]


def test_eval_bool_01():
    d = eval_typing(Bool[Literal[True]])
    assert d == _BoolLiteral[True]

    d = eval_typing(Bool[Literal[False]])
    assert d == _BoolLiteral[False]

    d = eval_typing(Bool[Literal[1]])
    assert d == _BoolLiteral[False]

    d = eval_typing(Bool[Literal[0]])
    assert d == _BoolLiteral[False]

    d = eval_typing(Bool[Literal["true"]])
    assert d == _BoolLiteral[False]

    d = eval_typing(Bool[Literal["false"]])
    assert d == _BoolLiteral[False]

    d = eval_typing(Bool[_BoolLiteral[True]])
    assert d == _BoolLiteral[True]

    d = eval_typing(Bool[_BoolLiteral[False]])
    assert d == _BoolLiteral[False]

    d = eval_typing(Bool[Never])
    assert d == _BoolLiteral[False]

    d = eval_typing(Bool[int])
    assert d == _BoolLiteral[False]

    class C:
        pass

    d = eval_typing(Bool[C])
    assert d == _BoolLiteral[False]

    d = eval_typing(Bool[True])
    assert d == _BoolLiteral[True]

    d = eval_typing(Bool[False])
    assert d == _BoolLiteral[False]


def test_eval_bool_02():
    d = eval_typing(Bool[Literal[True] | Literal[False]])
    assert d == _BoolLiteral[True]
    d = eval_typing(Bool[Literal[False] | Literal[True]])
    assert d == _BoolLiteral[True]
    d = eval_typing(Bool[Literal[True] | Never])
    assert d == _BoolLiteral[True]
    d = eval_typing(Bool[Never | Literal[True]])
    assert d == _BoolLiteral[True]
    d = eval_typing(Bool[Literal[False] | Never])
    assert d == _BoolLiteral[False]
    d = eval_typing(Bool[Never | Literal[False]])
    assert d == _BoolLiteral[False]
    d = eval_typing(Bool[Literal[True] | int])
    assert d == _BoolLiteral[True]
    d = eval_typing(Bool[int | Literal[True]])
    assert d == _BoolLiteral[True]
    d = eval_typing(Bool[Literal[False] | int])
    assert d == _BoolLiteral[False]
    d = eval_typing(Bool[int | Literal[False]])
    assert d == _BoolLiteral[False]
    d = eval_typing(Bool[int | str])
    assert d == _BoolLiteral[False]


def test_eval_bool_03():
    d = eval_typing(NotLiteralGeneric[Bool[Literal[True]]])
    assert d == _BoolLiteral[False]

    d = eval_typing(NotLiteralGeneric[Bool[Literal[False]]])
    assert d == _BoolLiteral[True]


type NestedBool0[T] = Bool[T]
type NestedBool1[T] = NestedBool0[Bool[T]]
type NestedBool2[T] = NestedBool1[Bool[T]]
type NestedBool3[T] = NestedBool2[Bool[T]]
type NestedBool4[T] = NestedBool3[Bool[T]]
type NestedBool5[T] = NestedBool4[Bool[T]]


def test_eval_bool_04():
    d = eval_typing(NestedBool5[Literal[True]])
    assert d == _BoolLiteral[True]

    d = eval_typing(NestedBool5[Literal[False]])
    assert d == _BoolLiteral[False]


type IsIntBool[T] = Bool[IsAssignable[T, int]]
type IsIntLiteral[T] = Literal[True] if Bool[IsIntBool[T]] else Literal[False]


def test_eval_bool_05():
    d = eval_typing(IsIntLiteral[int])
    assert d == Literal[True]

    d = eval_typing(IsIntLiteral[str])
    assert d == Literal[False]


def test_eval_bool_literal_01():
    d = eval_typing(_BoolLiteral[True])
    assert d == _BoolLiteral[True]
    d = eval_typing(_BoolLiteral[False])
    assert d == _BoolLiteral[False]
    d = eval_typing(_BoolLiteral[1])
    assert d == _BoolLiteral[True]
    d = eval_typing(_BoolLiteral[0])
    assert d == _BoolLiteral[False]
    d = eval_typing(_BoolLiteral[_BoolLiteral[True]])
    assert d == _BoolLiteral[True]
    d = eval_typing(_BoolLiteral[_BoolLiteral[False]])
    assert d == _BoolLiteral[False]


def test_eval_bool_literal_02():
    d = eval_typing(not _BoolLiteral[True])
    assert d == _BoolLiteral[False]

    d = eval_typing(NotLiteralGeneric[_BoolLiteral[True]])
    assert d == _BoolLiteral[False]
    d = eval_typing(NotLiteralGeneric[_BoolLiteral[False]])
    assert d == _BoolLiteral[True]


def test_eval_bool_literal_03():
    d = eval_typing(AndLiteralGeneric[_BoolLiteral[True], _BoolLiteral[True]])
    assert d == _BoolLiteral[True]
    d = eval_typing(AndLiteralGeneric[_BoolLiteral[True], _BoolLiteral[False]])
    assert d == _BoolLiteral[False]
    d = eval_typing(AndLiteralGeneric[_BoolLiteral[False], _BoolLiteral[True]])
    assert d == _BoolLiteral[False]
    d = eval_typing(AndLiteralGeneric[_BoolLiteral[False], _BoolLiteral[False]])
    assert d == _BoolLiteral[False]


def test_eval_bool_literal_04():
    d = eval_typing(OrLiteralGeneric[_BoolLiteral[True], _BoolLiteral[True]])
    assert d == _BoolLiteral[True]
    d = eval_typing(OrLiteralGeneric[_BoolLiteral[True], _BoolLiteral[False]])
    assert d == _BoolLiteral[True]
    d = eval_typing(OrLiteralGeneric[_BoolLiteral[False], _BoolLiteral[True]])
    assert d == _BoolLiteral[True]
    d = eval_typing(OrLiteralGeneric[_BoolLiteral[False], _BoolLiteral[False]])
    assert d == _BoolLiteral[False]


def test_eval_bool_literal_05():
    d = eval_typing(LiteralGenericToLiteral[_BoolLiteral[True]])
    assert d == Literal[True]
    d = eval_typing(LiteralGenericToLiteral[_BoolLiteral[False]])
    assert d == Literal[False]


def test_eval_bool_literal_06():
    d = eval_typing(NotLiteralGenericToLiteral[_BoolLiteral[True]])
    assert d == Literal[False]
    d = eval_typing(NotLiteralGenericToLiteral[_BoolLiteral[False]])
    assert d == Literal[True]


def test_eval_bool_literal_07():
    d = eval_typing(IsAssignable[_BoolLiteral[True], Literal[True]])
    assert d == _BoolLiteral[True]
    d = eval_typing(IsAssignable[_BoolLiteral[False], Literal[False]])
    assert d == _BoolLiteral[True]

    d = eval_typing(IsAssignable[Literal[True], _BoolLiteral[True]])
    assert d == _BoolLiteral[True]
    d = eval_typing(IsAssignable[Literal[False], _BoolLiteral[False]])
    assert d == _BoolLiteral[True]

    d = eval_typing(IsEquivalent[_BoolLiteral[True], Literal[True]])
    assert d == _BoolLiteral[True]
    d = eval_typing(IsEquivalent[_BoolLiteral[False], Literal[False]])
    assert d == _BoolLiteral[True]


def test_eval_bool_literal_error_01():
    with pytest.raises(TypeError, match="Expected literal type, got 'int'"):
        eval_typing(_BoolLiteral[int])


def test_eval_length_01():
    d = eval_typing(Length[tuple[int, str]])
    assert d == Literal[2]

    d = eval_typing(Length[Tuple[int, str]])
    assert d == Literal[2]

    d = eval_typing(Length[tuple[(int, str)]])
    assert d == Literal[2]

    d = eval_typing(Length[tuple[()]])
    assert d == Literal[0]

    d = eval_typing(Length[tuple[int, ...]])
    assert d == Literal[None]


def test_eval_slice_01():
    t = tuple[Literal[0], Literal[1], Literal[2], Literal[3], Literal[4]]
    d = eval_typing(Slice[t, Literal[1], Literal[3]])
    assert d == tuple[Literal[1], Literal[2]]
    d = eval_typing(Slice[t, Literal[1], Literal[None]])
    assert d == tuple[Literal[1], Literal[2], Literal[3], Literal[4]]
    d = eval_typing(Slice[t, Literal[None], Literal[3]])
    assert d == tuple[Literal[0], Literal[1], Literal[2]]
    d = eval_typing(Slice[t, Literal[None], Literal[None]])
    assert (
        d == tuple[Literal[0], Literal[1], Literal[2], Literal[3], Literal[4]]
    )
    d = eval_typing(Slice[t, Literal[1], Literal[1]])
    assert d == tuple[()]


def test_eval_slice_02():
    t = Literal["abcde"]
    d = eval_typing(Slice[t, Literal[1], Literal[3]])
    assert d == Literal["bc"]
    d = eval_typing(Slice[t, Literal[1], Literal[None]])
    assert d == Literal["bcde"]
    d = eval_typing(Slice[t, Literal[None], Literal[3]])
    assert d == Literal["abc"]
    d = eval_typing(Slice[t, Literal[None], Literal[None]])
    assert d == Literal["abcde"]
    d = eval_typing(Slice[t, Literal[1], Literal[1]])
    assert d == Literal[""]


def test_eval_slice_03():
    with pytest.raises(TypeMapError):
        eval_typing(Slice[int, Literal[1], Literal[2]])
    with pytest.raises(TypeMapError):
        eval_typing(Slice[dict[int, str], Literal[1], Literal[2]])


def test_eval_literal_idempotent_01():
    t = Literal[int]
    for _ in range(5):
        nt = eval_typing(t)
        assert t == nt
        t = nt


def test_is_literal_true_vs_one():
    assert (
        eval_typing(IsAssignable[Literal[True], Literal[1]])
        == _BoolLiteral[False]
    )


def test_callable_to_signature_01():
    from typemap.type_eval._eval_operators import _callable_type_to_signature

    # Test the example from the docstring:
    # def func(
    #     a: int,
    #     /,
    #     b: int,
    #     c: int = 0,
    #     *args: int,
    #     d: int,
    #     e: int = 0,
    #     **kwargs: int
    # ) -> int:
    callable_type = Callable[
        Params[
            Param[None, int],
            Param[Literal["b"], int],
            Param[Literal["c"], int, Literal["positional_or_keyword"], int],
            Param[None, int, Literal["*"]],
            Param[Literal["d"], int, Literal["keyword"]],
            Param[Literal["e"], int, Literal["keyword"], int],
            Param[None, int, Literal["**"]],
        ],
        int,
    ]

    sig = _callable_type_to_signature(callable_type)

    params = list(sig.parameters.values())
    assert len(params) == 7

    assert str(sig) == (
        '(_arg0: int, /, b: int, c: int = ..., *args: int, '
        'd: int, e: int = ..., **kwargs: int) -> int'
    )


def test_callable_to_signature_multi_kind_error():
    from typemap.type_eval._eval_operators import _callable_type_to_signature

    # Param can carry at most one kind; combining "positional" with
    # "keyword" is nonsense and should be rejected.
    callable_type = Callable[
        Params[Param[Literal["x"], int, Literal["positional", "keyword"]]],
        int,
    ]
    with pytest.raises(TypeError, match="at most one"):
        _callable_type_to_signature(callable_type)


def test_callable_to_signature_never_kind_error():
    from typemap.type_eval._eval_operators import _callable_type_to_signature

    # Never is not a valid kind; the explicit "normal" kind is
    # Literal["positional_or_keyword"].
    callable_type = Callable[
        Params[Param[Literal["x"], int, Never]],
        int,
    ]
    with pytest.raises(TypeError, match="cannot be Never"):
        _callable_type_to_signature(callable_type)


def test_new_protocol_with_methods_01():
    class C:
        def member_method(self, x: int) -> int: ...
        @classmethod
        def class_method(cls, x: int) -> int: ...
        @staticmethod
        def static_method(x: int) -> int: ...

    res = eval_typing(IndirectProtocol[C])
    fmt = format_helper.format_class(res)
    assert fmt == textwrap.dedent("""\
        class IndirectProtocol[tests.test_type_eval.test_new_protocol_with_methods_01.<locals>.C]:
            def member_method(self: Self, x: int) -> int: ...
            @classmethod
            def class_method(cls: type[typing.Self], x: int) -> int: ...
            @staticmethod
            def static_method(x: int) -> int: ...
    """)


def test_new_protocol_with_methods_02():
    C = NewProtocol[
        Member[
            Literal["member_method"],
            Callable[
                Params[Param[Literal["self"], Self], Param[Literal["x"], int]],
                int,
            ],
            Literal["ClassVar"],
        ],
        Member[
            Literal["class_method"],
            classmethod[Self, Params[Param[Literal["x"], int]], int],
            Literal["ClassVar"],
        ],
        Member[
            Literal["static_method"],
            staticmethod[Params[Param[Literal["x"], int]], int],
            Literal["ClassVar"],
        ],
    ]

    res = eval_typing(IndirectProtocol[C])
    fmt = format_helper.format_class(res)
    assert fmt == textwrap.dedent("""\
        class IndirectProtocol[typemap.type_eval._eval_operators.NewProtocol]:
            def member_method(self: Self, x: int) -> int: ...
            @classmethod
            def class_method(cls: type[typing.Self], x: int) -> int: ...
            @staticmethod
            def static_method(x: int) -> int: ...
    """)


def test_update_class_members_01():
    # Non-generic UpdateClass
    class A:
        a1: int  # not overridden
        a2: int  # overridden

        def __init_subclass__(
            cls,
        ) -> UpdateClass[
            Member[Literal["a2"], str],
            Member[Literal["b1"], str],
            Member[Literal["b2"], str],
        ]:
            super().__init_subclass__()

        def f(self) -> int: ...

    class B(A):
        b0: int  # kept
        b1: int  # overridden
        # b2 added in UpdateClass

        def g(self) -> int: ...  # kept

    # Attrs: UpdateClass members first (a2, b1, b2), then non-overridden (b0)
    attrs = eval_typing(Attrs[B])
    assert attrs.__args__ == (
        Member[Literal["a1"], int, Never, Never, A],
        Member[Literal["a2"], str, Never, Never, B],
        Member[Literal["b1"], str, Never, Never, B],
        Member[Literal["b2"], str, Never, Never, B],
        Member[Literal["b0"], int, Never, Never, B],
    )

    # Members
    members = eval_typing(Members[B])
    assert (
        members
        == tuple[
            Member[Literal["a1"], int, Never, Never, A],
            Member[Literal["a2"], str, Never, Never, B],
            Member[Literal["b1"], str, Never, Never, B],
            Member[Literal["b2"], str, Never, Never, B],
            Member[Literal["b0"], int, Never, Never, B],
            Member[
                Literal["__init_subclass__"],
                classmethod[
                    A,
                    Params[()],
                    UpdateClass[
                        Member[Literal["a2"], str],
                        Member[Literal["b1"], str],
                        Member[Literal["b2"], str],
                    ],
                ],
                Literal["ClassVar"],
                object,
                A,
            ],
            Member[
                Literal["f"],
                Callable[Params[Param[Literal["self"], A]], int],
                Literal["ClassVar"],
                object,
                A,
            ],
            Member[
                Literal["g"],
                Callable[Params[Param[Literal["self"], B]], int],
                Literal["ClassVar"],
                object,
                B,
            ],
        ]
    )

    # GetMember
    assert members == eval_typing(
        tuple[
            GetMember[B, Literal["a1"]],
            GetMember[B, Literal["a2"]],
            GetMember[B, Literal["b1"]],
            GetMember[B, Literal["b2"]],
            GetMember[B, Literal["b0"]],
            GetMember[B, Literal["__init_subclass__"]],
            GetMember[B, Literal["f"]],
            GetMember[B, Literal["g"]],
        ]
    )


type MembersExceptInitSubclass[T] = tuple[
    *[
        m
        for m in Iter[Members[T]]
        if not IsAssignable[m.name, Literal["__init_subclass__"]]
    ]
]


def test_update_class_members_02():
    # Generic UpdateClass, does not use T
    class A:
        a1: int  # not overridden
        a2: int  # overridden

        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[
            Member[Literal["a2"], str],
            Member[Literal["b1"], str],
            Member[Literal["b2"], str],
        ]:
            super().__init_subclass__()

        def f(self) -> int: ...

    class B(A):
        b0: int  # kept
        b1: int  # overridden
        # b2 added in UpdateClass

        def g(self) -> int: ...  # kept

    # Attrs: UpdateClass members first (a2, b1, b2), then non-overridden (b0)
    attrs = eval_typing(Attrs[B])
    assert (
        attrs
        == tuple[
            Member[Literal["a1"], int, Never, Never, A],
            Member[Literal["a2"], str, Never, Never, B],
            Member[Literal["b1"], str, Never, Never, B],
            Member[Literal["b2"], str, Never, Never, B],
            Member[Literal["b0"], int, Never, Never, B],
        ]
    )

    # Members
    members = eval_typing(MembersExceptInitSubclass[B])
    assert (
        members
        == tuple[
            Member[Literal["a1"], int, Never, Never, A],
            Member[Literal["a2"], str, Never, Never, B],
            Member[Literal["b1"], str, Never, Never, B],
            Member[Literal["b2"], str, Never, Never, B],
            Member[Literal["b0"], int, Never, Never, B],
            Member[
                Literal["f"],
                Callable[Params[Param[Literal["self"], A]], int],
                Literal["ClassVar"],
                object,
                A,
            ],
            Member[
                Literal["g"],
                Callable[Params[Param[Literal["self"], B]], int],
                Literal["ClassVar"],
                object,
                B,
            ],
        ]
    )

    # GetMember
    assert members == eval_typing(
        tuple[
            GetMember[B, Literal["a1"]],
            GetMember[B, Literal["a2"]],
            GetMember[B, Literal["b1"]],
            GetMember[B, Literal["b2"]],
            GetMember[B, Literal["b0"]],
            GetMember[B, Literal["f"]],
            GetMember[B, Literal["g"]],
        ]
    )


type AttrsAsSets[T] = UpdateClass[
    *[Member[m.name, set[m.type]] for m in Iter[Attrs[T]]]
]


def test_update_class_members_03():
    # Generic UpdateClass, uses T
    class A:
        a: int

        def __init_subclass__[T](
            cls: type[T],
        ) -> AttrsAsSets[T]:
            super().__init_subclass__()

        def f(self) -> int: ...

    class B(A):
        b: str

        def g(self) -> int: ...  # kept

    # Attrs
    attrs = eval_typing(Attrs[B])
    assert (
        attrs
        == tuple[
            Member[Literal["a"], set[int], Never, Never, B],
            Member[Literal["b"], set[str], Never, Never, B],
        ]
    )

    # Members
    members = eval_typing(MembersExceptInitSubclass[B])
    assert (
        members
        == tuple[
            Member[Literal["a"], set[int], Never, Never, B],
            Member[Literal["b"], set[str], Never, Never, B],
            Member[
                Literal["f"],
                Callable[Params[Param[Literal["self"], A]], int],
                Literal["ClassVar"],
                object,
                A,
            ],
            Member[
                Literal["g"],
                Callable[Params[Param[Literal["self"], B]], int],
                Literal["ClassVar"],
                object,
                B,
            ],
        ]
    )

    # GetMember
    assert members == eval_typing(
        tuple[
            GetMember[B, Literal["a"]],
            GetMember[B, Literal["b"]],
            GetMember[B, Literal["f"]],
            GetMember[B, Literal["g"]],
        ]
    )


def test_update_class_members_04():
    # Non-UpdateClass __init_subclass__ unaffected
    class A:
        a: int

        def __init_subclass__(
            cls,
        ) -> None:
            super().__init_subclass__()

        def f(self) -> int: ...

    class B(A):
        b: int

        def g(self) -> int: ...

    # Attrs
    attrs = eval_typing(Attrs[B])
    assert str(attrs) == str(
        tuple[
            Member[Literal["a"], int, Never, Never, A],
            Member[Literal["b"], int, Never, Never, B],
        ]
    )

    # Members
    members = eval_typing(Members[B])
    assert (
        members
        == tuple[
            Member[Literal["a"], int, Never, Never, A],
            Member[Literal["b"], int, Never, Never, B],
            Member[
                Literal["__init_subclass__"],
                classmethod[
                    A,
                    Params[()],
                    None,
                ],
                Literal["ClassVar"],
                object,
                A,
            ],
            Member[
                Literal["f"],
                Callable[Params[Param[Literal["self"], A]], int],
                Literal["ClassVar"],
                object,
                A,
            ],
            Member[
                Literal["g"],
                Callable[Params[Param[Literal["self"], B]], int],
                Literal["ClassVar"],
                object,
                B,
            ],
        ]
    )

    # GetMember
    assert members == eval_typing(
        tuple[
            GetMember[B, Literal["a"]],
            GetMember[B, Literal["b"]],
            GetMember[B, Literal["__init_subclass__"]],
            GetMember[B, Literal["f"]],
            GetMember[B, Literal["g"]],
        ]
    )


def test_update_class_members_05():
    # Generic base class with UpdateClass
    class A[T]:
        a: T

        def __init_subclass__[U](
            cls: type[U],
        ) -> AttrsAsSets[U]:
            super().__init_subclass__()

    class B(A[int]):
        b: str

    attrs = eval_typing(Attrs[B])
    assert attrs.__args__ == (
        Member[Literal["a"], set[int], Never, Never, B],
        Member[Literal["b"], set[str], Never, Never, B],
    )


def test_update_class_members_06():
    # Generic derived class with UpdateClass
    class A:
        a: int

        def __init_subclass__[T](
            cls: type[T],
        ) -> AttrsAsSets[T]:
            super().__init_subclass__()

    class B[T](A):
        b: T

    attrs = eval_typing(Attrs[B[int]])
    assert attrs.__args__ == (
        Member[Literal["a"], set[int], Never, Never, B[int]],
        Member[Literal["b"], set[int], Never, Never, B[int]],
    )

    attrs = eval_typing(Attrs[B[str]])
    assert attrs.__args__ == (
        Member[Literal["a"], set[int], Never, Never, B[str]],
        Member[Literal["b"], set[str], Never, Never, B[str]],
    )


def test_update_class_members_07():
    # Generic derived and base class with UpdateClass
    # derived from generic base
    class A[T]:
        a: T

        def __init_subclass__[U](
            cls: type[U],
        ) -> AttrsAsSets[U]:
            super().__init_subclass__()

    class B[T](A[tuple[T]]):
        b: T

    class C[T, U](A[U]):
        c: T

    attrs = eval_typing(Attrs[B[int]])
    assert attrs.__args__ == (
        Member[Literal["a"], set[tuple[int]], Never, Never, B[int]],
        Member[Literal["b"], set[int], Never, Never, B[int]],
    )

    attrs = eval_typing(Attrs[C[int, str]])
    assert attrs.__args__ == (
        Member[Literal["a"], set[str], Never, Never, C[int, str]],
        Member[Literal["c"], set[int], Never, Never, C[int, str]],
    )


def test_update_class_members_08():
    # Generic derived and base class with UpdateClass
    # derived from specialized base
    class A[T]:
        a: T

        def __init_subclass__[U](
            cls: type[U],
        ) -> AttrsAsSets[U]:
            super().__init_subclass__()

    class B[T](A[int]):
        b: T

    attrs = eval_typing(Attrs[B[int]])
    assert attrs.__args__ == (
        Member[Literal["a"], set[int], Never, Never, B[int]],
        Member[Literal["b"], set[int], Never, Never, B[int]],
    )

    attrs = eval_typing(Attrs[B[str]])
    assert attrs.__args__ == (
        Member[Literal["a"], set[int], Never, Never, B[str]],
        Member[Literal["b"], set[str], Never, Never, B[str]],
    )


def test_update_class_members_09():
    # Generic classes which use their type params in UpdateClass
    class A[V]:
        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[Member[Literal["a"], V], *Attrs[T]]:
            super().__init_subclass__()

    class B[V](A[int]):
        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[Member[Literal["b"], V], *Attrs[T]]:
            super().__init_subclass__()

    class C[V](B[str]):
        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[Member[Literal["c"], V], *Attrs[T]]:
            super().__init_subclass__()

    class D[V](C[float]):
        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[Member[Literal["d"], V]]:
            super().__init_subclass__()

    attrs = eval_typing(Attrs[A[int]])
    assert attrs == tuple[()]

    attrs = eval_typing(Attrs[B[str]])
    assert attrs == tuple[Member[Literal["a"], int, Never, Never, B[str]]]

    attrs = eval_typing(Attrs[C[float]])
    assert (
        attrs
        == tuple[
            Member[Literal["a"], int, Never, Never, C[float]],
            Member[Literal["b"], str, Never, Never, C[float]],
        ]
    )

    attrs = eval_typing(Attrs[D[bool]])
    assert (
        attrs
        == tuple[
            Member[Literal["a"], int, Never, Never, D[bool]],
            Member[Literal["b"], str, Never, Never, D[bool]],
            Member[Literal["c"], float, Never, Never, D[bool]],
        ]
    )


@pytest.mark.xfail(reason="Super sketchy....")
def test_update_class_members_10():
    # Generic classes which use other classes in their hierarchy
    # within UpdateClass.
    class A:
        a: int

        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[
            Member[Literal["b"], B[str]],
            Member[Literal["c"], C[float]],
            Member[Literal["d"], D[bool]],
        ]:
            super().__init_subclass__()

    class B[T](A):
        pass

    class C[T](B[T]):
        pass

    class D[T](C[T]):
        pass

    attrs = eval_typing(Attrs[C[int]])
    # A's __init_subclass__ adds Member["x", B[str]]; we get "a" from A and "x" from UpdateClass.
    assert (
        attrs
        == tuple[
            Member[Literal["a"], int, Never, Never, A],
            Member[Literal["b"], B[str], Never, Never, C[int]],
            Member[Literal["c"], C[float], Never, Never, C[int]],
            Member[Literal["d"], D[bool], Never, Never, C[int]],
        ]
    )


def test_update_class_members_11():
    class A:
        a: int

        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[*Members[T]]:
            super().__init_subclass__()

        def f(self) -> int: ...

    class B(A):
        b: str

        def g(self) -> str: ...

    attrs = eval_typing(Attrs[B])
    assert (
        attrs
        == tuple[
            Member[Literal["a"], int, Never, Never, B],
            Member[Literal["b"], str, Never, Never, B],
        ]
    )

    members = eval_typing(MembersExceptInitSubclass[B])
    assert (
        members
        == tuple[
            Member[Literal["a"], int, Never, Never, B],
            Member[Literal["b"], str, Never, Never, B],
            Member[
                Literal["f"],
                Callable[
                    Params[Param[Literal["self"], Self]],
                    int,
                ],
                Literal["ClassVar"],
                object,
                B,
            ],
            Member[
                Literal["g"],
                Callable[
                    Params[Param[Literal["self"], Self]],
                    str,
                ],
                Literal["ClassVar"],
                object,
                B,
            ],
        ]
    )


def test_update_class_inheritance_01():
    # current class init subclass is not applied
    class A:
        a: int

        def __init_subclass__[T](
            cls: type[T],
        ) -> AttrsAsSets[T]:
            super().__init_subclass__()

    class B(A):
        b: int

        def __init_subclass__[T](
            cls: type[T],
        ) -> AttrsAsSets[T]:
            super().__init_subclass__()

    attrs = eval_typing(Attrs[B])
    assert (
        attrs
        == tuple[
            Member[Literal["a"], set[int], Never, Never, B],
            Member[Literal["b"], set[int], Never, Never, B],
        ]
    )


def test_update_class_inheritance_02():
    # __init_subclass__ calls follow normal MRO
    class A:
        a: int

        def __init_subclass__[T](
            cls: type[T],
        ) -> AttrsAsSets[T]:
            super().__init_subclass__()

    class B(A):
        b: bytes

        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[
            *[Member[m.name, list[m.type]] for m in Iter[Attrs[T]]]
        ]:
            super().__init_subclass__()

    class C:
        c: float

        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[
            *[Member[m.name, tuple[m.type]] for m in Iter[Attrs[T]]]
        ]:
            super().__init_subclass__()

    class D(B, C):
        d: bool

    attrs = eval_typing(Attrs[D])
    # MRO = D, B, A, C, object
    assert attrs.__args__ == (
        Member[Literal["c"], tuple[set[list[float]]], Never, Never, D],
        Member[Literal["a"], tuple[set[list[int]]], Never, Never, D],
        Member[Literal["b"], tuple[set[list[bytes]]], Never, Never, D],
        Member[Literal["d"], tuple[set[list[bool]]], Never, Never, D],
    )


def test_update_class_is_assignable_01():
    # Subclass retains information about bases

    class A:
        a: int

        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[()]:
            super().__init_subclass__()

    class B(A):
        b: int

    class C(B):
        c: int

    assert eval_typing(IsAssignable[B, A]) == _BoolLiteral[True]
    assert eval_typing(IsAssignable[C, B]) == _BoolLiteral[True]
    assert eval_typing(IsAssignable[C, A]) == _BoolLiteral[True]


def test_update_class_getarg_01():
    # Subclass is able to get args from base classes

    class A[X0, X1]:
        a: X1

        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[()]:
            super().__init_subclass__()

    class B[Y](A[int, Y]):
        b: Y

    class C(B[float]):
        c: float

    assert eval_typing(GetArg[B[str], A, Literal[0]]) is int
    assert eval_typing(GetArg[B[str], A, Literal[1]]) is str
    assert eval_typing(GetArg[C, B, Literal[0]]) is float
    assert eval_typing(GetArg[C, A, Literal[0]]) is int
    assert eval_typing(GetArg[C, A, Literal[1]]) is float


def test_update_class_empty_01():
    class A:
        a: int

        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[()]:
            super().__init_subclass__()

    class B(A):
        b: int

    attrs = eval_typing(Attrs[B])
    assert (
        attrs
        == tuple[
            Member[Literal["a"], int, Never, Never, A],
            Member[Literal["b"], int, Never, Never, B],
        ]
    )


def test_update_class_never_removes():
    # A member with type Never in UpdateClass removes it
    class A:
        a: int
        b: str
        c: float

        def __init_subclass__[T](
            cls: type[T],
        ) -> UpdateClass[Member[Literal["b"], Never],]:
            super().__init_subclass__()

    class B(A):
        d: bool

    attrs = eval_typing(Attrs[B])
    assert (
        attrs
        == tuple[
            Member[Literal["a"], int, Never, Never, A],
            Member[Literal["c"], float, Never, Never, A],
            Member[Literal["d"], bool, Never, Never, B],
        ]
    )


##############

type XTest[X] = Annotated[X, 'blah']


class AnnoTest:
    a: XTest[int]
    b: XTest[Literal["test"]]


def test_type_eval_annotated_01():
    res = format_helper.format_class(eval_typing(AnnoTest))

    assert res == textwrap.dedent("""\
        class AnnoTest:
            a: typing.Annotated[int, 'blah']
            b: typing.Annotated[typing.Literal['test'], 'blah']
    """)


def test_type_eval_annotated_02():
    res = eval_typing(IsAssignable[GetMemberType[AnnoTest, Literal["a"]], int])
    assert res == _BoolLiteral[True]


def test_type_eval_annotated_03():
    res = eval_typing(Uppercase[GetMemberType[AnnoTest, Literal["b"]]])
    assert res == Literal["TEST"]


def test_type_eval_annotated_04():
    res = eval_typing(GetAnnotations[GetMemberType[AnnoTest, Literal["b"]]])
    assert res == Literal["blah"]


##############
# RaiseError tests

from typemap_extensions import RaiseError


def test_raise_error_basic():
    with pytest.raises(TypeMapError, match="Test error message"):
        eval_typing(RaiseError[Literal["Test error message"]])


def test_raise_error_with_types():
    with pytest.raises(TypeMapError, match="Broadcast mismatch.*int.*str"):
        eval_typing(RaiseError[Literal["Broadcast mismatch"], int, str])


def test_raise_error_with_literal_types():
    with pytest.raises(
        TypeMapError, match="Shape mismatch.*Literal\\[4\\].*Literal\\[3\\]"
    ):
        eval_typing(
            RaiseError[Literal["Shape mismatch"], Literal[4], Literal[3]]
        )
