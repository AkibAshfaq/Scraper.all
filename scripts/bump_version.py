"""Bump the project version and roll the changelog.

Usage (on a release/vX.Y.Z or hotfix/vX.Y.Z branch):

    python scripts/bump_version.py 0.2.0
    python scripts/bump_version.py minor        # or major / patch

Updates webscraper/__init__.py and moves the CHANGELOG "Unreleased" entries
under a new dated "X.Y.Z" heading. Commit, tagging and merging stay manual.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "webscraper" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
VERSION_RE = re.compile(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', re.M)
UNRELEASED = "## [Unreleased]"


def current_version() -> tuple[int, int, int]:
    match = VERSION_RE.search(INIT.read_text(encoding="utf-8"))
    if not match:
        sys.exit(f"Could not find __version__ in {INIT}")
    return tuple(int(p) for p in match.groups())  # type: ignore[return-value]


def next_version(current: tuple[int, int, int], spec: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if spec == "major":
        return major + 1, 0, 0
    if spec == "minor":
        return major, minor + 1, 0
    if spec == "patch":
        return major, minor, patch + 1
    if not re.fullmatch(r"\d+\.\d+\.\d+", spec):
        sys.exit(f"Version must be X.Y.Z or major/minor/patch, got {spec!r}")
    new = tuple(int(p) for p in spec.split("."))
    if new <= current:
        sys.exit(f"New version {spec} must be greater than {'.'.join(map(str, current))}")
    return new  # type: ignore[return-value]


def roll_changelog(version: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    if UNRELEASED not in text:
        sys.exit(f"{CHANGELOG.name} has no '{UNRELEASED}' section")
    heading = f"{UNRELEASED}\n\n## [{version}] - {date.today().isoformat()}"
    CHANGELOG.write_text(text.replace(UNRELEASED, heading, 1), encoding="utf-8")


def main(argv: list[str]) -> None:
    if len(argv) != 1:
        sys.exit(__doc__)
    old = current_version()
    new = ".".join(map(str, next_version(old, argv[0])))
    INIT.write_text(
        VERSION_RE.sub(f'__version__ = "{new}"', INIT.read_text(encoding="utf-8")), encoding="utf-8"
    )
    roll_changelog(new)
    print(f"{'.'.join(map(str, old))} -> {new}")
    print("Next: commit, merge into main, `git tag -a v{0} -m v{0}`, merge back into develop.".format(new))


if __name__ == "__main__":
    main(sys.argv[1:])
