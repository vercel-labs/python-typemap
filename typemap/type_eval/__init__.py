from ._eval_typing import (
    eval_typing,
    _get_current_context,
    _ensure_context,
    register_evaluator,
    _EvalProxy,
)
from ._apply_generic import flatten_class

# XXX: this needs to go second due to nasty circularity -- try to fix that!!
from ._eval_call import eval_call, eval_call_with_types
from ._subtype import issubtype
from ._type_ast import type_ast_to_type

# This one is imported for registering handlers
from . import _eval_operators  # noqa

from ._eval_operators import TypeMapError


__all__ = (
    "eval_typing",
    "register_evaluator",
    "eval_call",
    "eval_call_with_types",
    "flatten_class",
    "issubtype",
    "type_ast_to_type",
    "TypeMapError",
    "_EvalProxy",
    "_get_current_context",
    "_ensure_context",
)
