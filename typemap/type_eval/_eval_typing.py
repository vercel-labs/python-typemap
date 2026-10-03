import collections.abc
import contextlib
import contextvars
import dataclasses
import functools
import inspect
import types
import typing

from typing import (  # type: ignore [attr-defined]  # noqa: PLC2701
    _GenericAlias as typing_GenericAlias,
    _CallableGenericAlias as typing_CallableGenericAlias,
    _LiteralGenericAlias as typing_LiteralGenericAlias,
    _AnnotatedAlias as typing_AnnotatedAlias,
    _UnpackGenericAlias as typing_UnpackGenericAlias,
)

from typemap.typing import _AssociatedTypeGenericAlias


if typing.TYPE_CHECKING:
    from typing import Any, Sequence

from . import _apply_generic


__all__ = ("eval_typing",)


class StuckException(Exception):
    """Raised when a type operator receives a type variable argument."""

    pass


_eval_funcs: dict[type, typing.Callable[..., Any]] = {}
# Evaluators that receive their arguments unevaluated
_lazy_eval_funcs: set[type] = set()


def register_evaluator[T: typing.Callable[..., Any]](
    typ: type, *, lazy: bool = False
) -> typing.Callable[[T], T]:
    def func(f: T) -> T:
        assert typ not in _eval_funcs
        _eval_funcs[typ] = f
        if lazy:
            _lazy_eval_funcs.add(typ)
        return f

    return func


# Base type for the proxy classes we generate to hold __annotations__
class _EvalProxy:
    # Make sure __origin__ doesn't show up at runtime...
    if typing.TYPE_CHECKING:
        __origin__: type


@dataclasses.dataclass
class EvalContext:
    # Fully resolved types
    resolved: dict[Any, Any] = dataclasses.field(default_factory=dict)
    # Types that have been seen, but may not be fully resolved
    seen: dict[Any, Any] = dataclasses.field(default_factory=dict)

    # We want to resolve recursive type aliases correctly, but not have
    # haphazardly expanded results which vary based on order of evaluation,
    # nesting, etc.
    #
    # To produce consistent results, we leave recursive type aliases unexpanded,
    # unless they are the final result.
    #
    # For example, given A = int|list[A],
    #   A expands to int|list[A]
    #   list[A] remains as list[A]
    #
    # IMPLEMENTATION
    #
    # To achieve this behavior, we resolve recursive type aliases in a way that
    # prevents them from interacting with each other's evaluations.
    #
    # Once a recursive alias is fully resolved, we discard all intermediate
    # evaluations and only keep the final result. We then mark the resolve value
    # for the alias as itself, ensure that external evaluations don't expand it.
    # We keep the actual expanded value in `known_recursive_types` for future
    # reference.
    #
    # We identify recursive type aliases by tracking any aliases we see in
    # `alias_stack`. If an alias is seen again, we know it is a recursive alias
    # and note it in `recursive_type_alias`. When we finally unwind to the
    # previous time we saw the alias, we know it is fully resolved.
    #
    # Intermediate evaluations are discarded because evaluating recursive
    # generic classes use the `seen` dictionary as a cache. Sharing this cache
    # would cause inconsistent expansion results.
    #
    # For example, given A = C|list[B] and B = D|list[A], A|B could expand to
    # C|D|list[D|list[A]]|list[A] which is technically correct, but not
    # consistent in the way we want.
    #
    # The alias stack is also used to evaluate generic classes. The current
    # generic alias is tracked in `current_generic_alias`.
    # See `_eval_types_generic`.
    alias_stack: set[typing.TypeAliasType | types.GenericAlias] = (
        dataclasses.field(default_factory=set)
    )
    recursive_type_alias: typing.TypeAliasType | types.GenericAlias | None = (
        None
    )
    known_recursive_types: dict[
        typing.TypeAliasType | types.GenericAlias, typing.Any
    ] = dataclasses.field(default_factory=dict)

    box_cache: dict[typing.Any, _apply_generic.Boxed] = dataclasses.field(
        default_factory=dict
    )

    # The typing.Any is really a types.FunctionType, but mypy gets
    # confused and wants to treat it as a MethodType.
    current_generic_alias: types.GenericAlias | typing.Any | None = None


# `eval_types()` calls can be nested, context must be preserved
_current_context: contextvars.ContextVar[EvalContext | None] = (
    contextvars.ContextVar('_current_context', default=None)
)


@contextlib.contextmanager
def _ensure_context() -> typing.Iterator[EvalContext]:
    import typemap.typing as nt

    ctx = _current_context.get()
    ctx_set = False
    if ctx is None:
        ctx = EvalContext()
        _current_context.set(ctx)
        ctx_set = True
    evaluator_token = nt.special_form_evaluator.set(
        lambda t: _eval_types(t, _current_context.get())  # type: ignore[arg-type]
    )

    try:
        yield ctx
    finally:
        if ctx_set:
            _current_context.set(None)
        nt.special_form_evaluator.reset(evaluator_token)


def _get_current_context() -> EvalContext:
    ctx = _current_context.get()
    if not ctx:
        raise RuntimeError(
            "type_eval._get_current_context() called outside of eval_types()"
        )
    return ctx


