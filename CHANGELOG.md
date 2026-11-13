# Changelog

## 0.1.0 (2026-11-13)

> The first version: sending mail. A `Mailer` sends a `Mail` through Postal's HTTP API or to an
> outbox, never raises, and tells what became of it in a `SendResult`.

### Added

- `Mail` and `InlineImage` (`postduif.message`): text, optional HTML, images inside the mail
  (`cid:`), `reply_to`, a tag (`X-Postal-Tag`) and extra headers. `build_message` makes the MIME
  message: `Date` in UTC, `Message-ID` on the sender's domain; a line break in a header raises
  `ValueError`. `html_with_images` shows the HTML in a browser, with the images as `data:` URLs.
- `MailConfig` (`postduif.config`): `read(path)` for a JSON file (None when it is missing),
  `from_dict` with a check per key (`MailConfigError`), `describe()` for the log. `base_url` is
  optional (`can_link`).
- `Mailer` (`postduif.mailer`): `send(mail)` or `send(to, subject, text, html, ...)`, returning a
  `SendResult` (`sent`, `to`, `message_id`, `error`, `attempts`; true when sent). A temporary
  failure is tried again after 2 and 10 seconds. `redirect_to` with an adjustable
  `redirect_subject`; `link(path, **params)`; `send_in_background`; `aclose(timeout)` for the
  shutdown. `Mailer.from_file` (no file or a bad one: mail off, logged), `from_config`,
  `make_mailer` and `Mailer.off()`.
- Transports (`postduif.transports`): `PostalTransport` (one message at a time; HTTP 5xx and 429,
  no connection and a timeout are temporary), `OutboxTransport` (`.json` and `.eml` per mail,
  keeps the newest 50 for at most 7 days; `files()` and `mails()`) and `NullTransport` (mail off).
- `postduif.testing`: `FakeMailer` and `RecordingTransport`, which keep what they send and can
  be told to fail, and `PostalMock`, Postal's API for tests.
