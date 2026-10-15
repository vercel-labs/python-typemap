# SKIP MYPY: runs forever! must debug

import pytest
import typing

from typemap.type_eval import eval_call_with_types, eval_typing, TypeMapError
from typemap.typing import _BoolLiteral

from typemap_extensions import (
    Attrs,
    BaseTypedDict,
    GetArg,
    IsAssignable,
    IsEquivalent,
    Member,
    NewProtocol,
    RaiseError,
)


"""
An AST like system for doing simple type checked computation.

Provides Constant and Variable nodes which can be used with operators
(+, -, *, /, //, **, and %) to build up expression trees.

Calling eval on a Node with **kwargs corresponding to the Variables in
the expression will compute and return the result.

Example usage:
    a = Variable[int, typing.Literal["a"]]()
    b = Variable[int, typing.Literal["b"]]()
    c = Constant(3)
    z = a + b * c
    result = eval(z, a=1, b=2)
    assert result is 7
"""


type VarArg[Name: str, T: type] = tuple[Name, T]

type VarArgName[V: VarArg] = GetArg[V, tuple, typing.Literal[0]]
type VarArgType[V: VarArg] = GetArg[V, tuple, typing.Literal[1]]


type CombineVarArgs[Ls: tuple[VarArg], Rs: tuple[VarArg]] = tuple[
    *[
        VarArg[
            VarArgName[x],
            (
                VarArgType[x]
                if not any(  # Unique to Ls
                    IsEquivalent[VarArgName[x], VarArgName[y]] for y in Rs
                )
                else GetArg[  # Common to both Ls and Rs
                    tuple[
                        *[
                            (
                                VarArgType[x]
                                if IsAssignable[VarArgType[x], VarArgType[y]]
                                else VarArgType[y]
                                if IsAssignable[VarArgType[y], VarArgType[x]]
                                else RaiseError[
                                    typing.Literal[
                                        "Type mismatch for variable"
                                    ],
                                    VarArgName[x],
                                    VarArgType[x],
                                    VarArgType[y],
                                ]
                            )
                            for y in Rs
                            if IsEquivalent[VarArgName[x], VarArgName[y]]
                        ]
                    ],
                    tuple,
                    typing.Literal[0],
                ]
            ),
        ]
        for x in Ls
    ],
    *[  # Unique to Rs
        x
        for x in Rs
        if not any(  # Unique to Rs
            IsEquivalent[VarArgName[x], VarArgName[y]] for y in Ls
        )
    ],
]


def test_astlike_1_combine_varargs_01():
    t = eval_typing(
        CombineVarArgs[
            tuple[
                VarArg[typing.Literal["same"], int],
                VarArg[typing.Literal["left_sub"], bool],
                VarArg[typing.Literal["right_sub"], int],
                VarArg[typing.Literal["unique_left"], int],
            ],
            tuple[
                VarArg[typing.Literal["same"], int],
                VarArg[typing.Literal["left_sub"], int],
                VarArg[typing.Literal["right_sub"], bool],
                VarArg[typing.Literal["unique_right"], int],
            ],
        ]
    )
    assert (
        t
        == tuple[
            tuple[typing.Literal["same"], int],
            tuple[typing.Literal["left_sub"], bool],
            tuple[typing.Literal["right_sub"], bool],
            tuple[typing.Literal["unique_left"], int],
            tuple[typing.Literal["unique_right"], int],
        ]
    )


def test_astlike_1_combine_varargs_02():
    with pytest.raises(
        TypeMapError, match="Type mismatch for variable.*different.*int.*float"
    ):
        eval_typing(
            CombineVarArgs[
                tuple[VarArg[typing.Literal["different"], int],],
                tuple[VarArg[typing.Literal["different"], float],],
            ]
        )


type IsNumericAssignable[L, R] = (
    IsAssignable[R, L]
    or (IsEquivalent[L, float] and IsFloat[R])
    or (IsEquivalent[L, complex] and IsComplex[R])
)
type VarIsPresent[V: VarArg, K: BaseTypedDict] = any(
    IsEquivalent[VarArgName[V], x.name]
    and IsNumericAssignable[VarArgType[V], x.type]
    for x in Attrs[K]
)
type AllVarsPresent[Vs: tuple[VarArg, ...], K: BaseTypedDict] = all(
    VarIsPresent[v, K] for v in Vs
)


def test_astlike_1_all_vars_present_01():
    t = eval_typing(
        AllVarsPresent[
            tuple[VarArg[typing.Literal["x"], int]],
            NewProtocol[Member[typing.Literal["x"], int]],
        ]
    )
    assert t == _BoolLiteral[True]