@contextlib.contextmanager
def _child_context() -> typing.Iterator[EvalContext]:
    ctx = _current_context.get()
    if ctx is None:
        raise RuntimeError(
            "type_eval._create_child_context() called outside of eval_types()"
        )

    try:
        child_ctx = EvalContext(
            resolved={
                # Drop resolved recursive aliases.
                # This is to allow other recursive aliases to expand them out
                # independently. For example, if we have a recursive types
                # A = B|C and B = A|D, we want B to expand even if we already
                # know A.
                k: v
                for k, v in ctx.resolved.items()
                if k not in ctx.known_recursive_types
            },
            seen=ctx.seen.copy(),
            alias_stack=ctx.alias_stack.copy(),
            recursive_type_alias=ctx.recursive_type_alias,
            known_recursive_types=ctx.known_recursive_types.copy(),
            current_generic_alias=ctx.current_generic_alias,
            box_cache=ctx.box_cache,  # Not copied!
        )
        _current_context.set(child_ctx)
        yield child_ctx
    finally:
        _current_context.set(ctx)


def eval_typing(obj: typing.Any):
    with _ensure_context() as ctx:
        result = _eval_types(obj, ctx)
        if not isinstance(result, list) and result in ctx.known_recursive_types:
            result = ctx.known_recursive_types[result]
        return result


def _is_type_alias_type(obj: typing.Any) -> bool:
    return isinstance(obj, typing.TypeAliasType) or (
        isinstance(obj, types.GenericAlias)
        and isinstance(obj.__origin__, typing.TypeAliasType)
    )


def _apply_type(base, args):
    # Some type aliases (like Final) get mad if they get a 1-ary tuple...
    # TODO: Should we special case 0?
    # (Should we fill in Anys???)
    if len(args) == 1:
        return base[args[0]]
    else:
        return base[*args]


def _eval_types(obj: typing.Any, ctx: EvalContext):
    # Found a recursive alias, we need to unwind it
    if obj in ctx.alias_stack:
        if _is_type_alias_type(obj):
            ctx.recursive_type_alias = obj
        return obj

    # Already resolved or seen, return the result
    if obj in ctx.resolved:
        return ctx.resolved[obj]
    if obj in ctx.seen:
        return ctx.seen[obj]

    if _is_type_alias_type(obj):
        with _child_context() as child_ctx:
            child_ctx.alias_stack.add(obj)
            evaled = _eval_types_impl(obj, child_ctx)
    else:
        evaled = _eval_types_impl(obj, ctx)
        child_ctx = None

    # If we have identified a recursive alias, discard evaluation results.
    # This prevents external evaluations from being polluted by partial
    # evaluations.
    keep_intermediate = True
    if child_ctx:
        if child_ctx.recursive_type_alias:
            if child_ctx.recursive_type_alias == obj:
                # Finished unwinding.
                ctx.known_recursive_types[obj] = evaled
                evaled = obj
                keep_intermediate = False

            else:
                ctx.recursive_type_alias = child_ctx.recursive_type_alias

        if keep_intermediate:
            ctx.resolved |= child_ctx.resolved
            ctx.seen |= child_ctx.seen

        # In case a child context evaluated a nested recursive alias, we can
        # keep those results as they are already "consistent".
        ctx.resolved |= {x: x for x in child_ctx.known_recursive_types.keys()}
        ctx.known_recursive_types |= child_ctx.known_recursive_types

    if isinstance(evaled, bool):
        # Wrap a boolean result with _BoolLiteral
        # This is because `not` calls `__bool__` first so a boolean
        # expression like `not _BoolLiteral[True]` will result `False`,
        # not `_BoolLiteral[False]` as we want.
        import typemap.typing as nt

        evaled = nt._BoolLiteral[evaled]

    # Don't cache iterators as they are stateful and can only be consumed once.
    # This is important for Iter results that may be used multiple times.
    if not isinstance(evaled, collections.abc.Iterator):
        ctx.resolved[obj] = evaled
    return evaled


@functools.singledispatch
def _eval_types_impl(obj: typing.Any, ctx: EvalContext):
    return obj


@_eval_types_impl.register
def _eval_func(
    func: types.FunctionType | types.MethodType | staticmethod | classmethod,
    ctx: EvalContext,
):
    root = inspect.unwrap(func)  # type: ignore[arg-type]
    annos = typing.get_type_hints(root)

    annos = {name: _eval_types(tp, ctx) for name, tp in annos.items()}

    return _apply_generic.make_func(func, annos)


@_eval_types_impl.register
def _eval_type_type(obj: type, ctx: EvalContext):
    return obj


@_eval_types_impl.register
def _eval_type_var(obj: typing.TypeVar, ctx: EvalContext):
    return obj


# We don't want to evaluate the body of Literals; there's nothing to
# do there, and doing it puts weird stuff in the caches.
@_eval_types_impl.register
def _eval_literal(obj: typing_LiteralGenericAlias, ctx: EvalContext):
    from typemap.typing import _BoolLiteralGenericAlias

    if isinstance(obj, _BoolLiteralGenericAlias):
        # If this is _BoolLiteralGenericAlias, defer to the registered evaluator
        if func := _eval_funcs.get(obj.__origin__):
            return func(*typing.get_args(obj), ctx=ctx)

    return obj


