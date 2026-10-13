"""Convert the AST of a type annotation into ``typing`` objects.

The annotation is evaluated with ``eval``, after rewriting the syntax
proposed in PEP 827 into the equivalent type operators:

* ``A if B else C`` becomes ``_Cond[B, A, C]``
* ``not``, ``and``, ``or`` become ``_Not``, ``_And``, ``_Or``
* ``*[A for t in Iter[T] if B]`` becomes ``_UnpackMap[T, t, A, B]``,
  where ``t`` is a fresh ``TypeVar``
* ``any(A for ...)``/``all(A for ...)`` become ``_Any``/``_All`` of
  the ``_UnpackMap`` for ``*[A for ...]``
* ``M.name`` where ``M`` is a ``TypeVar`` becomes
  ``_GetAssociated[M, Literal["name"]]``

No type evaluation is performed.
"""

import ast
import builtins
import collections
import copy
import typing

from typing import Any, Callable, Collection, Mapping

from typemap.annotations import BindingEnvironment, BindingNamespace
from typemap.typing import (
    _Cond,
    _GetAssociated,
    Iter,
    _UnpackMap,
    _All,
    _And,
    _Any,
    _Not,
    _Or,
)


class _GlobalsWithFallback(dict):
    """A globals overlay that preserves a dict subclass's __missing__."""

    __slots__ = ("fallback",)

    def __init__(self, namespace, fallback):
        super().__init__(namespace)
        self.fallback = fallback

    def __missing__(self, key):
        if self.fallback is None:
            raise KeyError(key)
        return self.fallback[key]

    def copy(self):
        return type(self)(self, self.fallback)


def _strip_iter(tp):
    if typing.get_origin(tp) is not Iter:
        raise TypeError(
            f"Type comprehensions must iterate over Iter[...], got {tp!r}"
        )
    return typing.get_args(tp)[0]


def _getattr(obj, name):
    if isinstance(obj, typing.TypeVar):
        return _GetAssociated[obj, typing.Literal[name]]
    return getattr(obj, name)


_HELPERS = {
    "__typemap_Cond": _Cond,
    "__typemap_UnpackMap": _UnpackMap,
    "__typemap_Not": _Not,
    "__typemap_And": _And,
    "__typemap_Or": _Or,
    "__typemap_Any": _Any,
    "__typemap_All": _All,
    "__typemap_strip_iter": _strip_iter,
    "__typemap_getattr": _getattr,
}


def _name(name: str) -> ast.expr:
    return ast.Name(id=f"__typemap_{name}", ctx=ast.Load())


def _subscript(name: str, *args: ast.expr) -> ast.expr:
    return ast.Subscript(
        value=_name(name),
        slice=args[0]
        if len(args) == 1
        else ast.Tuple(elts=list(args), ctx=ast.Load()),
        ctx=ast.Load(),
    )


def _any_all_op(node: ast.Call) -> str | None:
    """The type operator for an any() or all() of a generator, if it is one."""
    if (
        isinstance(node.func, ast.Name)
        and node.func.id in ("any", "all")
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.GeneratorExp)
    ):
        return "Any" if node.func.id == "any" else "All"
    return None


class _Mangler(ast.NodeTransformer):
    """Mangle private names, for annotations taken from source."""

    def __init__(self, namespace: BindingNamespace) -> None:
        self.namespace = namespace

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = self.namespace.mangle(node.id)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        self.generic_visit(node)
        node.attr = self.namespace.mangle(node.attr)
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.arg = self.namespace.mangle(node.arg)
        return node


_CLASS_LOOKUP = "__typemap_class_lookup"


