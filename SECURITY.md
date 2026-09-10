# Security

Two values these packages handle are sensitive. **The IndexNow key** is public by design (search engines fetch it from
`/{key}.txt`), but anyone holding it can submit arbitrary URLs of your host: keep it in the environment, never commit
it, rotate it by changing `INDEXNOW_KEY` (the key file follows automatically; `previous_key` covers the rotation
window), and do not paste full keys into issues. Logs, exception messages and the `config` command mask keys to 4
characters — the current and the previous one, also inside `key_location` URLs. **The history and state files**
(`history.sqlite.path`, the `.indexnow/state.sqlite` of the CLI) hold the submitted URLs only, never the key; the CLI
creates the state directory with mode 0700 and `key generate --write-env` the env file with mode 0600.

Report vulnerabilities privately via [GitHub security advisories](https://github.com/indexnowkit/python/security/advisories/new)
or to i.pinchuk.work@gmail.com. Please do not open public issues for security reports. Reports are acknowledged within 5 business days; a fix or a mitigation plan follows within 30 days.
