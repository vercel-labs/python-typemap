import collections
import collections.abc
import contextlib
import dataclasses
import enum
import functools
import inspect
import itertools
import re
import types
import typing

from typing_extensions import _AnnotatedAlias as typing_AnnotatedAlias

from typemap import type_eval
from typemap.type_eval import _apply_generic, _typing_inspect
from typemap.type_eval._eval_typing import (
    _child_context,
    _eval_args,
    _eval_types,
    EvalContext,
)
from typemap.typing import (
    Attrs,
    Bool,
    Capitalize,
    DropAnnotations,
    FromUnion,
    GenericCallable,
    GetAnnotations,
    GetArg,
    GetArgs,
    GetMember,
    GetMemberType,
    GetSpecialAttr,
    InitField,
    IsAssignable,
    IsEquivalent,
    Iter,
    Length,
    Lowercase,
    Member,
    Members,
    NewProtocol,
    NewTypedDict,
    Overloaded,
    Param,
    Params,
    RaiseError,
    Slice,
    SpecialFormEllipsis,
    Concat,
    Uncapitalize,
    UpdateClass,
    Uppercase,
    _BoolLiteral,
)

##################################################################


def _from_literal(val):
    if _typing_inspect.is_literal(val):
        # TODO: check length?
        return val.__args__[0]
    elif val is type(None):
        return None
    raise AssertionError(f'expected a literal type, got {val!r}')


def _eval_literal(val, ctx):
    return _from_literal(_eval_types(val, ctx))


def _make_init_type(v):
    # Usually it's just a literal, but sometimes we need to handle
    # InitField.
    if isinstance(v, InitField):
        return type(v)[
            typing.TypedDict(
                type(v).__name__,
                {k: _make_init_type(sv) for k, sv in v.get_kwargs().items()},
            )
        ]
    else:
        # Wrap in tuple when creating Literal in case it *is* a tuple
        return typing.Literal[(v,)]


def cached_box(cls, *, ctx: EvalContext):
    if str(cls).startswith('typemap.typing'):
        return _apply_generic.box(cls)
    if cls in ctx.box_cache:
        return ctx.box_cache[cls]
    ctx.box_cache[cls] = box = _apply_generic.box(cls)
    assert box.mro
    # if not all(b.mro for b in box.mro):
    #     breakpoint()
    # assert all(b.mro for b in box.mro)

    if new_box := _eval_init_subclass(box, ctx):
        ctx.box_cache[cls] = box = new_box
    return box


def get_annotated_type_hints(cls, *, ctx, attrs_only=False, **kwargs):
    """Get the type hints/quals for a cls annotated with definition site.

    This traverses the mro and finds the definition site for each annotation.
    """

    box = cached_box(cls, ctx=ctx)

    # For TypedDicts with total=False, use __optional_keys__ to
    # identify which fields are NotRequired. TypedDict's metaclass
    # flattens parent annotations into subclasses, so we can't
    # reliably check __total__ per-class in our own MRO walk.
    td_optional_keys = getattr(cls, "__optional_keys__", frozenset())

    hints = {}
    for abox in reversed(box.mro):
        acls = abox.alias_type()

        annos, _ = _apply_generic.get_local_defns(abox)
        for k, ty in annos.items():
            quals = set()

            # Strip ClassVar/Final/NotRequired/ReadOnly/Required from ty
            # and add them to quals
            had_required_marker = False
            while True:
                for form in [
                    typing.ClassVar,
                    typing.Final,
                    typing.NotRequired,
                    typing.ReadOnly,
                    typing.Required,
                ]:
                    if _typing_inspect.is_special_form(ty, form):
                        if form in (
                            typing.Required,
                            typing.NotRequired,
                        ):
                            had_required_marker = True
                        # Required is the default; strip but don't add a qual
                        if form is not typing.Required:
                            quals.add(form.__name__)
                        ty = (
                            typing.get_args(ty)[0]
                            if typing.get_args(ty)
                            else typing.Any
                        )
                        break
                else:
                    break

            # For TypedDict fields without explicit Required/NotRequired,
            # check if they're optional (from total=False)
            if not had_required_marker and k in td_optional_keys:
                quals.add("NotRequired")

            # Skip method-like ClassVars when only attributes are wanted
            if attrs_only and "ClassVar" in quals and _is_method_like(ty):
                continue

            if k in abox.cls.__dict__:
                # Wrap in tuple when creating Literal in case it *is* a tuple
                init = _make_init_type(abox.cls.__dict__[k])
            else:
                init = typing.Never

            hints[k] = ty, tuple(sorted(quals)), init, acls

    # A type of Never in UpdateClass removes the member
    return {k: v for k, v in hints.items() if v[0] is not typing.Never}


def get_annotated_method_hints(cls, *, ctx):
    box = cached_box(cls, ctx=ctx)

    hints = {}
    for abox in reversed(box.mro):
        acls = abox.alias_type()

        _, dct = _apply_generic.get_local_defns(abox)
        for name, attr in dct.items():
            if isinstance(
                attr,
                (
                    types.FunctionType,
                    types.MethodType,
                    staticmethod,
                    classmethod,
                ),
            ):
                if attr is typing._no_init_or_replace_init:
                    continue

                hints[name] = (
                    _function_type(attr, receiver_type=acls),
                    ("ClassVar",),
                    object,
                    acls,
                )
            elif isinstance(attr, _apply_generic.WrappedOverloads):
                overloads = [
                    _function_type(_eval_types(of, ctx), receiver_type=acls)
                    for of in attr.functions
                ]
                hints[name] = (
                    Overloaded[*overloads],
                    ("ClassVar",),
                    object,
                    acls,
                )

    return hints


