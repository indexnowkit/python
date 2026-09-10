"""The ``indexnowkit`` command line (spec 20 §3.12).

Step 0 of wave P ships the entry point and ``--version`` only, so the console script of the wheel is provable in the
build smoke; the commands (``check``, ``config``, ``submit``, ``sitemap``, ``key generate``, ``key file``, ``history``,
``status``) arrive with the ``console`` and ``cli`` modules of step 1.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from indexnowkit import __version__

PROG = "indexnowkit"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="IndexNow for any site: check the setup, submit URLs, read a sitemap, manage the key file.",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
