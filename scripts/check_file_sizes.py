"""Reject handwritten source/test files exceeding 500 physical lines."""

import argparse
import os
from pathlib import Path

MAX_LINES = 500
SOURCE_SUFFIXES = {".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".css", ".sh"}
EXCLUDED_DIRECTORIES = {
    ".git",
    ".agents",
    ".codex",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "vendor",
    "generated",
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def oversized_files(root: Path) -> list[tuple[Path, int]]:
    """Inspect source files, including untracked files, without following symlinks."""
    violations = []
    for directory, children, names in os.walk(root, followlinks=False):
        children[:] = sorted(
            name
            for name in children
            if name not in EXCLUDED_DIRECTORIES
            and not name.startswith(".venv")
            and not name.endswith(".egg-info")
            and not (Path(directory) / name / "pyvenv.cfg").exists()
        )
        for name in sorted(names):
            path = Path(directory) / name
            if path.is_symlink() or path.suffix not in SOURCE_SUFFIXES:
                continue
            with path.open(encoding="utf-8") as source:
                count = sum(1 for _ in source)
            if count > MAX_LINES:
                violations.append((path.relative_to(root), count))
    return violations


def main() -> int:
    """Print violations and return a failing exit code when the limit is exceeded."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error(f"not a directory: {args.root}")
    try:
        violations = oversized_files(args.root.resolve())
    except (OSError, UnicodeError) as error:
        parser.exit(2, f"Cannot inspect source files: {error}\n")
    for path, count in violations:
        print(f"{path}: {count} lines (maximum {MAX_LINES})")
    if violations:
        return 1
    print(f"All handwritten source/test files are at most {MAX_LINES} lines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
