# postduif

[![Tests](https://github.com/seecr/postduif/actions/workflows/test.yml/badge.svg)](https://github.com/seecr/postduif/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/postduif.svg)](https://pypi.org/project/postduif/)

*postduif (Dutch for carrier pigeon) delivers your app's mail.*

Async mail for Python web apps. postduif builds the MIME message (text and HTML, with images
inside the mail), hands it to [Postal](https://docs.postalserver.io) over its HTTP API, and on a
development machine writes it to an outbox instead, so nobody mails a real customer from a
laptop.

- **Never raises when sending.** `send()` returns a `SendResult`; what went wrong is in the log
  and in the result, never the API key.
- **Retries** a temporary failure (HTTP 5xx or 429, no connection, a timeout) after 2 and 10
  seconds; a refusal is not tried again.
- **One message at a time** to Postal, which answers simultaneous requests with a 500 now and
  then.
- **Images inside the mail** (`cid:`), not linked from elsewhere: nothing to block, nothing that
  tells a server the mail was opened.
- **Attachments**: files that come with the mail, a PDF say.
- **Mail off is a Mailer too**: no `if mailer is None` in your app.
- **`redirect_to`** sends every mail to one address, to test with the real mail server.
- **Testing helpers**: a mailer that records what it sends, and a mock of Postal's API.

Python 3.11 or later. Its only dependency is [httpx](https://www.python-httpx.org).

```sh
pip install postduif
```

## Sending a mail

```python
from postduif import InlineImage, Mailer

mailer = Mailer.from_file("config.d/mail.json", outbox_path="data/outbox")

logo = InlineImage.from_file("static/logo.png", cid="logo@example.org")
result = await mailer.send(
    to="ann@example.org",
    subject="Your order",
    text="Thank you for your order.",
    html='<img src="cid:logo@example.org" alt=""><p>Thank you for your order.</p>',
    reply_to="shop@example.org",
    tag="order",              # Postal's tag, to find mails of one kind
    images=[logo],
)
if not result:
    print(result.error)       # also in the log; result.attempts says how often it was tried
```

Files come with a mail as attachments, with or without HTML:

```python
from postduif import Attachment

invoice = Attachment.from_bytes(pdf_bytes, "invoice-2026-001.pdf")   # or from_file(path)
await mailer.send(to="ann@example.org", subject="Your invoice", text="...",
                  attachments=[invoice])
```

`send` takes keywords only, so the fields can come from a dict: `send(**fields)`.
`mailer.send_in_background(...)` takes the same and sends without making the caller wait and returns the asyncio
task. At shutdown, `await mailer.aclose()` waits for mails that are still going.

Links in a mail come from the configured `base_url`, never from a request:

```python
mailer.link("/password-reset", token="a1b2")   # https://example.org/password-reset?token=a1b2
```

## Configuration

`Mailer.from_file(path)` reads a JSON file. Without the file, or with a file that is not
valid, mail is off and your app starts anyway; the log says why. If all your mails have links,
give `require_base_url=True`: without a `base_url` mail is off too.

```json
{
    "postal_url": "https://postal.example.org",
    "api_key": "...",
    "sender": "Example <noreply@example.org>",
    "base_url": "https://example.org",
    "timeout": 10
}
```

| Key | |
| --- | --- |
| `sender` | The `From:` of every mail. Required. |
| `transport` | `"postal"` (the default) or `"outbox"`: no mail is sent, each mail becomes a `.json` and an `.eml` file in `outbox_path`. |
| `postal_url`, `api_key` | The Postal server and an API key of its mail server. Required for `"postal"`. |
| `base_url` | Where your site is, for `link()`. Optional, unless `require_base_url=True`. |
| `timeout` | Seconds per request to Postal; default 10. |
| `redirect_to` | Send every mail to this address instead, with the real addressee in the subject. |
| `outbox_keep`, `outbox_days` | The outbox keeps the newest 50 mails, for at most 7 days. |

With `"transport": "outbox"`, `mailer.outbox` is the `OutboxTransport` (else it is `None`), to
show the mails in your app: `files()` are their `.json` files, `mails()` their contents as dicts,
newest first, and `Mail.from_dict(values)` makes a `Mail` of one again, images included.

To build the configuration in code: `MailConfig.from_dict(values)` or `MailConfig(...)`, then
`make_mailer(config, outbox_path)`. `Mailer.off()` is a Mailer that sends nothing.

The subject of a redirected mail is `"[test, for {to}] {subject}"`; give
`redirect_subject="..."` to `Mailer.from_file()` or `make_mailer()` for another one.

## Testing your app

```python
from postduif import MailError
from postduif.testing import FakeMailer

async def test_order_confirmation():
    mailer = FakeMailer()
    await place_order(mailer, ...)
    [mail] = mailer.mails                  # postduif Mail objects
    assert mail.to == "ann@example.org"
    mailer.clear()                         # forgets the mails sent so far
    mailer.transport.fail_with(MailError("refused"))   # the next mail fails
    mailer.transport.fail_when(True)       # every mail fails, until fail_when(None)
    mailer.transport.fail_when(lambda mail: mail.to == "bob@example.org")
```

`PostalMock` plays Postal's API for a `PostalTransport`, with its answers and failures:

```python
from postduif import Mailer, PostalTransport
from postduif.testing import PostalMock

postal = PostalMock()
postal.answer(PostalMock.http_error(500))              # first a temporary failure
transport = PostalTransport("https://postal.example.org", "key", httpx_transport=postal)
mailer = Mailer(transport, "noreply@example.org", retry_delays=(0, 0))
await mailer.send(to="ann@example.org", subject="Hello", text="text")
[_, sent] = postal.sent                                # rcpt_to, message, ...
```

## Development

```sh
python3 -m venv env
env/bin/pip install -e . --group dev   # pip >= 25.1
env/bin/pytest postduif
git config core.hooksPath .githooks   # flake8, isort, black and the tests before a push
```

## License

MIT, see [LICENSE](LICENSE). Made by [Seecr](https://seecr.nl).
