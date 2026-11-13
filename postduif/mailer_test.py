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

import asyncio
import json

import pytest

from .config import MailConfig
from .mailer import Mailer, SendResult, make_mailer
from .message import InlineImage, Mail
from .testing import FakeMailer, PostalMock
from .transports import MailError, NullTransport, OutboxTransport, PostalTransport

POSTAL = MailConfig(
    transport="postal",
    sender="Example <noreply@example.org>",
    base_url="https://example.org",
    postal_url="https://postal.example.org",
    api_key="secret",
    timeout=3,
)
LOGO = InlineImage("logo@example.org", "logo.png", "image/png", b"\x89PNG-logo")


@pytest.fixture
def caplog(caplog):
    caplog.set_level("INFO", logger="postduif")
    return caplog


async def test_send_a_mail(caplog):
    mailer = FakeMailer()
    result = await mailer.send(
        to="ann@example.org",
        subject="Your order",
        text="text",
        html="<p>html</p>",
        reply_to="shop@example.org",
        tag="order",
        headers={"Auto-Submitted": "auto-generated"},
    )
    assert result == SendResult(
        True, to="ann@example.org", message_id="recorded-1", attempts=1
    )
    assert result
    assert mailer.mails == [
        Mail(
            "ann@example.org",
            "Your order",
            "text",
            "<p>html</p>",
            reply_to="shop@example.org",
            tag="order",
            headers={"Auto-Submitted": "auto-generated"},
        )
    ]
    assert mailer.messages[0]["From"] == "Test <noreply@example.org>"
    assert (
        "Mail 'Your order' (order) to ann@example.org sent, message_id recorded-1"
        in caplog.text
    )


async def test_send_the_fields_of_a_dict():
    mailer = FakeMailer()
    fields = {"to": "ann@example.org", "subject": "Hello", "text": "text only"}
    await mailer.send(**fields)
    assert mailer.mails == [Mail("ann@example.org", "Hello", "text only")]


async def test_send_takes_only_keywords():
    with pytest.raises(TypeError):
        await FakeMailer().send("ann@example.org", "Hello", "text")


async def test_fields_that_make_no_mail_are_an_error():
    with pytest.raises(ValueError, match="images need html"):
        await FakeMailer().send(
            to="ann@example.org", subject="Hello", text="text", images=[LOGO]
        )


async def test_a_refusal_is_logged_and_not_tried_again(caplog):
    mailer = FakeMailer()
    mailer.transport.fail_with(MailError("refused by Postal: NoRecipients"))
    result = await mailer.send(
        to="ann@example.org", subject="Your order", text="text", tag="order"
    )
    assert result == SendResult(
        False, to="ann@example.org", error="refused by Postal: NoRecipients", attempts=1
    )
    assert not result
    assert mailer.mails == []
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        (
            "ERROR",
            "Mail 'Your order' (order) to ann@example.org not sent:"
            " refused by Postal: NoRecipients",
        )
    ]


async def test_a_temporary_failure_is_tried_three_times(caplog):
    mailer = FakeMailer()
    mailer.transport.fail_with(*[MailError("HTTP 500 from Postal", temporary=True)] * 3)
    result = await mailer.send(
        to="ann@example.org", subject="Your order", text="text", tag="order"
    )
    assert (result.sent, result.attempts, result.error) == (
        False,
        3,
        "HTTP 500 from Postal",
    )
    what = "Mail 'Your order' (order) to ann@example.org"
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("WARNING", f"{what}: attempt 1 failed (HTTP 500 from Postal); again in 0 s"),
        ("WARNING", f"{what}: attempt 2 failed (HTTP 500 from Postal); again in 0 s"),
        ("ERROR", f"{what} not sent after 3 attempts: HTTP 500 from Postal"),
    ]


async def test_after_a_temporary_failure_it_is_sent():
    mailer = FakeMailer()
    mailer.transport.fail_with(
        MailError("HTTP 500", temporary=True), MailError("ConnectError", temporary=True)
    )
    result = await mailer.send(to="ann@example.org", subject="Hello", text="text")
    assert (result.sent, result.message_id, result.attempts) == (True, "recorded-1", 3)


async def test_with_postal_it_tries_again():
    mock = PostalMock()
    mock.answer(PostalMock.http_error(500), PostalMock.http_error(429))
    transport = PostalTransport(
        "https://postal.example.org", "secret", httpx_transport=mock
    )
    mailer = Mailer(transport, "noreply@example.org", retry_delays=(0, 0))
    result = await mailer.send(to="ann@example.org", subject="Hello", text="text")
    assert (result.sent, result.message_id, result.attempts) == (True, "message-3", 3)
    assert len(mock.requests) == 3


async def test_it_waits_2_then_10_seconds():
    assert Mailer(NullTransport()).retry_delays == (2, 10)