def test_astlike_1_all_vars_present_02():
    t = eval_typing(
        AllVarsPresent[
            tuple[VarArg[typing.Literal["x"], int]],
            NewProtocol[Member[typing.Literal["x"], bool]],
        ]
    )
    assert t == _BoolLiteral[True]


def test_astlike_1_all_vars_present_03():
    t = eval_typing(
        AllVarsPresent[
            tuple[VarArg[typing.Literal["x"], int]],
            NewProtocol[Member[typing.Literal["x"], float]],
        ]
    )
    assert t == _BoolLiteral[False]


def test_astlike_1_all_vars_present_04():
    t = eval_typing(
        AllVarsPresent[
            tuple[VarArg[typing.Literal["x"], int]],
            NewProtocol[
                Member[typing.Literal["x"], int],
                Member[typing.Literal["y"], int],
            ],
        ]
    )
    assert t == _BoolLiteral[True]


def test_astlike_1_all_vars_present_05():
    t = eval_typing(
        AllVarsPresent[
            tuple[VarArg[typing.Literal["x"], int]],
            NewProtocol[Member[typing.Literal["y"], int]],
        ]
    )
    assert t == _BoolLiteral[False]


type IsIntegral[T] = IsAssignable[T, int]
type IsFloat[T] = IsIntegral[T] or IsAssignable[T, float]
type IsComplex[T] = IsFloat[T] or IsAssignable[T, complex]

type SimpleNumericOp[L, R, OpName: str] = (
    int
    if IsIntegral[L] and IsIntegral[R]
    else float
    if IsFloat[L] and IsFloat[R]
    else RaiseError[
        typing.Literal["Operation only supports int or float"], OpName
    ]
)
type ComplexNumericOp[L, R, OpName] = (
    SimpleNumericOp[L, R, OpName]
    if IsFloat[L] and IsFloat[R]
    else complex
    if IsComplex[L] and IsComplex[R]
    else RaiseError[
        typing.Literal["Operation only supports int, float, or complex"], OpName
    ]
)

type Add[L, R] = ComplexNumericOp[L, R, typing.Literal["+"]]
type Sub[L, R] = ComplexNumericOp[L, R, typing.Literal["-"]]
type Mul[L, R] = ComplexNumericOp[L, R, typing.Literal["*"]]
type TrueDiv[L, R] = (
    float
    if IsAssignable[L, int] and IsAssignable[R, int]
    else ComplexNumericOp[L, R, typing.Literal["/"]]
)
type FloorDiv[L, R] = SimpleNumericOp[L, R, typing.Literal["//"]]
type Pow[L, R] = ComplexNumericOp[L, R, typing.Literal["**"]]
type Mod[L, R] = SimpleNumericOp[L, R, typing.Literal["%"]]


def test_astlike_1_numeric_op_01():
    complex_ops = (
        (Add, r"\+"),
        (Sub, r"\-"),
        (Mul, r"\*"),
        (TrueDiv, r"/"),
        (Pow, r"\*\*"),
    )
    ts = (int, float, complex)

    for op, op_name in complex_ops:
        for lhs in range(len(ts)):
            for rhs in range(len(ts)):
                t = eval_typing(op[ts[lhs], ts[rhs]])

                expected = ts[max(lhs, rhs)]
                if op is TrueDiv and ts[lhs] is int and ts[rhs] is int:
                    expected = float

                assert t is expected

        for arg in range(len(ts)):
            with pytest.raises(
                TypeMapError,
                match=f"Operation only supports int, float, or complex:.*{op_name}",
            ):
                eval_typing(op[ts[arg], str])
            with pytest.raises(
                TypeMapError,
                match=f"Operation only supports int, float, or complex:.*{op_name}",
            ):
                eval_typing(op[str, ts[arg]])


def test_astlike_1_numeric_op_02():
    simple_ops = ((FloorDiv, r"//"), (Mod, r"%"))
    ts = (int, float)

    for op, op_name in simple_ops:
        for lhs in range(len(ts)):
            for rhs in range(len(ts)):
                t = eval_typing(op[ts[lhs], ts[rhs]])
                expected = ts[max(lhs, rhs)]
                assert t is expected

        for arg in range(len(ts)):
            with pytest.raises(
                TypeMapError,
                match=f"Operation only supports int or float: .*{op_name}",
            ):
                eval_typing(op[ts[arg], str])
            with pytest.raises(
                TypeMapError,
                match=f"Operation only supports int or float: .*{op_name}",
            ):
                eval_typing(op[str, ts[arg]])