def _eval_init_subclass(
    box: _apply_generic.Boxed, ctx: EvalContext
) -> _apply_generic.Boxed:
    """Get type after all __init_subclass__ with UpdateClass are evaluated."""
    for abox in box.mro[1:]:  # Skip the type itself
        with _child_context() as ctx:
            ms = _get_update_class_members(box, abox, ctx=ctx)
            if ms is not None:
                nbox = _apply_generic.box(
                    _create_updated_class(box, ms, ctx=ctx)
                )
                # We want to preserve the original cls for Members output
                box = dataclasses.replace(
                    nbox, orig_cls=box.canonical_cls, args=box.args
                )
                ctx.box_cache[box.alias_type()] = box
    return box


def _get_update_class_members(
    box: _apply_generic.Boxed,
    boxed_base: _apply_generic.Boxed,
    ctx: EvalContext,
) -> typing.Sequence[Member] | None:
    cls = box.cls

    # Get __init_subclass__ from the base class's origin if base is generic.
    base_origin = boxed_base.cls
    init_subclass = base_origin.__dict__.get("__init_subclass__")
    if not init_subclass:
        return None
    init_subclass = inspect.unwrap(init_subclass)

    args = {}
    # Get any type params from the base class if it is generic
    if (base_args := boxed_base.args.values()) and (
        origin_params := getattr(base_origin, '__type_params__', None)
    ):
        args = dict(
            zip((p.__name__ for p in origin_params), base_args, strict=True)
        )

    # Get type params from function
    if type_params := getattr(init_subclass, '__type_params__', None):
        args[type_params[0].__name__] = box.alias_type()

    init_subclass_annos = _apply_generic.get_annotations(init_subclass, args)

    if init_subclass_annos and (
        ret_annotation := init_subclass_annos.get("return")
    ):
        # Substitute the cls type var with the current class
        # This may not happen if cls is not generic!
        if (
            (
                cls_anno := next(
                    (
                        v
                        for k, v in init_subclass_annos.items()
                        if k != "return"
                    ),
                    None,
                )
            )
            and typing.get_origin(cls_anno) is type
            and (cls_type_args := typing.get_args(cls_anno))
            and (cls_type := cls_type_args[0])
            and isinstance(cls_type, typing.TypeVar)
        ):
            substitution = {cls_type: cls}
            ret_annotation = _apply_generic.substitute(
                ret_annotation, substitution
            )

        # Evaluate the return annotation
        evaled_ret = _eval_types(ret_annotation, ctx=ctx)

        # If the result is an UpdateClass, return the members
        if (
            _typing_inspect.is_generic_alias(evaled_ret)
            and typing.get_origin(evaled_ret) is UpdateClass
        ):
            return _eval_args(typing.get_args(evaled_ret), ctx)

    return None


def _create_updated_class(
    box: _apply_generic.Boxed, ms: typing.Sequence[Member], ctx: EvalContext
) -> type:
    t = box.cls
    dct: dict[str, object] = {}

    # Copy the module
    dct["__module__"] = t.__module__

    # Process UpdateClass members first to establish their ordering,
    # then append non-overridden existing members.
    dct["__annotations__"] = annos = {}
    update_names: set[str] = set()

    for m in ms:
        tname, typ, quals, init, _ = typing.get_args(m)
        member_name = _eval_literal(tname, ctx)
        typ = _eval_types(typ, ctx)
        tquals = _eval_types(quals, ctx)

        update_names.add(member_name)
        if (
            type_eval.issubtype(typing.Literal["ClassVar"], tquals)
            and _is_method_like(typ)
            and _typing_inspect.get_head(typ) is not GenericCallable
        ):
            dct[member_name] = _callable_type_to_method(member_name, typ, ctx)
        else:
            # Update/add the annotation
            annos[member_name] = _add_quals(typ, tquals)
            _unpack_init(dct, member_name, init)

    # Append non-overridden existing annotations (preserving their order)
    for name, typ in getattr(t, '__annotations__', {}).items():
        if name not in update_names:
            annos[name] = typ

    # Append non-overridden existing methods and annotation defaults
    existing_annos = getattr(t, '__annotations__', {})
    for name, value in t.__dict__.items():
        if name in update_names or name in _apply_generic.EXCLUDED_ATTRIBUTES:
            continue
        if isinstance(inspect.unwrap(value), types.FunctionType):
            dct[name] = value
        elif name in existing_annos:
            dct[name] = value

    # Create the updated class

    # If typing.Generic is a base, we need to use it with the type params
    # applied. Additionally, use types.newclass to properly resolve the mro.
    bases = tuple(
        b.alias_type()
        if b.cls is not typing.Generic
        else typing.Generic[t.__type_params__]
        for b in box.bases
    )

    kwds = {}
    mcls = type(t)
    if mcls is not type:
        kwds["metaclass"] = mcls

    cls = types.new_class(t.__name__, bases, kwds, lambda ns: ns.update(dct))
    # Explicitly set __type_params__. This normally doesn't work, but we are
    # creating fake classes for the purpose of type evaluation.
    cls.__type_params__ = t.__type_params__

    return cls


