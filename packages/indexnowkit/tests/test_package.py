"""The package imports, carries a PEP 440 version and answers ``--version`` — the step 0 smoke of wave P."""

from __future__ import annotations

import re
import subprocess
import sys

import indexnowkit
from indexnowkit.cli import main

PEP440 = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.dev\d+)?$")


def test_version_is_pep440() -> None:
    assert PEP440.match(indexnowkit.__version__), indexnowkit.__version__


def test_version_option_prints_the_version(capsys: object) -> None:
    try:
        main(["--version"])
    except SystemExit as exit_:  # argparse's version action exits 0 after printing
        assert exit_.code == 0
    else:
        raise AssertionError("--version must exit")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out.strip() == f"indexnowkit {indexnowkit.__version__}"


def test_module_entry_point_matches_the_console_script() -> None:
    result = subprocess.run(  # the interpreter running the tests, fixed arguments
        [sys.executable, "-m", "indexnowkit", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"indexnowkit {indexnowkit.__version__}"


def test_without_arguments_prints_help_and_exits_zero(capsys: object) -> None:
    assert main([]) == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out.startswith("usage: indexnowkit")