class NodeMeta(type): ...


class Node[T, Vs: tuple[VarArg, ...]](metaclass=NodeMeta):
    def __add__[OtherT, OtherVs: tuple[VarArg, ...]](
        self, other: Node[OtherT, OtherVs]
    ) -> Node[Add[T, OtherT], CombineVarArgs[Vs, OtherVs]]: ...

    def __sub__[OtherT, OtherVs: tuple[VarArg, ...]](
        self, other: Node[OtherT, OtherVs]
    ) -> Node[Sub[T, OtherT], CombineVarArgs[Vs, OtherVs]]: ...

    def __mul__[OtherT, OtherVs: tuple[VarArg, ...]](
        self, other: Node[OtherT, OtherVs]
    ) -> Node[Mul[T, OtherT], CombineVarArgs[Vs, OtherVs]]: ...

    def __truediv__[OtherT, OtherVs: tuple[VarArg, ...]](
        self, other: Node[OtherT, OtherVs]
    ) -> Node[TrueDiv[T, OtherT], CombineVarArgs[Vs, OtherVs]]: ...

    def __floordiv__[OtherT, OtherVs: tuple[VarArg, ...]](
        self, other: Node[OtherT, OtherVs]
    ) -> Node[FloorDiv[T, OtherT], CombineVarArgs[Vs, OtherVs]]: ...

    def __pow__[OtherT, OtherVs: tuple[VarArg, ...]](
        self, other: Node[OtherT, OtherVs]
    ) -> Node[Pow[T, OtherT], CombineVarArgs[Vs, OtherVs]]: ...

    def __mod__[OtherT, OtherVs: tuple[VarArg, ...]](
        self, other: Node[OtherT, OtherVs]
    ) -> Node[Mod[T, OtherT], CombineVarArgs[Vs, OtherVs]]: ...


class Constant[T](Node[T, tuple[()]]):
    value: typing.Any

    def __init__(self, value) -> None:
        self.value = value


def test_astlike_1_constant_01():
    t = eval_typing(Constant[int])
    assert t == Constant[int]


def test_astlike_1_constant_02():
    t = eval_call_with_types(eval, Constant[int])
    assert t is int

    t = eval_call_with_types(eval, Constant[int], x=int)
    assert t is int


class Variable[T, Name: typing.Literal[str]](Node[T, tuple[VarArg[Name, T]]]):
    @property
    def name(self) -> typing.Literal[Name]:
        return self.__orig_class__.__args__[1].__args__[0]

    def _eval(self, **kwargs) -> T:
        if self.name not in kwargs:
            raise ValueError(f"Expected '{self.name}' in kwargs")
        if not isinstance(kwargs[self.name], self.__orig_class__.__args__[0]):
            raise ValueError(
                f"Expected '{self.__orig_class__.__args__[0].__name__}', "
                f"got '{type(kwargs[self.name]).__name__}'"
            )
        return kwargs[self.name]


def test_astlike_1_variable_01():
    n = Variable[int, typing.Literal["x"]]
    assert n().name == "x"


def test_astlike_1_variable_02():
    t = eval_call_with_types(eval, Variable[int, typing.Literal["x"]], x=int)
    assert t is int
    t = eval_call_with_types(eval, Variable[int, typing.Literal["x"]], x=bool)
    assert t is int
    t = eval_call_with_types(eval, Variable[int, typing.Literal["x"]], x=str)
    assert t is typing.Never


def eval[T, Vs: tuple[VarArg, ...], K: BaseTypedDict](
    self: Node[T, Vs], **kwargs: typing.Unpack[K]
) -> T if AllVarsPresent[Vs, K] else typing.Never: ...


def test_astlike_1_eval_01():
    n = Node[int, tuple[VarArg[typing.Literal["x"], int]]]
    t = eval_call_with_types(eval, n, x=int)
    assert t is int
    t = eval_call_with_types(eval, n, x=bool)
    assert t is int
    t = eval_call_with_types(eval, n, x=str)
    assert t is typing.Never


def test_astlike_1_eval_02():
    n = Node[
        complex,
        tuple[
            VarArg[typing.Literal["x"], float],
            VarArg[typing.Literal["y"], float],
        ],
    ]
    t = eval_call_with_types(eval, n, x=int, y=int)
    assert t is complex
    t = eval_call_with_types(eval, n, x=bool, y=float)
    assert t is complex
    t = eval_call_with_types(eval, n, x=str, y=complex)
    assert t is typing.Never