async def test_an_unexpected_error_is_logged_with_its_traceback(caplog):
    mailer = FakeMailer()
    mailer.transport.fail_with(RuntimeError("a bug"))
    result = await mailer.send(to="ann@example.org", subject="Hello", text="text")
    assert (result.sent, result.error, result.attempts) == (
        False,
        "RuntimeError: a bug",
        1,
    )
    [record] = caplog.records
    assert (record.levelname, record.getMessage()) == (
        "ERROR",
        "Mail 'Hello' () to ann@example.org not sent",
    )
    assert record.exc_info


async def test_a_header_that_cannot_be_one_is_not_sent(caplog):
    mailer = FakeMailer()
    result = await mailer.send(
        to="ann@example.org", subject="Hello\nBcc: eve@example.org", text="text"
    )
    assert (result.sent, result.attempts) == (False, 0)
    assert mailer.mails == []
    [record] = caplog.records
    assert record.levelname == "ERROR" and not record.exc_info
    assert record.getMessage().startswith("Mail 'Hello\nBcc: eve@example.org' () to ann")


async def test_redirect_to():
    mailer = FakeMailer(redirect_to="test@example.org")
    result = await mailer.send(to="ann@example.org", subject="Your order", text="text")
    [mail] = mailer.mails
    assert (mail.to, mail.subject) == (
        "test@example.org",
        "[test, for ann@example.org] Your order",
    )
    assert result.to == "test@example.org"


async def test_redirect_subject():
    mailer = FakeMailer(
        redirect_to="test@example.org", redirect_subject="[test, voor {to}] {subject}"
    )
    await mailer.send(to="ann@example.org", subject="Je bestelling", text="text")
    assert mailer.mails[0].subject == "[test, voor ann@example.org] Je bestelling"


async def test_mail_off(caplog):
    mailer = Mailer.off()
    assert not mailer.enabled
    result = await mailer.send(
        to="ann@example.org", subject="Hello", text="text", tag="order"
    )
    assert result == SendResult(False, to="ann@example.org", error="mail is off")
    [record] = caplog.records
    assert (record.levelname, record.getMessage()) == (
        "INFO",
        "Mail 'Hello' (order) to ann@example.org not sent: mail is off",
    )


def test_a_mailer_that_sends_needs_a_sender(tmp_path):
    with pytest.raises(ValueError, match="sender"):
        Mailer(OutboxTransport(tmp_path))
    assert Mailer(NullTransport()).sender == ""


async def test_send_in_background():
    mailer = FakeMailer()
    task = mailer.send_in_background(
        to="ann@example.org", subject="Hello", text="text", tag="order"
    )
    result = await asyncio.wait_for(task, 1)
    assert result.message_id == "recorded-1"
    assert mailer.mails == [Mail("ann@example.org", "Hello", "text", tag="order")]
    assert not mailer._pending


def test_send_in_background_with_a_wrong_field_raises_at_once():
    with pytest.raises(TypeError):
        FakeMailer().send_in_background(to="ann@example.org", subject="Hello", txt="x")


async def test_clear():
    mailer = FakeMailer()
    await mailer.send(to="ann@example.org", subject="Hello", text="text")
    mailer.clear()
    assert (mailer.mails, mailer.messages) == ([], [])
    await mailer.send(to="bob@example.org", subject="Hello", text="text")
    assert [mail.to for mail in mailer.mails] == ["bob@example.org"]


async def test_aclose_waits_for_mails_in_the_background():
    mailer = FakeMailer(retry_delays=(0.05,))
    mailer.transport.fail_with(MailError("busy", temporary=True))
    task = mailer.send_in_background(to="ann@example.org", subject="Hello", text="text")
    await mailer.aclose()
    assert task.done() and task.result().sent


async def test_aclose_with_a_timeout_cancels(caplog):
    mailer = FakeMailer(retry_delays=(10,))
    mailer.transport.fail_with(MailError("busy", temporary=True))
    task = mailer.send_in_background(to="ann@example.org", subject="Hello", text="text")
    await mailer.aclose(timeout=0.05)
    await asyncio.sleep(0)
    assert task.cancelled()
    assert "1 mail(s) still being sent at shutdown, cancelled" in caplog.text


def test_link():
    mailer = FakeMailer(base_url="https://example.org/")
    assert mailer.can_link
    assert mailer.link("/orders/12") == "https://example.org/orders/12"
    assert mailer.link("orders") == "https://example.org/orders"
    assert mailer.link("/reset", token="a-b_c") == "https://example.org/reset?token=a-b_c"
    assert (
        mailer.link("/x", token="a b&c", n=1) == "https://example.org/x?token=a+b%26c&n=1"
    )


def test_no_link_without_base_url():
    mailer = FakeMailer(base_url="")
    assert not mailer.can_link
    with pytest.raises(ValueError, match="base_url"):
        mailer.link("/orders")


