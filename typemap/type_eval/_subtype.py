import typing


from . import _typing_inspect


__all__ = ("issubtype",)


def issubtype(lhs: typing.Any, rhs: typing.Any) -> bool:
    # TODO: Need to handle a lot of cases!
    # This is explicitly "best-effort", though.

    # TODO: We will probably need to carry a context around,
    # and maybe recursively invoke eval_typing?

    # N.B: All of the 'bool's in these are because black otherwise
    # formats the two-conditional chains in an unconscionably bad way.

    if lhs is None:
        lhs = type(None)
    if rhs is None:
        rhs = type(None)

    if lhs is typing.Any or rhs is typing.Any:
        return True

    # Unions first
    if lhs is typing.Never:
        return True
    elif rhs is typing.Never:
        return False
    if _typing_inspect.is_union_type(rhs):
        return any(issubtype(lhs, r) for r in typing.get_args(rhs))
    elif _typing_inspect.is_union_type(lhs):
        return all(issubtype(t, rhs) for t in typing.get_args(lhs))

    # For _EvalProxy's just blow through them, since we don't yet care
    # about the attribute types here.
    # TODO: But we'll need to once we support Protocols??
    elif _typing_inspect.is_eval_proxy(lhs):
        return issubtype(lhs.__origin__, rhs)
    elif _typing_inspect.is_eval_proxy(rhs):
        return issubtype(lhs, rhs.__origin__)

    elif bool(
        _typing_inspect.is_valid_isinstance_arg(lhs)
        and _typing_inspect.is_valid_isinstance_arg(rhs)
    ):
        return issubclass(lhs, rhs)

    # literal <:? literal
    elif _typing_inspect.is_literal(lhs) and _typing_inspect.is_literal(rhs):
        # We need to check both value and type, since True == 1 but
        # Literal[True] should not be a subtype of Literal[1]
        rhs_args = {(t, type(t)) for t in typing.get_args(rhs)}
        return all((lv, type(lv)) in rhs_args for lv in typing.get_args(lhs))

    # XXX: This case is kind of a hack, to support NoLiterals.
    elif rhs is typing.Literal:
        return _typing_inspect.is_literal(lhs)

    # literal <:? type
    elif _typing_inspect.is_literal(lhs):
        return all(issubtype(type(x), rhs) for x in typing.get_args(lhs))

    # C[A] <:? D
    elif bool(
        _typing_inspect.is_generic_alias(lhs)
        and _typing_inspect.is_valid_isinstance_arg(rhs)
    ):
        return issubtype(_typing_inspect.get_origin(lhs), rhs)

    # C <:? D[A]
    elif bool(
        _typing_inspect.is_valid_isinstance_arg(lhs)
        and _typing_inspect.is_generic_alias(rhs)
    ):
        return issubtype(lhs, _typing_inspect.get_origin(rhs))

    # C[A] <:? D[B] -- just match the heads!
    # Super wrong!
    # TODO: What to do about C[A] <:? D[B]???
    # TODO: and we will we need to infer variance ourselves with the new syntax
    elif bool(
        _typing_inspect.is_generic_alias(lhs)
        and _typing_inspect.is_generic_alias(rhs)
    ):
        return issubtype(
            _typing_inspect.get_origin(lhs), _typing_inspect.get_origin(rhs)
        )

    # XXX: I think this is probably wrong, but a test currently has
    # an unbound type variable...
    elif _typing_inspect.is_type_var(lhs):
        return lhs is rhs

    # TODO: Protocols???

    # TODO: tuple

    # TODO: Callable -- oh no, and callable needs

    # TODO: Annotated

    # TODO: TypedDict

    # TODO: We will need to have some sort of hook to support runtime
    # checking of typechecker extensions.
    #
    # We could have restrictions if we are willing to document them.

    # This will probably fail
    try:
        return issubclass(lhs, rhs)
    except TypeError as e:
        raise TypeError(*e.args, lhs, rhs)