def _union_elems(tp, ctx):
    tp = _eval_types(tp, ctx)
    if tp is typing.Never:
        return ()
    elif isinstance(tp, types.UnionType):
        return tuple(y for x in tp.__args__ for y in _union_elems(x, ctx))
    elif _typing_inspect.is_literal(tp) and len(tp.__args__) > 1:
        return tuple(typing.Literal[x] for x in tp.__args__)
    else:
        return (tp,)


# TODO: Need to be able to do this in type system!
def _mk_union(*parts):
    if not parts:
        return typing.Never
    else:
        return typing.Union[*parts]


def _mk_literal_union(*parts):
    if not parts:
        return typing.Never
    else:
        return typing.Literal[*parts]


def _unwrap_anno(tp):
    if isinstance(tp, typing_AnnotatedAlias):
        return tp.__origin__
    else:
        return tp


def _lift_evaluated(func):
    @functools.wraps(func)
    def wrapper(*args, ctx):
        return func(
            *[_unwrap_anno(_eval_types(arg, ctx)) for arg in args], ctx=ctx
        )

    return wrapper


def _lift_over_unions(func):
    @functools.wraps(func)
    def wrapper(*args, ctx):
        args2 = [_union_elems(x, ctx) for x in args]
        parts = [
            func(*[_unwrap_anno(x) for x in xs], ctx=ctx)
            for xs in itertools.product(*args2)
        ]
        return _mk_union(*parts)

    return wrapper


##################################################################


@type_eval.register_evaluator(Iter)
@_lift_evaluated
def _eval_Iter(tp, *, ctx):
    tp = _eval_types(tp, ctx)
    if (
        _typing_inspect.is_generic_alias(tp)
        and tp.__origin__ is tuple
        and (not tp.__args__ or tp.__args__[-1] is not Ellipsis)
    ):
        return iter(tp.__args__)
    else:
        # XXX: Or should we return []?
        # We *definitely* should return [] for Never
        # Maybe we should lift over unions and return the union of
        # each tuples position...
        raise TypeError(
            f"Invalid type argument to Iter: {tp} is not a fixed-length tuple"
        )


# N.B: These handle unions on their own


@type_eval.register_evaluator(IsAssignable)
@_lift_evaluated
def _eval_IsAssignable(lhs, rhs, *, ctx):
    return _BoolLiteral[type_eval.issubtype(lhs, rhs)]


@type_eval.register_evaluator(IsEquivalent)
@_lift_evaluated
def _eval_IsEquivalent(lhs, rhs, *, ctx):
    return _BoolLiteral[
        type_eval.issubtype(lhs, rhs) and type_eval.issubtype(rhs, lhs)
    ]


def _eval_bool_tp(tp, ctx):
    if _typing_inspect.is_generic_alias(tp) and tp.__origin__ is _BoolLiteral:
        return _BoolLiteral[bool(tp.__args__[0])]
    else:
        return _BoolLiteral[
            any(
                type_eval.issubtype(arg, typing.Literal[True])
                and not type_eval.issubtype(arg, typing.Never)
                for arg in _union_elems(tp, ctx)
            )
        ]


@type_eval.register_evaluator(Bool)
@_lift_evaluated
def _eval_Bool(tp, *, ctx):
    return _eval_bool_tp(tp, ctx)


##################################################################


def _get_kind(kind_type) -> str | None:
    # Extract the single kind from a Literal of one ParamKind value.
    # Multiple kinds, or Never, are an error.
    if kind_type is typing.Never:
        raise TypeError(
            "Param kind cannot be Never; "
            "use Literal['positional_or_keyword'] for the default"
        )
    if not _typing_inspect.is_literal(kind_type):
        return None
    kind_args = typing.get_args(kind_type)
    if len(kind_args) > 1:
        raise TypeError(
            f"Param kind must have at most one value, got {kind_type}"
        )
    return kind_args[0] if kind_args else None


class _DummyDefault:
    # A dummy class to assign to defaults that will display as '...'
    # Putting actual `...` displays as 'Ellipsis'.
    def __repr__(self):
        return "..."


_DUMMY_DEFAULT = _DummyDefault()


def _unwrap_params(param_types) -> list:
    """Unwrap params into a list of Param types.

    Accepts Params[...] (extended format), Ellipsis (any params),
    or a list/tuple of plain types (standard format, converted to
    positional-only Params).
    """
    if typing.get_origin(param_types) is Params:
        return list(typing.get_args(param_types))

    if param_types is ...:
        return [
            Param[typing.Literal[None], typing.Any, typing.Literal["*"]],
            Param[typing.Literal[None], typing.Any, typing.Literal["**"]],
        ]

    if isinstance(param_types, (list, tuple)):
        items = list(param_types)
    else:
        raise TypeError(
            f"Expected Params[...] or list of types, got {param_types}"
        )
    # Error if someone passes Param types without Params wrapper
    for t in items:
        if typing.get_origin(t) is Param:
            raise TypeError(
                f"Param types must be wrapped in Params[...], got [{t}, ...]"
            )
    # Convert standard types to positional-only Params
    return [
        Param[typing.Literal[None], t]  # type: ignore[valid-type]
        for t in items
    ]


