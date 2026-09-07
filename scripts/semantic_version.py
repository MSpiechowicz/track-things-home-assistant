"""Preview or apply a Conventional Commits bump to both integration versions."""

import argparse
import json
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = Path("pyproject.toml")
MANIFEST = Path("custom_components/track_things/manifest.json")
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
SUBJECT = re.compile(r"(?P<type>[a-z]+)(?:\([^\n)]+\))?(?P<breaking>!)?: .+")
BREAKING = re.compile(r"^BREAKING(?: CHANGE|-CHANGE):\s*\S", re.MULTILINE)


@dataclass(frozen=True)
class Release:
    """A release decision derived from synchronized files and reachable history."""

    current: str
    next: str
    level: str
    tag: str | None

    @property
    def changed(self) -> bool:
        """Whether history warrants a new release."""
        return self.current != self.next


def git(root: Path, *args: str) -> str:
    """Execute Git without a shell or interpolation of commit contents."""
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def parse_version(value: str) -> tuple[int, int, int]:
    """Accept stable three-part SemVer only, shared by Python and HA."""
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError(f"Invalid stable semantic version: {value!r}")
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def release_level(messages: list[str]) -> str:
    """Choose the highest Conventional Commits increment across all messages."""
    level = "none"
    for message in messages:
        subject = message.splitlines()[0] if message else ""
        match = SUBJECT.fullmatch(subject)
        if BREAKING.search(message) or (match and match["breaking"]):
            return "major"
        if not match:
            continue
        if match["type"] == "feat":
            level = "minor"
        elif match["type"] in {"fix", "perf", "revert"} and level == "none":
            level = "patch"
    return level


def calculate(root: Path) -> Release:
    """Read versions and commits since the highest reachable stable release tag."""
    current = tomllib.loads((root / PROJECT).read_text())["project"]["version"]
    manifest_version = json.loads((root / MANIFEST).read_text())["version"]
    major, minor, patch = parse_version(current)
    if manifest_version != current:
        raise ValueError("pyproject.toml and manifest.json versions must match")
    if git(root, "rev-parse", "--is-shallow-repository") == "true":
        raise ValueError("Full Git history is required; fetch with fetch-depth: 0")
    tags = [
        tag
        for tag in git(root, "tag", "--merged", "HEAD", "--list", "v*").splitlines()
        if VERSION.fullmatch(tag[1:])
    ]
    tag = max(tags, key=lambda name: parse_version(name[1:]), default=None)
    if tag and tag[1:] != current:
        raise ValueError(f"Stored version {current} does not match reachable release tag {tag}")
    revision = f"{tag}..HEAD" if tag else "HEAD"
    messages = [
        message.strip() for message in git(root, "log", "--format=%B%x00", revision).split("\0")
    ]
    level = release_level(messages)
    if level == "major":
        major, minor, patch = major + 1, 0, 0
    elif level == "minor":
        minor, patch = minor + 1, 0
    elif level == "patch":
        patch += 1
    return Release(current, f"{major}.{minor}.{patch}", level, tag)


def apply(root: Path, release: Release) -> None:
    """Update exactly the two version declarations, preserving unrelated TOML."""
    if not release.changed:
        return
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Commit tracked changes before applying a version bump")
    project = (root / PROJECT).read_text()
    section = re.search(r"(?ms)^\[project\]\s*\n(?P<body>.*?)(?=^\[|\Z)", project)
    if section is None:
        raise ValueError("Missing [project] section")
    body, count = re.subn(
        r"(?m)^(version\s*=\s*)([\"']).*?\2",
        lambda match: f'{match[1]}"{release.next}"',
        section["body"],
    )
    if count != 1:
        raise ValueError("Expected exactly one project.version declaration")
    updated = project[: section.start("body")] + body + project[section.end("body") :]
    if tomllib.loads(updated)["project"]["version"] != release.next:
        raise ValueError("Updated TOML did not contain the expected version")
    manifest = json.loads((root / MANIFEST).read_text())
    manifest["version"] = release.next
    (root / PROJECT).write_text(updated)
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    """Default to a read-only preview; only CI explicitly requests --apply."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    release = calculate(ROOT)
    if args.apply:
        apply(ROOT, release)
    print(f"{release.level}: {release.current} -> {release.next}")
    if args.github_output:
        with args.github_output.open("a") as output:
            output.write(f"changed={str(release.changed).lower()}\nversion={release.next}\n")


if __name__ == "__main__":
    main()
