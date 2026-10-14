import builtins
from collections.abc import Iterable, Iterator
from typing import assert_type, cast, Literal, Never, Union

import typemap_extensions as typing

import pytest

from typemap.type_eval import eval_typing, TypeMapError

# Begin PEP section

"""
Using type iteration and ``GetArg``, we can give a proper type to ``zip``.
"""


type ElemOf[T] = typing.GetArg[T, Iterable, Literal[0]]


def zip[*Ts](
    *args: *Ts, strict: bool = False
) -> Iterator[tuple[*[ElemOf[t] for t in tuple[*Ts]]]]:
    return builtins.zip(*args, strict=strict)  # type: ignore[call-overload]


"""
Using the ``Slice`` operator and type alias recursion, we can
also give a more precise type for zipping together heterogeneous tuples.

For example, zipping ``tuple[int, str]`` and ``tuple[str, bool]``
should produce ``tuple[tuple[int, float], tuple[str, bool]]``

"""


def zip_pairs[*Ts, *Us](
    a: tuple[*Ts], b: tuple[*Us]
) -> Zip[tuple[*Ts], tuple[*Us]]:
    return cast(
        Zip[tuple[*Ts], tuple[*Us]],
        tuple(zip(a, b, strict=True)),
    )


type DropLast[T] = typing.Slice[T, Literal[0], Literal[-1]]
type Last[T] = typing.GetArg[T, tuple, Literal[-1]]

# Matching on Never here is intentional; it prevents infinite
# recursions when T is not a tuple.
type Empty[T] = typing.IsAssignable[typing.Length[T], Literal[0]]

"""
Zip recursively walks down the input tuples until one or both of them
is empty. If the lengths don't match (because only one is empty),
raise an error.
"""

type Zip[T, S] = (
    tuple[()]
    if Empty[T] and Empty[S]
    else typing.RaiseError[Literal["Zip length mismatch"], T, S]
    if Empty[T] or Empty[S]
    else tuple[*Zip[DropLast[T], DropLast[S]], tuple[Last[T], Last[S]]]
)


# End PEP section


# ZipN generalizes Zip to any number of input tuples. Its argument T
# is a tuple of tuples; T lets us map operators over each input.
# The length check is expressed as a union: all lengths collapse to a
# single Literal iff they agree.

type First[T] = typing.GetArg[T, tuple, Literal[0]]
type DropLastEach[T] = tuple[*[DropLast[t] for t in T]]
type LastEach[T] = tuple[*[Last[t] for t in T]]
type AllSameLength[T] = typing.IsEquivalent[
    Union[*[typing.Length[t] for t in T]],
    typing.Length[First[T]],
]

type ZipN[T] = (
    tuple[()]
    if Empty[First[T]] and AllSameLength[T]
    else tuple[*ZipN[DropLastEach[T]], LastEach[T]]
    if AllSameLength[T]
    else typing.RaiseError[Literal["ZipN length mismatch"], T]
)


def zip_n[*Ts](*ts: *Ts) -> ZipN[tuple[*Ts]]:
    return cast(
        ZipN[tuple[*Ts]],
        tuple(zip(*ts, strict=False)),
    )


def _check_zip() -> None:
    r2 = zip([1, 2, 3], ("a", "b", "c"))
    assert_type(r2, Iterator[tuple[int, str]])
    r3 = zip([1.0], ["x"], [True])
    assert_type(r3, Iterator[tuple[float, str, bool]])


# mypy assert_type checks
def _check_zip_two(
    x: Zip[tuple[int, str], tuple[float, bool]],
) -> None:
    assert_type(x, tuple[tuple[int, float], tuple[str, bool]])


def _check_zip_single(
    x: Zip[tuple[int], tuple[str]],
) -> None:
    assert_type(x, tuple[tuple[int, str]])


def _check_zip_empty(
    x: Zip[tuple[()], tuple[()]],
) -> None:
    assert_type(x, tuple[()])


def _check_zip_three(
    x: Zip[tuple[int, str, float], tuple[bool, bytes, list[int]]],
) -> None:
    assert_type(
        x, tuple[tuple[int, bool], tuple[str, bytes], tuple[float, list[int]]]
    )


def _check_zip_pairs(x: int) -> None:
    result = zip_pairs((1, "hello"), (3.14, True))
    assert_type(result, tuple[tuple[int, float], tuple[str, bool]])


def _check_zip_n_three(
    x: ZipN[tuple[tuple[int, str], tuple[float, bool], tuple[list, dict]]],
) -> None:
    assert_type(
        x,
        tuple[tuple[int, float, list], tuple[str, bool, dict]],
    )


def _check_zip_n_single(
    x: ZipN[tuple[tuple[int, str]]],
) -> None:
    assert_type(x, tuple[tuple[int], tuple[str]])


def _check_zip_n_empty(
    x: ZipN[tuple[tuple[()], tuple[()]]],
) -> None:
    assert_type(x, tuple[()])


def _check_zip_n_fn() -> None:
    result = zip_n((1, "a"), (2.0, True), ([0], {}))
    assert_type(
        result,
        tuple[
            tuple[int, float, list[int]],
            tuple[str, bool, dict[Never, Never]],
        ],
    )


# Runtime eval tests
def test_zip_basic():
    res = eval_typing(Zip[tuple[int, str], tuple[float, bool]])
    assert res == tuple[tuple[int, float], tuple[str, bool]]


def test_zip_single():
    res = eval_typing(Zip[tuple[int], tuple[str]])
    assert res == tuple[tuple[int, str]]


def test_zip_empty():
    res = eval_typing(Zip[tuple[()], tuple[()]])
    assert res == tuple[()]


def test_zip_three():
    res = eval_typing(
        Zip[tuple[int, str, float], tuple[bool, bytes, list[int]]]
    )
    assert (
        res
        == tuple[tuple[int, bool], tuple[str, bytes], tuple[float, list[int]]]
    )


def test_zip_mismatch():
    with pytest.raises(TypeMapError, match="Zip length mismatch"):
        eval_typing(Zip[tuple[int, str], tuple[float]])


def test_zip_mismatch_longer_second():
    with pytest.raises(TypeMapError, match="Zip length mismatch"):
        eval_typing(Zip[tuple[int], tuple[float, bool, str]])


def test_zip_pairs_runtime():
    result = zip_pairs((1, "hello"), (3.14, True))
    assert result == ((1, 3.14), ("hello", True))


def test_zip_n_three():
    res = eval_typing(
        ZipN[tuple[tuple[int, str], tuple[float, bool], tuple[list, dict]]]
    )
    assert res == tuple[tuple[int, float, list], tuple[str, bool, dict]]


def test_zip_n_single():
    res = eval_typing(ZipN[tuple[tuple[int, str]]])
    assert res == tuple[tuple[int], tuple[str]]


def test_zip_n_empty():
    res = eval_typing(ZipN[tuple[tuple[()], tuple[()]]])
    assert res == tuple[()]


def test_zip_n_mismatch():
    with pytest.raises(TypeMapError, match="ZipN length mismatch"):
        eval_typing(ZipN[tuple[tuple[int, str], tuple[float]]])


def test_zip_n_mismatch_three():
    with pytest.raises(TypeMapError, match="ZipN length mismatch"):
        eval_typing(
            ZipN[
                tuple[
                    tuple[int, str, bool],
                    tuple[float, bool],
                    tuple[list, dict, bytes],
                ]
            ]
        )


def test_zip_n_runtime():
    result = zip_n((1, "hello"), (3.14, True), ([], {}))
    assert result == ((1, 3.14, []), ("hello", True, {}))
