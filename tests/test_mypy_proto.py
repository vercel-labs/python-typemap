"""Run mypy on each test file that doesn't have # SKIP MYPY."""

import os
import pathlib
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).parent.parent

# Set MYPY_SOURCE_DIR to use a local mypy source checkout.
_mypy_source = os.environ.get("MYPY_SOURCE_DIR")
MYPY_SOURCE_DIR = pathlib.Path(_mypy_source).resolve() if _mypy_source else None


# Files that depend on the 4-arg Param shape, which the pinned
# mypy-typemap stub fork hasn't been updated for yet.
_XFAIL_PARAM_D = {"test_dataclass_like", "test_fastapilike_2"}


def _collect_mypy_test_files():
    """Collect test files that don't have # SKIP MYPY."""
    tests_dir = pathlib.Path(__file__).parent
    for path in sorted(tests_dir.glob("test_*.py")):
        if path.name in ("test_cqa.py", "test_mypy_proto.py"):
            continue
        text = path.read_text()
        if "# SKIP MYPY" not in text:
            marks = []
            if path.stem in _XFAIL_PARAM_D:
                marks.append(
                    pytest.mark.xfail(
                        reason="mypy-typemap stubs still have 3-arg Param",
                        strict=True,
                    )
                )
            yield pytest.param(path, id=path.stem, marks=marks)


@pytest.mark.parametrize("test_file", _collect_mypy_test_files())
def test_mypy(test_file):
    """Test that individual test files pass mypy."""
    env = None
    if MYPY_SOURCE_DIR:
        env = {**os.environ, "PYTHONPATH": str(MYPY_SOURCE_DIR)}
    cmd = [
        sys.executable,
        "-m",
        "mypy",
        "--config-file",
        str(PROJECT_ROOT / "pyproject.toml"),
        str(test_file),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env=env,
    )

    if result.returncode != 0:
        output = result.stdout
        if result.stderr:
            output += "\n\n" + result.stderr
        pytest.fail(
            f"mypy failed on {test_file.name}:\n{output}", pytrace=False
        )
