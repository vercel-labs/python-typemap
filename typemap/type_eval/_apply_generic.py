import annotationlib
import collections
import collections.abc
import dataclasses
import inspect
import sys
import types
import typing


from .. import annotations
from . import _eval_typing
from . import _type_ast
from . import _typing_inspect


if typing.TYPE_CHECKING:
    from typing import Any, Mapping


@dataclasses.dataclass(frozen=True)
class Boxed:
    cls: type[Any]
    bases: list[Boxed]
    args: dict[Any, Any]
    orig_cls: type[Any] | None = (
        None  # Original class, before __init_subclass__ applied
    )

    str_args: dict[str, Any] = dataclasses.field(init=False)
    mro: tuple[Boxed, ...] = dataclasses.field(init=False)

    def __post_init__(self):
        object.__setattr__(
            self,
            "str_args",
            {
                # Use __name__ when available instead of str()
                # str(TypeVar('A')) returns '~A'
                (k.__name__ if hasattr(k, '__name__') else str(k)): v
                for k, v in self.args.items()
            },
        )
        object.__setattr__(
            self,
            "mro",
            tuple(_compute_mro(self)),
        )

    @property
    def canonical_cls(self):
        """The class for the original boxing.

        (Possibly a new one was created after __init_subclass__ applied.
        """
        return self.orig_cls or self.cls

    def alias_type(self):
        if self.args:
            return self.canonical_cls[*self.args.values()]
        else:
            return self.canonical_cls

    def __repr__(self):
        return f"Boxed<{self.cls} {self.args}>"

    def __hash__(self):
        return hash(self.cls)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Boxed):
            return NotImplemented
        return self.cls == other.cls

    def dump(self, *, _level: int = 0):
        print("    " * _level, self.cls)
        print("    " * _level, self.args)

        for b in self.bases:
            b.dump(_level=_level + 1)


_TYPE_VAR_LIKE = (typing.TypeVar, typing.TypeVarTuple, typing.ParamSpec)


def _bound_vars(binder):
    if isinstance(binder, _TYPE_VAR_LIKE):
        return {binder}
    bound = set()
    for v in typing.get_args(binder):
        if _typing_inspect.is_type_var_tuple_unpack(v):
            v = typing.get_args(v)[0]
        bound.add(v)
    return bound


def _subst_args(tys, args, *, binding_sites=(), flatten_params=False):
    """Substitute into a sequence of type arguments.

    binding_sites is in the format of ``__binding_sites__`` (see
    substitute), giving which variables in tys are bound where.

    TypeVarTuples substituted with a fixed-length tuple are spliced
    in. If flatten_params, ParamSpecs substituted with a list of types
    are too, as is the result of substituting into a Concatenate.
    """
    # TODO: This doesn't avoid capture: if a type being substituted in
    # has a free variable that is bound here, it gets captured. Full
    # capture avoidance would need to compute the free variables of
    # the substituted types and rename any bound variables that clash.
    arg_maps = [args] * len(tys)
    for vars_index, positions in binding_sites:
        bound = _bound_vars(tys[vars_index])
        # The binders themselves are never substituted
        arg_maps[vars_index] = {}
        for pos in positions:
            arg_maps[pos] = {
                k: v for k, v in arg_maps[pos].items() if k not in bound
            }

    res = []
    for ty, ty_args in zip(tys, arg_maps, strict=True):
        new = substitute(ty, ty_args)
        if (
            _typing_inspect.is_type_var_tuple_unpack(ty)
            and typing.get_origin(new) is typing.Unpack
            and typing.get_origin(inner := typing.get_args(new)[0]) is tuple
            and not _typing_inspect.is_unbounded_tuple(inner)
        ):
            res.extend(typing.get_args(inner))
        elif flatten_params and isinstance(new, (list, tuple)):
            res.extend(new)
        else:
            res.append(new)
    return res


def _same(old, new):
    return len(old) == len(new) and all(
        a is b for a, b in zip(old, new, strict=True)
    )


