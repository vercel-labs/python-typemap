# SKIP MYPY: lots of weird testing stuff
# but TODO: some failures seem bad

import textwrap
import typing
from typing import Literal, Never, TypeVar, TypedDict, Union, ReadOnly

from typemap.type_eval import eval_typing, _ensure_context
from typemap_extensions import (
    Attrs,
    FromUnion,
    GetArg,
    InitField,
    IsAssignable,
    Iter,
    Member,
    Members,
    NewProtocol,
    Uppercase,
)

from typemap.type_eval import format_helper

type OrGotcha[K] = K | Literal['gotcha!']

type StrForInt[X] = (str | OrGotcha[X]) if X is int else (X | OrGotcha[X])


class Ordinary:
    ordinary: str


class AnotherBase[I]:
    iii: OrGotcha[StrForInt[I]]


# This K is dodgy
K = TypeVar("K")


class Base[T]:
    t: dict[str, StrForInt[T]]

    fin: typing.Final[int]

    def foo(self, a: T | None, *, b: int = 0) -> dict[str, T]:
        pass

    def base[Z](self, a: T | Z | None, b: K) -> dict[str, T | Z]:
        pass

    @classmethod
    def cbase(cls, a: T | None, b: K) -> dict[str, T]:
        pass

    @staticmethod
    def sbase[Z](a: OrGotcha[T] | Z | None, b: K) -> dict[str, T | Z]:
        pass


class CMethod:
    @classmethod
    def cbase2(cls, lol: int, /, a: bool | None) -> int:
        pass


class Wrapper[X](Base[X], AnotherBase[X]):
    x: "Wrapper[X | None]"


class Mine(Wrapper[int]):
    pass


class Last[O]:
    last: O | Literal[True]


class Final(Mine, Ordinary, Wrapper[float], AnotherBase[float], Last[int]):
    pass


type BaseArg[T] = (
    GetArg[T, Base, Literal[0]] if IsAssignable[T, Base] else Never
)


type AllOptional[T] = NewProtocol[
    *[Member[p.name, p.type | None, p.quals] for p in Iter[Attrs[T]]]
]

type OptionalFinal = AllOptional[Final]


type Capitalize[T] = NewProtocol[
    *[Member[Uppercase[p.name], p.type, p.quals] for p in Iter[Attrs[T]]]
]

type Prims[T] = NewProtocol[
    *[p for p in Iter[Attrs[T]] if IsAssignable[p.type, int | str]]
]

type NoLiterals1[T] = NewProtocol[
    *[
        Member[
            p.name,
            Union[
                *[
                    t
                    for t in Iter[FromUnion[p.type]]
                    # XXX: 'typing.Literal' is not *really* a type...
                    # Maybe we can't do this, which maybe is fine.
                    if not IsAssignable[t, Literal]
                ]
            ],
            p.quals,
        ]
        for p in Iter[Attrs[T]]
    ]
]


# Try to implement IsLiteral. This is basically what is recommended
# for doing it in TS.
# XXX: This doesn't work in python! We can subtype str!
type IsLiteral[T] = (
    Literal[True]
    if (
        (IsAssignable[T, str] and not IsAssignable[str, T])
        or (IsAssignable[T, bytes] and not IsAssignable[bytes, T])
        or (IsAssignable[T, bool] and not IsAssignable[bool, T])
        or (IsAssignable[T, int] and not IsAssignable[int, T])
        # XXX: enum, None
    )
    else Literal[False]
)

type NoLiterals2[T] = NewProtocol[
    *[
        Member[
            p.name,
            Union[
                *[
                    t
                    for t in Iter[FromUnion[p.type]]
                    # XXX: 'typing.Literal' is not *really* a type...
                    # Maybe we can't do this, which maybe is fine.
                    # if not IsAssignabletype[t, Literal]
                    if not IsAssignable[IsLiteral[t], Literal[True]]
                ]
            ],
            p.quals,
        ]
        for p in Iter[Attrs[T]]
    ]
]


# Subtyping Eval used to do something
class Eval[T]:
    pass


class Loop(Eval[int]):
    loop: Loop


class Foo(Eval[int]):
    bar: Bar


class Bar(Eval[float]):
    foo: Foo


def test_type_dir_link_1():
    d = eval_typing(Loop)
    loop = d.__annotations__["loop"]
    assert loop is d
    assert loop is Loop


def test_type_dir_link_2():
    d = eval_typing(Foo)
    loop = d.__annotations__["bar"].__annotations__["foo"]
    assert loop is d
    assert loop is Foo


