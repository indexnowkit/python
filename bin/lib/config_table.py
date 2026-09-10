"""Render the configuration table of a package from its ``Config`` class (run through bin/config-table).

The contract with the package (spec 20 §3.2, §6): the module ``<module>.config`` exposes ``Config`` with
``OPTIONS`` (the dotted keys, in the order of the table) and a zero-argument constructor whose ``to_mapping()``
returns the nested mapping of resolved values; ``ENV_PREFIX`` (default ``INDEXNOW_``) names the variables. Each row:
the key, the environment variable (``INDEXNOW_<KEY_PATH>``), the default. Descriptions stay hand-written in the
prose around the table; the table is the fact the code guarantees.

Usage: python bin/lib/config_table.py <package> [--check]
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

START = "<!-- config-table:start -->"
END = "<!-- config-table:end -->"
ROOT = Path(__file__).resolve().parent.parent.parent


def resolve(mapping: Any, key: str) -> Any:
    value = mapping
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def render_default(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "`true`" if value else "`false`"
    if isinstance(value, (list, tuple)):
        return "`" + ",".join(str(item) for item in value) + "`" if value else "(empty)"
    if isinstance(value, dict):
        return "`" + json.dumps(value, sort_keys=True) + "`" if value else "(empty)"
    return "`" + str(value) + "`"


def render(config_module: Any) -> str:
    config_class = config_module.Config
    prefix = getattr(config_class, "ENV_PREFIX", "INDEXNOW_")
    defaults = config_class().to_mapping()
    rows = ["| Key | Environment variable | Default |", "|---|---|---|"]
    for key in config_class.OPTIONS:
        env = prefix + key.upper().replace(".", "_")
        rows.append(f"| `{key}` | `{env}` | {render_default(resolve(defaults, key))} |")
    return "\n".join(rows) + "\n"


def splice(text: str, table: str) -> str:
    start, end = text.find(START), text.find(END)
    if start < 0 or end < 0 or end < start:
        raise SystemExit(f"config-table: the markers {START} / {END} are missing or out of order")
    return text[: start + len(START)] + "\n" + table + text[end:]


def main(argv: list[str]) -> int:
    if not argv or len(argv) > 2 or (len(argv) == 2 and argv[1] != "--check"):
        print(__doc__, file=sys.stderr)
        return 2
    package, check = argv[0], len(argv) == 2
    module_name = package.replace("-", "_") + ".config"
    try:
        config_module = importlib.import_module(module_name)
    except ImportError as error:
        print(f"config-table: cannot import {module_name}: {error}", file=sys.stderr)
        return 1
    doc = ROOT / "packages" / package / "docs" / "configuration.md"
    if not doc.is_file():
        print(f"config-table: no {doc.relative_to(ROOT)}", file=sys.stderr)
        return 1
    current = doc.read_text(encoding="utf-8")
    expected = splice(current, render(config_module))
    if check:
        if current != expected:
            rel = doc.relative_to(ROOT)
            print(f"config-table: {rel} is out of date; run bin/config-table {package}", file=sys.stderr)
            return 1
        print(f"config-table: {doc.relative_to(ROOT)} matches {module_name}.Config.OPTIONS")
        return 0
    doc.write_text(expected, encoding="utf-8")
    print(f"config-table: {doc.relative_to(ROOT)} regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