class _ClassScoper(ast.NodeTransformer):
    """Make names see the class namespace like in a class's annotation scope.

    Names are looked up in the class namespace first, unless they are
    declared global.  Lambda bodies and all but the outermost iterable
    of comprehensions are nested scopes, which can't see it.
    """

    def __init__(self, global_names: Collection[str]) -> None:
        self.global_names = global_names

    def visit_Name(self, node: ast.Name) -> ast.expr:
        if not isinstance(node.ctx, ast.Load) or node.id in self.global_names:
            return node
        return ast.Call(
            func=ast.Name(id=_CLASS_LOOKUP, ctx=ast.Load()),
            args=[ast.Constant(value=node.id)],
            keywords=[],
        )

    def visit_Lambda(self, node: ast.Lambda) -> ast.Lambda:
        args = node.args
        args.defaults = [self.visit(d) for d in args.defaults]
        args.kw_defaults = [
            None if d is None else self.visit(d) for d in args.kw_defaults
        ]
        return node

    def _comprehension[
        C: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ](self, node: C) -> C:
        gen = node.generators[0]
        gen.iter = self.visit(gen.iter)
        return node

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension

    def visit_Call(self, node: ast.Call) -> ast.Call:
        # The rewriter treats these as syntax, so leave any and all alone
        if _any_all_op(node):
            node.args = [self.visit(node.args[0])]
            return node
        self.generic_visit(node)
        return node


def _class_lookup(
    classdict: Mapping[str, Any], scope: Mapping[str, Any]
) -> Callable[[str], Any]:
    def lookup(name: str) -> Any:
        try:
            return classdict[name]
        except KeyError:
            pass
        try:
            return scope[name]
        except KeyError:
            pass
        try:
            return getattr(builtins, name)
        except AttributeError:
            raise NameError(
                f"name {name!r} is not defined", name=name
            ) from None

    return lookup


class _Rewriter(ast.NodeTransformer):
    def __init__(self) -> None:
        self.typevars: dict[str, typing.TypeVar] = {}
        # Maps comprehension variables in scope to the names of their
        # TypeVars
        self.scope: dict[str, str] = {}

    def visit_Name(self, node: ast.Name) -> ast.expr:
        if isinstance(node.ctx, ast.Load) and node.id in self.scope:
            return ast.Name(id=self.scope[node.id], ctx=ast.Load())
        return node

    def _comprehension(
        self,
        elt: ast.expr,
        generators: list[ast.comprehension],
    ) -> ast.expr:
        gen, *rest = generators
        if gen.is_async:
            raise SyntaxError("async type comprehensions are not supported")
        if not isinstance(gen.target, ast.Name):
            raise SyntaxError(
                "type comprehensions must bind a single variable, "
                f"got {ast.unparse(gen.target)!r}"
            )
        var = gen.target.id

        iter = ast.Call(
            func=_name("strip_iter"),
            args=[self.visit(gen.iter)],
            keywords=[],
        )

        tv_name = f"__typemap_tv{len(self.typevars)}"
        self.typevars[tv_name] = typing.TypeVar(var)
        old_scope = self.scope
        self.scope = {**old_scope, var: tv_name}
        try:
            conds = [self.visit(c) for c in gen.ifs]
            if rest:
                body = self._comprehension(elt, rest)
            else:
                body = self.visit(elt)
        finally:
            self.scope = old_scope

        tv = ast.Name(id=tv_name, ctx=ast.Load())
        args = [iter, tv, body]
        if len(conds) == 1:
            args.extend(conds)
        elif conds:
            args.append(_subscript("And", *conds))
        return _subscript("UnpackMap", *args)

    def visit_Starred(self, node: ast.Starred) -> ast.AST:
        if isinstance(node.value, ast.ListComp):
            return ast.Starred(
                value=ast.List(
                    elts=[
                        self._comprehension(
                            node.value.elt, node.value.generators
                        ),
                        ast.Starred(
                            value=ast.Subscript(
                                value=ast.Name(id='tuple'),  # XXX
                                slice=ast.Tuple(),
                            ),
                        ),
                    ],
                )
            )

        return self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> ast.expr:
        return _subscript(
            "Cond",
            self.visit(node.test),
            self.visit(node.body),
            self.visit(node.orelse),
        )

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.expr:
        op = "And" if isinstance(node.op, ast.And) else "Or"
        return _subscript(op, *[self.visit(v) for v in node.values])

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        if isinstance(node.op, ast.Not):
            return _subscript("Not", self.visit(node.operand))
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        if op := _any_all_op(node):
            gen = node.args[0]
            assert isinstance(gen, ast.GeneratorExp)
            return _subscript(op, self._comprehension(gen.elt, gen.generators))
        return self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.expr:
        return ast.Call(
            func=_name("getattr"),
            args=[self.visit(node.value), ast.Constant(value=node.attr)],
            keywords=[],
        )

    def _bad_comprehension(self, node: ast.expr) -> ast.expr:
        raise SyntaxError(
            "type comprehensions must be unpacked lists: *[... for ...], "
            f"got {ast.unparse(node)!r}"
        )

    visit_ListComp = _bad_comprehension
    visit_SetComp = _bad_comprehension
    visit_DictComp = _bad_comprehension
    visit_GeneratorExp = _bad_comprehension