def _callable_type_to_signature(callable_type: object) -> inspect.Signature:
    """Convert a Callable[Params[...], ret] type to an inspect.Signature."""
    args = typing.get_args(callable_type)
    if len(args) != 2:
        raise TypeError(
            f"Expected Callable[Params[...], ret], got {callable_type}"
        )

    raw_params, return_type = args
    param_types = _unwrap_params(raw_params)

    parameters: list[inspect.Parameter] = []
    saw_keyword_only = False

    for param_type in param_types:
        # Extract Param arguments: Param[name, type, kind]
        origin = typing.get_origin(param_type)
        if origin is not Param:
            raise TypeError(f"Expected Param type, got {param_type}")

        param_args = typing.get_args(param_type)
        if len(param_args) < 2:
            raise TypeError(
                f"Param must have at least name and type, got {param_type}"
            )

        name_type = param_args[0]
        annotation = param_args[1]
        kind_type = (
            param_args[2]
            if len(param_args) > 2
            else typing.Literal["positional_or_keyword"]
        )

        # Extract name from Literal[name] or None
        name = _from_literal(name_type)

        param_kind = _get_kind(kind_type)

        # Determine parameter kind and default
        kind: inspect._ParameterKind
        if param_kind == "**":
            kind = inspect.Parameter.VAR_KEYWORD
            name = name or "kwargs"
        elif param_kind == "*":
            kind = inspect.Parameter.VAR_POSITIONAL
            name = name or "args"
            # XXX: not sure we need this
            saw_keyword_only = True
        elif param_kind == "keyword":
            kind = inspect.Parameter.KEYWORD_ONLY
            saw_keyword_only = True
        elif param_kind == "positional" or name is None:
            kind = inspect.Parameter.POSITIONAL_ONLY
        elif param_kind == "positional_or_keyword":
            kind = inspect.Parameter.POSITIONAL_OR_KEYWORD
        elif saw_keyword_only:
            kind = inspect.Parameter.KEYWORD_ONLY
        else:
            kind = inspect.Parameter.POSITIONAL_OR_KEYWORD

        # Handle default value from the 4th Param arg (D)
        default_type = param_args[3] if len(param_args) > 3 else typing.Never
        default: typing.Any
        if default_type is typing.Never:
            default = inspect.Parameter.empty
        elif (
            _typing_inspect.is_literal(default_type)
            and len(default_type.__args__) == 1
        ):
            default = default_type.__args__[0]
        else:
            default = _DUMMY_DEFAULT

        # Generate a name for positional-only params if needed
        if name is None:
            name = f"_arg{len(parameters)}"

        parameters.append(
            inspect.Parameter(
                name=name,
                kind=kind,
                default=default,
                annotation=annotation,
            )
        )

    # HACK: Makes output look nicer, but I'm not 100% where it is
    # sneaking in...
    if return_type is type(None):
        return_type = None

    return inspect.Signature(
        parameters=parameters,
        return_annotation=return_type,
    )


def _signature_to_function(name: str, sig: inspect.Signature):
    """
    Creates a new function with a specific inspect.Signature.
    """

    def fn(*args, **kwargs):
        raise NotImplementedError

    fn.__name__ = fn.__qualname__ = name
    fn.__signature__ = sig  # type: ignore[attr-defined]
    fn.__annotations__ = {
        p.name: p.annotation
        for p in sig.parameters.values()
        if p.annotation is not inspect.Parameter.empty
    }

    return fn


def _is_pos_only(param):
    args = typing.get_args(param)
    name, _, kind_type = args[0], args[1], args[2]
    kind = _get_kind(kind_type)
    return kind == "positional" or (name is None and kind not in ("*", "**"))


