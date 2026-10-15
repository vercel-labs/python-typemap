import textwrap

from typing import Callable, Literal

from typemap.type_eval import eval_typing
from typemap_extensions import (
    NewProtocol,
    Attrs,
    Member,
    NamedParam,
    Param,
    Params,
    Concat,
)

from typemap.type_eval import format_helper


class Schema:
    pass


class Type:
    pass


class Expression:
    pass


# hmmmm... recursion with this sort of thing will be funny...
# how will we handle the decorators or __init_subclass__ or what have you


class Property:
    name: str
    required: bool
    multi: bool
    typ: Type
    expr: Expression | None


type Schemaify[T] = NewProtocol[
    *[p for p in Attrs[T]],
    *[
        Member[
            Concat[Literal["get_"], p.name],
            Callable[
                Params[
                    Param[Literal["self"], Schemaify[T]],
                    NamedParam[Literal["schema"], Schema],
                ],
                p.type,
            ],
            Literal["ClassVar"],
        ]
        for p in Attrs[T]
    ],
]


def test_schema_like_1():
    tgt = eval_typing(Schemaify[Property])
    fmt = format_helper.format_class(tgt)

    getter_params = "self: Self, *, schema: tests.test_schemalike.Schema"
    assert fmt == textwrap.dedent(f"""\
    class Schemaify[tests.test_schemalike.Property]:
        name: str
        required: bool
        multi: bool
        typ: tests.test_schemalike.Type
        expr: tests.test_schemalike.Expression | None
        def get_name({getter_params}) -> str: ...
        def get_required({getter_params}) -> bool: ...
        def get_multi({getter_params}) -> bool: ...
        def get_typ({getter_params}) -> tests.test_schemalike.Type: ...
        def get_expr({getter_params}) -> tests.test_schemalike.Expression | None: ...
    """)
