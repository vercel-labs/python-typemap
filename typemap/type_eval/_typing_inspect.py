# SPDX-PackageName: gel-python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright Gel Data Inc. and the contributors.


import annotationlib
import typing
from types import GenericAlias, UnionType
from typing import (  # type: ignore [attr-defined]  # noqa: PLC2701
    Annotated,
    Any,
    ForwardRef,
    Literal,
    TypeGuard,
    TypeVar,
    Union,
    _GenericAlias,
    _SpecialGenericAlias,
    get_args,
    get_origin,
)

from typing_extensions import TypeAliasType, TypeVarTuple, Unpack

from . import _eval_typing


def is_special_form(t: Any, form: Any) -> bool:
    """Check if t is a special form or a generic alias of that form.

    Args:
        t: The type to check
        form: The special form to check against (e.g., ClassVar, Final, Literal)

    Returns:
        True if t is the special form or a generic alias with that origin
    """
    return t is form or (is_generic_alias(t) and get_origin(t) is form)


def is_generic_alias(t: Any) -> TypeGuard[GenericAlias]:
    return isinstance(t, (GenericAlias, _GenericAlias, _SpecialGenericAlias))


def is_valid_type_arg(t: Any) -> bool:
    return isinstance(t, type) or (
        is_generic_alias(t) and get_origin(t) is not Unpack
    )


# In Python 3.10 isinstance(tuple[int], type) is True, but
# issubclass will fail if you pass such type to it.
def is_valid_isinstance_arg(t: Any) -> typing.TypeGuard[type[Any]]:
    return isinstance(t, type) and not is_generic_alias(t)


def is_type_alias(t: Any) -> TypeGuard[TypeAliasType]:
    return isinstance(t, TypeAliasType) and not is_generic_alias(t)


def is_type_var(t: Any) -> bool:
    return type(t) is TypeVar


if (TypingTypeVarTuple := getattr(typing, "TypeVarTuple", None)) is not None:

    def is_type_var_tuple(t: Any) -> bool:
        tt = type(t)
        return tt is TypeVarTuple or tt is TypingTypeVarTuple

    def is_type_var_or_tuple(t: Any) -> bool:
        tt = type(t)
        return tt is TypeVar or tt is TypeVarTuple or tt is TypingTypeVarTuple
else:

    def is_type_var_tuple(t: Any) -> bool:
        return type(t) is TypeVarTuple

    def is_type_var_or_tuple(t: Any) -> bool:
        tt = type(t)
        return tt is TypeVar or tt is TypeVarTuple


def is_type_var_tuple_unpack(t: Any) -> TypeGuard[GenericAlias]:
    return (
        is_generic_alias(t)
        and get_origin(t) is Unpack
        and is_type_var_tuple(get_args(t)[0])
    )


def is_type_var_or_tuple_unpack(t: Any) -> bool:
    return is_type_var(t) or is_type_var_tuple_unpack(t)


def is_unbounded_tuple(t: Any) -> bool:
    """Whether t is tuple[X, ...]."""
    if not (is_generic_alias(t) and get_origin(t) is tuple):
        return False
    args = get_args(t)
    return len(args) == 2 and args[1] is Ellipsis


def is_unbounded_tuple_unpack(t: Any) -> bool:
    """Whether t is Unpack[tuple[X, ...]]."""
    return (
        is_generic_alias(t)
        and get_origin(t) is Unpack
        and is_unbounded_tuple(get_args(t)[0])
    )


def is_generic_type_alias(t: Any) -> TypeGuard[GenericAlias]:
    return is_generic_alias(t) and isinstance(get_origin(t), TypeAliasType)


def is_annotated(t: Any) -> TypeGuard[Annotated[Any, ...]]:
    return is_generic_alias(t) and get_origin(t) is Annotated


def is_forward_ref(t: Any) -> TypeGuard[ForwardRef]:
    return isinstance(t, ForwardRef)


def contains_forward_refs(t: Any) -> bool:
    if isinstance(t, (ForwardRef, str)):
        # A direct ForwardRef or a PEP563/649 postponed annotation
        return True
    elif isinstance(t, TypeAliasType):
        # PEP 695 type alias: unwrap and recurse
        return contains_forward_refs(t.__value__)
    elif args := get_args(t):
        # Generic type: unwrap and recurse
        return any(contains_forward_refs(arg) for arg in args)
    else:
        # No forward refs.
        return False


def is_union_type(t: Any) -> TypeGuard[UnionType]:
    return (is_generic_alias(t) and get_origin(t) is Union) or isinstance(
        t, UnionType
    )


def is_optional_type(t: Any) -> TypeGuard[UnionType]:
    return is_union_type(t) and type(None) in get_args(t)


def is_literal(t: Any) -> TypeGuard[GenericAlias]:
    return is_generic_alias(t) and get_origin(t) is Literal


def get_head(t: Any) -> type | None:
    if is_generic_alias(t):
        return get_head(get_origin(t))
    elif is_eval_proxy(t):
        return get_head(t.__origin__)
    elif isinstance(t, type):
        return t
    else:
        return None


def is_eval_proxy(t: Any) -> TypeGuard[type[_eval_typing._EvalProxy]]:
    return isinstance(t, type) and issubclass(t, _eval_typing._EvalProxy)


def param_default(p) -> Any:
    return Any if p.__default__ == typing.NoDefault else p.__default__


def get_local_type_hints(obj, **kwargs) -> dict[str, Any]:
    """Return type hints for an object, excluding inherited annotations.

    This works by calling typing.get_type_hints() and then filtering out
    any keys that don't also appear in annotationlib.get_annotations().
    """
    hints = typing.get_type_hints(obj, **kwargs)
    local_annotations = annotationlib.get_annotations(obj)
    return {k: v for k, v in hints.items() if k in local_annotations}


__all__ = (
    "get_local_type_hints",
    "is_annotated",
    "is_forward_ref",
    "is_generic_alias",
    "is_generic_type_alias",
    "is_literal",
    "is_optional_type",
    "is_special_form",
    "is_type_alias",
    "is_union_type",
)
