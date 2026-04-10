"""100 functions with diverse return-type annotations.

Targets Python 3.14 (PEP 649 deferred evaluation, PEP 695 type params).
No ``from __future__ import annotations`` needed; forward references resolve
without quoting.
"""

import collections
import typing
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    Sequence,
)
from typing import (
    Annotated,
    Any,
    Literal,
    LiteralString,
    NamedTuple,
    Never,
    NoReturn,
    NotRequired,
    Protocol,
    Required,
    Self,
    TypeGuard,
    TypedDict,
    Unpack,
    runtime_checkable,
)


# ---------------------------------------------------------------------------
# PEP 695 type aliases and type variables
# ---------------------------------------------------------------------------

type Pair[T] = tuple[T, T]
type Result[T, E] = T | E
type NestedList[T] = list[T | NestedList[T]]
type JSON = str | int | float | bool | None | list[JSON] | dict[str, JSON]
type Callback[**P, R] = Callable[P, R]
type Matrix[T] = list[list[T]]
type Tree[T] = T | list[Tree[T]]


# ---------------------------------------------------------------------------
# Forward-referenced classes (defined later in the file)
# ---------------------------------------------------------------------------


def fn01() -> Node: ...


def fn02() -> list[Node]: ...


def fn03() -> dict[str, Node]: ...


def fn04() -> Node | Leaf: ...


def fn05() -> tuple[Node, Leaf, Edge]: ...


# ---------------------------------------------------------------------------
# Primitives and builtins
# ---------------------------------------------------------------------------


def fn06() -> int: ...


def fn07() -> str: ...


def fn08() -> bytes: ...


def fn09() -> float: ...


def fn10() -> complex: ...


def fn11() -> bool: ...


def fn12() -> None: ...


def fn13() -> type[int]: ...


def fn14() -> object: ...


# ---------------------------------------------------------------------------
# Union types (PEP 604 syntax)
# ---------------------------------------------------------------------------


def fn15() -> int | str: ...


def fn16() -> int | None: ...


def fn17() -> str | bytes | None: ...


def fn18() -> int | str | float | bool: ...


def fn19() -> list[int] | tuple[str, ...]: ...


# ---------------------------------------------------------------------------
# Generic builtins
# ---------------------------------------------------------------------------


def fn20() -> list[int]: ...


def fn21() -> dict[str, Any]: ...


def fn22() -> set[str]: ...


def fn23() -> frozenset[int]: ...


def fn24() -> tuple[int, str, float]: ...


def fn25() -> tuple[int, ...]: ...


def fn26() -> tuple[()]: ...


def fn27() -> list[dict[str, list[int]]]: ...


# ---------------------------------------------------------------------------
# collections / collections.abc
# ---------------------------------------------------------------------------


def fn28() -> collections.OrderedDict[str, int]: ...


def fn29() -> collections.defaultdict[str, list[int]]: ...


def fn30() -> collections.deque[str]: ...


def fn31() -> collections.Counter[str]: ...


def fn32() -> Sequence[int]: ...


def fn33() -> MutableSequence[str]: ...


def fn34() -> Mapping[str, int]: ...


def fn35() -> MutableMapping[str, Any]: ...


def fn36() -> Iterator[int]: ...


# ---------------------------------------------------------------------------
# Callable signatures
# ---------------------------------------------------------------------------


def fn37() -> Callable[[], None]: ...


def fn38() -> Callable[[int, str], bool]: ...


def fn39() -> Callable[..., Any]: ...


def fn40() -> Callable[[int], Callable[[str], bool]]: ...


# ---------------------------------------------------------------------------
# Async types
# ---------------------------------------------------------------------------


def fn41() -> Awaitable[int]: ...


def fn42() -> AsyncIterator[str]: ...


def fn43() -> AsyncGenerator[int, None]: ...


def fn44() -> Coroutine[Any, Any, int]: ...


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def fn45() -> Generator[int, str, bool]: ...


def fn46() -> Generator[int, None, None]: ...


# ---------------------------------------------------------------------------
# Literal and LiteralString
# ---------------------------------------------------------------------------


def fn47() -> Literal["a", "b", "c"]: ...


def fn48() -> Literal[1, 2, 3]: ...


def fn49() -> Literal[True]: ...


def fn50() -> LiteralString: ...


def fn51() -> Literal["x"] | Literal["y"]: ...


# ---------------------------------------------------------------------------
# Special forms
# ---------------------------------------------------------------------------


def fn52() -> Any: ...


def fn53() -> NoReturn: ...


def fn54() -> Never: ...


def fn55() -> type[Any]: ...


# ---------------------------------------------------------------------------
# Annotated
# ---------------------------------------------------------------------------


def fn56() -> Annotated[int, "positive"]: ...


def fn57() -> Annotated[str, lambda s: len(s) > 0]: ...


def fn58() -> Annotated[list[int], "non-empty", 42]: ...


