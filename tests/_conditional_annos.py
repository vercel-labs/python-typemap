"""Classes and a module with conditionally defined annotations.

Their ``__annotate__`` bytecode checks ``__conditional_annotations__`` to
decide which annotations were actually executed.
"""

FLAG = True

mod_a: int
if FLAG:
    mod_b: str
else:
    mod_c: bytes
if not FLAG:
    mod_d: float
mod_e: list[int] if FLAG else None


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