def _rewrite_star_unpack(expr: ast.expr) -> ast.expr:
    if not isinstance(expr, ast.Starred):
        return expr

    result = ast.Subscript(
        value=ast.Tuple(elts=[expr], ctx=ast.Load()),
        slice=ast.Constant(value=0),
        ctx=ast.Load(),
    )
    return ast.copy_location(result, expr)


def type_ast_to_type(
    node: str | ast.expr | ast.Expression,
    globals: dict[str, Any] | None = None,
    locals: Mapping[str, Any] | None = None,
    *,
    env: BindingEnvironment | None = None,
    namespace: BindingNamespace | None = None,
) -> Any:
    """Convert the AST of a type annotation into ``typing`` objects.

    The PEP 827 syntax (conditional types, unpacked comprehensions,
    type booleans and member access) is rewritten into type operators,
    but nothing is evaluated.

    Names resolve in *locals*, then *globals*.  An *env* can be given
    instead of both, in which case names resolve in its closure, then
    its globals, and its class namespace, if any, is visible the way it
    is in an annotation scope in a class body.

    A *namespace* says how names are bound where the annotation was
    written: its ``global`` declarations bypass the class namespace,
    and private names are mangled.  (Mangling only matters for
    annotations from source, since decompiled ones are already mangled.)
    """
    if env is None:
        env = BindingEnvironment(
            globals={} if globals is None else globals,
            closure={} if locals is None else locals,
            classdict=None,
        )
    elif globals is not None or locals is not None:
        raise TypeError("globals and locals can't be given with env")

    if isinstance(node, str):
        node = ast.parse(node, mode="eval")

    if isinstance(node, ast.Expression):
        node = node.body

    # NodeTransformers modify the tree in place
    tree = copy.deepcopy(node)
    if namespace is not None:
        tree = _Mangler(namespace).visit(tree)
    if env.classdict is not None:
        global_names = namespace.global_names if namespace else ()
        tree = _ClassScoper(global_names).visit(tree)

    rewriter = _Rewriter()
    rewritten = ast.fix_missing_locations(
        ast.Expression(body=_rewrite_star_unpack(rewriter.visit(tree)))
    )
    code = compile(rewritten, "<type>", "eval")

    scope = collections.ChainMap(env.closure, env.globals)  # type: ignore[arg-type]
    helpers = _HELPERS
    if env.classdict is not None:
        helpers = {
            **_HELPERS,
            _CLASS_LOOKUP: _class_lookup(env.classdict, scope),
        }

    # Lambdas (like in GenericCallable) created by eval can't see a
    # separate locals dict, so everything needs to go in globals. The
    # fallback lets that be done without copying globals.
    return eval(
        code,
        _GlobalsWithFallback(
            {}, collections.ChainMap(helpers, rewriter.typevars, scope)
        ),
    )


def annotations_ast_to_types(
    node: str
    | ast.expr
    | ast.Expression
    | Mapping[str, str | ast.expr | ast.Expression],
    globals: dict[str, Any] | None = None,
    locals: Mapping[str, Any] | None = None,
    *,
    env: BindingEnvironment | None = None,
    namespace: BindingNamespace | None = None,
) -> Any:
    if isinstance(node, Mapping):
        return {
            k: type_ast_to_type(
                v, globals, locals, env=env, namespace=namespace
            )
            for k, v in node.items()
        }
    return type_ast_to_type(node, globals, locals, env=env, namespace=namespace)
