"""Enumerate every function in _annos and print its return annotation.

For each function, shows three views:
  1. VALUE  — the live evaluated annotation (PEP 649 / annotationlib)
  2. STRING — the stringified annotation (from a __future__.annotations copy)
  3. AST    — ast.parse() of that string
"""

import ast
import importlib.util
import pathlib
import sys
import tempfile
import types

import annotationlib

import tests._annos as mod

ANNOS_PATH = pathlib.Path(mod.__file__)


def iter_functions(
    obj: type | types.ModuleType, prefix: str = ""
) -> list[tuple[str, types.FunctionType]]:
    """Yield (qualified_name, underlying_function) for every fn* in obj."""
    results: list[tuple[str, types.FunctionType]] = []
    for name in sorted(vars(obj)):
        if not name.startswith("fn"):
            continue
        val = vars(obj)[name]
        func = val
        if isinstance(val, (classmethod, staticmethod)):
            func = val.__func__
        if callable(func):
            results.append((f"{prefix}{name}", func))

    # Recurse into nested classes
    for name in sorted(vars(obj)):
        val = vars(obj)[name]
        if isinstance(val, type):
            results.extend(iter_functions(val, prefix=f"{prefix}{name}."))
    return results


def collect_functions(
    module: types.ModuleType,
) -> list[tuple[str, types.FunctionType]]:
    """Collect all fn* functions from a module (top-level + nested in classes)."""
    functions: list[tuple[str, types.FunctionType]] = []
    for name in sorted(vars(module)):
        val = getattr(module, name)
        if isinstance(val, type):
            functions.extend(iter_functions(val, prefix=f"{name}."))
        elif callable(val) and name.startswith("fn"):
            functions.append((name, val))
    return functions


def load_stringified_copy(
    source_path: pathlib.Path | None = None,
) -> types.ModuleType:
    """Create a temp copy of a ``.py`` file with
    ``from __future__ import annotations`` prepended, import it, and return
    the module.

    Defaults to ``_annos.py`` when *source_path* is ``None``.
    """
    if source_path is None:
        source_path = ANNOS_PATH
    source = source_path.read_text()
    patched = "from __future__ import annotations\n" + source

    mod_name = f"_stringified_{source_path.stem}"

    tmp = tempfile.NamedTemporaryFile(
        suffix=".py", prefix=f"{source_path.stem}_str_", delete=False, mode="w"
    )
    tmp.write(patched)
    tmp.flush()
    tmp.close()

    spec = importlib.util.spec_from_file_location(mod_name, tmp.name)
    string_mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = string_mod
    spec.loader.exec_module(string_mod)
    return string_mod


def _is_compiler_annotate(obj: types.FunctionType | type) -> bool:
    """True if *obj*'s ``__annotate__`` looks compiler-generated.

    Compiler-generated ``__annotate__`` functions start with the guard
    ``format > 2 → raise NotImplementedError`` (LOAD_FAST, LOAD_SMALL_INT 2,
    COMPARE_OP).  Synthetic versions from TypedDict, dataclass, etc. start
    with ``LOAD_GLOBAL annotationlib`` instead.
    """
    annotate = getattr(obj, "__annotate__", None)
    if annotate is None:
        return False
    import dis

    instrs = list(dis.get_instructions(annotate))
    # Skip COPY_FREE_VARS and RESUME preamble
    for i, instr in enumerate(instrs):
        if instr.opname in ("LOAD_FAST", "LOAD_FAST_BORROW"):
            # Compiler-generated: LOAD_FAST(format), LOAD_SMALL_INT(2), COMPARE_OP(>)
            return (
                i + 2 < len(instrs)
                and instrs[i + 1].opname == "LOAD_SMALL_INT"
                and instrs[i + 1].argval == 2
            )
        if instr.opname in ("COPY_FREE_VARS", "RESUME"):
            continue
        # Anything else before the LOAD_FAST guard means synthetic
        return False
    return False


def _iter_annotated(
    cls: type, prefix: str = ""
) -> list[tuple[str, types.FunctionType | type]]:
    """Yield (qualified_name, object) for annotated items in a class."""
    results: list[tuple[str, types.FunctionType | type]] = []
    for name in sorted(vars(cls)):
        val = vars(cls)[name]
        func = val
        if isinstance(val, (classmethod, staticmethod)):
            func = val.__func__
        if isinstance(func, types.FunctionType) and _is_compiler_annotate(func):
            results.append((f"{prefix}{name}", func))
        if isinstance(val, type):
            if _is_compiler_annotate(val):
                results.append((f"{prefix}{name}", val))
            results.extend(_iter_annotated(val, prefix=f"{prefix}{name}."))
    return results


def collect_annotated(
    module: types.ModuleType,
) -> list[tuple[str, types.FunctionType | type]]:
    """Collect all annotated functions and classes defined in *module*.

    Returns ``(qualified_name, object)`` pairs where *object* has a
    compiler-generated ``__annotate__`` method.  Only objects whose
    ``__module__`` matches the module are included (imported names are
    skipped).  Objects with synthetic ``__annotate__`` (TypedDict,
    dataclass, NamedTuple, etc.) are skipped.
    """
    results: list[tuple[str, types.FunctionType | type]] = []
    for name in sorted(vars(module)):
        val = getattr(module, name)
        mod = getattr(val, "__module__", None)
        if mod is not None and mod != module.__name__:
            continue
        if isinstance(val, type):
            if _is_compiler_annotate(val):
                results.append((name, val))
            results.extend(_iter_annotated(val, prefix=f"{name}."))
        elif isinstance(val, types.FunctionType):
            if _is_compiler_annotate(val):
                results.append((name, val))
    return results


def get_annotations_str(
    obj: types.FunctionType | type,
) -> dict[str, str]:
    """Return the string-form annotations for *obj* (function or class)."""
    return annotationlib.get_annotations(
        obj, format=annotationlib.Format.STRING
    )


def parse_annotation(anno_str: str) -> ast.expr:
    """Parse an annotation string into an AST expression node."""
    return ast.parse(anno_str, mode="eval").body


def main() -> None:
    # Evaluated annotations (PEP 649)
    value_fns = collect_functions(mod)

    # Stringified annotations (from __future__ import annotations)
    string_mod = load_stringified_copy()
    string_fns = collect_functions(string_mod)

    string_map: dict[str, types.FunctionType] = dict(string_fns)

    for qname, func in value_fns:
        value_annos = annotationlib.get_annotations(
            func, format=annotationlib.Format.VALUE
        )
        string_func = string_map.get(qname)
        string_annos = get_annotations_str(string_func) if string_func else {}

        params = [k for k in value_annos if k != "return"]
        all_keys = params + (["return"] if "return" in value_annos else [])

        print(f"{qname}:")
        for key in all_keys:
            label = f"  {key}: " if key != "return" else "  -> "
            val = value_annos.get(key)
            sval = string_annos.get(key)

            print(f"{label}")
            print(f"    VALUE:  {val!r}")
            if sval is not None:
                print(f"    STRING: {sval!r}")
                try:
                    tree = parse_annotation(sval)
                    print(f"    AST:    {ast.dump(tree)}")
                except SyntaxError as e:
                    print(f"    AST:    <SyntaxError: {e}>")
            else:
                print(f"    STRING: <missing>")
                print(f"    AST:    <missing>")
        print()


if __name__ == "__main__":
    main()