def test_type_dir_1a():
    d = eval_typing(Final)

    assert format_helper.format_class(d) == textwrap.dedent("""\
        class Final:
            last: int | typing.Literal[True]
            iii: str | int | typing.Literal['gotcha!']
            t: dict[str, str | int | typing.Literal['gotcha!']]
            fin: typing.Final[int]
            x: tests.test_type_dir.Wrapper[int | None]
            ordinary: str
            def foo(self: Self, a: int | None, *, b: int = ...) -> dict[str, int]: ...
            def base[Z](self: Self, a: int | Z | None, b: ~K) -> dict[str, int | Z]: ...
            @classmethod
            def cbase(cls: type[typing.Self], a: int | None, b: ~K) -> dict[str, int]: ...
            @staticmethod
            def sbase[Z](a: OrGotcha[int] | Z | None, b: ~K) -> dict[str, int | Z]: ...
    """)


def test_type_dir_1b():
    d = eval_typing(CMethod)

    assert format_helper.format_class(d) == textwrap.dedent("""\
        class CMethod:
            @classmethod
            def cbase2(cls: type[typing.Self], lol: int, /, a: bool | None) -> int: ...
    """)


def test_type_dir_2():
    d = eval_typing(OptionalFinal)

    # XXX: `Atrs` skips methods, true to its name. Perhaps we just need
    #      `Members` that would iterate over everything
    assert format_helper.format_class(d) == textwrap.dedent("""\
        class AllOptional[tests.test_type_dir.Final]:
            last: int | typing.Literal[True] | None
            iii: str | int | typing.Literal['gotcha!'] | None
            t: dict[str, str | int | typing.Literal['gotcha!']] | None
            fin: typing.Final[int | None]
            x: tests.test_type_dir.Wrapper[int | None] | None
            ordinary: str | None
    """)


def test_type_dir_3():
    d = eval_typing(Capitalize[Final])

    assert format_helper.format_class(d) == textwrap.dedent("""\
        class Capitalize[tests.test_type_dir.Final]:
            LAST: int | typing.Literal[True]
            III: str | int | typing.Literal['gotcha!']
            T: dict[str, str | int | typing.Literal['gotcha!']]
            FIN: typing.Final[int]
            X: tests.test_type_dir.Wrapper[int | None]
            ORDINARY: str
    """)


def test_type_dir_4():
    d = eval_typing(Prims[Final])

    assert format_helper.format_class(d) == textwrap.dedent("""\
        class Prims[tests.test_type_dir.Final]:
            last: int | typing.Literal[True]
            fin: typing.Final[int]
            ordinary: str
    """)


def test_type_dir_5():
    global fuck
    d = eval_typing(NoLiterals1[Final])

    assert format_helper.format_class(d) == textwrap.dedent("""\
        class NoLiterals1[tests.test_type_dir.Final]:
            last: int
            iii: str | int
            t: dict[str, str | int | typing.Literal['gotcha!']]
            fin: typing.Final[int]
            x: tests.test_type_dir.Wrapper[int | None]
            ordinary: str
    """)


def test_type_dir_6():
    d = eval_typing(NoLiterals2[Final])

    assert format_helper.format_class(d) == textwrap.dedent("""\
        class NoLiterals2[tests.test_type_dir.Final]:
            last: int
            iii: str | int
            t: dict[str, str | int | typing.Literal['gotcha!']]
            fin: typing.Final[int]
            x: tests.test_type_dir.Wrapper[int | None]
            ordinary: str
    """)


class Simple[T]:
    simple: T


class Funny[T](Simple[list[T]]):
    pass


class Funny2(Funny[int]):
    pass


def test_type_dir_7():
    d = eval_typing(Funny2)

    assert format_helper.format_class(d) == textwrap.dedent("""\
        class Funny2:
            simple: list[int]
    """)


def test_type_dir_9():
    d = eval_typing(Last[bool])

    assert format_helper.format_class(d) == textwrap.dedent("""\
        class Last[bool]:
            last: bool | typing.Literal[True]
    """)


def test_type_dir_10():
    class Lurr:
        def foo[T](x: T) -> int if IsAssignable[T, str] else list[int]: ...

    d = eval_typing(Lurr)

    assert format_helper.format_class(d) == textwrap.dedent("""\
        class Lurr:
            foo: typing.ClassVar[typemap.typing.GenericCallable[tuple[T], <...>]]
    """)

    member = _get_member(eval_typing(Members[Lurr]), "foo")

    fn = member.__args__[1].__args__[1]
    with _ensure_context():
        assert fn(str).__args__[1] is int
        assert fn(bool).__args__[1] == list[int]