def _make_callable_params(params):
    if len(params) == 1 and (
        params[0] is Ellipsis
        or isinstance(
            params[0], (typing.ParamSpec, typing._ConcatenateGenericAlias)
        )
    ):
        return params[0]
    return list(params)


def substitute(ty, args):
    """Substitute type variables in ty according to args.

    Respects binding sites, given by a ``__binding_sites__`` attribute
    on the origin of a generic alias: a list of ``(vars_index,
    positions)`` pairs saying that the type variable (or tuple of
    type variables) at argument ``vars_index`` is bound in the
    arguments at ``positions``. Bound variables are not substituted
    within their scope.
    """
    if not args:
        return ty

    if isinstance(ty, _TYPE_VAR_LIKE):
        return args.get(ty, ty)

    if isinstance(ty, (list, tuple)):
        new = _subst_args(ty, args)
        return ty if _same(ty, new) else type(ty)(new)

    if _typing_inspect.is_union_type(ty):
        old = typing.get_args(ty)
        new = _subst_args(old, args)
        return ty if _same(old, new) else typing.Union[*new]

    if not _typing_inspect.is_generic_alias(ty):
        return ty

    origin = typing.get_origin(ty)
    old = typing.get_args(ty)

    if not old or origin is typing.Literal:
        return ty

    if origin is typing.Annotated:
        new_origin = substitute(old[0], args)
        if new_origin is old[0]:
            return ty
        return typing.Annotated[new_origin, *ty.__metadata__]

    if origin is collections.abc.Callable:
        new_params = _subst_args(old[:-1], args, flatten_params=True)
        ret = substitute(old[-1], args)
        if _same(old, [*new_params, ret]):
            return ty
        if isinstance(ty, typing._GenericAlias):
            return ty.copy_with((*new_params, ret))
        return collections.abc.Callable[_make_callable_params(new_params), ret]

    new = _subst_args(
        old, args, binding_sites=getattr(origin, "__binding_sites__", ())
    )
    if _same(old, new):
        return ty

    if isinstance(ty, types.GenericAlias):
        res = types.GenericAlias(origin, tuple(new))
        if ty.__unpacked__:
            (res,) = res
        return res

    # Everything else is a typing._GenericAlias. A ParamSpec argument
    # substituted with a list of types is stored as a tuple.
    new = [tuple(a) if isinstance(a, list) else a for a in new]
    return ty.copy_with(tuple(new))


def box(cls: type[Any]) -> Boxed:
    # TODO: We want a cache for this!!
    def _box(cls: type[Any], args: dict[Any, Any]) -> Boxed:
        boxed_bases: list[Boxed] = []

        orig_bases = cls.__dict__.get("__orig_bases__")
        if orig_bases is None:
            # Regular Python class, not a generic
            for base in cls.__bases__:
                boxed_bases.append(_box(base, {}))
        else:
            assert len(cls.__bases__) == len(orig_bases)
            for i, base in enumerate(cls.__bases__):
                obase = orig_bases[i]

                if issubclass(base, typing.Generic):
                    if base_params := getattr(base, "__parameters__", None):
                        # obase should be _GenericAlias...
                        boxed_args = {}
                        for param, arg in zip(
                            base_params, obase.__args__, strict=True
                        ):
                            boxed_args[param] = substitute(arg, args)
                    else:
                        boxed_args = {}

                    boxed_bases.append(_box(base, boxed_args))
                else:
                    boxed_bases.append(_box(base, {}))

        return Boxed(cls, boxed_bases, args)

    if isinstance(cls, (typing._GenericAlias, types.GenericAlias)):  # type: ignore[attr-defined]
        if params := getattr(cls.__origin__, "__parameters__", None):
            args = dict(
                zip(cls.__origin__.__parameters__, cls.__args__, strict=True)
            )
        else:
            args = {}
        cls = cls.__origin__
    else:
        if params := getattr(cls, "__parameters__", None):
            args = {p: _typing_inspect.param_default(p) for p in params}
        else:
            args = {}

    return _box(cls, args)


