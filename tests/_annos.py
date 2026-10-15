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

from typemap.typing import GenericCallable, IsAssignable, Member


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


def fn119[T, U]() -> tuple[int if T else (str if U else bytes), float]: ...


def fn120[T, U]() -> tuple[(str if U else bytes) if T else int, float]: ...


# Tail position in an evaluate function: both branches extend the same list.
type StarredIfExp[T] = tuple[*([] if T else [int])]

# Tail position inside other kinds of shared structure
type CallIfExp[T] = Annotated[int, len(str if T else bytes)]
type CompareIfExp[T] = Literal[(str if T else bytes) in int]
type NotIfExp[T] = not (str if T else bytes)
type ListStarredIfExp[T] = tuple[[*(str if T else bytes)]]


# ---------------------------------------------------------------------------
# Outer if-expressions (NOT factored into inner position)
# ---------------------------------------------------------------------------


def fn110[T]() -> list[int] if T else list[str]: ...


def fn111[T]() -> (int | None) if T else (str | None): ...


##


def fn112[T](
    x: list[int if T else str],
    y: list[int] if T else list[str],
) -> None: ...


def fn113[T](
    x: (int | None) if T else (str | None),
    y: (int if T else str) | None,
) -> None: ...


# ---------------------------------------------------------------------------
# Unpacked comprehension types (PEP 827)
# ---------------------------------------------------------------------------


# Module-level functions — inlined comprehension bytecode (Pattern B)


def fn114[T]() -> tuple[*[x for x in T]]: ...


def fn115[T]() -> tuple[*[m.name for m in T]]: ...


def fn116[T]() -> tuple[*[Member[m.name, m.type] for m in T]]: ...


def fn117[T]() -> tuple[*[m for m in T if IsAssignable[m.type, int]]]: ...


def fn118[A, B]() -> tuple[
    *[x for x in A],
    *[y for y in B],
]: ...


# Class methods — separate code object bytecode (Pattern A)


class CompNode[T]:
    def fn119(self) -> tuple[*[x for x in T]]: ...

    def fn120(self) -> tuple[*[Member[m.name, m.type] for m in T]]: ...

    def fn121(
        self,
    ) -> tuple[*[m for m in T if IsAssignable[m.type, int]]]: ...


# ---------------------------------------------------------------------------
# Dict displays (not to be confused with the annotations dict)
# ---------------------------------------------------------------------------


def fn122(x: Annotated[int, {}]) -> Annotated[int, {"k": str, "v": int}]: ...


def fn123[T]() -> Annotated[int, {"k": str if T else bytes}]: ...


class DictAnnos[T]:
    a: Annotated[int, {}]
    b: Annotated[int, {"k": str}]
    c: Annotated[int, {"k": str if T else bytes}]


type DictAlias = Annotated[int, {"k": str}]


# ---------------------------------------------------------------------------
# Module annotations
# ---------------------------------------------------------------------------

FLAG = True
mod_x: list[int]
mod_y: dict[str, int if FLAG else str]


# ---------------------------------------------------------------------------
# Lambdas
# ---------------------------------------------------------------------------


def fn124[T]() -> GenericCallable[tuple[T], Callable[[T], T]]: ...


def fn125() -> Annotated[int, lambda a, /, b=int, *c, d, e=str, **f: a]: ...


def fn126() -> Annotated[int, lambda a: lambda b: a[b]]: ...


def fn127() -> Annotated[int, lambda a: [x for x in a if x]]: ...


class LambdaAnnos[T]:
    a: Annotated[T, lambda T: Callable[[T], T]]


type LambdaAlias[T] = Annotated[T, lambda T: Callable[[T], T]]


# ---------------------------------------------------------------------------
# Comprehension filters that are also the element
# ---------------------------------------------------------------------------


def fn128[T]() -> tuple[*[x for x in T if x]]: ...


def fn129[T]() -> tuple[*[x for x in T if not x]]: ...


# ---------------------------------------------------------------------------
# Keyword arguments
# ---------------------------------------------------------------------------


def fn130() -> Annotated[int, len(str, key=int)]: ...


def fn131() -> Annotated[int, len(key=lambda: [1], other=str)]: ...


def fn132[T]() -> Annotated[int, len(key=int if T else str)]: ...


class KeywordAnnos[T]:
    a: Annotated[int, len(str, key=int)]
    b: Annotated[int, len(key=int if T else str)]


type KeywordAlias[T] = Annotated[int, len(key=int if T else str)]


# ---------------------------------------------------------------------------
# Consecutive loads of locals (fused into LOAD_FAST_LOAD_FAST and
# LOAD_FAST_BORROW_LOAD_FAST_BORROW)
# ---------------------------------------------------------------------------


