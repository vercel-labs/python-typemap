# SKIP MYPY

import pytest

from typing import Callable, Generic, Literal, Self, TypeVar

from typemap.type_eval import eval_call_with_types
from typemap_extensions import (
    GenericCallable,
    GetArg,
    IsAssignable,
    Iter,
    Members,
    Param,
    ParamKind,
    Params,
)


def test_eval_call_with_types_callable_01():
    res = eval_call_with_types(Callable[[], int])
    assert res is int


def test_eval_call_with_types_callable_02():
    res = eval_call_with_types(
        Callable[Params[Param[Literal["x"], int]], int], int
    )
    assert res is int


def test_eval_call_with_types_callable_03():
    res = eval_call_with_types(
        Callable[
            Params[Param[Literal["x"], int, Literal[ParamKind.KEYWORD_ONLY]]],
            int,
        ],
        x=int,
    )
    assert res is int


def test_eval_call_with_types_callable_04():
    class C: ...

    res = eval_call_with_types(
        Callable[Params[Param[Literal["self"], Self]], int], C
    )
    assert res is int


def test_eval_call_with_types_callable_05():
    class C: ...

    res = eval_call_with_types(
        Callable[Params[Param[Literal["self"], Self]], C], C
    )
    assert res is C


def test_eval_call_with_types_callable_06():
    class C: ...

    res = eval_call_with_types(
        Callable[
            Params[Param[Literal["self"], Self], Param[Literal["x"], int]],
            int,
        ],
        C,
        int,
    )
    assert res is int


def test_eval_call_with_types_callable_07():
    class C: ...

    res = eval_call_with_types(
        Callable[
            Params[
                Param[Literal["self"], Self],
                Param[Literal["x"], int, Literal[ParamKind.KEYWORD_ONLY]],
            ],
            int,
        ],
        C,
        x=int,
    )
    assert res is int


def test_eval_call_with_types_callable_08():
    T = TypeVar("T")
    res = eval_call_with_types(
        Callable[Params[Param[Literal["x"], T]], str], int
    )
    assert res is str


def test_eval_call_with_types_callable_09():
    T = TypeVar("T")
    res = eval_call_with_types(Callable[Params[Param[Literal["x"], T]], T], int)
    assert res is int


def test_eval_call_with_types_callable_10():
    T = TypeVar("T")

    class C(Generic[T]): ...

    res = eval_call_with_types(
        Callable[Params[Param[Literal["x"], C[T]]], T], C[int]
    )
    assert res is int


def test_eval_call_with_types_callable_11():
    T = TypeVar("T")

    class C(Generic[T]): ...

    class D(C[int]): ...

    class E(D): ...

    res = eval_call_with_types(
        Callable[Params[Param[Literal["x"], C[T]]], T], D
    )
    assert res is int
    res = eval_call_with_types(
        Callable[Params[Param[Literal["x"], C[T]]], T], E
    )
    assert res is int


def test_eval_call_with_types_local_function_01():
    def func(x: int) -> int: ...

    res = eval_call_with_types(func, int)
    assert res is int


def test_eval_call_with_types_local_function_02():
    def func(*, x: int) -> int: ...

    res = eval_call_with_types(func, x=int)
    assert res is int


def test_eval_call_with_types_local_function_03():
    def func[T](x: T) -> T: ...

    res = eval_call_with_types(func, int)
    assert res is int


def test_eval_call_with_types_local_function_04():
    class C: ...

    def func(x: C) -> C: ...

    res = eval_call_with_types(func, C)
    assert res is C


def test_eval_call_with_types_local_function_05():
    class C: ...

    def func[T](x: T) -> T: ...

    res = eval_call_with_types(func, C)
    assert res is C


def test_eval_call_with_types_local_function_06():
    T = TypeVar("T")

    class C(Generic[T]): ...

    def func[U](x: C[U]) -> C[U]: ...

    res = eval_call_with_types(func, C[int])
    assert res == C[int]