def test_make_mailer(tmp_path):
    off = make_mailer(None)
    assert isinstance(off, Mailer) and not off.enabled
    postal = make_mailer(POSTAL)
    assert type(postal.transport) is PostalTransport and postal.enabled
    assert (postal.sender, postal.base_url) == (
        "Example <noreply@example.org>",
        "https://example.org",
    )
    assert "secret" not in repr(postal)
    config = MailConfig(
        transport="outbox", sender="noreply@example.org", outbox_keep=3, outbox_days=1
    )
    outbox = make_mailer(config, tmp_path / "outbox")
    assert type(outbox.transport) is OutboxTransport
    assert (outbox.transport.path, outbox.transport.keep, outbox.transport.days) == (
        tmp_path / "outbox",
        3,
        1,
    )
    with pytest.raises(ValueError, match="outbox_path"):
        make_mailer(config)


def test_make_mailer_takes_the_redirect_and_extra_arguments():
    mailer = make_mailer(
        MailConfig(**{**POSTAL.__dict__, "redirect_to": "test@example.org"}),
        redirect_subject="[{to}] {subject}",
        retry_delays=(1,),
    )
    assert (mailer.redirect_to, mailer.redirect_subject, mailer.retry_delays) == (
        "test@example.org",
        "[{to}] {subject}",
        (1,),
    )


def test_from_file(tmp_path, caplog):
    path = tmp_path / "mail.json"
    path.write_text(json.dumps({"transport": "outbox", "sender": "noreply@example.org"}))
    mailer = Mailer.from_file(path, tmp_path / "outbox")
    assert mailer.enabled and type(mailer.transport) is OutboxTransport
    assert "Mail: to the outbox" in caplog.text


def test_from_file_without_a_file_is_mail_off(tmp_path, caplog):
    mailer = Mailer.from_file(tmp_path / "mail.json")
    assert not mailer.enabled
    assert f"Mail: off, no {tmp_path / 'mail.json'}" in caplog.text


def test_from_file_with_a_bad_file_is_mail_off_and_a_warning(tmp_path, caplog):
    path = tmp_path / "mail.json"
    path.write_text(json.dumps({"sender": "noreply@example.org", "api_key": "secret"}))
    mailer = Mailer.from_file(path)
    assert not mailer.enabled
    [record] = caplog.records
    assert record.levelname == "WARNING"
    assert record.getMessage().startswith(
        f"Mail: off, {path}: 'postal_url' must be the URL"
    )
    assert "secret" not in caplog.text


def test_from_file_requiring_a_base_url(tmp_path, caplog):
    path = tmp_path / "mail.json"
    path.write_text(json.dumps({"transport": "outbox", "sender": "noreply@example.org"}))
    mailer = Mailer.from_file(path, tmp_path / "outbox", require_base_url=True)
    assert not mailer.enabled
    [record] = caplog.records
    assert record.levelname == "WARNING"
    assert record.getMessage() == (
        f"Mail: off, {path}: 'base_url' is required: where the site is,"
        ' e.g. "https://example.org"'
    )


def test_outbox(tmp_path):
    config = MailConfig(transport="outbox", sender="noreply@example.org")
    mailer = make_mailer(config, tmp_path / "outbox")
    assert mailer.outbox is mailer.transport
    assert mailer.outbox.path == tmp_path / "outbox"
    assert make_mailer(POSTAL).outbox is None
    assert Mailer.off().outbox is None
    assert FakeMailer().outbox is None


async def test_fail_when_always():
    mailer = FakeMailer()
    mailer.transport.fail_when(True)
    for _ in range(2):
        result = await mailer.send(to="ann@example.org", subject="Hello", text="text")
        assert (result.sent, result.attempts) == (False, 1)
        assert result.error == "refused by the RecordingTransport"
    mailer.transport.fail_when(None)
    assert await mailer.send(to="ann@example.org", subject="Hello", text="text")
    assert len(mailer.mails) == 1


async def test_fail_when_for_some_mails():
    mailer = FakeMailer()
    mailer.transport.fail_when(
        lambda mail: mail.to == "bob@example.org",
        MailError("HTTP 500 from Postal", temporary=True),
    )
    assert await mailer.send(to="ann@example.org", subject="Hello", text="text")
    result = await mailer.send(to="bob@example.org", subject="Hello", text="text")
    assert (result.sent, result.attempts) == (False, 3)
    assert [mail.to for mail in mailer.mails] == ["ann@example.org"]


async def test_fail_with_goes_before_fail_when():
    mailer = FakeMailer()
    mailer.transport.fail_when(True)
    mailer.transport.fail_with(RuntimeError("a bug"))
    first = await mailer.send(to="ann@example.org", subject="Hello", text="text")
    second = await mailer.send(to="ann@example.org", subject="Hello", text="text")
    assert (first.error, second.error) == (
        "RuntimeError: a bug",
        "refused by the RecordingTransport",
    )
