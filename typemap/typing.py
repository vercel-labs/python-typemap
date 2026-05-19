# mypy: ignore-errors

import contextvars
import typing
import types

from typing import Literal, Unpack
from typing import (
    _GenericAlias,
    _LiteralGenericAlias,
    _UnpackGenericAlias,
)

_SpecialForm: typing.Any = typing._SpecialForm

###

# Here is a bunch of annoying internals stuff!


class _TupleLikeOperator:
    @classmethod
    def __class_getitem__(cls, args):
        # Return an _IterSafeGenericAlias instead of a _GenericAlias
        res = super().__class_getitem__(args)
        return _IterSafeGenericAlias(res.__origin__, res.__args__)


# The base _GenericAlias has an __iter__ method that returns
# Unpack[self], which blows up when it's passed to something and
# doesn't have a tuple inside (because it hasn't been evaluated yet!).
# So we make own _GenericAlias that makes our own _UnpackGenericAlias
# that we make sure works.
#
# Probably these exact hacks will need to go into our
# typing_extensions version of this, but for the typing version they
# can get merged into real classes.
class _IterSafeGenericAlias(_GenericAlias, _root=True):
    def __iter__(self):
        yield _IterSafeUnpackGenericAlias(origin=Unpack, args=(self,))


class _IterSafeUnpackGenericAlias(_UnpackGenericAlias, _root=True):
    @property
    def __typing_unpacked_tuple_args__(self):
        # This is basically the same as in _UnpackGenericAlias except
        # we don't blow up if the origin isn't a tuple.
        assert self.__origin__ is Unpack
        assert len(self.__args__) == 1
        (arg,) = self.__args__
        if isinstance(arg, (_GenericAlias, types.GenericAlias)):
            if arg.__origin__ is tuple:
                return arg.__args__
        return None


###


def has_associated_types(ocls):
    def __class_getitem__(cls, args):
        # Return an _HasAssociatedTypesGenericAlias instead of a _GenericAlias
        res = super(ocls, cls).__class_getitem__(args)
        return _HasAssociatedTypesGenericAlias(res.__origin__, res.__args__)

    ocls.__class_getitem__ = classmethod(__class_getitem__)
    return ocls


class _AssociatedTypeGenericAlias(_GenericAlias, _root=True):
    pass


class _AssociatedType[Obj, Alias]:
    pass


class _HasAssociatedTypesGenericAlias(_GenericAlias, _root=True):
    def __getattr__(self, attr):
        res = super().__getattr__(attr)
        if isinstance(res, typing.TypeAliasType):
            res = _AssociatedTypeGenericAlias(_AssociatedType, (self, res))
        return res


###


# Not type-level computation but related


class BaseTypedDict(typing.TypedDict):
    pass


class SpecialFormEllipsis:
    pass


###


class _GenericCallableGenericAlias(_GenericAlias, _root=True):
    def __repr__(self):
        from typing import _type_repr

        name = _type_repr(self.__origin__)
        if self.__args__:
            rargs = [_type_repr(self.__args__[0]), "<...>"]
            args = ", ".join(rargs)
        else:
            # To ensure the repr is eval-able.
            args = "()"
        return f'{name}[{args}]'


class GenericCallable:
    def __class_getitem__(cls, params):
        message = (
            "GenericCallable must be used as "
            "GenericCallable[tuple[TypeVar, ...], lambda <vs>: callable]."
        )
        if not isinstance(params, tuple) or len(params) != 2:
            raise TypeError(message)

        typevars, func = params
        if not callable(func):
            raise TypeError(message)

        return _GenericCallableGenericAlias(cls, (typevars, func))


class Overloaded[*Callables]:
    pass


###


class InitField[KwargDict: BaseTypedDict]:
    """Base class to support dataclass.Field type initializers!

    Will require some magical treatment in typecheckers...
    """

    __kwargs: KwargDict

    def __init__(self, **kwargs: typing.Unpack[KwargDict]) -> None:
        self.__kwargs = kwargs

    def get_kwargs(self) -> KwargDict:
        return self.__kwargs

    def __repr__(self) -> str:
        args = ', '.join(f'{k}={v!r}' for k, v in self.__kwargs.items())
        return f'{type(self).__name__}({args})'


###


class GetAnnotations[T]:
    """Fetch the annotations of a potentially Annotated type, as Literals.

    GetAnnotations[Annotated[int, 'xxx']] = Literal['xxx']
    GetAnnotations[Annotated[int, 'xxx', 5]] = Literal['xxx', 5]
    GetAnnotations[int] = Never
    """


class DropAnnotations[T]:
    """Drop the annotations of a potentially Annotated type

    DropAnnotations[Annotated[int, 'xxx']] = int
    DropAnnotations[Annotated[int, 'xxx', 5]] = int
    DropAnnotations[int] = int
    """