def merge_boxed_mro[T](seqs: list[list[T]]) -> list[T]:
    res: list[T] = []
    i = 0
    cand: T | None = None
    while 1:
        nonemptyseqs = [seq for seq in seqs if seq]
        if not nonemptyseqs:
            return res
        i += 1
        for seq in nonemptyseqs:
            cand = seq[0]
            nothead = [s for s in nonemptyseqs if cand in s[1:]]
            if nothead:
                cand = None
            else:
                break
        if cand is None:
            raise TypeError("Inconsistent hierarchy")
        res.append(cand)
        for seq in nonemptyseqs:
            if seq[0] == cand:
                del seq[0]

    raise RuntimeError("unreachable")


def _compute_mro(C: Boxed) -> list[Boxed]:
    return merge_boxed_mro(
        [[C]] + [list(b.mro) for b in C.bases] + [list(C.bases)]
    )


def make_func(
    orig_func: types.FunctionType
    | types.MethodType
    | staticmethod
    | classmethod,
    annos: dict[str, Any],
) -> types.FunctionType:
    func = inspect.unwrap(orig_func)  # type: ignore[arg-type]

    new_func: Any = types.FunctionType(
        func.__code__,
        func.__globals__,
        "__call__",
        func.__defaults__,
        func.__closure__,
        func.__kwdefaults__,
    )

    new_func.__module__ = func.__module__
    new_func.__name__ = func.__name__
    new_func.__annotations__ = annos
    new_func.__type_params__ = func.__type_params__

    if isinstance(orig_func, staticmethod):
        new_func = staticmethod(new_func)
    elif isinstance(orig_func, classmethod):
        new_func = classmethod(new_func)

    return new_func


EXCLUDED_ATTRIBUTES = typing.EXCLUDED_ATTRIBUTES - {'__init__'}  # type: ignore[attr-defined]


def _maybe_get_annotate(obj: object, key: str) -> types.FunctionType | None:
    af = typing.cast(types.FunctionType, getattr(obj, key, None))
    if not af:
        return None
    try:
        af(annotationlib.Format.VALUE_WITH_FAKE_GLOBALS)
    except NotImplementedError:
        return None
    except ValueError as e:
        if 'VALUE_WITH_FAKE_GLOBALS' in str(e):
            return None
    except Exception:
        pass
    return af


def _shadow_closure(
    env: annotations.BindingEnvironment, names: Mapping[str, object]
) -> annotations.BindingEnvironment:
    closure = collections.ChainMap(dict(names), env.closure)  # type: ignore[arg-type]
    return dataclasses.replace(env, closure=closure)


def get_annotations(
    obj: object,
    args: Mapping[str, object],
    key: str = '__annotate__',
    cls: type | None = None,
    annos_ok: bool = True,
) -> Any | None:
    """Get the annotations on an object, substituting in type vars."""

    rr = None
    env = annotations.BindingEnvironment(globals={}, closure={}, classdict=None)
    if af := _maybe_get_annotate(obj, key):
        ast, info = annotations.get_annotate_ast(af)
        env = info.env
        rr = _type_ast.annotations_ast_to_types(
            ast, env=_shadow_closure(env, args), namespace=info.namespace
        )
    elif annos_ok and (rr := getattr(obj, "__annotations__", None)):
        if mod := sys.modules.get(obj.__module__):
            env.globals.update(vars(mod))

        # Make a copy in case we need to eval the annotations. We don't want to
        # modify the original.
        rr = dict(rr)

    if isinstance(rr, dict) and any(isinstance(v, str) for v in rr.values()):
        locals = dict(args)
        # Copy in any __type_params__ that aren't provided for, so that if
        # we have to eval, we have them.
        if params := getattr(obj, "__type_params__", None):
            for param in params:
                if str(param) not in args:
                    locals[str(param)] = param

        # Include the class itself in args so that self-referential string
        # annotations (e.g. from `from __future__ import annotations`) in
        # nested scopes can be resolved during eval. (This only half
        # solves that general problem, but it is the best we can do.)
        rcls = cls or obj
        if isinstance(rcls, (type, typing.TypeAliasType)):
            if rcls.__name__ not in args:
                locals[rcls.__name__] = rcls

        str_env = _shadow_closure(env, locals)
        for k, v in rr.items():
            # Eval strings
            if isinstance(v, str):
                v = _type_ast.annotations_ast_to_types(v, env=str_env)
                # Handle cases where annotation is explicitly a string,
                # e.g.:
                #   class Foo[X]:
                #       x: "Foo[X | None]"
                if isinstance(v, str):
                    v = _type_ast.annotations_ast_to_types(v, env=str_env)
            rr[k] = v

    return rr


