from typing import (
    assert_type,
    Callable,
    Literal,
    ReadOnly,
    TypedDict,
)

import typemap_extensions as typing


class FieldArgs(TypedDict, total=False):
    default: ReadOnly[object]


class Field[T: FieldArgs](typing.InitField[T]):
    pass


####

# TODO: Should this go into the stdlib?
type GetFieldItem[T, K] = typing.GetMemberType[
    typing.GetArg[T, typing.InitField, Literal[0]], K
]


# Extract the default type from an Init field.
# If it is a Field, then we try pulling out the "default" field,
# otherwise we return the type itself.
type GetDefault[Init] = (
    GetFieldItem[Init, Literal["default"]]
    if typing.IsAssignable[Init, Field]
    else Init
)


def _check_hero_init() -> None:
    # required only
    h = Hero(name='test', secret_name='secret')
    assert_type(h, Hero)
    # all keyword args
    h2 = Hero(id=1, name='test', age=25, secret_name='secret')
    assert_type(h2, Hero)


# TODO: what could we do to make dataclass_ish work at runtime?


# Begin PEP section: dataclass like __init__

"""

``InitFnType`` generates a ``Member`` for a new ``__init__`` function
based on iterating over all attributes.

``GetDefault`` here is borrowed from our FastAPI-like example above.

"""

# Generate the Member field for __init__ for a class
type InitFnType[T] = typing.Member[
    Literal["__init__"],
    Callable[
        typing.Params[
            typing.Param[Literal["self"], T],
            *[
                typing.Param[
                    p.name,
                    p.type,
                    # All arguments are keyword-only
                    Literal[typing.ParamKind.KEYWORD_ONLY],
                    # GetDefault is Never when there's no default, so use it
                    # directly as D.
                    GetDefault[p.init],
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

"""

``UpdateClass`` can then be used to create a class decorator (a la
``@dataclass``) adds a new ``__init__`` method to a class.

"""


def dataclass_ish[T](
    cls: type[T],
) -> typing.UpdateClass[
    # Add the computed __init__ function
    InitFnType[T],
]:
    raise NotImplementedError


"""

Or to create a base class (a la Pydantic) that does.

"""


class Model:
    def __init_subclass__[T](
        cls: type[T],
    ) -> typing.UpdateClass[
        # Add the computed __init__ function
        InitFnType[T],
    ]:
        pass


# End PEP section


class Hero(Model):
    id: int | None = None

    name: str
    age: int | None = Field(default=None)

    secret_name: str


#######

import textwrap

from typemap.type_eval import eval_typing
from typemap.type_eval import format_helper


def test_dataclass_like_1():
    tgt = eval_typing(Hero)
    fmt = format_helper.format_class(tgt)

    # 3.15 inserts the module name in a place that 3.14 doesn't, so replace
    assert fmt.replace("tests.test_dataclass_like.", "") == textwrap.dedent("""\
        class Hero:
            id: int | None = None
            name: str
            age: int | None = Field(default=None)
            secret_name: str
            @classmethod
            def __init_subclass__[T](cls: type[T]) -> typemap.typing.UpdateClass[InitFnType[T]]: ...
            def __init__(self: Self, *, id: int | None = None, name: str, age: int | None = None, secret_name: str) -> None: ...
    """)
