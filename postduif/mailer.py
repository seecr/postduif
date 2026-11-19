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

"""The Mailer: sends a Mail through its transport, and never raises doing so.

    mailer = Mailer.from_file("config.d/mail.json", outbox_path="data/outbox")
    result = await mailer.send(to=..., subject=..., text=..., html=..., tag="order")
    if not result:
        ...                                   # result.error says why, for the log
    mailer.send_in_background(to=..., ...)    # without waiting; returns the task
    mailer.link("/orders/12", token="abc")    # https://example.org/orders/12?token=abc
    await mailer.aclose()                     # at shutdown: waits for mails still going

What goes wrong is logged (logger "postduif") and returned in the SendResult. A temporary
failure is tried again after retry_delays (2 and 10 seconds); a refusal is not. The
message_id is what to look for at the mail server when someone says a mail never arrived.

Mail off is a Mailer too, with a NullTransport: `mailer.enabled` is false, and every send
logs that the mail was not sent. With redirect_to, every mail goes to that address
instead, with the real addressee in the subject.
"""

import asyncio
import dataclasses
import logging
import urllib.parse

from .config import MailConfig, MailConfigError
from .message import Mail, build_message
from .transports import MailError, NullTransport, OutboxTransport, PostalTransport

logger = logging.getLogger("postduif")

# seconds to wait before the second and the third attempt
RETRY_DELAYS = (2, 10)
REDIRECT_SUBJECT = "[test, for {to}] {subject}"


@dataclasses.dataclass(frozen=True)
class SendResult:
    """What became of a mail. True when it was sent.

    to: where it went (the redirect_to address, when there is one). message_id: the id the
    transport gave it. error: why it was not sent, for the log. attempts: how often it was
    tried (0 when it was never tried: mail is off, or the message could not be made)."""

    sent: bool
    to: str = ""
    message_id: str | None = None
    error: str = ""
    attempts: int = 0

    def __bool__(self):
        return self.sent