def _callable_type_to_method(name, typ, ctx):
    """Turn a callable type into a method.

    I'm not totally sure if this is worth doing! The main accomplishment
    is in how it pretty prints...
    """

    type_params = ()

    head = typing.get_origin(typ)
    if head is GenericCallable:
        # Call the lambda with type variables to substitute the type variables
        ttparams, ttfunc = typing.get_args(typ)
        type_params = typing.get_args(ttparams)
        typ = ttfunc(*type_params)
        head = typing.get_origin(typ)

    if head is classmethod:
        # XXX: handle other amounts
        cls, raw_params, ret = typing.get_args(typ)
        param_list = _unwrap_params(raw_params)
        # We have to make class positional only if there is some other
        # positional only argument. Annoying!
        has_pos_only = any(_is_pos_only(p) for p in param_list)
        kind = (
            typing.Literal["positional"]
            if has_pos_only
            else typing.Literal["positional_or_keyword"]
        )
        # Override the receiver type with type[Self].
        if name == "__init_subclass__" and isinstance(cls, typing.TypeVar):
            # For __init_subclass__ generic on cls: T, keep type[T]
            cls_typ = type[cls]
        else:
            cls_typ = type[typing.Self]
        cls_param = Param[typing.Literal["cls"], cls_typ, kind]
        typ = typing.Callable[Params[cls_param, *param_list], ret]
    elif head is staticmethod:
        raw_params, ret = typing.get_args(typ)
        param_list = _unwrap_params(raw_params)
        typ = typing.Callable[Params[*param_list], ret]
    else:
        raw_params, ret = typing.get_args(typ)
        param_list = _unwrap_params(raw_params)
        # Override the annotations for methods
        # - use Self for the "self" param, otherwise the fully qualified cls
        #   name gets used. This ends up being long and annoying to handle.
        #   GetDefiner can always be used to get the actual type.
        # - __init__ should return None regardless of what the user says.
        #   The default return type for methods is Any, so this also handles
        #   the un-annotated case.
        param_list = [
            (
                p
                if typing.get_args(p)[0] != typing.Literal["self"]
                else Param[
                    typing.Literal["self"],
                    typing.Self,
                    typing.get_args(p)[2],
                ]
            )
            for p in param_list
        ]
        ret = type(None) if name == "__init__" else ret
        typ = typing.Callable[Params[*param_list], ret]
        head = lambda x: x

    func = _signature_to_function(name, _callable_type_to_signature(typ))
    func.__type_params__ = type_params
    return head(func)


def _function_type_from_sig(sig, func, *, receiver_type):
    empty = inspect.Parameter.empty

    def _ann(x):
        return typing.Any if x is empty else None if x is type(None) else x

    specified_receiver = receiver_type

    params = []
    for i, p in enumerate(sig.parameters.values()):
        ann = p.annotation
        # Special handling for first argument on methods.
        if i == 0 and receiver_type and not isinstance(func, staticmethod):
            if ann is empty:
                ann = receiver_type
            else:
                if (
                    isinstance(func, classmethod)
                    and typing.get_origin(ann) is type
                    and (receiver_args := typing.get_args(ann))
                ):
                    # The annotation for cls in a classmethod should be type[C]
                    specified_receiver = receiver_args[0]
                else:
                    specified_receiver = ann

        kinds = []
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            kinds.append("*")
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            kinds.append("**")
        if p.kind == inspect.Parameter.KEYWORD_ONLY:
            kinds.append("keyword")
        if p.kind == inspect.Parameter.POSITIONAL_ONLY:
            kinds.append("positional")
        if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
            kinds.append("positional_or_keyword")
        ann_type = _ann(ann)
        has_default = p.default is not empty
        if has_default:
            v = p.default
            if v is None or isinstance(v, (int, str, bytes, bool, enum.Enum)):
                default_type = typing.Literal[(v,)]
            else:
                default_type = ann_type
        else:
            default_type = typing.Never
        params.append(
            Param[
                typing.Literal[p.name],
                ann_type,
                typing.Literal[*kinds] if kinds else typing.Never,
                default_type,
            ]
        )

    ret = _ann(sig.return_annotation)

    f: typing.Any  # type: ignore[annotation-unchecked]
    if isinstance(func, staticmethod):
        f = staticmethod[Params[*params], ret]
    elif isinstance(func, classmethod):
        f = classmethod[specified_receiver, Params[*params[1:]], ret]
    else:
        f = typing.Callable[Params[*params], ret]

    return f


def _function_type(func, *, receiver_type):
    root = inspect.unwrap(func)
    sig = inspect.signature(root)
    f = _function_type_from_sig(sig, func, receiver_type=receiver_type)

    if root.__type_params__:
        # Must store a lambda that performs type variable substitution
        type_params = root.__type_params__
        callable_lambda = _create_generic_callable_lambda(f, type_params)
        f = GenericCallable[tuple[*type_params], callable_lambda]
    return f


def _create_generic_callable_lambda(
    f: typing.Callable | classmethod | staticmethod,
    type_params: tuple[typing.TypeVar, ...],
):
    if typing.get_origin(f) in (staticmethod, classmethod):
        return lambda *vs: _apply_generic.substitute(
            f, dict(zip(type_params, vs, strict=True))
        )

    else:
        # Callable params are stored as Params[...]
        params, ret = typing.get_args(f)

        return lambda *vs: typing.Callable[
            _apply_generic.substitute(
                params,
                dict(zip(type_params, vs, strict=True)),
            ),
            _apply_generic.substitute(
                ret, dict(zip(type_params, vs, strict=True))
            ),
        ]


def _hint_to_member(n, t, qs, init, d, *, ctx):
    return Member[
        typing.Literal[n],
        _eval_types(t, ctx),
        _mk_literal_union(*qs),
        init,
        d,
    ]


def _hints_to_members(hints, ctx):
    """Convert a hints dictionary to a tuple of Member types."""
    return tuple[
        *[_hint_to_member(n, *hint, ctx=ctx) for n, hint in hints.items()]
    ]


@type_eval.register_evaluator(Attrs)
@_lift_over_unions
def _eval_Attrs(tp, *, ctx):
    hints = get_annotated_type_hints(
        tp, include_extras=True, attrs_only=True, ctx=ctx
    )
    return _hints_to_members(hints, ctx)


