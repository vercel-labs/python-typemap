"""Test harness: run the annotation decompiler against _annos.py and compare
with string-form ASTs produced via ``from __future__ import annotations``."""

from __future__ import annotations

import ast

from typemap.type_eval._decompile import DecompileError, decompile_annotations


def main() -> None:
    import annotationlib  # noqa: F401

    from tests.dump_annos import (
        collect_functions,
        get_annotations_str,
        load_stringified_copy,
        parse_annotation,
    )
    import tests._annos as mod

    value_fns = collect_functions(mod)
    string_mod = load_stringified_copy()
    string_fns = collect_functions(string_mod)
    string_map = dict(string_fns)

    passed = 0
    failed = 0
    skipped = 0
    errors: list[str] = []

    for qname, func in value_fns:
        string_func = string_map.get(qname)
        if string_func is None:
            skipped += 1
            continue

        string_annos = get_annotations_str(string_func)

        try:
            decompiled = decompile_annotations(func)
        except DecompileError as e:
            errors.append(f"{qname}: DecompileError: {e}")
            failed += 1
            continue

        for key in string_annos:
            expected_str = string_annos[key]
            try:
                expected_ast = parse_annotation(expected_str)
            except SyntaxError:
                skipped += 1
                continue

            expected_dump = ast.dump(expected_ast)

            if key not in decompiled:
                errors.append(f"{qname}.{key}: missing from decompiled output")
                failed += 1
                continue

            got_dump = ast.dump(decompiled[key])
            if got_dump == expected_dump:
                passed += 1
            else:
                errors.append(
                    f"{qname}.{key}:\n"
                    f"  expected: {expected_dump}\n"
                    f"  got:      {got_dump}"
                )
                failed += 1

    print(f"Passed: {passed}, Failed: {failed}, Skipped: {skipped}")
    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
