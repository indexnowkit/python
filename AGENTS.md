# Working in this repository (for coding agents and humans alike)

This is the uv workspace of the `indexnowkit` Python packages: `packages/{indexnowkit,indexnowkit-django,indexnowkit-sqlalchemy,indexnowkit-fastapi,indexnowkit-flask,indexnowkit-wagtail}`
(the adapters arrive step by step; see the README). Every package is published to PyPI from this repository by
trusted publishing; issues and pull requests live here. The specification the code follows is `docs/spec/` of the
private workspace this repository is mirrored from, public as [indexnowkit/spec](https://github.com/indexnowkit/spec) —
the README and `docs/*.md` of each package are the public contract. The PHP family ([indexnowkit/php](https://github.com/indexnowkit/php))
is the reference implementation: the behaviour, the configuration keys, the `check` codes, the log and error texts
and the conformance ids are the same; the idioms are Python's (spec 26 §2).

## Tooling: no local Python

Everything runs in Docker through `bin/*`:

| Command | What |
|---|---|
| `bin/ci [package] [flavour]` | the CI pipeline: `uv lock --check`, `uv sync --all-packages`, ruff check + format check, `mypy --strict`, pytest under coverage against `tests/coverage-floor.txt`, `config-table --check`, `uv build --no-sources`, twine check, the wheel in a clean environment (`highest` = the committed lock, `lowest` = the oldest direct dependencies) |
| `bin/lint [--fix]` | ruff and mypy over the whole workspace |
| `bin/test <package> [pytest args]` | pytest of one package (`bin/test indexnowkit -k c05 -x`) |
| `bin/coverage-floor <package> [--write]` | compare with the floor; `--write` records the CI number |
| `bin/build <package>` | sdist + wheel without workspace sources, twine, wheel smoke |
| `bin/config-table <package> [--check]` | the generated table of `docs/configuration.md` from `Config.OPTIONS` |
| `bin/uv …` · `bin/python …` | uv and the interpreter of the image (`-v 3.11` or `PYTHON_VERSION=3.11`, `-C packages/<pkg>`) |
| `bin/docs-collect` | the docs site sources (`docs-site/docs`, `mkdocs.yml`) |
| `bin/tag <short> <version>` · `bin/pypi-wait` · `bin/release-notes` | release tooling (maintainers) |

`PYTHON_VERSION=3.11 bin/ci indexnowkit lowest` switches the Python version (matrix 3.11–3.14; `3.15-rc` experimental).

## Before you change code

- Read the package README and `docs/*.md` for the area; the behaviour is specified there, not only in tests.
- Adapter behaviour is covered by the shared conformance kits of `indexnowkit.testing.conformance` (ids C01–C22,
  A01–A21, S01–S08, H01–H06): a change in an adapter must keep them green unchanged. The core never depends on an
  adapter; `indexnowkit.testing` imports pytest lazily, so the core has no test dependency at runtime.
- The core is framework-agnostic: nothing under `packages/indexnowkit/src` imports Django, SQLAlchemy, Starlette,
  Flask or Wagtail; the command bodies are `indexnowkit.console`, the conformance kits `indexnowkit.testing.conformance`.
- Zero dependencies in the core (`urllib`, `xml.etree`, `sqlite3`, `argparse`, `html.parser`); `httpx` and `pytest`
  are extras. No `requests`, `pydantic`, `click`, `defusedxml`.
- Keys are never logged or printed in full: `KeyValidator.mask()`.
- Error and log texts follow one rule: the fact, what is allowed, how to fix it. Texts are the PHP ones one to one.
- Nothing raises out of a hook (`ObjectChangeHandler`, `GuardedUrlResolver`, dispatchers, debounce stores): log and continue.
- Python ≥ 3.11: `StrEnum`, `Self`, `tomllib`, PEP 604 unions — but no PEP 695 (`class Foo[T]`, `type X = …`) until
  the minimum is 3.12. `mypy --strict` without `type: ignore` (an error code and a reason when unavoidable); ruff
  with the `S` rules; modules under 400 lines.

## Gates before a commit

1. `bin/ci <package>` green (and `lowest` when dependencies changed); `uv.lock` committed with any dependency change.
2. Tests for the change; new adapter behaviour named after its conformance id when one applies (`test_a05_…`).
3. `CHANGELOG.md` of the package under "Unreleased" for anything user-visible; breaking changes under "Changed" with
   the migration.
4. README EN and RU plus `docs/*.md` updated when configuration, commands or extension points changed;
   `bin/config-table <package>` after a configuration key change.

## Commits and pull requests

Conventional commits (`feat(core): …`, `fix(django): …`, `docs: …`, `build(python): …`, `ci: …`), one package per PR
when possible, no attribution trailers. The PR template lists the checklist.

## Where things are

- Configuration keys: `Config.OPTIONS` (core), `SitemapConfig.OPTIONS`, `VerifyConfig.OPTIONS`, `HistoryConfig.OPTIONS`;
  the adapters add their own through `adapter.ConfigFactory(owned_options=…)`. Unknown keys warn at boot.
- Commands: `console.Definitions` declares arguments and options once (argparse); the adapters render them
  (Django `add_arguments`, Flask click).
- Checks (`check`): `check.Check` implementations registered per adapter; codes in `docs/check-codes.md`.
- Tests: `tests/unit`, `tests/integration` (the mock server), `tests/conformance` (`test_core.py`, `test_ids.py`),
  `tests/property` (hypothesis), `tests/readme`.
