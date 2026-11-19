# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# postduif

Async mail for Python web apps: MIME messages with inline images, sent through Postal's HTTP API
(`/api/v1/send/raw`), or written to an outbox during development. MIT license, on GitHub
(`seecr/postduif`) and PyPI. Maintained by Seecr (Thijs Janssen, Johan Jonkers).

The name is Dutch for carrier pigeon. Everything else is English: code, docstrings, error
messages, log lines, README. Nothing Seecr-specific in code, examples or tests (no
`postal.seecrmail.nl`, no project names).

## State of the project

- 0.3.0 is released (PyPI): `message`, `config`, `mailer`, `transports` and `testing`;
  0.2.0 has what moving Sponsor Mee over asked for, 0.3.0 attachments (see `CHANGELOG.md`).
  The code comes from Sponsor Mee's `sponsormee/mail.py`; Sponsor Mee, Spring Leden, Vault and
  Guard App move over after 0.1.0, each in its own time.
- Decided: httpx (`AsyncClient`, inside `PostalTransport`, not in the API); `send` returns a
  `SendResult` and never raises; mail off is a `NullTransport`, never `None`. The first version
  is small: only sending. `compose` (templates, `subject_moment`, `duration`, macros) and `cli`
  (a test-mail command) come when two apps run on the package. Later still: SMTP, a queue on
  disk.

## Where things are

- `postduif/message.py`: `Mail`, `InlineImage`, `Attachment`, `build_message`,
  `html_with_images`.
- `postduif/config.py`: `MailConfig`, `MailConfigError`.
- `postduif/transports.py`: `Transport` (`async deliver(sender, mail, message) -> message_id`,
  raising `MailError`), `PostalTransport`, `OutboxTransport`, `NullTransport`.
- `postduif/mailer.py`: `Mailer` (retries, redirect, log, `SendResult`), `make_mailer`.
- `postduif/testing.py`: `FakeMailer`, `RecordingTransport`, `PostalMock`.

## Conventions

- Tests sit next to the code as `*_test.py`; `env/bin/pytest postduif`. Test data is generic:
  `example.org` addresses, English texts.
- flake8, isort and black (90 columns) as in CI; the pre-push hook runs them:
  `git config core.hooksPath .githooks`.
- New source files get their license header: `seecr-license doc/license.conf postduif`
  (seecr-license >= 3.3.1, which knows MIT).
- Versions are git tags (`0.1.0`), read by setuptools_scm. Pushing a tag publishes to PyPI
  (trusted publishing) and makes a GitHub release from that version's section in `CHANGELOG.md`.
- Commit messages start with the initials of who works on it: `TJ: ` (thijs), `JJ: ` (johan).
