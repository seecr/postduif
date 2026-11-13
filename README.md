# postduif

[![Tests](https://github.com/seecr/postduif/actions/workflows/test.yml/badge.svg)](https://github.com/seecr/postduif/actions/workflows/test.yml)

*postduif (Dutch for carrier pigeon) delivers your app's mail.*

Async mail for web apps: it builds the MIME message (text and HTML, images inline with `cid:`),
hands it to [Postal](https://docs.postalserver.io) over HTTP, and on a development machine writes
it to an outbox instead, so nobody mails a real customer from a laptop.

**Status: pre-alpha.** Nothing to use yet; the API is being moved here from the apps that use it.

## What it will do

- `Mail` and `InlineImage`: the message, with images inside the mail, never linked from elsewhere.
- One `Mailer` with a pluggable transport: `PostalTransport` (one message at a time, retries on a
  temporary error), `OutboxTransport` (`.json` + `.eml` files that clean themselves up) and
  `NullTransport` (mail is off; the log still says what was not sent).
- `send()` never raises: it returns a `SendResult` with the message id, or the error.
- `redirect_to` for test servers, `link(path, **params)` from a configured base URL.
- Testing helpers: a recording transport and a mock of Postal's API.

## Development

```sh
python3 -m venv env
env/bin/pip install -e '.[test]' -r requirements-dev.txt
env/bin/pytest postduif
git config core.hooksPath .githooks   # flake8, isort and the tests before a push
```

## License

MIT, see [LICENSE](LICENSE). Made by [Seecr](https://seecr.nl).