class Mailer:
    """Sends mail through a transport (postduif.transports), as `sender`.

    base_url: where the site is, for link(). redirect_to: send every mail there instead;
    redirect_subject says how the subject shows the real addressee. retry_delays: seconds
    before each next attempt after a temporary failure."""

    def __init__(
        self,
        transport,
        sender="",
        *,
        base_url="",
        redirect_to="",
        redirect_subject=REDIRECT_SUBJECT,
        retry_delays=RETRY_DELAYS,
    ):
        if not isinstance(transport, NullTransport) and "@" not in sender:
            raise ValueError("a Mailer that sends needs a sender address")
        self.transport = transport
        self.sender = sender
        self.base_url = base_url.rstrip("/")
        self.redirect_to = redirect_to
        self.redirect_subject = redirect_subject
        self.retry_delays = tuple(retry_delays)
        # the tasks of send_in_background, so they are not garbage collected while running
        self._pending = set()

    def __repr__(self):
        return f"Mailer({self.transport!r}, {self.sender!r})"

    @classmethod
    def off(cls, base_url=""):
        """A Mailer that sends nothing."""
        return cls(NullTransport(), base_url=base_url)

    @classmethod
    def from_config(cls, config, outbox_path=None, **kwargs):
        """The Mailer for a MailConfig; mail off for None. kwargs go to Mailer()."""
        if config is None:
            return cls.off()
        if config.transport == "outbox":
            if outbox_path is None:
                raise ValueError("transport 'outbox' needs an outbox_path")
            transport = OutboxTransport(
                outbox_path, keep=config.outbox_keep, days=config.outbox_days
            )
        else:
            transport = PostalTransport(config.postal_url, config.api_key, config.timeout)
        return cls(
            transport,
            config.sender,
            base_url=config.base_url,
            redirect_to=config.redirect_to,
            **kwargs,
        )

    @classmethod
    def from_file(cls, path, outbox_path=None, *, require_base_url=False, **kwargs):
        """The Mailer for a JSON file with a MailConfig (postduif.config).

        No file, or a file that is not valid (or without a base_url, while
        require_base_url): mail is off, and the app starts anyway. It logs how mail is
        sent (never the api key); call it once, at startup."""
        try:
            config = MailConfig.read(path, require_base_url=require_base_url)
        except MailConfigError as e:
            logger.warning(f"Mail: off, {e}")
            return cls.off()
        if config is None:
            logger.info(f"Mail: off, no {path}")
            return cls.off()
        logger.info(config.describe())
        return cls.from_config(config, outbox_path, **kwargs)

    @property
    def enabled(self):
        """Whether mail is sent (to a mail server or an outbox) at all."""
        return not isinstance(self.transport, NullTransport)

    @property
    def outbox(self):
        """The OutboxTransport when mail goes to the outbox (nothing is sent), else None:
        `if mailer.outbox:`, `mailer.outbox.files()`, `mailer.outbox.path`."""
        return self.transport if isinstance(self.transport, OutboxTransport) else None

    @property
    def can_link(self):
        return bool(self.base_url)

    def link(self, path, **params):
        """The full address of a page of the site, for a mail: from base_url, never from a
        request. params become the query string."""
        if not self.base_url:
            raise ValueError("no base_url: a Mailer without one cannot make links")
        url = self.base_url + "/" + path.lstrip("/")
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    async def send(
        self,
        *,
        to,
        subject,
        text,
        html="",
        reply_to="",
        tag="",
        images=(),
        headers=(),
        attachments=(),
    ):
        """Sends one mail; the fields are those of a Mail (postduif.message). Never raises
        for what goes wrong in sending; returns a SendResult. Fields that cannot make a
        Mail (images without html) are a mistake in the app: ValueError."""
        mail = Mail(
            to=to,
            subject=subject,
            text=text,
            html=html,
            reply_to=reply_to,
            tag=tag,
            images=images,
            headers=headers,
            attachments=attachments,
        )
        return await self._send(mail)

    async def _send(self, mail):
        if self.redirect_to:
            mail = dataclasses.replace(
                mail,
                to=self.redirect_to,
                subject=self.redirect_subject.format(to=mail.to, subject=mail.subject),
            )
        what = f"Mail '{mail.subject}' ({mail.tag}) to {mail.to}"
        if not self.enabled:
            logger.info(f"{what} not sent: mail is off")
            return SendResult(False, to=mail.to, error="mail is off")
        try:
            message = build_message(self.sender, mail)
        except ValueError as e:
            logger.error(f"{what} not sent: {e}")
            return SendResult(False, to=mail.to, error=str(e))
        attempts = 1 + len(self.retry_delays)
        for attempt in range(1, attempts + 1):
            try:
                message_id = await self.transport.deliver(self.sender, mail, message)
                break
            except MailError as e:
                if not e.temporary:
                    logger.error(f"{what} not sent: {e}")
                    return SendResult(False, to=mail.to, error=str(e), attempts=attempt)
                if attempt == attempts:
                    logger.error(f"{what} not sent after {attempts} attempts: {e}")
                    return SendResult(False, to=mail.to, error=str(e), attempts=attempt)
                delay = self.retry_delays[attempt - 1]
                logger.warning(
                    f"{what}: attempt {attempt} failed ({e}); again in {delay} s"
                )
                await asyncio.sleep(delay)  # outside the transport's lock: others go on
            except Exception as e:
                logger.exception(f"{what} not sent")
                error = f"{type(e).__name__}: {e}"
                return SendResult(False, to=mail.to, error=error, attempts=attempt)
        logger.info(f"{what} sent, message_id {message_id}")
        return SendResult(True, to=mail.to, message_id=message_id, attempts=attempt)

    def send_in_background(self, **fields):
        """Sends it (the fields of send) without making the caller wait (or fail);
        returns the asyncio task, whose result is the SendResult. Fields that cannot
        make a Mail raise here, not in the task."""
        mail = Mail(**fields)
        task = asyncio.get_running_loop().create_task(
            self._send(mail), name="postduif send"
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return task

    async def aclose(self, timeout=None):
        """Waits for the mails of send_in_background that are still going (at most timeout
        seconds, if given), then closes the transport. For the app's shutdown."""
        if pending := list(self._pending):
            done, not_done = await asyncio.wait(pending, timeout=timeout)
            for task in not_done:
                task.cancel()
            if not_done:
                logger.warning(
                    f"{len(not_done)} mail(s) still being sent at shutdown, cancelled"
                )
        await self.transport.aclose()


def make_mailer(config, outbox_path=None, **kwargs):
    """The Mailer for a MailConfig, or mail off for None; never None itself."""
    return Mailer.from_config(config, outbox_path, **kwargs)