###


MemberQuals = Literal["ClassVar", "Final", "NotRequired", "ReadOnly"]


@has_associated_types
class Member[
    N: str,
    T,
    Q: MemberQuals = typing.Never,
    I = typing.Never,
    D = typing.Never,
]:
    type name = N
    type type = T
    type quals = Q
    type init = I
    type definer = D


ParamQuals = Literal["*", "**", "keyword", "positional"]


@has_associated_types
class Param[N: str | None, T, Q: ParamQuals = typing.Never, D = typing.Never]:
    type name = N
    type type = T
    type quals = Q
    type default = D


type PosParam[N: str | None, T] = Param[N, T, Literal["positional"]]
type PosDefaultParam[N: str | None, T] = Param[N, T, Literal["positional"], T]
type DefaultParam[N: str, T] = Param[N, T, typing.Never, T]
type NamedParam[N: str, T] = Param[N, T, Literal["keyword"]]
type NamedDefaultParam[N: str, T] = Param[N, T, Literal["keyword"], T]
type ArgsParam[T] = Param[Literal[None], T, Literal["*"]]
type KwargsParam[T] = Param[Literal[None], T, Literal["**"]]


class Params:
    """A concrete parameter specification for extended Callable types.

    Params[Param[...], ...] can be used as the first argument to
    Callable, like ParamSpec. It survives the typing.Callable round-trip
    by using _ConcatenateGenericAlias internally.
    """

    def __class_getitem__(cls, params):
        if not isinstance(params, tuple):
            params = (params,)
        return typing._ConcatenateGenericAlias(cls, params)


type GetName[T: Member | Param] = T.name
type GetType[T: Member | Param] = T.type
type GetQuals[T: Member | Param] = T.quals
type GetDefault[T: Param] = T.default
type GetInit[T: Member] = T.init
type GetDefiner[T: Member] = T.definer


class Attrs[T](_TupleLikeOperator):
    pass


class Members[T](_TupleLikeOperator):
    pass


class FromUnion[T](_TupleLikeOperator):
    pass


class GetMember[Lhs, Prop]:
    pass


class GetMemberType[Lhs, Prop]:
    pass


class GetArg[Tp, Base, Idx: int]:
    pass


class GetArgs[Tp, Base](_TupleLikeOperator):
    pass


class GetSpecialAttr[T: type, Attr: str]:
    pass


class Length[S: tuple]:
    pass


class Slice[S: str | tuple, Start: int | None, End: int | None](
    _TupleLikeOperator
):
    pass


class Uppercase[S: str]:
    pass


class Lowercase[S: str]:
    pass


class Capitalize[S: str]:
    pass


class Uncapitalize[S: str]:
    pass


class Concat[S: str, T: str]:
    pass


class NewProtocol[*T]:
    pass


class NewTypedDict[*T]:
    pass


class UpdateClass[*Ms]:
    pass


class RaiseError[S: str, *Ts]:
    """Raise a type error with the given message when evaluated.

    RaiseError[S: Literal[str], *Ts]: If this type needs to be evaluated
    to determine some actual type, generate a type error with the
    provided message.

    Any additional type arguments should be included in the message.
    """

    pass


##################################################################

# TODO: type better
special_form_evaluator: contextvars.ContextVar[
    typing.Callable[[typing.Any], typing.Any] | None
] = contextvars.ContextVar("special_form_evaluator", default=None)


class _IterGenericAlias(_GenericAlias, _root=True):
    def __iter__(self):
        evaluator = special_form_evaluator.get()
        if evaluator:
            return evaluator(self)
        else:
            return iter(())


@_SpecialForm
def Iter(self, tp):
    return _IterGenericAlias(self, (tp,))


class _BoolGenericAlias(_GenericAlias, _root=True):
    def __bool__(self):
        evaluator = special_form_evaluator.get()
        if evaluator:
            result = evaluator(self)
            # Unwrap _LiteralGeneric
            return bool(result)
        else:
            return False


@_SpecialForm
def IsAssignable(self, tps):
    return _BoolGenericAlias(self, tps)


@_SpecialForm
def IsEquivalent(self, tps):
    return _BoolGenericAlias(self, tps)


@_SpecialForm
def Bool(self, tp):
    return _BoolGenericAlias(self, tp)


class _BoolLiteralGenericAlias(_LiteralGenericAlias, _root=True):
    def __bool__(self):
        return typing.get_args(self)[0]


@_SpecialForm
def _BoolLiteral(self, tp):
    if isinstance(tp, type):
        raise TypeError(f"Expected literal type, got '{tp.__name__}'")

    # If already wrapped, just return it
    if isinstance(tp, _BoolLiteralGenericAlias):
        return tp

    return _BoolLiteralGenericAlias(Literal, tp)
