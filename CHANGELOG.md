# Changelog

All notable changes to the Python packages are documented here, newest release wave first. Tags: `<short>@<version>`
(`core@0.1.0` for `indexnowkit`, `django@0.1.0` for `indexnowkit-django`, …). Per-package detail (and the migration
notes for every breaking change) lives in each package's own changelog.

## Unreleased — wave P

**Step 0 (2026-09-10) — the workspace**: `python/` next to `php/` in the private workspace, mirrored here; one uv
workspace with the packages under `packages/*`, the Docker wrappers of `bin/` over `python:<version>-slim` + uv (no
local Python), the CI matrix of spec 26 §5 (3.11–3.14, 3.15 experimental, lowest-direct on 3.11), the release by
trusted publishing on a `<short>@<version>` tag with one environment per package (`pypi-core` … `pypi-wagtail`), the
docs site at [indexnowkit.dev/python](https://indexnowkit.dev/python/), and the canonical `check.schema.json` /
`status.schema.json` copied from the cross-language specification. The core `indexnowkit` (spec 20) is step 1; nothing is
released before the Django and SQLAlchemy adapters are green (spec 26 §9.4).
