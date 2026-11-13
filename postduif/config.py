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

"""How mail is sent: MailConfig, usually read from a JSON file such as config.d/mail.json.

    {
        "postal_url": "https://postal.example.org",   # the Postal server
        "api_key": "...",                             # an API key of its mail server
        "sender": "Example <noreply@example.org>",    # the From: of every mail
        "base_url": "https://example.org",            # optional: for the links in a mail
        "timeout": 10                                 # optional: seconds
    }

Optional as well:

- "transport": "postal" (the default) or "outbox": no mail is sent, every mail becomes a
  file in an outbox, to look at while developing; then postal_url and api_key are not
  needed.
- "redirect_to": every mail goes to this address instead, to test with the real mail
  server without mailing real people.
- "outbox_keep" and "outbox_days": the outbox keeps only the newest outbox_keep mails
  (default 50), for at most outbox_days days (default 7).

Links in a mail come from base_url, never from the Host header of a request: that is the
visitor's to choose.
"""

import dataclasses
import email.utils
import json
import pathlib
import urllib.parse


class MailConfigError(ValueError):
    """The mail configuration is not valid: the message says which key and why (and never
    shows the api key)."""


@dataclasses.dataclass(frozen=True)
class MailConfig:
    TRANSPORTS = ("postal", "outbox")
    KEYS = (
        "transport",
        "postal_url",
        "api_key",
        "sender",
        "base_url",
        "timeout",
        "redirect_to",
        "outbox_keep",
        "outbox_days",
    )
    DEFAULT_TIMEOUT = 10
    DEFAULT_OUTBOX_KEEP = 50
    DEFAULT_OUTBOX_DAYS = 7

    transport: str
    sender: str
    base_url: str = ""
    postal_url: str = ""
    api_key: str = dataclasses.field(default="", repr=False)
    timeout: float = DEFAULT_TIMEOUT
    redirect_to: str = ""
    outbox_keep: int = DEFAULT_OUTBOX_KEEP
    outbox_days: float = DEFAULT_OUTBOX_DAYS

    @property
    def can_link(self):
        """Whether there is a base_url to make links with."""
        return bool(self.base_url)

    @classmethod
    def read(cls, path):
        """The MailConfig in a JSON file; None when there is no such file (mail is off).

        Raises MailConfigError when the file is not valid. Whether the app then stops or
        starts without mail is the app's to decide."""
        path = pathlib.Path(path)
        try:
            text = path.read_text()
        except FileNotFoundError:
            return None
        try:
            values = json.loads(text)
        except json.JSONDecodeError as e:
            raise MailConfigError(f"{path}: not valid JSON ({e})") from None
        return cls.from_dict(values, source=path)

    @classmethod
    def from_dict(cls, values, source="mail config"):
        def fail(message):
            raise MailConfigError(f"{source}: {message}")

        def text(key):
            value = values.get(key, "")
            if not isinstance(value, str):
                fail(f"'{key}' must be a string")
            return value.strip()

        def number(key, default, kind=(int, float)):
            value = values.get(key, default)
            if isinstance(value, bool) or not isinstance(value, kind):
                return None
            return value

        if not isinstance(values, dict):
            fail("expected a JSON object")
        if unknown := sorted(set(values) - set(cls.KEYS)):
            fail(f"unknown keys {unknown}; known are {list(cls.KEYS)}")

        transport = text("transport") or "postal"
        if transport not in cls.TRANSPORTS:
            fail(f"'transport' must be one of {list(cls.TRANSPORTS)}")
        if not _is_address(sender := text("sender")):
            fail(
                "'sender' must be an e-mail address,"
                ' e.g. "Example <noreply@example.org>"'
            )
        if (base_url := text("base_url")) and not _is_url(base_url):
            fail(
                "'base_url' must be where the site is,"
                ' e.g. "https://example.org", or left out'
            )
        postal_url, api_key = text("postal_url"), text("api_key")
        if transport == "postal":
            if not _is_url(postal_url):
                fail(
                    "'postal_url' must be the URL of the Postal server,"
                    ' e.g. "https://postal.example.org"'
                )
            if not api_key:
                fail("'api_key' is required for transport 'postal'")
        timeout = number("timeout", cls.DEFAULT_TIMEOUT)
        if timeout is None or timeout <= 0:
            fail("'timeout' must be a number of seconds")
        if (redirect_to := text("redirect_to")) and not _is_address(redirect_to):
            fail("'redirect_to' must be an e-mail address, or left out")
        outbox_keep = number("outbox_keep", cls.DEFAULT_OUTBOX_KEEP, kind=int)
        if outbox_keep is None or outbox_keep < 1:
            fail("'outbox_keep' must be a number of mails, at least 1")
        outbox_days = number("outbox_days", cls.DEFAULT_OUTBOX_DAYS)
        if outbox_days is None or outbox_days <= 0:
            fail("'outbox_days' must be a number of days")

        return cls(
            transport=transport,
            sender=sender,
            base_url=base_url.rstrip("/"),
            postal_url=postal_url.rstrip("/"),
            api_key=api_key,
            timeout=timeout,
            redirect_to=redirect_to,
            outbox_keep=outbox_keep,
            outbox_days=outbox_days,
        )

    def describe(self):
        """One line for the log at startup; never the api key."""
        if self.transport == "postal":
            where = f"Postal at {self.postal_url}"
        else:
            where = (
                f"the outbox (no mail is sent; the newest {self.outbox_keep},"
                f" at most {self.outbox_days:g} days)"
            )
        text = f"Mail: to {where}, from {self.sender}"
        text += (
            f", links to {self.base_url}" if self.base_url else ", no links (no base_url)"
        )
        if self.redirect_to:
            text += f", all mail redirected to {self.redirect_to}"
        return text


def _is_url(value):
    parts = urllib.parse.urlsplit(value)
    return (
        parts.scheme in ("http", "https")
        and bool(parts.netloc)
        and not (parts.query or parts.fragment)
    )


def _is_address(value):
    """An e-mail address, with or without a name: "noreply@example.org",
    "Example <noreply@example.org>"."""
    if any(c in value for c in "\r\n"):
        return False
    address = email.utils.parseaddr(value)[1]
    local, at, domain = address.rpartition("@")
    return bool(local and at and domain)
