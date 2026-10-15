"""
TypeScript-style utility type operators: Pick, Omit, Partial.

See https://www.typescriptlang.org/docs/handbook/utility-types.html
"""

import textwrap
from typing import (
    assert_type,
    get_args,
    Literal,
    Never,
    NotRequired,
    Required,
    TypedDict,
    Union,
)

import typemap_extensions as typing
from typemap.type_eval import eval_typing

from typemap.type_eval import format_helper


# The "Todo" type from the TypeScript utility-types examples
class Todo:
    title: str
    description: str
    completed: bool


class TodoTD(TypedDict):
    title: str
    description: str
    completed: bool


# Begin PEP section: Utility types
"""
TypeScript defines a number of `utility types
<https://www.typescriptlang.org/docs/handbook/utility-types.html>`__
for performing common type operations.

We present implementations of a selection of them::

"""


# Pick<T, Keys>
# Constructs a type by picking the set of properties Keys from T.
type Pick[T, Keys] = typing.NewProtocol[
    *[p for p in typing.Members[T] if typing.IsAssignable[p.name, Keys]]
]

# Omit<T, Keys>
# Constructs a type by picking all properties from T and then removing Keys.
# Note that unlike in TS, our Omit does not depend on Exclude.
type Omit[T, Keys] = typing.NewProtocol[
    *[p for p in typing.Members[T] if not typing.IsAssignable[p.name, Keys]]
]

# KeyOf[T]
# Constructs a union of the names of every member of T.
type KeyOf[T] = Union[*[p.name for p in typing.Members[T]]]

# Exclude<T, U>
# Constructs a type by excluding from T all union members assignable to U.
type Exclude[T, U] = Union[
    *[x for x in typing.FromUnion[T] if not typing.IsAssignable[x, U]]
]

# Extract<T, U>
# Constructs a type by extracting from T all union members assignable to U.
type Extract[T, U] = Union[
    *[
        x
        for x in typing.FromUnion[T]
        # Just the inverse of Exclude, really
        if typing.IsAssignable[x, U]
    ]
]

# Partial<T>
# Constructs a type with all properties of T set to optional (T | None).
type Partial[T] = typing.NewProtocol[
    *[typing.Member[p.name, p.type | None, p.quals] for p in typing.Attrs[T]]
]

# PartialTD<T>
# Like Partial, but for TypedDicts: wraps all fields in NotRequired
# rather than making them T | None.
type PartialTD[T] = typing.NewTypedDict[
    *[
        typing.Member[p.name, p.type, p.quals | Literal["NotRequired"]]
        for p in typing.Attrs[T]
    ]
]
# End PEP section: Utility types


def _check_exclude(x0: Exclude[str | int | bool, int]) -> None:
    assert_type(x0, str)


def _check_extract(x1: Extract[str | int | bool, int]) -> None:
    assert_type(x1, int | bool)


def _check_keyof(x2: KeyOf[Todo]) -> None:
    assert_type(
        x2, Literal["title"] | Literal["description"] | Literal["completed"]
    )


def _check_pick(
    x3: Pick[Todo, Literal["title"] | Literal["completed"]],
) -> None:
    assert_type(x3.title, str)
    assert_type(x3.completed, bool)
    assert_type(
        x3,
        typing.NewProtocol[
            typing.Member[Literal["title"], str],
            typing.Member[Literal["completed"], bool],
        ],
    )


def _check_omit(x4: Omit[Todo, Literal["description"]]) -> None:
    assert_type(x4.title, str)
    assert_type(x4.completed, bool)
    assert_type(
        x4,
        typing.NewProtocol[
            typing.Member[Literal["title"], str],
            typing.Member[Literal["completed"], bool],
        ],
    )


def _check_partial(x5: Partial[Todo]) -> None:
    assert_type(x5.title, str | None)
    assert_type(x5.description, str | None)
    assert_type(x5.completed, bool | None)
    assert_type(
        x5,
        typing.NewProtocol[
            typing.Member[Literal["title"], str | None],
            typing.Member[Literal["description"], str | None],
            typing.Member[Literal["completed"], bool | None],
        ],
    )


def test_pick():
    tgt = eval_typing(Pick[Todo, Literal["title"] | Literal["completed"]])
    fmt = format_helper.format_class(tgt)
    assert fmt == textwrap.dedent("""\
        class Pick[tests.test_ts_utility.Todo, typing.Literal['title'] | typing.Literal['completed']]:
            title: str
            completed: bool
    """)


def test_omit():
    tgt = eval_typing(Omit[Todo, Literal["description"]])
    fmt = format_helper.format_class(tgt)
    assert fmt == textwrap.dedent("""\
        class Omit[tests.test_ts_utility.Todo, typing.Literal['description']]:
            title: str
            completed: bool
    """)


def test_partial():
    tgt = eval_typing(Partial[Todo])
    fmt = format_helper.format_class(tgt)
    assert fmt == textwrap.dedent("""\
        class Partial[tests.test_ts_utility.Todo]:
            title: str | None
            description: str | None
            completed: bool | None
    """)


def test_partial_td():
    tgt = eval_typing(PartialTD[TodoTD])
    assert tgt.__required_keys__ == frozenset()
    assert tgt.__optional_keys__ == {"title", "description", "completed"}
    assert tgt.__annotations__ == {
        "title": NotRequired[str],
        "description": NotRequired[str],
        "completed": NotRequired[bool],
    }


class OptionalTD(TypedDict, total=False):
    x: int
    y: Required[str]


class ChildTD(OptionalTD):
    z: bool


def _get_quals(cls):
    """Return {name: quals} for all Attrs of cls."""
    result = {}
    for p in get_args(eval_typing(typing.Attrs[cls])):
        name = eval_typing(p.name).__args__[0]
        quals = eval_typing(p.quals)
        result[name] = quals
    return result


def test_td_total_false():
    quals = _get_quals(OptionalTD)
    # x is bare in total=False -> NotRequired
    assert quals["x"] == Literal["NotRequired"]
    # y has explicit Required -> no qual
    assert quals["y"] is Never


def test_td_total_false_inherited():
    quals = _get_quals(ChildTD)
    # x inherited from total=False parent -> still NotRequired
    assert quals["x"] == Literal["NotRequired"]
    # y had explicit Required in parent -> no qual
    assert quals["y"] is Never
    # z defined in total=True child -> no qual
    assert quals["z"] is Never


def test_exclude():
    # bool is assignable to int, so it gets excluded too
    assert eval_typing(Exclude[str | int | bool, int]) is str

    assert eval_typing(
        Exclude[Literal["a"] | Literal["b"] | Literal["c"], Literal["a"]]
    ) == (Literal["b"] | Literal["c"])

    assert eval_typing(Exclude[str | int | float, str | int]) is float


def test_extract():
    # bool is assignable to int, so it gets extracted
    assert eval_typing(Extract[str | int | bool, int]) == (int | bool)

    assert (
        eval_typing(
            Extract[Literal["a"] | Literal["b"] | Literal["c"], Literal["a"]]
        )
        == Literal["a"]
    )

    assert eval_typing(Extract[str | int | float, str | int]) == (str | int)


def test_keyof():
    assert eval_typing(KeyOf[Todo]) == (
        Literal["title"] | Literal["description"] | Literal["completed"]
    )