def test_type_dir_get_arg_1():
    d = eval_typing(BaseArg[Final])
    assert d is int


def _get_member(members, name):
    return next(
        iter(m for m in members.__args__ if m.__args__[0].__args__[0] == name)
    )


def test_type_members_attr_1():
    d = eval_typing(Members[Final])
    member = _get_member(d, "ordinary")
    assert typing.get_origin(member) is Member
    _, _, _, _, origin = typing.get_args(member)
    assert origin.__name__ == "Ordinary"


def test_type_members_attr_2():
    d = eval_typing(Members[Final])
    member = _get_member(d, "last")
    assert typing.get_origin(member) is Member
    _, typ, _, _, origin = typing.get_args(member)
    assert typ == int | Literal[True]
    assert str(origin) == "tests.test_type_dir.Last[int]"


def test_type_members_attr_3():
    d = eval_typing(Members[Last[int]])
    member = _get_member(d, "last")
    assert typing.get_origin(member) is Member
    _, typ, _, _, origin = typing.get_args(member)
    assert typ == int | Literal[True]
    assert str(origin) == "tests.test_type_dir.Last[int]"


def test_type_members_func_1():
    d = eval_typing(Members[Final])
    member = _get_member(d, "foo")
    assert typing.get_origin(member) is Member
    name, typ, quals, _, origin = typing.get_args(member)
    assert name == typing.Literal["foo"]
    assert quals == typing.Literal["ClassVar"]

    assert (
        str(typ)
        == "\
typing.Callable[\
typemap.typing.Params[typemap.typing.Param[typing.Literal['self'], tests.test_type_dir.Base[int], typing.Never, typing.Never], \
typemap.typing.Param[typing.Literal['a'], int | None, typing.Never, typing.Never], \
typemap.typing.Param[typing.Literal['b'], int, typing.Literal['keyword'], int]], \
dict[str, int]]"
    )

    assert str(origin) == "tests.test_type_dir.Base[int]"


def test_type_members_func_2():
    d = eval_typing(Members[Final])
    member = _get_member(d, "cbase")
    assert typing.get_origin(member) is Member
    name, typ, quals, _origin, _ = typing.get_args(member)
    assert name == typing.Literal["cbase"]
    assert quals == typing.Literal["ClassVar"]

    assert (
        str(typ)
        == "\
classmethod[tests.test_type_dir.Base[int], typemap.typing.Params[typemap.typing.Param[typing.Literal['a'], int | None, typing.Never, typing.Never], typemap.typing.Param[typing.Literal['b'], ~K, typing.Never, typing.Never]], dict[str, int]]"
    )


def test_type_members_func_3():
    d = eval_typing(Members[Final])
    member = _get_member(d, "sbase")
    assert typing.get_origin(member) is Member
    name, typ, quals, _origin, _ = typing.get_args(member)
    assert name == typing.Literal["sbase"]
    assert quals == typing.Literal["ClassVar"]

    assert str(typ) == "typemap.typing.GenericCallable[tuple[Z], <...>]"

    evaled = eval_typing(
        typing.get_args(typ)[1](*typing.get_args(typing.get_args(typ)[0]))
    )
    assert (
        str(evaled)
        == "staticmethod[typemap.typing.Params[typemap.typing.Param[typing.Literal['a'], int | typing.Literal['gotcha!'] | Z | None, typing.Never, typing.Never], typemap.typing.Param[typing.Literal['b'], ~K, typing.Never, typing.Never]], dict[str, int | Z]]"
    )


# Test initializers


class FieldArgs(TypedDict, total=False):
    foo: ReadOnly[bool]
    bar: ReadOnly[int]


class Field[T: FieldArgs](InitField[T]):
    pass


class Inited:
    foo: int = 10
    bar: bool = Field(foo=False)


def test_type_dir_inits_1():
    d = eval_typing(Inited)

    assert format_helper.format_class(d) == textwrap.dedent("""\
        class Inited:
            foo: int = 10
            bar: bool = Field(foo=False)
    """)


class AnnoyingProjection:
    def foo[T: typing.Member](self, a: T) -> T.name:
        pass

    def bar[T: typing.Member](self, a: T) -> 'T.name':
        pass


def test_type_dir_dot_projection_1():
    d = eval_typing(AnnoyingProjection)

    assert format_helper.format_class(d) == textwrap.dedent("""\
         class AnnoyingProjection:
             foo: typing.ClassVar[typemap.typing.GenericCallable[tuple[T], <...>]]
             bar: typing.ClassVar[typemap.typing.GenericCallable[tuple[T], <...>]]
    """)
