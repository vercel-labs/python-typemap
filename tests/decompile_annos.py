"""Test harness: run the annotation decompiler and compare with string-form
ASTs produced via ``from __future__ import annotations``.

Works both as ``python -m tests.decompile_annos [paths…]`` (summary printout)
and via ``pytest tests/decompile_annos.py`` (one test case per annotation).

With no paths, all ``.py`` files in the ``tests/`` directory are checked.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
import types

import annotationlib  # noqa: F401
import pytest

from tests.dump_annos import (
    collect_annotated,
    get_annotations_str,
    load_stringified_copy,
    parse_annotation,
)
from typemap.type_eval._decompile import DecompileError, decompile_annotations

TESTS_DIR = pathlib.Path(__file__).parent

_SKIP_FILES = frozenset({"decompile_annos.py", "dump_annos.py", "__init__.py"})


# ---------------------------------------------------------------------------
# Module discovery / import
# ---------------------------------------------------------------------------


def _has_future_annotations(path: pathlib.Path) -> bool:
    """Return True if *path* has a ``from __future__ import annotations`` import."""
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return False
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in ast.iter_child_nodes(tree)
    )


def _discover_test_files() -> list[pathlib.Path]:
    """Find all .py files in the tests/ directory.

    Skips modules that use ``from __future__ import annotations`` because
    their ``__annotate__`` bytecode stores string constants (PEP 563) rather
    than the type-constructing opcodes the decompiler targets (PEP 649).
    """
    return sorted(
        p
        for p in TESTS_DIR.glob("*.py")
        if p.name not in _SKIP_FILES and not _has_future_annotations(p)
    )


def _import_path(path: pathlib.Path) -> types.ModuleType:
    """Import a .py file and return the module object."""
    path = path.resolve()
    if path.parent.samefile(TESTS_DIR):
        mod_name = f"tests.{path.stem}"
    else:
        mod_name = f"_decompile_target_{path.stem}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Case collection
# ---------------------------------------------------------------------------

# (label, annotation_key, original_obj, stringified_obj)
Case = tuple[str, str, types.FunctionType | type, types.FunctionType | type]


def _collect_cases_for(path: pathlib.Path) -> list[Case]:
    """Build cases for every annotation in a module file.

    Decompilation is done against the *original* module's objects.
    Expected strings come from a ``from __future__ import annotations``
    copy so they faithfully reproduce the source text.
    """
    orig_mod = _import_path(path)
    orig_map = dict(collect_annotated(orig_mod))

    string_mod = load_stringified_copy(path)
    string_map = dict(collect_annotated(string_mod))

    stem = path.stem
    cases: list[Case] = []
    for qname, orig_obj in orig_map.items():
        string_obj = string_map.get(qname)
        if string_obj is None:
            continue
        string_annos = get_annotations_str(string_obj)
        for key in string_annos:
            cases.append((f"{stem}::{qname}", key, orig_obj, string_obj))
    return cases


def _collect_all_cases(
    paths: list[pathlib.Path] | None = None,
) -> list[Case]:
    """Build cases from the given paths (default: all test modules)."""
    if paths is None:
        paths = _discover_test_files()
    all_cases: list[Case] = []
    for path in paths:
        try:
            all_cases.extend(_collect_cases_for(path))
        except Exception as exc:
            print(f"Warning: skipping {path.name}: {exc}", file=sys.stderr)
    return all_cases


_CASES = _collect_all_cases()

# Known failures — listed explicitly so new breakages aren't silently hidden.
_KNOWN_XFAILS: frozenset[str] = frozenset(
    {
        # lambda in Annotated — not decompilable
        "_annos::fn57.return",
    }
)


def _case_id(case: Case) -> str:
    label, key, _, _ = case
    return f"{label}.{key}"


# ---------------------------------------------------------------------------
# Pytest parametrised test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _CASES, ids=[_case_id(c) for c in _CASES])
def test_decompile_annotation(case: Case) -> None:
    label, key, obj, string_obj = case
    test_id = f"{label}.{key}"

    if test_id in _KNOWN_XFAILS:
        pytest.xfail(f"known failure: {test_id}")

    string_annos = get_annotations_str(string_obj)
    expected_str = string_annos[key]

    try:
        expected_ast = parse_annotation(expected_str)
    except SyntaxError:
        pytest.skip(f"string form is not parseable: {expected_str!r}")

    expected_dump = ast.dump(expected_ast)

    decompiled = decompile_annotations(obj)
    assert key in decompiled, f"{label}.{key}: missing from decompiled output"

    got_dump = ast.dump(decompiled[key])
    assert got_dump == expected_dump, (
        f"{label}.{key}:\n  expected: {expected_dump}\n  got:      {got_dump}"
    )


# ---------------------------------------------------------------------------
# Standalone mode: summary printout
# ---------------------------------------------------------------------------


def main(paths: list[pathlib.Path] | None = None) -> None:
    cases = _collect_all_cases(paths)
    passed = 0
    failed = 0
    skipped = 0
    xfailed = 0
    errors: list[str] = []

    for label, key, obj, string_obj in cases:
        string_annos = get_annotations_str(string_obj)
        expected_str = string_annos[key]

        try:
            expected_ast = parse_annotation(expected_str)
        except SyntaxError:
            skipped += 1
            continue

        expected_dump = ast.dump(expected_ast)

        try:
            decompiled = decompile_annotations(obj)
        except DecompileError as exc:
            errors.append(f"{label}.{key}: DecompileError: {exc}")
            failed += 1
            continue

        if key not in decompiled:
            errors.append(f"{label}.{key}: missing from decompiled output")
            failed += 1
            continue

        got_dump = ast.dump(decompiled[key])
        if got_dump == expected_dump:
            passed += 1
        elif "<function>" in got_dump:
            xfailed += 1
        else:
            errors.append(
                f"{label}.{key}:\n"
                f"  expected: {expected_dump}\n"
                f"  got:      {got_dump}"
            )
            failed += 1

    print(
        f"Passed: {passed}, Failed: {failed}, "
        f"Skipped: {skipped}, XFailed: {xfailed}"
    )
    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    file_paths = None
    if len(sys.argv) > 1:
        file_paths = [pathlib.Path(p) for p in sys.argv[1:]]
    main(file_paths)
