"""Verify physical-line enforcement and command-line failure reporting."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_file_sizes import REPOSITORY_ROOT, oversized_files


@pytest.mark.parametrize("lines", [0, 499, 500, 501])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_line_limit(tmp_path: Path, lines: int, newline: str) -> None:
    """The boundary counts physical lines, including a final unterminated line."""
    source = tmp_path / "example.py"
    source.write_bytes(newline.join(["# a line"] * lines).encode())
    assert oversized_files(tmp_path) == ([(Path("example.py"), lines)] if lines > 500 else [])


def test_handwritten_sources_and_exclusions(tmp_path: Path) -> None:
    """Check untracked nested code while ignoring dependencies and generated data."""
    for relative in [
        "tests/large.py",
        "scripts/large.sh",
        "custom_components/large.ts",
        ".venv/lib/large.py",
        "environment/pyvenv.cfg",
        "environment/lib/large.py",
        "generated/large.py",
        "vendor/large.py",
        ".git/large.py",
        "data/large.json",
    ]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# line\n" * 501)
    assert set(oversized_files(tmp_path)) == {
        (Path("tests/large.py"), 501),
        (Path("scripts/large.sh"), 501),
        (Path("custom_components/large.ts"), 501),
    }


def test_symlinks_are_not_followed(tmp_path: Path) -> None:
    """Do not scan a linked dependency tree or loop forever through a directory link."""
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "external.py"
    outside.write_text("# line\n" * 501)
    (source / "linked.py").symlink_to(outside)
    (source / "loop").symlink_to(source, target_is_directory=True)
    assert oversized_files(source) == []


def test_cli_reports_failure(tmp_path: Path) -> None:
    """An oversized fixture fails CI with a useful relative filename and line count."""
    (tmp_path / "large.py").write_text("# line\n" * 501)
    result = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "scripts/check_file_sizes.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "large.py: 501 lines (maximum 500)" in result.stdout


def test_repository_fits_limit() -> None:
    """Enforce the limit on the actual checkout as well as synthetic fixtures."""
    assert oversized_files(REPOSITORY_ROOT) == []
