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
import base64
import datetime
import email
import email.policy
import json

import httpx
import pytest

from .message import InlineImage, Mail, build_message
from .testing import PostalMock
from .transports import MailError, NullTransport, OutboxTransport, PostalTransport

SENDER = "Example <noreply@example.org>"
LOGO = InlineImage(
    cid="logo@example.org",
    filename="logo.png",
    content_type="image/png",
    data=b"\x89PNG-logo",
)


def postal(mock=None):
    mock = mock or PostalMock()
    return (
        PostalTransport("https://postal.example.org/", "secret", 3, httpx_transport=mock),
        mock,
    )


async def deliver(transport, mail):
    return await transport.deliver(SENDER, mail, build_message(SENDER, mail))


def parse(data):
    return email.message_from_bytes(data, policy=email.policy.default)


async def test_postal_sends_through_the_api():
    transport, mock = postal()
    mail = Mail("ann@example.org", "Your order", "text", "<p>html</p>", tag="order")
    assert await deliver(transport, mail) == "message-1"
    [request] = mock.requests
    assert str(request.url) == "https://postal.example.org/api/v1/send/raw"
    assert request.headers["X-Server-API-Key"] == "secret"
    [sent] = mock.sent
    assert (sent["mail_from"], sent["rcpt_to"], sent["bounce"]) == (
        "noreply@example.org",
        ["ann@example.org"],
        False,
    )
    assert sent["message"]["Subject"] == "Your order"
    assert sent["message"]["X-Postal-Tag"] == "order"


def test_postal_repr_without_the_api_key():
    transport, _ = postal()
    assert repr(transport) == "PostalTransport('https://postal.example.org')"
    assert "secret" not in repr(transport)


@pytest.mark.parametrize(
    "answer, reason",
    [
        (
            PostalMock.refused("NoRecipients", "None given", status="parameter-error"),
            "refused by Postal: NoRecipients: None given",
        ),
        (
            PostalMock.refused("InvalidServerAPIKey"),
            "refused by Postal: InvalidServerAPIKey",
        ),
        (httpx.Response(200, json={"status": "error"}), "refused by Postal: error"),
        (PostalMock.http_error(401), "HTTP 401 from Postal"),
        (PostalMock.http_error(422), "HTTP 422 from Postal"),
        (httpx.Response(200, text="<html>"), "Postal's answer is not JSON"),
        (httpx.Response(200, json=["success"]), "Postal's answer is not a JSON object"),
    ],
)
async def test_postal_refusals(answer, reason):
    transport, mock = postal()
    mock.answer(answer)
    with pytest.raises(MailError) as error:
        await deliver(transport, Mail("ann@example.org", "Hello", "text"))
    assert (str(error.value), error.value.temporary) == (reason, False)


@pytest.mark.parametrize(
    "answer, reason",
    [
        (PostalMock.http_error(500), "HTTP 500 from Postal"),
        (PostalMock.http_error(503), "HTTP 503 from Postal"),
        (PostalMock.http_error(429), "HTTP 429 from Postal"),
        (httpx.ConnectError("no connection"), "ConnectError: no connection"),
        (httpx.ReadTimeout("too slow"), "ReadTimeout: too slow"),
        (httpx.RemoteProtocolError("hung up"), "RemoteProtocolError: hung up"),
    ],
)
async def test_postal_temporary_failures(answer, reason):
    transport, mock = postal()
    mock.answer(answer)
    with pytest.raises(MailError) as error:
        await deliver(transport, Mail("ann@example.org", "Hello", "text"))
    assert (str(error.value), error.value.temporary) == (reason, True)
    assert "secret" not in str(error.value)


