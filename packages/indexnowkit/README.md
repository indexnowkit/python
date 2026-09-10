# indexnowkit — IndexNow for Python

Tell Bing, Yandex, Naver, Seznam, Yep and the other participants of the [IndexNow](https://www.indexnow.org/) registry
which URLs changed, the moment they change. The core of the indexnowkit Python family: the protocol client with
batching, debounce and retries, the `@indexnow` rule model that turns a saved object into its public URLs, the
`check` command that proves a setup end to end, the key file for WSGI and ASGI, a sitemap reader, a pre-flight GET
before every submission, a submission history and the `indexnowkit` command line for any site — with zero
dependencies. The Django, SQLAlchemy, FastAPI, Flask and Wagtail adapters build on it.

**Status: wave P step 0 — the package is being built; nothing is released yet.** The specification the code
follows is public: [indexnowkit/spec](https://github.com/indexnowkit/spec) (`20-python-core.md`). The PHP family of
the same specification is released: [indexnowkit.dev/php](https://indexnowkit.dev/php/).

Google does not participate in IndexNow; IndexNow is a notification, not indexing.

## Install

```bash
pip install indexnowkit            # or: uv add indexnowkit
pip install "indexnowkit[httpx]"   # the async transport
```

Python 3.11 or newer. Русская версия: [README.ru.md](README.ru.md).

## Documentation

[indexnowkit.dev/python](https://indexnowkit.dev/python/) — the pages of `docs/` and this README. Issues and pull
requests: [github.com/indexnowkit/python](https://github.com/indexnowkit/python). MIT.