def fn133[T]() -> tuple[*[Unpack[tuple[X, X]] for X in T]]: ...


def fn134[T]() -> tuple[*[x for x in T if IsAssignable[x, x]]]: ...


def fn135() -> Annotated[int, lambda a, b: a[b]]: ...


def fn136() -> Annotated[int, lambda a: (len(x, x) for x in a)]: ...


def fn137() -> Annotated[int, lambda a, b: len(a, b, [a for a in b])]: ...


class FusedLoads[T]:
    a: tuple[*[Unpack[tuple[X, X]] for X in T]]

    def fn138(self) -> tuple[*[Unpack[tuple[X, X]] for X in T]]: ...


type FusedLoadsAlias[T] = tuple[*[Unpack[tuple[X, X]] for X in T]]


# ---------------------------------------------------------------------------
# Arithmetic and bitwise operators
# ---------------------------------------------------------------------------


def fn139[A, B]() -> Annotated[int, A + B]: ...


def fn140[A, B, C]() -> Annotated[
    int, A - B * C @ A / B // C % A**B, (A - B) * C, A - (B - C)
]: ...


def fn141[A, B, C]() -> Annotated[int, A << B >> C & A ^ B | C]: ...


def fn142[A, B, T]() -> Annotated[int, A + (B if T else A), int | A + B]: ...


def fn143[T]() -> tuple[*[x + x for x in T]]: ...


class BinOps[A, B]:
    a: Annotated[int, A + B]
    b: Annotated[int, (A if B else int) * A]

    def fn144(self) -> tuple[*[x + A for x in B]]: ...


type BinOpsAlias[A, B] = Annotated[int, A + B, A ^ B]


# ---------------------------------------------------------------------------
# Slices (BINARY_SLICE, BUILD_SLICE, and constant slices)
# ---------------------------------------------------------------------------


def fn145[A, B, C]() -> Annotated[int, C[A:B], C[:B], C[A:], C[A:B][B:A]]: ...


def fn146[A, B, C]() -> Annotated[int, C[A:B:C], C[::C], C[A::]]: ...


def fn147[A, B, C]() -> Annotated[int, C[A:B, C], C[:, A], C[A, ::B]]: ...


def fn148[C]() -> Annotated[int, C[:], C[1:2], C[-1:], C[::-1], C[1:2, 3]]: ...


def fn149[T]() -> tuple[*[x[1:] for x in T]]: ...


class Slices[A, B]:
    a: Annotated[int, A[B:], A[B:A, ::B]]

    def fn150(self) -> Annotated[int, B[A:A]]: ...


type SlicesAlias[A, B] = Annotated[int, A[B:], A[:B:A], A[1:]]


# ---------------------------------------------------------------------------
# Comprehensions with multiple for clauses
# ---------------------------------------------------------------------------


def fn151[T]() -> tuple[*[x[y] for x in T for y in x]]: ...


def fn152[A]() -> tuple[
    *[
        dict[a, b]
        for a in A
        if not IsAssignable[a, bool]
        for b in tuple[a, None]
        if IsAssignable[a, int] and IsAssignable[b, None]
    ]
]: ...


def fn153[T]() -> tuple[*[list[t] for t in T for t in t]]: ...


def fn154[A, B, C]() -> tuple[
    *[tuple[a, b, c] for a in A for b in B if b for c in C]
]: ...


def fn155[T]() -> tuple[*[[y for y in x] for x in T for z in x]]: ...


def fn156[As, Bs]() -> Annotated[
    int, any(IsAssignable[a, b] for a in As for b in Bs)
]: ...


def fn157() -> Annotated[int, lambda a: [x[y] for x in a for y in x]]: ...


class MultiFor[A, B]:
    a: tuple[*[x[y] for x in A for y in x]]
    b: Annotated[
        int,
        all(
            IsAssignable[a, b]
            for a in A
            if IsAssignable[a, int]
            for b in tuple[int, a]
        ),
    ]

    def fn158(self) -> tuple[*[x[y] for x in A for y in x]]: ...


type MultiForAlias[A, B] = tuple[
    *[a for a in A if IsAssignable[a, int] for b in tuple[a]]
]


def fn159[T]() -> tuple[*[x + y for x in T for y in x]]: ...


# ---------------------------------------------------------------------------
# Mixed and/or
# ---------------------------------------------------------------------------

type AndThenOr[A, B, C] = (A and B) or C
type AndOrAnd[A, B, C, D] = (A and B) or (C and D)
type OrOfAnds[A, B, C, D, E] = A or (B and C) or (D and E)
type IfAndElse[A, B, C] = B if A and B else C