async def test_mails_go_to_postal_one_at_a_time():
    """Postal answers simultaneous requests with a 500 now and then: mails sent at the
    same moment wait for each other."""
    busy, overlapped = [], []

    async def handler(request):
        overlapped.append(bool(busy))
        busy.append(1)
        await asyncio.sleep(0.01)
        busy.pop()
        return PostalMock.success("abc")

    transport, _ = postal(httpx.MockTransport(handler))
    mails = [Mail(f"{n}@example.org", "Hello", "text") for n in range(3)]
    assert (
        await asyncio.gather(*(deliver(transport, mail) for mail in mails)) == ["abc"] * 3
    )
    assert overlapped == [False, False, False]


async def test_null_transport():
    with pytest.raises(MailError, match="mail is off"):
        await deliver(NullTransport(), Mail("ann@example.org", "Hello", "text"))


async def test_outbox(tmp_path):
    outbox = OutboxTransport(tmp_path / "outbox")
    first = await deliver(outbox, Mail("ann@example.org", "First", "text", tag="order"))
    second = await deliver(
        outbox,
        Mail(
            "bob@example.org",
            "Second",
            "text",
            '<p><img src="cid:logo@example.org"></p>',
            reply_to="shop@example.org",
            images=[LOGO],
        ),
    )
    assert first.startswith("outbox-") and first != second
    files = outbox.files()
    assert [f.name.split("-", 3)[3] for f in files] == [
        f"mail-{second}.json",
        f"order-{first}.json",
    ]
    message = parse(files[0].with_suffix(".eml").read_bytes())
    assert (message["To"], message["Reply-To"]) == ("bob@example.org", "shop@example.org")
    [newest, oldest] = outbox.mails()
    assert (newest["subject"], oldest["subject"]) == ("Second", "First")
    assert newest | {"sent_at": None} == {
        "to": "bob@example.org",
        "from": SENDER,
        "subject": "Second",
        "text": "text",
        "html": '<p><img src="cid:logo@example.org"></p>',
        "reply_to": "shop@example.org",
        "tag": "",
        "images": [
            {
                "cid": "logo@example.org",
                "filename": "logo.png",
                "content_type": "image/png",
                "data": base64.b64encode(b"\x89PNG-logo").decode(),
            }
        ],
        "headers": {},
        "message_id": second,
        "sent_at": None,
    }


async def test_outbox_tag_in_a_file_name(tmp_path):
    outbox = OutboxTransport(tmp_path)
    await deliver(outbox, Mail("ann@example.org", "Hello", "text", tag="../a b"))
    [path] = outbox.files()
    assert path.parent == tmp_path
    assert "-___a_b-outbox-" in path.name


def test_an_empty_outbox(tmp_path):
    outbox = OutboxTransport(tmp_path / "not-yet")
    assert (outbox.files(), outbox.mails()) == ([], [])


async def test_outbox_keeps_the_newest(tmp_path):
    outbox = OutboxTransport(tmp_path, keep=3)
    ids = [
        await deliver(outbox, Mail("ann@example.org", f"Mail {n}", "text"))
        for n in range(5)
    ]
    names = sorted(path.name for path in tmp_path.iterdir())
    assert len(names) == 6  # 3 mails: .json and .eml
    assert all(any(i in name for name in names) for i in ids[2:])
    assert not any(i in name for name in names for i in ids[:2])


async def test_outbox_removes_old_mails(tmp_path):
    now = datetime.datetime.now(datetime.timezone.utc)
    for when, name in [
        (now - datetime.timedelta(days=8), "old"),
        (now - datetime.timedelta(days=6), "recent"),
    ]:
        stem = f"{when:%Y%m%d-%H%M%S-%f}-mail-outbox-{name}"
        (tmp_path / f"{stem}.json").write_text("{}")
        (tmp_path / f"{stem}.eml").write_text("")
    (tmp_path / "no-time.json").write_text("{}")
    await deliver(
        OutboxTransport(tmp_path, days=7), Mail("ann@example.org", "New", "text")
    )
    names = sorted(path.name for path in tmp_path.iterdir())
    assert not any("old" in name or "no-time" in name for name in names)
    assert sum("recent" in name for name in names) == 2
    assert len(names) == 4
