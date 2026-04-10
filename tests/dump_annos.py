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


def load_stringified_copy() -> types.ModuleType:
    """Create a temp copy of _annos.py with ``from __future__ import annotations``
    prepended, import it, and return the module."""
    source = ANNOS_PATH.read_text()
    patched = "from __future__ import annotations\n" + source

    tmp = tempfile.NamedTemporaryFile(
        suffix=".py", prefix="_annos_str_", delete=False, mode="w"
    )
    tmp.write(patched)
    tmp.flush()
    tmp.close()

    spec = importlib.util.spec_from_file_location(
        "_annos_stringified", tmp.name
    )
    string_mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = string_mod
    spec.loader.exec_module(string_mod)
    return string_mod


def get_annotations_str(func: types.FunctionType) -> dict[str, str]:
    """Get annotations from a function that used ``from __future__ import annotations``
    (all values will be plain strings)."""
    return annotationlib.get_annotations(
        func, format=annotationlib.Format.STRING
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
