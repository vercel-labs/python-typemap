"""Classes with conditionally defined annotations.

Their ``__annotate__`` bytecode checks ``__conditional_annotations__`` to
decide which annotations were actually executed.
"""

FLAG = True


class IfElse:
    a: int
    if FLAG:
        b: str
    else:
        c: bytes
    d: list[int]


class IfNotTaken:
    if not FLAG:
        a: int
    b: str


class Loop:
    for _ in range(1):
        a: tuple[int, ...] if FLAG else None
    while False:
        b: int


class Nested:
    if FLAG:
        if not FLAG:
            a: int
        else:
            b: dict[str, int]
    c: str
