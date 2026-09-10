<!-- One package per PR when possible. Conventional commit title: feat(core): …, fix(django): …, docs: … -->

## What and why

<!-- The behaviour before, the behaviour after, and the reason. Link the issue or the spec section. -->

## Checklist (from CONTRIBUTING.md)

- [ ] `bin/ci <package>` is green (ruff, mypy --strict, pytest, the coverage floor, the build) — and `bin/ci <package> lowest` when dependencies changed
- [ ] Tests cover the change; adapter behaviour is named after its conformance id (`test_a05_…`, `test_h01_…`) when one applies
- [ ] A user-visible change has a line in the package's `CHANGELOG.md` under "Unreleased"; a breaking change is under "Changed" with the migration
- [ ] Docs updated (README EN and RU, `docs/*.md`, `bin/config-table <package>` when a configuration key changed) when configuration, commands or extension points changed
- [ ] No full IndexNow key in code, tests, fixtures or logs (`KeyValidator.mask()`)