@_eval_types_impl.register
def _eval_annotated(obj: typing_AnnotatedAlias, ctx: EvalContext):
    # Don't evaluate the args
    return typing.Annotated[
        _eval_types(obj.__origin__, ctx),
        *obj.__metadata__,
    ]


@_eval_types_impl.register
def _eval_type_alias(obj: typing.TypeAliasType, ctx: EvalContext):
    unpacked = _apply_generic.get_annotations(
        obj, args={}, key='evaluate_value'
    )
    return _eval_types(unpacked, ctx)


def _eval_args(args: Sequence[Any], ctx: EvalContext) -> tuple[Any]:
    evaled = []
    for arg in args:
        ev = _eval_types(arg, ctx)
        if isinstance(ev, typing_UnpackGenericAlias):
            if (args := ev.__typing_unpacked_tuple_args__) is not None:
                evaled.extend(args)
            else:
                evaled.append(ev)
        else:
            evaled.append(ev)
    return tuple(evaled)


@_eval_types_impl.register
def _eval_applied_type_alias(obj: types.GenericAlias, ctx: EvalContext):
    """Eval a types.GenericAlias -- typically an applied type alias

    This is typically an application of a type alias... except it can
    also be an application of a built-in type (like list, tuple, dict).

    It can *also* have an Unpack integrated with it, if __unpacked__ is set.
    """

    # If __unpacked__ is set, then we reconstruct a version without
    # __unpacked__ set and evaluate *that*. This centralizes the
    # unpacked handling and simplifies the cache situation.
    if obj.__unpacked__:
        stripped = _apply_type(obj.__origin__, obj.__args__)
        return typing.Unpack[_eval_types(stripped, ctx)]

    new_args = _eval_args(obj.__args__, ctx)

    new_obj = _apply_type(obj.__origin__, new_args)
    if isinstance(obj.__origin__, type):
        # This is a GenericAlias over a Python class, e.g. `dict[str, int]`
        # Let's reconstruct it by evaluating all arguments
        return new_obj

    named_args = dict(
        zip(
            (p.__name__ for p in obj.__origin__.__type_params__),
            obj.__args__,
            strict=False,
        )
    )

    with _child_context() as child_ctx:
        child_ctx.current_generic_alias = new_obj
        if not _is_type_alias_type(new_obj):
            # Type alias types are already added in _eval_types
            child_ctx.alias_stack.add(new_obj)

        unpacked = _apply_generic.get_annotations(
            obj, named_args, key='evaluate_value'
        )

        child_ctx.seen[obj] = unpacked
        evaled = _eval_types(unpacked, child_ctx)

    ctx.seen[obj] = unpacked
    ctx.recursive_type_alias = child_ctx.recursive_type_alias

    return evaled


@_eval_types_impl.register
def _eval_nested_generic_alias(
    obj: _AssociatedTypeGenericAlias, ctx: EvalContext
):
    base, alias = obj.__args__

    # TODO: what if it has parameters of its own

    named_args = dict(
        zip(
            (p.__name__ for p in base.__origin__.__type_params__),
            base.__args__,
            strict=False,
        )
    )

    unpacked = _apply_generic.get_annotations(
        alias, named_args, key='evaluate_value'
    )

    return _eval_types(unpacked, ctx)


@_eval_types_impl.register
def _eval_applied_class(obj: typing_GenericAlias, ctx: EvalContext):
    """Eval a typing._GenericAlias -- an applied user-defined class"""
    # generic *classes* are typing._GenericAlias while generic type
    # aliases are types.GenericAlias? Why in the world.
    if obj.__origin__ in _lazy_eval_funcs:
        return _eval_funcs[obj.__origin__](*typing.get_args(obj), ctx=ctx)

    new_args = _eval_args(typing.get_args(obj), ctx)

    if func := _eval_funcs.get(obj.__origin__):
        _tvars = (
            typing.TypeVar,
            typing.ParamSpec,
            typing.TypeVarTuple,
        )
        if any(isinstance(a, _tvars) for a in new_args):
            raise StuckException(obj)
        ret = func(*new_args, ctx=ctx)
        # return _eval_types(ret, ctx)  # ???
        return ret
    else:
        return _apply_type(obj.__origin__, new_args)


@_eval_types_impl.register
def _eval_callable(obj: typing_CallableGenericAlias, ctx: EvalContext):
    """Eval a typing._CallableGenericAlias"""

    def _eval_ty_or_list(obj):
        if isinstance(obj, list):
            return [_eval_types(t, ctx) for t in obj]
        else:
            return _eval_types(obj, ctx)

    new_args = tuple(_eval_ty_or_list(arg) for arg in typing.get_args(obj))
    # origin for Callable is collections.abc.Callable which kind of annoying
    return _apply_type(typing.Callable, new_args)


@_eval_types_impl.register
def _eval_union(obj: typing.Union, ctx: EvalContext):
    return typing.Union[_eval_args(obj.__args__, ctx)]
