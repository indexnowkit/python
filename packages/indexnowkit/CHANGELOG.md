# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: SemVer; until 1.0 minor versions may
contain breaking changes, listed under "Changed". What the compatibility promise covers: [docs/bc.md](docs/bc.md).

## [Unreleased]

### Added

- The package skeleton (wave P step 0, spec 26 §3): `indexnowkit.__version__`, the `indexnowkit` console script and
  `python -m indexnowkit` with `--version`, `py.typed`, the extras `httpx` and `testing`, and the canonical
  `docs/check.schema.json` / `docs/status.schema.json` of the `check --json` and `status --json` reports (copies of
  the cross-language contract in `indexnowkit/spec`, kept in sync by the workspace).
