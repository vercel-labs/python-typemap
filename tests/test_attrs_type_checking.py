from typing import TYPE_CHECKING, Literal

from typemap.type_eval import eval_typing
import typemap_extensions as typing

if TYPE_CHECKING:

    class HiddenNamespace:
        pass


class Base:
    def rebuild(self, ns: HiddenNamespace | None = None) -> bool | None:
        return None


class Model(Base):
    name: str


def test_attrs_does_not_evaluate_method_annotations() -> None:
    attrs = eval_typing(typing.Attrs[Model])

    assert len(attrs.__args__) == 1
    assert eval_typing(attrs.__args__[0].name) == Literal["name"]
    assert eval_typing(attrs.__args__[0].type) is str