@type_eval.register_evaluator(Members)
@_lift_over_unions
def _eval_Members(tp, *, ctx):
    hints = {
        **get_annotated_type_hints(tp, include_extras=True, ctx=ctx),
        **get_annotated_method_hints(tp, ctx=ctx),
    }
    return _hints_to_members(hints, ctx)


@type_eval.register_evaluator(GetMember)
@_lift_over_unions
def _eval_GetMember(tp, prop, *, ctx):
    # XXX: extras?
    name = _from_literal(prop)
    hints = {
        **get_annotated_type_hints(tp, include_extras=True, ctx=ctx),
        **get_annotated_method_hints(tp, ctx=ctx),
    }
    if name in hints:
        return _hint_to_member(name, *hints[name], ctx=ctx)
    else:
        raise TypeMapError(f"GetMember: {name!r} not found in {tp!r}")


##################################################################


@type_eval.register_evaluator(FromUnion)
@_lift_evaluated
def _eval_FromUnion(tp, *, ctx):
    if tp in ctx.known_recursive_types:
        return tuple[*_union_elems(ctx.known_recursive_types[tp], ctx)]
    else:
        return tuple[*_union_elems(tp, ctx)]


##################################################################


@type_eval.register_evaluator(GetMemberType)
@_lift_over_unions
def _eval_GetMemberType(tp, prop, *, ctx):
    # XXX: extras?
    name = _from_literal(prop)
    hints = {
        **get_annotated_type_hints(tp, include_extras=True, ctx=ctx),
        **get_annotated_method_hints(tp, ctx=ctx),
    }
    if name in hints:
        return hints[name][0]
    else:
        return typing.Never


def _fix_callable_args(base, args):
    idx = FUNC_LIKES[base]
    if idx >= len(args):
        return args
    args = list(args)
    args[idx] = Params[*_unwrap_params(args[idx])]
    return tuple(args)


def _get_raw_args(tp, base_head, ctx) -> typing.Any:
    evaled = _eval_types(tp, ctx)

    tp_head = _typing_inspect.get_head(tp)
    if not tp_head or not base_head:
        return None

    if tp_head is base_head:
        args = typing.get_args(evaled)
        if _is_method_like(tp) and base_head is not GenericCallable:
            args = _fix_callable_args(base_head, args)

        return args

    # Scan the fully-annotated MRO to find the base
    box = _apply_generic.box(tp)
    for anc in box.mro:
        if anc.cls is base_head:
            return tuple(anc.args.values())

    # or error??
    return None


def _get_args(tp, base, ctx) -> typing.Any:
    base_head = _typing_inspect.get_head(base)
    args = _get_raw_args(tp, base, ctx)
    if args == ():
        args = _get_defaults(base_head)
    return args


def _fix_type(tp):
    """Fix up a type getting returned from GetArg

    In particular, this means turning a list into Params (for
    Callable parameter lists) or a tuple, and turning ... into
    SpecialFormEllipsis.

    """
    if isinstance(tp, list):
        return Params[*tp]
    elif isinstance(tp, tuple):
        return tuple[*tp]
    elif tp is ...:
        return SpecialFormEllipsis
    else:
        return tp


# The number of generic parameters to all the builtin types that had
# subscripting added in PEP 585.
_BUILTIN_GENERIC_ARITIES = {
    tuple: 2,  # variadic, like Callable...
    collections.abc.Callable: 2,  # special syntax
    # TODO: Need special handling for the ParamSpec?
    staticmethod: 2,
    classmethod: 3,
    # Normal and boring stuff
    list: 1,
    dict: 2,
    set: 1,
    frozenset: 1,
    type: 1,
    collections.deque: 1,
    collections.defaultdict: 2,
    collections.OrderedDict: 2,
    collections.Counter: 1,
    collections.ChainMap: 2,
    collections.abc.Awaitable: 1,
    collections.abc.Coroutine: 3,
    collections.abc.AsyncIterable: 1,
    collections.abc.AsyncIterator: 1,
    collections.abc.AsyncGenerator: 2,
    collections.abc.Iterable: 1,
    collections.abc.Iterator: 1,
    collections.abc.Generator: 3,
    collections.abc.Reversible: 1,
    collections.abc.Container: 1,
    collections.abc.Collection: 1,
    collections.abc.Set: 1,
    collections.abc.MutableSet: 1,
    collections.abc.Mapping: 2,
    collections.abc.MutableMapping: 2,
    collections.abc.Sequence: 1,
    collections.abc.MutableSequence: 1,
    collections.abc.KeysView: 1,
    collections.abc.ItemsView: 2,
    collections.abc.ValuesView: 1,
    contextlib.AbstractContextManager: 1,
    contextlib.AbstractAsyncContextManager: 1,
    re.Pattern: 1,
    re.Match: 1,
}


def _get_params(base_head):
    if (params := getattr(base_head, "__parameters__", None)) is not None:
        return params
    elif (params := getattr(base_head, "__type_params__", None)) is not None:
        return params
    else:
        return None


def _get_generic_arity(base_head):
    if (n := _BUILTIN_GENERIC_ARITIES.get(base_head)) is not None:
        return n
    # XXX: check the type?
    elif (n := getattr(base_head, "_nparams", None)) is not None:
        return n
    elif (params := _get_params(base_head)) is not None:
        # TODO: also check for TypeVarTuple!
        return len(params)
    else:
        return -1


