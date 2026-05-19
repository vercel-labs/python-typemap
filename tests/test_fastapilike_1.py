# SKIP MYPY: Invalid use of Self
# TODO: resolve

# We should have at least *one* test with this...
from __future__ import annotations

import dataclasses
import enum
import textwrap

from typing import Annotated, Callable, Literal, Never, Union, Self

from typemap.type_eval import eval_typing
from typemap_extensions import (
    NewProtocol,
    Iter,
    Attrs,
    IsAssignable,
    GetAnnotations,
    DropAnnotations,
    FromUnion,
    Member,
    Members,
    Param,
    Params,
)

from typemap.type_eval import format_helper


class PropQuals(enum.Enum):
    HIDDEN = "HIDDEN"
    PRIMARY = "PRIMARY"
    HAS_DEFAULT = "HAS_DEFAULT"


@dataclasses.dataclass(frozen=True)
class _Default:
    val: object


type Hidden[T] = Annotated[T, Literal[PropQuals.HIDDEN]]
type Primary[T] = Annotated[T, Literal[PropQuals.PRIMARY]]
type HasDefault[T, default] = Annotated[
    T, _Default(default), Literal[PropQuals.HAS_DEFAULT]
]


####

type InitFnType[T] = Member[
    Literal["__init__"],
    Callable[
        Params[
            Param[Literal["self"], Self],
            *[
                Param[
                    p.name,
                    DropAnnotations[p.type],
                    Literal["keyword"],
                    DropAnnotations[p.type]
                    if IsAssignable[
                        Literal[PropQuals.HAS_DEFAULT],
                        GetAnnotations[p.type],
                    ]
                    else Never,
                ]
                for p in Iter[Attrs[T]]
            ],
        ],
        None,
    ],
    Literal["ClassVar"],
]

type AddInit[T] = NewProtocol[
    InitFnType[T],
    # TODO: mypy rejects this -- should it work?
    # *Members[T],
    *[t for t in Iter[Members[T]]],
]

# Strip `| None` from a type by iterating over its union components
# and filtering
type NotOptional[T] = Union[
    *[x for x in Iter[FromUnion[T]] if not IsAssignable[x, None]]
]

# Adjust an attribute type for use in Public below by dropping | None for
# primary keys and stripping all annotations.
type FixPublicType[T] = DropAnnotations[
    NotOptional[T]
    if IsAssignable[Literal[PropQuals.PRIMARY], GetAnnotations[T]]
    else T
]

# Strip out everything that is Hidden and also make the primary key required
# Drop all the annotations, since this is for data getting returned to users
# from the DB, so we don't need default values.
type Public[T] = NewProtocol[
    *[
        Member[p.name, FixPublicType[p.type], p.quals]
        for p in Iter[Attrs[T]]
        if not IsAssignable[Literal[PropQuals.HIDDEN], GetAnnotations[p.type]]
    ]
]

# Create takes everything but the primary key and preserves defaults
type Create[T] = NewProtocol[
    *[
        Member[p.name, p.type, p.quals]
        for p in Iter[Attrs[T]]
        if not IsAssignable[Literal[PropQuals.PRIMARY], GetAnnotations[p.type]]
    ]
]


# Update takes everything but the primary key, but makes them all have
# None defaults
type Update[T] = NewProtocol[
    *[
        Member[
            p.name,
            HasDefault[DropAnnotations[p.type] | None, None],
            p.quals,
        ]
        for p in Iter[Attrs[T]]
        if not IsAssignable[Literal[PropQuals.PRIMARY], GetAnnotations[p.type]]
    ]
]


####

# This is the FastAPI example code that we are trying to repair!
# Adapted from https://fastapi.tiangolo.com/tutorial/sql-databases/#heroupdate-the-data-model-to-update-a-hero
"""
class HeroBase(SQLModel):
    name: str = Field(index=True)
    age: int | None = Field(default=None, index=True)


class Hero(HeroBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    secret_name: str


class HeroPublic(HeroBase):
    id: int


class HeroCreate(HeroBase):
    secret_name: str


class HeroUpdate(HeroBase):
    name: str | None = None
    age: int | None = None
    secret_name: str | None = None
"""


class Hero:
    id: Primary[
        HasDefault[int | None, None]
    ]  # = Field(default=None, primary_key=True)

    name: "str"
    age: HasDefault[int | None, None]  # = Field(default=None, index=True)

    secret_name: Hidden[str]


#######


def test_eval_drop_optional_1():
    tgt = eval_typing(NotOptional[int | None])
    assert tgt is int


def test_fastapi_like_1():
    tgt = eval_typing(Public[Hero])
    fmt = format_helper.format_class(tgt)

    assert fmt == textwrap.dedent("""\
        class Public[tests.test_fastapilike_1.Hero]:
            id: int
            name: str
            age: int | None
    """)


def test_fastapi_like_2():
    tgt = eval_typing(Create[Hero])
    fmt = format_helper.format_class(tgt)

    assert fmt == textwrap.dedent("""\
        class Create[tests.test_fastapilike_1.Hero]:
            name: str
            age: typing.Annotated[int | None, _Default(val=None), typing.Literal[<PropQuals.HAS_DEFAULT: 'HAS_DEFAULT'>]]
            secret_name: typing.Annotated[str, typing.Literal[<PropQuals.HIDDEN: 'HIDDEN'>]]
    """)


def test_fastapi_like_3():
    tgt = eval_typing(Update[Hero])
    fmt = format_helper.format_class(tgt)

    assert fmt == textwrap.dedent("""\
        class Update[tests.test_fastapilike_1.Hero]:
            name: typing.Annotated[str | None, _Default(val=None), typing.Literal[<PropQuals.HAS_DEFAULT: 'HAS_DEFAULT'>]]
            age: typing.Annotated[int | None, _Default(val=None), typing.Literal[<PropQuals.HAS_DEFAULT: 'HAS_DEFAULT'>]]
            secret_name: typing.Annotated[str | None, _Default(val=None), typing.Literal[<PropQuals.HAS_DEFAULT: 'HAS_DEFAULT'>]]
    """)


def test_fastapi_like_4():
    tgt = eval_typing(AddInit[Public[Hero]])
    fmt = format_helper.format_class(tgt)

    assert fmt == textwrap.dedent("""\
        class AddInit[tests.test_fastapilike_1.Public[tests.test_fastapilike_1.Hero]]:
            id: int
            name: str
            age: int | None
            def __init__(self: Self, *, id: int, name: str, age: int | None) -> None: ...
    """)


def test_fastapi_like_6():
    tgt = eval_typing(AddInit[Update[Hero]])
    fmt = format_helper.format_class(tgt)

    assert fmt == textwrap.dedent("""\
        class AddInit[tests.test_fastapilike_1.Update[tests.test_fastapilike_1.Hero]]:
            name: typing.Annotated[str | None, _Default(val=None), typing.Literal[<PropQuals.HAS_DEFAULT: 'HAS_DEFAULT'>]]
            age: typing.Annotated[int | None, _Default(val=None), typing.Literal[<PropQuals.HAS_DEFAULT: 'HAS_DEFAULT'>]]
            secret_name: typing.Annotated[str | None, _Default(val=None), typing.Literal[<PropQuals.HAS_DEFAULT: 'HAS_DEFAULT'>]]
            def __init__(self: Self, *, name: str | None = ..., age: int | None = ..., secret_name: str | None = ...) -> None: ...
    """)
