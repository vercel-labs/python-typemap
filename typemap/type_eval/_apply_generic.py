import annotationlib
import contextlib
import dataclasses
import inspect
import sys
import types
import typing

from typing import _GenericAlias as typing_GenericAlias  # type: ignore [attr-defined]  # noqa: PLC2701


from . import _eval_typing
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


def substitute(ty, args):
    if ty in args:
        return args[ty]
    elif isinstance(
        ty, (typing_GenericAlias, types.GenericAlias, types.UnionType)
    ):
        return ty.__origin__[*[substitute(t, args) for t in ty.__args__]]
    elif isinstance(ty, list):
        return [substitute(t, args) for t in ty]
    else:
        return ty


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


@contextlib.contextmanager
def _make_typevar_getattr_stuck():
    """Catch AttributeError on typing.TypeVar and turn it into StuckError."""
    try:
        yield
    except AttributeError as e:
        if str(e).startswith("'typing.TypeVar'"):
            raise _eval_typing.StuckException
        raise


def get_annotations(
    obj: object,
    args: Mapping[str, object],
    key: str = '__annotate__',
    cls: type | None = None,
    annos_ok: bool = True,
) -> Any | None:
    """Get the annotations on an object, substituting in type vars."""

    rr = None
    globs = None
    if af := typing.cast(types.FunctionType, getattr(obj, key, None)):
        # Substitute in names that are provided but keep the existing
        # values for everything else.
        closure = tuple(
            types.CellType(args[name]) if name in args else orig_value
            for name, orig_value in zip(
                af.__code__.co_freevars, af.__closure__ or (), strict=True
            )
        )

        globs = af.__globals__
        ff = types.FunctionType(af.__code__, globs, af.__name__, None, closure)
        with _make_typevar_getattr_stuck():
            rr = ff(annotationlib.Format.VALUE)
    elif annos_ok and (rr := getattr(obj, "__annotations__", None)):
        globs = {}
        if mod := sys.modules.get(obj.__module__):
            globs.update(vars(mod))

        # Make a copy in case we need to eval the annotations. We don't want to
        # modify the original.
        rr = dict(rr)

    if isinstance(rr, dict) and any(isinstance(v, str) for v in rr.values()):
        args = dict(args)
        # Copy in any __type_params__ that aren't provided for, so that if
        # we have to eval, we have them.
        if params := getattr(obj, "__type_params__", None):
            for param in params:
                if str(param) not in args:
                    args[str(param)] = param

        # Include the class itself in args so that self-referential string
        # annotations (e.g. from `from __future__ import annotations`) in
        # nested scopes can be resolved during eval. (This only half
        # solves that general problem, but it is the best we can do.)
        rcls = cls or obj
        if isinstance(rcls, (type, typing.TypeAliasType)):
            if rcls.__name__ not in args:
                args[rcls.__name__] = rcls

        for k, v in rr.items():
            # Eval strings
            if isinstance(v, str):
                with _make_typevar_getattr_stuck():
                    v = eval(v, globs, args)
                # Handle cases where annotation is explicitly a string,
                # e.g.:
                #   class Foo[X]:
                #       x: "Foo[X | None]"
                if isinstance(v, str):
                    with _make_typevar_getattr_stuck():
                        v = eval(v, globs, args)
            rr[k] = v

    return rr


def _resolved_function_signature(func, args):
    """Get the signature of a function with type hints resolved to arg values"""

    import typemap.typing as nt

    # We need to grab the signature and don't care about annotations,
    # since we will be replacing those immediately.
    # We use format=FORWARDREF to swallow all problems, and we disable
    # the special_form_evaluator on top of that mostly for performance.
    #
    # (Before we added dot notation for Member, disabling the
    # special_form_evaluator was sufficient.)
    token = nt.special_form_evaluator.set(None)
    try:
        sig = inspect.signature(
            func, annotation_format=annotationlib.Format.FORWARDREF
        )
    finally:
        nt.special_form_evaluator.reset(token)

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
) -> tuple[
    dict[str, Any],
    dict[
        str, types.FunctionType | classmethod | staticmethod | WrappedOverloads
    ],
]:
    from typemap.typing import GenericCallable

    annos: dict[str, Any] = {}
    dct: dict[str, Any] = {}

    if (rr := get_annotations(boxed.cls, boxed.str_args)) is not None:
        annos.update(rr)

    for name, orig in boxed.cls.__dict__.items():
        if name in EXCLUDED_ATTRIBUTES:
            continue

        stuff = inspect.unwrap(orig)

        if isinstance(stuff, types.FunctionType):
            local_fn: Any = None

            # TODO: This annos_ok thing is a hack because processing
            # __annotations__ on methods broke stuff and I didn't want
            # to chase it down yet.
            stuck = False
            try:
                rr = get_annotations(
                    stuff, boxed.str_args, cls=boxed.cls, annos_ok=False
                )
            except _eval_typing.StuckException:
                stuck = True
                rr = None

            if rr is not None:
                local_fn = make_func(orig, rr)
            elif not stuck and getattr(stuff, "__annotations__", None):
                # XXX: This is totally wrong; we still need to do
                # substitute in class vars
                local_fn = stuff
            elif overloads := typing.get_overloads(stuff):
                local_fn = WrappedOverloads(tuple(overloads))

            # If we got stuck, we build a GenericCallable that
            # computes the type once it has been given type
            # variables!
            if stuck and stuff.__type_params__:
                type_params = stuff.__type_params__
                str_args = boxed.str_args
                canonical_cls = boxed.canonical_cls

                def _make_lambda(fn, o, sa, tp, cls):
                    from ._eval_operators import _function_type_from_sig

                    def lam(*vs):
                        args = dict(sa)
                        args.update(
                            zip(
                                (str(p) for p in tp),
                                vs,
                                strict=True,
                            )
                        )
                        sig = _resolved_function_signature(fn, args)
                        return _function_type_from_sig(
                            sig, o, receiver_type=cls
                        )

                    return lam

                gc = GenericCallable[  # type: ignore[valid-type,misc]
                    tuple[*type_params],  # type: ignore[valid-type]
                    _make_lambda(
                        stuff, orig, str_args, type_params, canonical_cls
                    ),
                ]
                annos[name] = typing.ClassVar[gc]
            elif local_fn is not None:
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
        Iter,
        Members,
        NewProtocol,
    )

    type ClsAlias = NewProtocol[*[m for m in Iter[Members[cls]]]]  # type: ignore[valid-type]
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
