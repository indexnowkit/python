"""``python -m indexnowkit`` — the same entry point as the ``indexnowkit`` console script."""

import sys

from indexnowkit.cli import main

if __name__ == "__main__":
    sys.exit(main())
