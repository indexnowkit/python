"""The conformance identifiers are a cross-language contract (spec 03, 17 §7): C01–C22 (the core suite here), A01–A21
with A05b/A05c/A10b and S01–S08 (the kits of ``indexnowkit.testing.conformance``), H01–H06 (every framework adapter
of the workspace). Every id is in a test name (``test_c01_…``), each exactly once per suite, none missing, none beyond
the frozen range. Which packages are framework adapters is read off the file system, so a new one cannot land without
its H ids. Kits that do not exist yet (the steps after the core) are skipped."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2]
WORKSPACE = PACKAGE.parent
KITS = PACKAGE / "src" / "indexnowkit" / "testing" / "conformance"
NAME = re.compile(r"def (test_[a-z0-9_]+)")
ID = re.compile(r"(?<![a-z0-9])([cash])(\d{2})([bc]?)(?![a-z0-9])")
LIBRARIES = {"indexnowkit"}


def ids(directory: Path, prefix: str) -> list[str]:
    """The ids of every Python file under ``directory``, in file order (duplicates kept)."""
    found: list[str] = []
    for file in sorted(directory.rglob("*.py")):
        if file.name == "test_ids.py":  # this file names the ranges in its own test names
            continue
        for name in NAME.findall(file.read_text(encoding="utf-8")):
            for match in ID.finditer(name):
                if match.group(1) == prefix:
                    found.append(f"{prefix.upper()}{match.group(2)}{match.group(3)}")
    return found


def expected(prefix: str, count: int, extra: tuple[str, ...] = ()) -> list[str]:
    return sorted([f"{prefix}{n:02d}" for n in range(1, count + 1)] + list(extra))


def test_the_core_suite_defines_c01_to_c22_once_each() -> None:
    found = ids(PACKAGE / "tests" / "conformance", "c")
    assert sorted(found) == expected("C", 22)
    assert len(set(found)) == len(found)


def test_the_kits_define_a01_to_a21_and_s01_to_s08_once_each() -> None:
    if not KITS.is_dir():
        pytest.skip("the conformance kits are not written yet (wave P step 1, module testing)")
    a_ids, s_ids, c_ids = ids(KITS, "a"), ids(KITS, "s"), ids(KITS, "c")
    assert sorted(a_ids) == expected("A", 21, ("A05b", "A05c", "A10b"))
    assert sorted(s_ids) == expected("S", 8)
    for c_id in c_ids:
        assert c_id in expected("C", 22), f"{c_id} is beyond the frozen core range"
    assert len(set(a_ids + s_ids + c_ids)) == len(a_ids + s_ids + c_ids)


def adapters() -> list[Path]:
    """Every ``packages/*`` whose ``pyproject.toml`` depends on ``indexnowkit`` and that has a ``tests/`` directory."""
    found = []
    for manifest in sorted(WORKSPACE.glob("*/pyproject.toml")):
        package = manifest.parent
        if package.name in LIBRARIES or not (package / "tests").is_dir():
            continue
        dependencies = tomllib.loads(manifest.read_text(encoding="utf-8")).get("project", {}).get("dependencies", [])
        if any(re.match(r"^indexnowkit\b", dependency) for dependency in dependencies):
            found.append(package)
    return found


def test_every_framework_adapter_defines_h01_to_h06_once_each() -> None:
    found = adapters()
    if not found:
        pytest.skip("no adapter next door yet (wave P steps 2–6)")
    for adapter in found:
        h_ids = ids(adapter / "tests", "h")
        assert len(set(h_ids)) == len(h_ids), f"{adapter.name}: an H id is defined twice"
        for h_id in expected("H", 6):
            assert h_id in h_ids, f"{adapter.name} lacks {h_id}"
        for h_id in h_ids:
            assert int(h_id[1:3]) <= 6, f"{adapter.name}: {h_id} is beyond the frozen range"
