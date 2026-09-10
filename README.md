# indexnowkit — Python monorepo

IndexNow for Python: tell Yandex, Bing, Naver, Seznam and Yep which URLs changed, the moment they change.
The packages are developed here as one [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) and
published to PyPI from this repository by trusted publishing; the PHP family of the same specification is
[indexnowkit/php](https://github.com/indexnowkit/php).

| Package | What | Status |
|---|---|---|
| [`indexnowkit`](packages/indexnowkit) | the core: protocol client, batching, debounce, retry policy, the `@indexnow` rule model, the adapter kit, `check`, the key file for WSGI/ASGI, sitemap reader, pre-flight, history, the `indexnowkit` command line for any site (cron, CI) — zero dependencies; extras `httpx` (async transport) and `testing` (the conformance kits) | wave P step 1 |
| `indexnowkit-django` | Django: signals + `on_commit`, management commands, system checks, key view, `django.tasks` / callable dispatch, history model, sitemaps | step 2 |
| `indexnowkit-sqlalchemy` | SQLAlchemy 2: session events, `SessionStaging`, async sessions | step 3 |
| `indexnowkit-fastapi` | FastAPI / Starlette: middleware, key route, `await asubmit()` after the response | step 4 |
| `indexnowkit-wagtail` | Wagtail: page publish/unpublish hooks | second phase |
| `indexnowkit-flask` | Flask: extension, CLI group, key view | second phase |

Nothing is released yet: the core is tagged together with the Django and SQLAlchemy adapters once both are green
(spec 26 §9.4). Python 3.11 or newer for every package.

## Documentation

[indexnowkit.dev/python](https://indexnowkit.dev/python/) — built from the READMEs and `docs/` of the packages
(`bin/docs-collect` + MkDocs Material). The specification the code follows — the protocol, the rule model, the
conformance scenarios C01–C22 / A01–A21 / S01–S08 / H01–H06 and the JSON schemas of `check --json` and
`status --json` — is [indexnowkit/spec](https://github.com/indexnowkit/spec) (Russian). Russian READMEs exist for every
package (`README.ru.md`).

## Development

No local Python needed: the `bin/` scripts run everything in the development image (`docker/python/Dockerfile`:
`python:<version>-slim` plus [uv](https://docs.astral.sh/uv/), built on first use per `PYTHON_VERSION`). The
workspace is mounted at `/app`; the uv cache and one environment per Python version live under `var/` (git-ignored).

```bash
bin/ci                                   # every package: lock --check, sync, ruff, mypy --strict, pytest + coverage floor, build + wheel smoke
bin/ci indexnowkit                       # one package
PYTHON_VERSION=3.11 bin/ci indexnowkit lowest   # the CI matrix runs 3.11–3.14 (3.15-rc experimental); lowest = the oldest direct dependencies
bin/lint [--fix]                         # ruff check, ruff format --check, mypy (--fix: ruff fixes and formats in place)
bin/test indexnowkit -k normalizer -x    # pytest of one package under coverage, from packages/indexnowkit
bin/coverage-floor indexnowkit [--write] # compare with packages/indexnowkit/tests/coverage-floor.txt (--write records the CI number)
bin/build indexnowkit                    # uv build --no-sources, twine check, install the wheel into a clean environment
bin/config-table indexnowkit [--check]   # regenerate the configuration table of docs/configuration.md from Config.OPTIONS
bin/docs-collect && bin/uv run --group docs mkdocs build --strict -f docs-site/mkdocs.yml   # the docs site
bin/uv add --package indexnowkit-django "django>=5.2,<6.2"   # a dependency of one member; commit uv.lock
bin/python -C packages/indexnowkit -m pytest tests            # the interpreter of the image, in a directory
```

Coverage: `bin/test` leaves `.coverage` in the package; the floor (`tests/coverage-floor.txt`) is the line coverage
the CI cell *3.12 / highest* measured when it was set — record that number, a local run may differ by a statement.
A lower floor is a commit of its own with the reason.

A mock IndexNow server for manual testing ships with the core's `testing` extra (`indexnowkit.testing.mock_server`,
the same contract as the PHP `router.php`: scenarios `ok200`, `pending202`, `forbidden403`, `ratelimit429`, … through
the `X-Mock-Scenario` header, `/_mock/requests`, `MOCK_KEYS`; step 1).

## Releasing

One package at a time, in dependency order (core; then django and sqlalchemy; then fastapi; then wagtail and flask),
each with a `CHANGELOG.md` section `## [x.y.z] — YYYY-MM-DD` and `__version__` set in `src/<module>/__init__.py`:

```bash
bin/tag core 0.1.0                      # push the python/ subtree of the workspace, tag core@0.1.0 here; release.yml publishes indexnowkit to PyPI
bin/pypi-wait core 0.1.0                # poll PyPI before tagging the packages that require the new version
bin/release-notes core 0.1.0 --create   # the GitHub release from the changelog section (release.yml creates it too)
```

Tags are `<short>@<version>`: `core` is `indexnowkit`, every other short name `x` is `indexnowkit-x`. The release
workflow publishes through the environment `pypi-<short>` — the pending trusted publisher of each PyPI project names
this repository, `release.yml` and that environment (one environment per package: PyPI accepts one pending publisher
per repository/workflow/environment triple, and at most three pending publishers at once, so the publishers of the
second-phase packages are registered once the first projects exist). No tokens, no secrets.

## Layout

```
python/
├── packages/
│   ├── indexnowkit/             # the core: src/indexnowkit, tests/ (C01–C22, S01–S08, the property tests), docs/, README EN/RU
│   ├── indexnowkit-django/      # step 2 (A01–A21, H01–H06)
│   ├── indexnowkit-sqlalchemy/  # step 3
│   └── …
├── bin/                         # Docker wrappers: python, uv, ci, lint, test, coverage-floor, build, config-table, docs-collect; release: tag, pypi-wait, release-notes
├── docker/python/               # development image (python:<version>-slim + uv)
├── docs-site/                   # MkDocs template; docs/ and mkdocs.yml are generated
├── pyproject.toml               # the workspace root: members, dev dependencies, ruff and mypy configuration
├── uv.lock
├── CHANGELOG.md                 # monorepo changelog, per wave
├── CONTRIBUTING.md
└── SECURITY.md
```

Each package keeps its own `CHANGELOG.md`; [CHANGELOG.md](CHANGELOG.md) here summarises them per release wave with
the `<short>@<version>` tag format. Contributing: [CONTRIBUTING.md](CONTRIBUTING.md). Security reports:
[SECURITY.md](SECURITY.md). MIT.
