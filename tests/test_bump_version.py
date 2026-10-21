from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bump_version.py"
spec = importlib.util.spec_from_file_location("bump_version", SCRIPT)
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)


@pytest.mark.parametrize(
    ("arg", "expected"),
    [("patch", (1, 2, 4)), ("minor", (1, 3, 0)), ("major", (2, 0, 0)), ("1.10.0", (1, 10, 0))],
)
def test_next_version(arg, expected):
    assert bump.next_version((1, 2, 3), arg) == expected


@pytest.mark.parametrize("arg", ["1.2.3", "1.0.0", "1.2", "v1.3.0"])
def test_next_version_rejects_bad_input(arg):
    with pytest.raises(SystemExit):
        bump.next_version((1, 2, 3), arg)


def test_bump_updates_init_and_changelog(tmp_path, monkeypatch):
    init = tmp_path / "__init__.py"
    init.write_text('"""doc"""\n\n__version__ = "0.1.0"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Unreleased]\n\n### Added\n- thing\n", encoding="utf-8")
    monkeypatch.setattr(bump, "INIT", init)
    monkeypatch.setattr(bump, "CHANGELOG", changelog)

    bump.main(["minor"])

    assert '__version__ = "0.2.0"' in init.read_text(encoding="utf-8")
    text = changelog.read_text(encoding="utf-8")
    assert text.index("## [Unreleased]") < text.index("## [0.2.0] - ") < text.index("- thing")