# ---------------------------------------------------------------------------
# TypeGuard / TypeIs (3.13+)
# ---------------------------------------------------------------------------


def fn59(x: object) -> TypeGuard[int]: ...


def fn60(x: object) -> typing.TypeIs[str]: ...


# ---------------------------------------------------------------------------
# PEP 695 type-param functions
# ---------------------------------------------------------------------------


def fn61[T](x: T) -> T: ...


def fn62[T, U](x: T, y: U) -> tuple[T, U]: ...


def fn63[T](xs: list[T]) -> T | None: ...


def fn64[T: int](x: T) -> T: ...


def fn65[T: (str, bytes)](x: T) -> T: ...


def fn66[**P](f: Callable[P, int]) -> Callable[P, str]: ...


def fn67[*Ts](*args: Unpack[tuple[Unpack[Ts]]]) -> tuple[Unpack[Ts]]: ...


def fn68[T, **P](f: Callable[P, T]) -> Callback[P, list[T]]: ...


# ---------------------------------------------------------------------------
# PEP 695 type alias usage
# ---------------------------------------------------------------------------


def fn69() -> Pair[int]: ...


def fn70() -> Result[str, Exception]: ...


def fn71() -> NestedList[int]: ...


def fn72() -> JSON: ...


def fn73() -> Matrix[float]: ...


def fn74() -> Tree[str]: ...


# ---------------------------------------------------------------------------
# Classes with methods
# ---------------------------------------------------------------------------


class Node:
    value: int
    children: list[Node]

    def fn75(self) -> Self: ...

    def fn76(self) -> list[Self]: ...

    def fn77(self) -> Node: ...

    def fn78(self) -> tuple[Self, int]: ...

    @classmethod
    def fn79(cls) -> Self: ...

    @staticmethod
    def fn80() -> Node | None: ...

    def fn81(self) -> Iterator[Node]: ...

    class Inner:
        def fn82(self) -> Node: ...

        def fn83(self) -> Self: ...

        def fn84(self) -> Node.Inner: ...


class Leaf:
    label: str


class Edge:
    source: Node
    target: Node
    weight: float


# ---------------------------------------------------------------------------
# Generic class with PEP 695 syntax
# ---------------------------------------------------------------------------


class Container[T]:
    items: list[T]

    def fn85(self) -> T: ...

    def fn86(self) -> list[T]: ...

    def fn87(self) -> Container[T]: ...

    def fn88[U](self, f: Callable[[T], U]) -> Container[U]: ...


class KeyedContainer[K, V](Container[V]):
    index: dict[K, V]

    def fn89(self) -> Mapping[K, V]: ...

    def fn90(self) -> Iterator[tuple[K, V]]: ...


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class Renderable(Protocol):
    def fn91(self) -> str: ...


class Subscribable[T](Protocol):
    def fn92(self, callback: Callable[[T], None]) -> Callable[[], None]: ...


# ---------------------------------------------------------------------------
# TypedDict / NamedTuple in return types
# ---------------------------------------------------------------------------


class UserInfo(TypedDict):
    name: str
    age: int
    email: NotRequired[str]


class Point(NamedTuple):
    x: float
    y: float


def fn93() -> UserInfo: ...


def fn94() -> Point: ...


def fn95() -> Required[str]: ...


# ---------------------------------------------------------------------------
# Deeply nested / complex
# ---------------------------------------------------------------------------


def fn96() -> dict[str, list[tuple[int, Callable[[str], Awaitable[bool]]]]]: ...


def fn97() -> Mapping[str, Sequence[Node | Leaf | None]]: ...


def fn98() -> Callable[[Callable[[int], str]], Callable[[str], int]]: ...


def fn99() -> tuple[
    list[int],
    dict[str, set[float]],
    Callable[..., Generator[int, None, None]],
]: ...


def fn100() -> (
    dict[
        str,
        list[
            tuple[
                int,
                Annotated[str, "label"],
                Node | None,
            ]
        ],
    ]
    | None
): ...


# ---------------------------------------------------------------------------
# If-expressions (conditional types, PEP 827)
# ---------------------------------------------------------------------------


def fn101[T](x: T) -> int if T else str: ...


def fn102[T](x: int if T else str, y: float) -> None: ...


def fn103[T, U]() -> int if T else str if U else float: ...


class ConditionalAttrs[T]:
    x: int if T else str
    y: float

    def fn104(self) -> int if T else str: ...


class ConditionalAttrsLast[T]:
    y: float
    x: int if T else str


# ---------------------------------------------------------------------------
# If-expressions nested inside other type constructs
# ---------------------------------------------------------------------------


def fn105[T]() -> list[int if T else str]: ...


def fn106[T]() -> dict[str, int if T else str]: ...


def fn107[T]() -> (int if T else str) | None: ...


def fn108[T]() -> tuple[int if T else str, float]: ...


def fn109[T]() -> Callable[[int if T else str], bool]: ...
