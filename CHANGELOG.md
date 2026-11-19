# Changelog

## 0.3.0 (2026-11-19)

> Attachments: files that come with a mail, a PDF say. Nothing changes for mails without them,
> except that `Mail.as_dict()` (and so `OutboxTransport.mails()`) has an `attachments` key.

### Added

- `Attachment` (`postduif.message`, also `from postduif import Attachment`): a file that comes
  with a mail, `from_bytes(data, filename)` or `from_file(path)`, the content type guessed from
  the name if not given. `Mail.attachments` and `send(..., attachments=[...])`;
  `build_message` puts them after the body in a `multipart/mixed`. `as_dict` and `from_dict`
  (the outbox) have them too, base64-encoded.

## 0.2.0 (2026-11-13)

> What moving Sponsor Mee over asked for: `send` with keywords only, and fewer workarounds in an
> app and its tests (`fail_when`, `clear`, `Mailer.outbox`, `Mail.from_dict`,
> `require_base_url`). Calls of `send` with a `Mail` or positional arguments must change.

### Changed

- `Mailer.send` and `send_in_background` take keywords only: `send(to=..., subject=...,
  text=..., ...)`, so `send(**fields)` works. They no longer take a `Mail`, nor the fields as
  positional arguments. `send_in_background` raises at once for fields that make no `Mail`.

### Added

- `Mail.from_dict`, the inverse of `as_dict`: reads a mail of `OutboxTransport.mails()` back,
  images included.
- `FakeMailer.clear()` and `RecordingTransport.clear()` forget the mails sent so far.
- `RecordingTransport.fail_when(when, error=None)`: every delivery fails (`True`), or those of
  the mails `when(mail)` is true for, until `fail_when(None)`.
- `Mailer.outbox`: the `OutboxTransport` when mail goes to the outbox, else `None`.
- `require_base_url=True` for `MailConfig.read`, `MailConfig.from_dict` and `Mailer.from_file`:
  without a `base_url` the config is not valid (`from_file`: mail is off, with a warning).

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
