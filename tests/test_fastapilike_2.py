# TODO: resolve the invalid Self use issue that is type: ignored

from typing import (
    Callable,
    Literal,
    Union,
    ReadOnly,
    TypedDict,
    Never,
    Self,
)

import typemap_extensions as typing


class FieldArgs(TypedDict, total=False):
    hidden: ReadOnly[bool]
    primary_key: ReadOnly[bool]
    index: ReadOnly[bool]
    default: ReadOnly[object]


class Field[T: FieldArgs](typing.InitField[T]):
    pass


####

# TODO: Should this go into the stdlib?
type GetFieldItem[T, K] = typing.GetMemberType[
    typing.GetArg[T, typing.InitField, Literal[0]], K
]


##

# Strip `| None` from a type by iterating over its union components
# and filtering
type NotOptional[T] = Union[
    *[
        x
        for x in typing.Iter[typing.FromUnion[T]]
        if not typing.IsAssignable[x, None]
    ]
]

# Adjust an attribute type for use in Public below by dropping | None for
# primary keys and stripping all annotations.
type FixPublicType[T, Init] = (
    NotOptional[T]
    if typing.IsAssignable[
        Literal[True], GetFieldItem[Init, Literal["primary_key"]]
    ]
    else T
)

# Strip out everything that is Hidden and also make the primary key required
# Drop all the annotations, since this is for data getting returned to users
# from the DB, so we don't need default values.
type Public[T] = typing.NewProtocol[
    *[
        typing.Member[
            p.name,
            FixPublicType[p.type, p.init],
            p.quals,
        ]
        for p in typing.Iter[typing.Attrs[T]]
        if not typing.IsAssignable[
            Literal[True], GetFieldItem[p.init, Literal["hidden"]]
        ]
    ]
]

# Begin PEP section: Automatically deriving FastAPI CRUD models
"""
We have a more `fully-worked example <#fastapi-test_>`_ in our test
suite, but here is a possible implementation of just ``Create``::
"""

# Extract the default type from an Init field.
# If it is a Field, then we try pulling out the "default" field,
# otherwise we return the type itself.
type GetDefault[Init] = (
    GetFieldItem[Init, Literal["default"]]
    if typing.IsAssignable[Init, Field]
    else Init
)

# Create takes everything but the primary key and preserves defaults
type Create[T] = typing.NewProtocol[
    *[
        typing.Member[
            p.name,
            p.type,
            p.quals,
            GetDefault[p.init],
        ]
        for p in typing.Iter[typing.Attrs[T]]
        if not typing.IsAssignable[
            Literal[True],
            GetFieldItem[p.init, Literal["primary_key"]],
        ]
    ]
]

"""
The ``Create`` type alias creates a new type (via ``NewProtocol``) by
iterating over the attributes of the original type.  It has access to
names, types, qualifiers, and the literal types of initializers (in
part through new facilities to handle the extremely common
``= Field(...)``-like pattern used here).

Here, we filter out attributes that have ``primary_key=True`` in their
``Field`` as well as extracting default arguments (which may be either
from a ``default`` argument to a field or specified directly as an
initializer).
"""

# End PEP section


# Update takes everything but the primary key, but makes them all have
# None defaults
type Update[T] = typing.NewProtocol[
    *[
        typing.Member[
            p.name,
            p.type | None,
            p.quals,
            Literal[None],
        ]
        for p in typing.Iter[typing.Attrs[T]]
        if not typing.IsAssignable[
            Literal[True],
            GetFieldItem[p.init, Literal["primary_key"]],
        ]
    ]
]

##

# Generate the Member field for __init__ for a class
type InitFnType[T] = typing.Member[
    Literal["__init__"],
    Callable[
        typing.Params[
            typing.Param[Literal["self"], Self],  # type: ignore[misc]
            *[
                typing.Param[
                    p.name,
                    p.type,
                    # All arguments are keyword-only
                    Literal["keyword"],
                    # It takes a default if a default is specified in the class
                    p.type
                    if not typing.IsAssignable[
                        GetDefault[p.init],
                        Never,
                    ]
                    else Never,
                ]
                for p in typing.Iter[typing.Attrs[T]]
            ],
        ],
        None,
    ],
    Literal["ClassVar"],
]
type AddInit[T] = typing.NewProtocol[
    InitFnType[T],
    *[x for x in typing.Iter[typing.Members[T]]],
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
    id: int | None = Field(default=None, primary_key=True)

    name: str = Field(index=True)
    age: int | None = Field(default=None, index=True)

    secret_name: str = Field(hidden=True)


from typing import assert_type


def _check_public(x: Public[Hero]) -> None:
    # id becomes required int (primary_key strips | None), secret_name hidden
    assert_type(
        x,
        typing.NewProtocol[
            typing.Member[Literal["id"], int],
            typing.Member[Literal["name"], str],
            typing.Member[Literal["age"], int | None],
        ],
    )


def _check_create(x: Create[Hero]) -> None:
    # primary key excluded, rest preserved
    assert_type(
        x,
        typing.NewProtocol[
            typing.Member[Literal["name"], str],
            typing.Member[Literal["age"], int | None],
            typing.Member[Literal["secret_name"], str],
        ],
    )


def _check_update(x: Update[Hero]) -> None:
    # primary key excluded, all fields optional (| None)
    assert_type(
        x,
        typing.NewProtocol[
            typing.Member[Literal["name"], str | None],
            typing.Member[Literal["age"], int | None],
            typing.Member[Literal["secret_name"], str | None],
        ],
    )


#######

import textwrap

from typemap.type_eval import eval_typing
from typemap.type_eval import format_helper


def test_fastapi_like_0():
    tgt = eval_typing(AddInit[Hero])
    fmt = format_helper.format_class(tgt)

    assert fmt == textwrap.dedent("""\
        class AddInit[tests.test_fastapilike_2.Hero]:
            id: int | None = Field(default=None, primary_key=True)
            name: str = Field(index=True)
            age: int | None = Field(default=None, index=True)
            secret_name: str = Field(hidden=True)
            def __init__(self: Self, *, id: int | None = ..., name: str, age: int | None = ..., secret_name: str) -> None: ...
    """)


def test_fastapi_like_1():
    tgt = eval_typing(AddInit[Public[Hero]])
    fmt = format_helper.format_class(tgt)

    assert fmt == textwrap.dedent("""\
        class AddInit[tests.test_fastapilike_2.Public[tests.test_fastapilike_2.Hero]]:
            id: int
            name: str
            age: int | None
            def __init__(self: Self, *, id: int, name: str, age: int | None) -> None: ...
    """)


def test_fastapi_like_2():
    tgt = eval_typing(AddInit[Create[Hero]])
    fmt = format_helper.format_class(tgt)

    assert fmt == textwrap.dedent("""\
        class AddInit[tests.test_fastapilike_2.Create[tests.test_fastapilike_2.Hero]]:
            name: str
            age: int | None = None
            secret_name: str
            def __init__(self: Self, *, name: str, age: int | None = ..., secret_name: str) -> None: ...
    """)


def test_fastapi_like_3():
    tgt = eval_typing(AddInit[Update[Hero]])
    fmt = format_helper.format_class(tgt)

    assert fmt == textwrap.dedent("""\
        class AddInit[tests.test_fastapilike_2.Update[tests.test_fastapilike_2.Hero]]:
            name: str | None = None
            age: int | None = None
            secret_name: str | None = None
            def __init__(self: Self, *, name: str | None = ..., age: int | None = ..., secret_name: str | None = ...) -> None: ...
    """)
