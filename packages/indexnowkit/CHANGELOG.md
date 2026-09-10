# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: SemVer; until 1.0 minor versions may
contain breaking changes, listed under "Changed". What the compatibility promise covers: [docs/bc.md](docs/bc.md).

## [Unreleased]

### Added

- **The protocol layer of the core** (wave P step 1, spec 20 §3.2–3.8): `Engine`, `Result`/`Reason`/`ResultStatus`, the URL
  normalizer and the canonical form of `normalizer.*`, `Config` (the 42 keys of the family, `from_mapping`/`from_env`/
  `mapping_from_env`/`to_mapping`/`replace`/`unknown_options`), the keys (`KeyValidator`, `generate_key`, `StaticKeyProvider`,
  `KeyFileResponder`), `http` (`UrllibTransport`, `LazyTransport`, the `httpx` extra), `Client` with the 403 counter,
  `Submitter`, the debounce stores, `TokenBucket`, `RetryPolicy`/`RetryingSubmitter`/`WorkerOutcome`, `Collector`, the
  dispatchers (`sync`, `none`, `thread`, `asyncio`, callable), the submission store contract, the testing doubles and the
  mock IndexNow server with pytest fixtures. Conformance C01–C22 green.
- The package skeleton (wave P step 0, spec 26 §3): `indexnowkit.__version__`, the `indexnowkit` console script and
  `python -m indexnowkit` with `--version`, `py.typed`, the extras `httpx` and `testing`, and the canonical
  `docs/check.schema.json` / `docs/status.schema.json` of the `check --json` and `status --json` reports (copies of
  the cross-language contract in `indexnowkit/spec`, kept in sync by the workspace).