def _resolved_function_signature(func, args):
    """Get the signature of a function with type hints resolved to arg values"""

    # We need to grab the signature and don't care about annotations,
    # since we will be replacing those immediately.
    # We use format=FORWARDREF to swallow all problems.
    sig = inspect.signature(
        func, annotation_format=annotationlib.Format.FORWARDREF
    )

    if hints := get_annotations(func, args):
        params = []
        for name, param in sig.parameters.items():
            annotation = hints.get(name, param.annotation)
            params.append(param.replace(annotation=annotation))

        return_annotation = hints.get("return", sig.return_annotation)
        sig = sig.replace(
            parameters=params, return_annotation=return_annotation
        )

    return sig


def get_local_defns(
    boxed: Boxed,
    *,
    include_methods: bool = True,
) -> tuple[
    dict[str, Any],
    dict[
        str, types.FunctionType | classmethod | staticmethod | WrappedOverloads
    ],
]:
    annos: dict[str, Any] = {}
    dct: dict[str, Any] = {}

    if (rr := get_annotations(boxed.cls, boxed.str_args)) is not None:
        annos.update(rr)

    for name, orig in boxed.cls.__dict__.items():
        if name in EXCLUDED_ATTRIBUTES:
            continue

        stuff = inspect.unwrap(orig)

        if include_methods and isinstance(stuff, types.FunctionType):
            local_fn: Any = None

            # TODO: This annos_ok thing is a hack because processing
            # __annotations__ on methods broke stuff and I didn't want
            # to chase it down yet.
            rr = get_annotations(
                stuff, boxed.str_args, cls=boxed.cls, annos_ok=False
            )

            if rr is not None:
                local_fn = make_func(orig, rr)
            elif getattr(stuff, "__annotations__", None):
                # XXX: This is totally wrong; we still need to do
                # substitute in class vars
                local_fn = stuff
            elif overloads := typing.get_overloads(stuff):
                local_fn = WrappedOverloads(tuple(overloads))

            if local_fn is not None:
                if orig.__class__ is classmethod:
                    local_fn = classmethod(local_fn)
                elif orig.__class__ is staticmethod:
                    local_fn = staticmethod(local_fn)

                dct[name] = local_fn

    return annos, dct


@dataclasses.dataclass(frozen=True)
class WrappedOverloads:
    functions: tuple[typing.Callable[..., Any], ...]


def flatten_class_new_proto(cls: type) -> type:
    # This is a hacky version of flatten_class that works by using
    # NewProtocol on Members!
    #
    # It works except for methods, since NewProtocol doesn't understand those.
    from typemap.typing import (
        Members,
        NewProtocol,
    )

    type ClsAlias = NewProtocol[*[m for m in Members[cls]]]  # type: ignore[valid-type]
    nt = _eval_typing.eval_typing(ClsAlias)

    args = typing.get_args(cls)
    args_str = ", ".join(_type_repr(a) for a in args)
    args_str = f'[{args_str}]' if args_str else ''

    nt.__name__ = f'{cls.__name__}{args_str}'
    nt.__qualname__ = f'{cls.__qualname__}{args_str}'
    nt.__module__ = cls.__module__
    del nt.__subclasshook__

    return nt


def _type_repr(t: Any) -> str:
    if isinstance(t, type):
        if t.__module__ == "builtins":
            return t.__qualname__
        else:
            return f"{t.__module__}.{t.__qualname__}"
    else:
        return repr(t)


flatten_class = flatten_class_new_proto
