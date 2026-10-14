import textwrap

from typing import Literal, Unpack

from typemap.type_eval import (
    eval_call,
    eval_call_with_types,
    eval_typing,
)
from typemap_extensions import (
    BaseTypedDict,
    NewProtocol,
    Attrs,
    IsAssignable,
    Member,
    GetMemberType,
    GetArg,
)

from typemap.type_eval import format_helper


class Property[T]:
    pass


class Link[T]:
    pass


type PropsOnly[T] = NewProtocol[
    *[p for p in Attrs[T] if IsAssignable[p.type, Property]]
]

# Conditional type alias!
type FilterLinks[T] = (
    Link[PropsOnly[GetArg[T, Link, Literal[0]]]] if IsAssignable[T, Link] else T
)


def select[K: BaseTypedDict](
    rcv: A,
    /,
    **kwargs: Unpack[K],
) -> NewProtocol[
    *[
        Member[
            c.name,
            FilterLinks[GetMemberType[A, c.name]],
        ]
        for c in Attrs[K]
    ]
]:
    raise NotImplementedError


# Basic filtering
class Tgt2:
    pass


class Tgt:
    name: Property[str]
    tgt2: Link[Tgt2]


class A:
    x: Property[int]
    y: Property[bool | None]
    z: Link[Tgt]
    w: Property[list[str]]


def test_qblike_1():
    ret = eval_call(
        select,
        A(),
        x=True,
        w=True,
    )
    fmt = format_helper.format_class(ret)

    assert fmt == textwrap.dedent("""\
        class select[...]:
            x: tests.test_qblike.Property[int]
            w: tests.test_qblike.Property[list[str]]
        """)


def test_qblike_2():
    ret = eval_typing(PropsOnly[A])
    fmt = format_helper.format_class(ret)

    assert fmt == textwrap.dedent("""\
        class PropsOnly[tests.test_qblike.A]:
            x: tests.test_qblike.Property[int]
            y: tests.test_qblike.Property[bool | None]
            w: tests.test_qblike.Property[list[str]]
        """)


def test_qblike_3():
    ret = eval_call(
        select,
        A(),
        x=True,
        w=True,
        z=True,
    )
    fmt = format_helper.format_class(ret)

    assert fmt == textwrap.dedent("""\
        class select[...]:
            x: tests.test_qblike.Property[int]
            w: tests.test_qblike.Property[list[str]]
            z: tests.test_qblike.Link[tests.test_qblike.PropsOnly[tests.test_qblike.Tgt]]
        """)

    res = eval_typing(GetMemberType[ret, Literal["z"]])
    tgt = res.__args__[0]
    # XXX: this should probably be pre-evaluated already?
    tgt = eval_typing(tgt)
    fmt = format_helper.format_class(tgt)

    assert fmt == textwrap.dedent("""\
        class PropsOnly[tests.test_qblike.Tgt]:
            name: tests.test_qblike.Property[str]
    """)


def test_qblike_4():
    t = eval_call_with_types(
        select,
        A,
        x=bool,
        w=bool,
        z=bool,
    )
    fmt = format_helper.format_class(t)

    assert fmt == textwrap.dedent("""\
        class select[...]:
            x: tests.test_qblike.Property[int]
            w: tests.test_qblike.Property[list[str]]
            z: tests.test_qblike.Link[tests.test_qblike.PropsOnly[tests.test_qblike.Tgt]]
        """)
