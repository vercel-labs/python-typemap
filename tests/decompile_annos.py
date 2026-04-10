"""Test harness: run the annotation decompiler against _annos.py and compare
with string-form ASTs produced via ``from __future__ import annotations``.

Works both as ``python -m tests.decompile_annos`` (summary printout) and
via ``pytest tests/decompile_annos.py`` (one test case per annotation).
"""

from __future__ import annotations

import ast
import types

import annotationlib  # noqa: F401
import pytest

import tests._annos as mod
from tests.dump_annos import (
    collect_functions,
    get_annotations_str,
    load_stringified_copy,
    parse_annotation,
)
from typemap.type_eval._decompile import DecompileError, decompile_annotations


def _collect_cases() -> (
    list[tuple[str, str, types.FunctionType, types.FunctionType]]
):
    """Build (qname, key, value_func, string_func) for every annotation."""
    value_fns = collect_functions(mod)
    string_mod = load_stringified_copy()
    string_map = dict(collect_functions(string_mod))

    cases: list[tuple[str, str, types.FunctionType, types.FunctionType]] = []
    for qname, func in value_fns:
        string_func = string_map.get(qname)
        if string_func is None:
            continue
        string_annos = get_annotations_str(string_func)
        for key in string_annos:
            cases.append((qname, key, func, string_func))
    return cases


_CASES = _collect_cases()


def _case_id(case: tuple[str, str, types.FunctionType, types.FunctionType]) -> str:
    qname, key, _, _ = case
    return f"{qname}.{key}"


@pytest.mark.parametrize("case", _CASES, ids=[_case_id(c) for c in _CASES])
def test_decompile_annotation(
    case: tuple[str, str, types.FunctionType, types.FunctionType],
) -> None:
    qname, key, func, string_func = case
    string_annos = get_annotations_str(string_func)
    expected_str = string_annos[key]

    try:
        expected_ast = parse_annotation(expected_str)
    except SyntaxError:
        pytest.skip(f"string form is not parseable: {expected_str!r}")

    expected_dump = ast.dump(expected_ast)

    decompiled = decompile_annotations(func)
    assert key in decompiled, f"{qname}.{key}: missing from decompiled output"

    got_dump = ast.dump(decompiled[key])
    if got_dump != expected_dump:
        # Check if this is the known lambda-in-Annotated case
        if "<function>" in got_dump:
            pytest.xfail("lambda/function objects in annotations cannot be decompiled")
        assert got_dump == expected_dump, (
            f"{qname}.{key}:\n  expected: {expected_dump}\n  got:      {got_dump}"
        )


# ---------------------------------------------------------------------------
# Standalone mode: summary printout
# ---------------------------------------------------------------------------


def main() -> None:
    passed = 0
    failed = 0
    skipped = 0
    xfailed = 0
    errors: list[str] = []

    for qname, key, func, string_func in _CASES:
        string_annos = get_annotations_str(string_func)
        expected_str = string_annos[key]

        try:
            expected_ast = parse_annotation(expected_str)
        except SyntaxError:
            skipped += 1
            continue

        expected_dump = ast.dump(expected_ast)

        try:
            decompiled = decompile_annotations(func)
        except DecompileError as e:
            errors.append(f"{qname}.{key}: DecompileError: {e}")
            failed += 1
            continue

        if key not in decompiled:
            errors.append(f"{qname}.{key}: missing from decompiled output")
            failed += 1
            continue

        got_dump = ast.dump(decompiled[key])
        if got_dump == expected_dump:
            passed += 1
        elif "<function>" in got_dump:
            xfailed += 1
        else:
            errors.append(
                f"{qname}.{key}:\n"
                f"  expected: {expected_dump}\n"
                f"  got:      {got_dump}"
            )
            failed += 1

    print(f"Passed: {passed}, Failed: {failed}, Skipped: {skipped}, XFailed: {xfailed}")
    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