def _get_defaults(base_head):
    """Get the *default* type params for a type

    `list` is equivalent to `list[Any]`, so `GetArg[list, list, 0]
    ought to return `Any`, while `GetArg[list, list, 1]` ought to
    return `Never` because the index is invalid.

    Annoyingly we need to consult a table for built-in arities for this.
    """
    arity = _get_generic_arity(base_head)
    if arity < 0:
        return None

    # Callable and tuple need to produce a SpecialFormEllipsis for arg
    # 0 and 1, respectively.
    if base_head is collections.abc.Callable:
        return (
            Params[
                Param[typing.Literal[None], typing.Any, typing.Literal["*"]],
                Param[typing.Literal[None], typing.Any, typing.Literal["**"]],
            ],
            typing.Any,
        )
    elif base_head is tuple:
        return (typing.Any, SpecialFormEllipsis)

    if params := _get_params(base_head):
        return tuple(_typing_inspect.param_default(p) for p in params)

    return (typing.Any,) * arity


@type_eval.register_evaluator(GetArg)
@_lift_over_unions
def _eval_GetArg(tp, base, idx, *, ctx) -> typing.Any:
    base_head = _typing_inspect.get_head(base)
    args = _get_args(tp, base_head, ctx)
    if args is None:
        raise TypeMapError(f"GetArg: {tp!r} is not a subclass of {base!r}")

    try:
        idx_val = _eval_literal(idx, ctx)

        if base_head is GenericCallable and idx_val >= 1:
            # Disallow access to callable lambda
            raise TypeMapError(
                f"GetArg: cannot access index {idx_val} of GenericCallable"
            )

        return _fix_type(args[idx_val])
    except IndexError:
        raise TypeMapError(f"GetArg: index out of range for {tp!r} as {base!r}")


@type_eval.register_evaluator(GetArgs)
@_lift_over_unions
def _eval_GetArgs(tp, base, *, ctx) -> typing.Any:
    base_head = _typing_inspect.get_head(base)
    args = _get_args(tp, base_head, ctx)
    if args is None:
        raise TypeMapError(f"GetArgs: {tp!r} is not a subclass of {base!r}")

    if base_head is GenericCallable:
        # Disallow access to callable lambda
        return tuple[args[0]]  # type: ignore[valid-type]

    return tuple[*args]  # type: ignore[valid-type]


@type_eval.register_evaluator(GetSpecialAttr)
@_lift_over_unions
def _eval_GetSpecialAttr(tp, attr, *, ctx) -> typing.Any:
    if not (
        _typing_inspect.is_generic_alias(attr)
        and attr.__origin__ is typing.Literal
        and isinstance(attr.__args__[0], str)
    ):
        raise TypeError(
            f"Invalid type argument to GetSpecialAttr: "
            f"{attr} is not a string Literal"
        )
    if attr.__args__[0] == "__name__":
        return typing.Literal[tp.__name__]
    elif attr.__args__[0] == "__module__":
        return typing.Literal[tp.__module__]
    elif attr.__args__[0] == "__qualname__":
        return typing.Literal[tp.__qualname__]
    else:
        raise TypeMapError(
            f"GetSpecialAttr: {attr.__args__[0]!r} is not a valid attribute"
        )


@type_eval.register_evaluator(GetAnnotations)
def _eval_GetAnnotations(tp, *, ctx) -> typing.Any:
    tp = _eval_types(tp, ctx=ctx)
    # XXX: Should *this* lift over unions??
    if isinstance(tp, typing_AnnotatedAlias):
        return typing.Literal[*tp.__metadata__]
    else:
        return typing.Never


@type_eval.register_evaluator(DropAnnotations)
def _eval_DropAnnotations(tp, *, ctx) -> typing.Any:
    tp = _eval_types(tp, ctx=ctx)
    # XXX: Should *this* lift over unions??
    if isinstance(tp, typing_AnnotatedAlias):
        return tp.__origin__
    else:
        return tp


@type_eval.register_evaluator(Length)
@_lift_over_unions
def _eval_Length(tp, *, ctx) -> typing.Any:
    tp = _eval_types(tp, ctx)
    if _typing_inspect.is_generic_alias(tp) and tp.__origin__ is tuple:
        # TODO: Unpack in the middle?
        if not tp.__args__ or tp.__args__[-1] is not Ellipsis:
            return typing.Literal[len(tp.__args__)]
        else:
            return typing.Literal[None]
    else:
        # XXX: Or should we return Never?
        raise TypeError(f"Invalid type argument to Length: {tp} is not a tuple")


@type_eval.register_evaluator(Slice)
@_lift_over_unions
def _eval_Slice(tp, start, end, *, ctx):
    tp = _eval_types(tp, ctx)
    start = _eval_literal(start, ctx)
    end = _eval_literal(end, ctx)
    if _typing_inspect.is_generic_alias(tp) and tp.__origin__ is tuple:
        return tp.__origin__[tp.__args__[start:end]]
    elif (
        _typing_inspect.is_generic_alias(tp)
        and tp.__origin__ is typing.Literal
        and isinstance(tp.__args__[0], str)
    ):
        return tp.__origin__[tp.__args__[0][start:end]]
    else:
        raise TypeMapError(f"Slice: {tp!r} is not a tuple or string Literal")