def test_eval_call_with_types_local_function_07():
    T = TypeVar("T")

    class C(Generic[T]): ...

    class D(C[int]): ...

    class E(D): ...

    def func[U](x: C[U]) -> U: ...

    res = eval_call_with_types(func, D)
    assert res is int
    res = eval_call_with_types(func, E)
    assert res is int


def test_eval_call_with_types_local_function_08():
    class C[T]: ...

    class D(C[int]): ...

    class E(C[str]): ...

    class F(D, E): ...

    def func[U](x: C[U]) -> U: ...

    res = eval_call_with_types(func, F)
    assert res is int


def test_eval_call_with_types_local_function_09():
    class C[T, U]: ...

    def func[V](x: C[int, V]) -> V: ...

    res = eval_call_with_types(func, C[int, str])
    assert res is str


def test_eval_call_with_types_bind_error_01():
    T = TypeVar("T")

    with pytest.raises(
        ValueError, match="Type variable T is already bound to int, but got str"
    ):
        eval_call_with_types(
            Callable[
                Params[Param[Literal["x"], T], Param[Literal["y"], T]],
                T,
            ],
            int,
            str,
        )


def test_eval_call_with_types_bind_error_02():
    def func[T](x: T, y: T) -> T: ...

    with pytest.raises(
        ValueError, match="Type variable T is already bound to int, but got str"
    ):
        eval_call_with_types(func, int, str)


def test_eval_call_with_types_bind_error_03():
    T = TypeVar("T")

    class C(Generic[T]): ...

    with pytest.raises(
        ValueError, match="Type variable T is already bound to int, but got str"
    ):
        eval_call_with_types(
            Callable[
                Params[Param[Literal["x"], C[T]], Param[Literal["y"], C[T]]],
                T,
            ],
            C[int],
            C[str],
        )


def test_eval_call_with_types_bind_error_04():
    class C[T]: ...

    def func[T](x: C[T], y: C[T]) -> T: ...

    with pytest.raises(
        ValueError, match="Type variable T is already bound to int, but got str"
    ):
        eval_call_with_types(func, C[int], C[str])


def test_eval_call_with_types_bind_error_05():
    class C[T]: ...

    class D[T]: ...

    def func[T](x: C[T]) -> T: ...

    with pytest.raises(ValueError, match="Argument type mismatch for x"):
        eval_call_with_types(func, D[int])


type GetCallableMember[T, N: str] = GetArg[
    tuple[
        *[
            m.type
            for m in Iter[Members[T]]
            if (
                IsAssignable[m.type, Callable]
                or IsAssignable[m.type, GenericCallable]
            )
            and IsAssignable[m.name, N]
        ]
    ],
    tuple,
    Literal[0],
]


def test_eval_call_with_types_member_01():
    class C:
        def invoke(self, x: int) -> int: ...

    res = eval_call_with_types(GetCallableMember[C, Literal["invoke"]], C, int)
    assert res is int


def test_eval_call_with_types_member_02():
    class C:
        def invoke[T](self, x: T) -> T: ...

    res = eval_call_with_types(GetCallableMember[C, Literal["invoke"]], C, int)
    assert res is int


def test_eval_call_with_types_member_03():
    class C[T]:
        def invoke(self, x: str) -> str: ...

    res = eval_call_with_types(
        GetCallableMember[C[int], Literal["invoke"]], C[int], str
    )
    assert res is str


def test_eval_call_with_types_member_04():
    class C[T]:
        def invoke(self, x: T) -> T: ...

    res = eval_call_with_types(
        GetCallableMember[C[int], Literal["invoke"]], C[int], int
    )
    assert res is int


def test_eval_call_with_types_member_05():
    class C[T]:
        def invoke(self) -> C[T]: ...

    res = eval_call_with_types(
        GetCallableMember[C[int], Literal["invoke"]], C[int]
    )
    assert res == C[int]


def test_eval_call_with_types_member_06():
    class C[T]:
        def invoke[U](self, x: U) -> C[U]: ...

    res = eval_call_with_types(
        GetCallableMember[C[int], Literal["invoke"]], C[int], str
    )
    assert res == C[str]
