import textwrap

from typing import Unpack

from typemap.type_eval import eval_call
from typemap_extensions import (
    Attrs,
    BaseTypedDict,
    NewProtocol,
    Member,
)

from typemap.type_eval import format_helper


def func[*T, K: BaseTypedDict](
    *args: Unpack[T],
    **kwargs: Unpack[K],
) -> NewProtocol[*[Member[c.name, int] for c in Attrs[K]]]:
    raise NotImplementedError


def test_call_1():
    ret = eval_call(func, a=1, b=2, c="aaa")
    fmt = format_helper.format_class(ret)

    assert fmt == textwrap.dedent("""\
        class func[...]:
            a: int
            b: int
            c: int
        """)


def func_trivial[*T, K: BaseTypedDict](
    *args: Unpack[T],
    **kwargs: Unpack[K],
) -> K:
    return kwargs


def test_call_2():
    ret = eval_call(func_trivial, a=1, b=2, c="aaa")
    fmt = format_helper.format_class(ret)

    assert fmt == textwrap.dedent("""\
        class **kwargs:
            a: typing.Literal[1]
            b: typing.Literal[2]
            c: typing.Literal['aaa']
        """)


class Wrapped[T]:  # noqa: B903
    value: T

    def __init__(self, value: T):
        self.value = value


def wrapped[T](value: T) -> Wrapped[T]:
    return Wrapped[T](value)


def test_call_3():
    ret = eval_call(wrapped, 1)
    fmt = format_helper.format_class(ret)

    assert fmt == textwrap.dedent("""\
        class Wrapped[typing.Literal[1]]:
            value: typing.Literal[1]
            def __init__(self: Self, value: Literal[1]) -> None: ...
        """)