# String literals


def _string_literal_op(typ, op):
    @_lift_over_unions
    def func(*args, ctx):
        return typing.Literal[op(*[_eval_literal(x, ctx) for x in args])]

    type_eval.register_evaluator(typ)(func)


_string_literal_op(Uppercase, op=str.upper)
_string_literal_op(Lowercase, op=str.lower)
_string_literal_op(Capitalize, op=str.capitalize)
_string_literal_op(Uncapitalize, op=lambda s: s[0:1].lower() + s[1:])
_string_literal_op(Concat, op=lambda s, t: s + t)


##################################################################


class TypeMapError(TypeError):
    """Exception raised when RaiseError is evaluated."""

    pass


@type_eval.register_evaluator(RaiseError)
@_lift_evaluated
def _eval_RaiseError(msg, *extra_types, ctx):
    """Evaluate RaiseError by raising a TypeMapError.

    RaiseError[S, *Ts] raises a type error with message S,
    including the string representations of any extra type arguments.
    """
    message = _from_literal(msg)
    if extra_types:
        type_strs = ", ".join(repr(t) for t in extra_types)
        message = f"{message}: {type_strs}"
    raise TypeMapError(message)


##################################################################


def _add_quals(typ, quals):
    for qual in (typing.ClassVar, typing.Final):
        if type_eval.issubtype(typing.Literal[qual.__name__], quals):
            typ = qual[typ]
    return typ


FUNC_LIKES = {
    GenericCallable: 0,
    collections.abc.Callable: 0,
    staticmethod: 0,
    classmethod: 1,
}


def _is_method_like(typ):
    return typing.get_origin(typ) in FUNC_LIKES


def _unpack_init(dct, name, init):
    """Unpack an initializer type into a __dict__.

    If init is a literal with a single value, then dct[name] gets that
    value. If it is an InitField subclass, we recursively unpack the
    TypedDict it is parameterized over into a new InitField object,
    and include that.
    """
    origin = typing.get_origin(init)
    if _typing_inspect.is_literal(init) and len(init.__args__) == 1:
        dct[name] = init.__args__[0]
    if isinstance(origin, type) and issubclass(origin, InitField):
        args = {}
        for k, v in typing.get_type_hints(init.__args__[0]).items():
            _unpack_init(args, k, v)
        dct[name] = origin(**args)


@type_eval.register_evaluator(NewProtocol)
@_lift_evaluated
def _eval_NewProtocol(*etyps: Member, ctx):
    dct: dict[str, object] = {}
    dct["__annotations__"] = annos = {}

    members = [typing.get_args(prop) for prop in etyps]
    for tname, typ, quals, init, _ in members:
        name = _eval_literal(tname, ctx)
        typ = _eval_types(typ, ctx)
        tquals = _eval_types(quals, ctx)

        if type_eval.issubtype(
            typing.Literal["ClassVar"], tquals
        ) and _is_method_like(typ):
            try:
                dct[name] = _callable_type_to_method(name, typ, ctx)
            except type_eval.StuckException:
                annos[name] = _add_quals(typ, tquals)
        else:
            annos[name] = _add_quals(typ, tquals)
            _unpack_init(dct, name, init)

    module_name = __name__
    name = "NewProtocol"

    # If the type evaluation context
    ctx = type_eval._get_current_context()
    if ctx.current_generic_alias:
        if isinstance(ctx.current_generic_alias, types.GenericAlias):
            name = str(ctx.current_generic_alias)
        else:
            name = f"{ctx.current_generic_alias.__name__}[...]"
        module_name = ctx.current_generic_alias.__module__

    dct["__module__"] = module_name

    mcls: type = type(typing.cast(type, typing.Protocol))
    cls = mcls(name, (typing.Protocol,), dct)
    # Stick __init__ back in, since Protocol messes with it
    if '__init__' in dct:
        cls.__init__ = dct['__init__']

    return cls


def _add_td_quals(typ, quals):
    for qual in (typing.NotRequired, typing.ReadOnly):
        if type_eval.issubtype(typing.Literal[qual.__name__], quals):
            typ = qual[typ]
    return typ


@type_eval.register_evaluator(NewTypedDict)
@_lift_evaluated
def _eval_NewTypedDict(*etyps: Member, ctx):
    annos = {}

    members = [typing.get_args(prop) for prop in etyps]
    for tname, typ, quals, _init, _ in members:
        name = _eval_literal(tname, ctx)
        typ = _eval_types(typ, ctx)
        tquals = _eval_types(quals, ctx)
        annos[name] = _add_td_quals(typ, tquals)

    td_name = "NewTypedDict"
    module_name = __name__

    ctx = type_eval._get_current_context()
    if ctx.current_generic_alias:
        if isinstance(ctx.current_generic_alias, types.GenericAlias):
            td_name = str(ctx.current_generic_alias)
        else:
            td_name = f"{ctx.current_generic_alias.__name__}[...]"
        module_name = ctx.current_generic_alias.__module__

    cls = typing.TypedDict(td_name, annos)  # type: ignore[misc]
    cls.__module__ = module_name

    return cls
