"""Exercise version calculation and file updates against disposable Git history."""

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from scripts.semantic_version import (
    MANIFEST,
    PROJECT,
    apply,
    calculate,
    parse_version,
    release_level,
)


def git(root: Path, *args: str) -> str:
    """Keep temporary test commits independent of user signing/identity settings."""
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Version tests",
            "-c",
            "user.email=version-tests@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a clean repository with matching initial version files."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (tmp_path / PROJECT).write_text(
        '[project]\nname = "example"\nversion = "0.1.0" # keep comment\n'
        '\n[tool.example]\nversion = "unchanged"\n'
    )
    (tmp_path / MANIFEST).parent.mkdir(parents=True)
    (tmp_path / MANIFEST).write_text('{"domain": "track_things", "version": "0.1.0"}\n')
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "chore: initial files")
    return tmp_path


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("feat: calendar", "minor"),
        ("feat(voice): support Polish", "minor"),
        ("fix: timeout", "patch"),
        ("perf(api): cache", "patch"),
        ("revert: undo regression", "patch"),
        ("feat!: change account model", "major"),
        ("fix(api)!: change format", "major"),
        ("chore: migration\n\nBREAKING CHANGE: drop old config", "major"),
        ("refactor: migration\n\nBREAKING-CHANGE: old config removed", "major"),
        ("docs: README", "none"),
        ("chore(release): v0.2.0 [skip ci]", "none"),
        ("Merge pull request #24", "none"),
        ("test: feat: is an example", "none"),
    ],
)
def test_conventional_messages(message: str, expected: str) -> None:
    assert release_level([message]) == expected


def test_highest_increment_wins() -> None:
    assert release_level(["fix: a", "feat: b", "perf: c"]) == "minor"
    assert release_level(["feat: a", "fix!: b", "feat: c"]) == "major"


@pytest.mark.parametrize("value", ["01.2.3", "v1.2.3", "1.2", "1.2.3-rc1", "1.2.3\n"])
def test_reject_invalid_stable_version(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid stable"):
        parse_version(value)


@pytest.mark.parametrize(
    ("message", "version"),
    [("fix: a", "0.1.1"), ("feat: a", "0.2.0"), ("feat!: a", "1.0.0")],
)
def test_initial_bump_and_synced_files(repository: Path, message: str, version: str) -> None:
    git(repository, "commit", "--allow-empty", "-m", message)
    before = (repository / PROJECT).read_text()
    release = calculate(repository)
    assert release.tag is None
    assert release.next == version
    assert (repository / PROJECT).read_text() == before  # preview does not write
    apply(repository, release)
    project = tomllib.loads((repository / PROJECT).read_text())
    manifest = json.loads((repository / MANIFEST).read_text())
    assert project["project"]["version"] == manifest["version"] == version
    assert project["tool"]["example"]["version"] == "unchanged"
    assert "# keep comment" in (repository / PROJECT).read_text()
    assert manifest["domain"] == "track_things"
    assert set(git(repository, "diff", "--name-only").splitlines()) == {
        str(PROJECT),
        str(MANIFEST),
    }


def test_release_rerun_and_only_new_commits(repository: Path) -> None:
    git(repository, "commit", "--allow-empty", "-m", "feat: first feature")
    apply(repository, calculate(repository))
    git(repository, "add", ".")
    git(repository, "commit", "-m", "chore(release): v0.2.0 [skip ci]")
    git(repository, "tag", "-a", "v0.2.0", "-m", "Release v0.2.0")
    assert not calculate(repository).changed
    git(repository, "commit", "--allow-empty", "-m", "docs: clarify setup")
    apply(repository, calculate(repository))
    assert git(repository, "status", "--porcelain") == ""
    git(repository, "commit", "--allow-empty", "-m", "fix: one bug")
    assert calculate(repository).next == "0.2.1"


def test_ignore_unreachable_and_nonrelease_tags(repository: Path) -> None:
    git(repository, "tag", "test-only")
    git(repository, "tag", "v8.0.0-rc1")
    git(repository, "switch", "-c", "unmerged")
    git(repository, "commit", "--allow-empty", "-m", "feat!: unrelated feature")
    git(repository, "tag", "v9.0.0")
    git(repository, "switch", "main")
    assert not calculate(repository).changed
    assert calculate(repository).tag is None


def test_reject_version_drift(repository: Path) -> None:
    (repository / MANIFEST).write_text('{"version": "0.2.0"}')
    with pytest.raises(ValueError, match="versions must match"):
        calculate(repository)


def test_reject_tag_drift(repository: Path) -> None:
    git(repository, "tag", "v0.2.0")
    with pytest.raises(ValueError, match="does not match reachable"):
        calculate(repository)


def test_reject_dirty_apply(repository: Path) -> None:
    git(repository, "commit", "--allow-empty", "-m", "fix: change")
    (repository / PROJECT).write_text((repository / PROJECT).read_text() + "# edit\n")
    with pytest.raises(ValueError, match="Commit tracked changes"):
        apply(repository, calculate(repository))


def test_reject_shallow_history(repository: Path, tmp_path: Path) -> None:
    # file:// ensures Git honors --depth for a local clone.
    clone = tmp_path / "shallow"
    git(repository, "clone", "--depth", "1", repository.as_uri(), str(clone))
    with pytest.raises(ValueError, match="Full Git history"):
        calculate(clone)


def test_cli_preview_apply_and_action_outputs(repository: Path) -> None:
    """Exercise the same entry point and output file used by GitHub Actions."""
    script = repository / "scripts/semantic_version.py"
    script.parent.mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts/semantic_version.py", script)
    git(repository, "add", ".")
    git(repository, "commit", "-m", "feat: release tooling")
    preview = subprocess.run(
        [sys.executable, str(script)], cwd=repository, check=True, capture_output=True, text=True
    )
    assert "minor: 0.1.0 -> 0.2.0" in preview.stdout
    assert git(repository, "status", "--porcelain") == ""
    output = repository / ".git/action-output"
    subprocess.run(
        [sys.executable, str(script), "--apply", "--github-output", str(output)],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    assert output.read_text() == "changed=true\nversion=0.2.0\n"
    assert json.loads((repository / MANIFEST).read_text())["version"] == "0.2.0"
    assert tomllib.loads((repository / PROJECT).read_text())["project"]["version"] == "0.2.0"
