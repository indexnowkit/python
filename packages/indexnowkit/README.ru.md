# indexnowkit — IndexNow для Python

Сообщайте Bing, Yandex, Naver, Seznam, Yep и остальным участникам реестра [IndexNow](https://www.indexnow.org/),
какие URL изменились, в момент изменения. Ядро семейства indexnowkit для Python: клиент протокола с батчами,
дебаунсом и повторами, модель правил `@indexnow`, превращающая сохранённый объект в его публичные URL, команда
`check`, проверяющая настройку насквозь, файл ключа для WSGI и ASGI, читатель sitemap, проверка страницы перед
каждой отправкой, история отправок и командная строка `indexnowkit` для любого сайта — без зависимостей. Адаптеры
Django, SQLAlchemy, FastAPI, Flask и Wagtail строятся на нём.

**Статус: волна P, шаг 0 — пакет строится; релизов ещё нет.** Спецификация, которой следует код, открыта:
[indexnowkit/spec](https://github.com/indexnowkit/spec) (`20-python-core.md`). PHP-семейство той же спецификации
выпущено: [indexnowkit.dev/php](https://indexnowkit.dev/php/).

Google в IndexNow не участвует; IndexNow — уведомление, не индексация.

## Установка

```bash
pip install indexnowkit            # или: uv add indexnowkit
pip install "indexnowkit[httpx]"   # асинхронный транспорт
```

Python 3.11 и новее. English version: [README.md](README.md).

## Документация

[indexnowkit.dev/python](https://indexnowkit.dev/python/) — страницы `docs/` и этот README. Вопросы и pull request'ы:
[github.com/indexnowkit/python](https://github.com/indexnowkit/python). MIT.
