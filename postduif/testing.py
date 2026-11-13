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

"""Helpers for the tests of an app that sends mail with postduif. No pytest needed.

mailer = FakeMailer()                     # keeps what it sends in a list
await mailer.send(to="ann@example.org", subject="Hello", text="text")
[mail] = mailer.mails                     # postduif Mail objects
mailer.clear()                            # forgets them
mailer.transport.fail_with(MailError("refused"))   # the next mail fails

postal = PostalMock()                     # Postal's API, without a network
transport = PostalTransport("https://postal.example.org", "key", httpx_transport=postal)
postal.answer(postal.refused("NoRecipients", "No recipients"))
[sent] = postal.sent                      # what reached "Postal": rcpt_to, message, ...
"""

import base64
import email
import email.policy
import json

import httpx

from .mailer import Mailer
from .transports import MailError, Transport

TEST_SENDER = "Test <noreply@example.org>"
TEST_BASE_URL = "https://example.org"


class RecordingTransport(Transport):
    """Sends nothing; keeps every mail it gets. `fail_with(error)` makes the next delivery
    raise that error (a MailError, or anything else to play a bug)."""

    def __init__(self):
        self.delivered = []  # (sender, mail, message)
        self._failures = []

    @property
    def mails(self):
        return [mail for _, mail, _ in self.delivered]

    def clear(self):
        """Forgets the mails delivered so far."""
        self.delivered.clear()

    def fail_with(self, *errors):
        """The next deliveries raise these errors, one each, in this order."""
        self._failures.extend(errors)

    async def deliver(self, sender, mail, message):
        if self._failures:
            raise self._failures.pop(0)
        self.delivered.append((sender, mail, message))
        return f"recorded-{len(self.delivered)}"


class FakeMailer(Mailer):
    """A Mailer with a RecordingTransport; retries at once. `mails` are the Mail objects
    sent, `messages` their MIME messages."""

    def __init__(self, sender=TEST_SENDER, *, base_url=TEST_BASE_URL, **kwargs):
        kwargs.setdefault("retry_delays", (0, 0))
        super().__init__(RecordingTransport(), sender, base_url=base_url, **kwargs)

    @property
    def mails(self):
        return self.transport.mails

    @property
    def messages(self):
        return [message for _, _, message in self.transport.delivered]

    def clear(self):
        """Forgets the mails sent so far."""
        self.transport.clear()


class PostalMock(httpx.MockTransport):
    """Postal's send/raw API for a PostalTransport (httpx_transport=...).

    It answers success by default, with message ids "message-1", "message-2", ... Give
    other answers with answer(): an httpx.Response, an exception to raise
    (httpx.ConnectError(...)), or one of the helpers below; each answer is used once, in
    order."""

    def __init__(self):
        super().__init__(self._handle)
        self.requests = []
        self._answers = []

    def answer(self, *answers):
        self._answers.extend(answers)

    @property
    def sent(self):
        """Every request as a dict: mail_from, rcpt_to, bounce, api_key, url and message
        (the parsed MIME message)."""
        return [_parse(request) for request in self.requests]

    def _handle(self, request):
        self.requests.append(request)
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer
        return self.success(f"message-{len(self.requests)}")

    @staticmethod
    def success(message_id="message-1"):
        return httpx.Response(
            200,
            json={
                "status": "success",
                "time": 0.05,
                "flags": {},
                "data": {"message_id": message_id, "messages": {}},
            },
        )

    @staticmethod
    def refused(code, message="", status="error"):
        """Postal refusing a mail: HTTP 200 with "status": "error" (or
        "parameter-error")."""
        data = {"code": code} | ({"message": message} if message else {})
        return httpx.Response(
            200, json={"status": status, "time": 0.01, "flags": {}, "data": data}
        )

    @staticmethod
    def http_error(status):
        """An HTTP error: 5xx and 429 are temporary for postduif, the others a refusal."""
        return httpx.Response(status, text="error")


def _parse(request):
    payload = json.loads(request.content)
    message = email.message_from_bytes(
        base64.b64decode(payload["data"]), policy=email.policy.default
    )
    return {
        "url": str(request.url),
        "api_key": request.headers.get("X-Server-API-Key"),
        "mail_from": payload["mail_from"],
        "rcpt_to": payload["rcpt_to"],
        "bounce": payload.get("bounce"),
        "message": message,
    }


__all__ = ["FakeMailer", "MailError", "PostalMock", "RecordingTransport"]
