# Contributing

- No local Python needed. `bin/ci <package>` runs the package's pipeline in Docker (`uv lock --check`, sync, ruff,
  mypy --strict, pytest under coverage against the floor, the build without workspace sources and the wheel smoke);
  `bin/lint --fix` lets ruff fix and format. See the README for the step-by-step commands and `PYTHON_VERSION=3.11`
  to switch the Python version.
- One uv workspace: the root `pyproject.toml` holds the dev dependencies and the tool configuration, every package
  under `packages/<name>` its own `pyproject.toml`, and there is one `uv.lock`. A new dependency goes into the package's
  `pyproject.toml` (`bin/uv add --package <name> <dep>`), a new dev tool into the root `dev` group; commit the lock.
- Every change needs tests. Adapter behaviour is specified in the cross-language `docs/spec/03-conformance.md` of
  [indexnowkit/spec](https://github.com/indexnowkit/spec); name tests after the scenario id (`test_a05_…`, `test_h01_…`).
- Conventional commits (`feat(core): …`, `fix(django): …`). One package per PR when possible.
- Never log a full IndexNow key; use `KeyValidator.mask()`.
- Style: ruff (`E, F, I, UP, B, S, N, RUF`, the ruff formatter, 120 columns), `mypy --strict` over sources and tests,
  no `type: ignore` without an error code and a reason, files under 400 lines, no PEP 695 syntax until the minimum
  Python is 3.12.
