## begin license ##
#
# postduif (Dutch for carrier pigeon) delivers your app's mail
#
# Copyright (C) 2026 Seecr (Seek You Too B.V.) https://seecr.nl
#
# This file is part of "postduif"
#
# "postduif" is licensed under the MIT License; see the LICENSE file.
# SPDX-License-Identifier: MIT
#
## end license ##

"""Transports: how a message leaves the app. The Mailer (postduif.mailer) chooses none of
this itself; it hands each message to its transport.

- PostalTransport: Postal's HTTP API (POST {postal_url}/api/v1/send/raw).
- OutboxTransport: sends nothing; every mail becomes a JSON file in a directory, with the
  message itself next to it (.eml), to look at while developing.
- NullTransport: mail is off; nothing is sent.

A transport has one method, `async deliver(sender, mail, message) -> message_id`: mail is
the postduif Mail, message the MIME message made of it. It raises MailError when the mail
was not sent; temporary=True when trying again later may help.
"""

import asyncio
import base64
import datetime
import email.utils
import json
import pathlib
import uuid

import httpx

SEND_PATH = "/api/v1/send/raw"


class MailError(Exception):
    """Why a mail was not sent, for the log: never with the api key. temporary: trying
    again later may help (the server is busy or away); otherwise it was refused."""

    def __init__(self, message, temporary=False):
        super().__init__(message)
        self.temporary = temporary


class Transport:
    async def deliver(self, sender, mail, message):
        raise NotImplementedError

    async def aclose(self):
        """Called by Mailer.aclose(), after the last mail."""


class NullTransport(Transport):
    """Mail is off. The Mailer does not call deliver; this is here for completeness."""

    async def deliver(self, sender, mail, message):
        raise MailError("mail is off")


class PostalTransport(Transport):
    """Sends through Postal's HTTP API, one message at a time.

    Postal answers simultaneous API requests with a 500 now and then (a deadlock in its
    database), and the mails of one event (an invite and the mail to the admins) would go
    out at the same moment; so this transport sends them one after the other.

    A temporary failure (HTTP 5xx or 429, no connection, a timeout) raises MailError with
    temporary=True; a refusal (another status, or Postal's "status": "error") does not: it
    would only be refused again.

    httpx_transport is for tests: an httpx.MockTransport, see postduif.testing.PostalMock.
    """

    def __init__(self, postal_url, api_key, timeout=10, httpx_transport=None):
        self.postal_url = postal_url.rstrip("/")
        self._api_key = api_key
        self.timeout = timeout
        self._httpx_transport = httpx_transport
        self._one_at_a_time = None  # an asyncio.Lock, made in the loop that sends

    def __repr__(self):
        return f"PostalTransport({self.postal_url!r})"  # never the api key

    async def deliver(self, sender, mail, message):
        payload = {
            "mail_from": email.utils.parseaddr(sender)[1],
            "rcpt_to": [mail.to],
            "data": base64.b64encode(message.as_bytes()).decode(),
            "bounce": False,
        }
        if self._one_at_a_time is None:
            self._one_at_a_time = asyncio.Lock()
        try:
            async with self._one_at_a_time:
                async with httpx.AsyncClient(
                    timeout=self.timeout, transport=self._httpx_transport
                ) as client:
                    response = await client.post(
                        self.postal_url + SEND_PATH,
                        json=payload,
                        headers={"X-Server-API-Key": self._api_key},
                    )
        except httpx.HTTPError as e:  # unreachable, a timeout
            temporary = isinstance(
                e, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
            )
            # the type and the text only: a repr could show the request, with the api key
            raise MailError(f"{type(e).__name__}: {e}", temporary=temporary) from None
        if response.status_code != 200:
            status = response.status_code
            raise MailError(
                f"HTTP {status} from Postal", temporary=status >= 500 or status == 429
            )
        try:
            answer = response.json()
        except ValueError:
            raise MailError("Postal's answer is not JSON") from None
        # Postal answers 200 with {"status": "error" or "parameter-error",
        # "data": {"code": .., "message": ..}} when it refuses a mail
        if not isinstance(answer, dict):
            raise MailError("Postal's answer is not a JSON object")
        data = answer.get("data") if isinstance(answer.get("data"), dict) else {}
        if answer.get("status") != "success":
            reason = ": ".join(
                str(data[key]) for key in ("code", "message") if data.get(key)
            )
            raise MailError(f"refused by Postal: {reason or answer.get('status')}")
        return data.get("message_id")


class OutboxTransport(Transport):
    """Sends nothing: each mail is a JSON file in the outbox directory, named so that the
    newest sorts last, and the MIME message next to it with the same name, ending in .eml
    (to open in a mail program).

    It is for development, so it cleans up after itself: after each mail only the newest
    `keep` stay, none older than `days` days."""

    def __init__(self, path, keep=50, days=7):
        self.path = pathlib.Path(path)
        self.keep = keep
        self.days = days

    def __repr__(self):
        return f"OutboxTransport({str(self.path)!r})"

    async def deliver(self, sender, mail, message):
        now = datetime.datetime.now(datetime.timezone.utc)
        message_id = f"outbox-{uuid.uuid4().hex[:12]}"
        name = f"{now:%Y%m%d-%H%M%S-%f}-{_safe(mail.tag) or 'mail'}-{message_id}.json"
        self.path.mkdir(parents=True, exist_ok=True)
        content = mail.as_dict() | {
            "from": sender,
            "message_id": message_id,
            "sent_at": now.isoformat(),
        }
        path = self.path / name
        path.write_text(json.dumps(content, indent=4, ensure_ascii=False))
        path.with_suffix(".eml").write_bytes(message.as_bytes())
        self.clean_up(now)
        return message_id

    def files(self):
        """The JSON files of the mails in the outbox, newest first."""
        if not self.path.is_dir():
            return []
        return sorted(self.path.glob("*.json"), reverse=True)

    def mails(self):
        """The mails in the outbox as dicts (Mail.as_dict() plus from, message_id and
        sent_at), newest first. Mail.from_dict(values) makes a Mail of one again."""
        mails = []
        for path in self.files():
            try:
                mails.append(json.loads(path.read_text()))
            except (OSError, ValueError):
                continue  # removed meanwhile, or not ours
        return mails

    def clean_up(self, now=None):
        """Removes the mails beyond the newest `keep`, and those older than `days` (by the
        time in their name)."""
        now = now or datetime.datetime.now(datetime.timezone.utc)
        oldest = now - datetime.timedelta(days=self.days)
        for index, path in enumerate(self.files()):
            if index >= self.keep or _sent_at(path) < oldest:
                path.unlink(missing_ok=True)
                path.with_suffix(".eml").unlink(missing_ok=True)


def _safe(tag):
    """A tag as part of a file name."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)[:40]


def _sent_at(path):
    """When a mail in the outbox was made, from its name; a name without a time counts as
    old."""
    try:
        return datetime.datetime.strptime(path.name[:22], "%Y%m%d-%H%M%S-%f").replace(
            tzinfo=datetime.timezone.utc
        )
    except ValueError:
        return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
