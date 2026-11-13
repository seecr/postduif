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

import base64
import email
import email.policy
import email.utils

import pytest

from .message import InlineImage, Mail, build_message, html_with_images

SENDER = "Example <noreply@example.org>"
LOGO = InlineImage(
    cid="logo@example.org",
    filename="logo.png",
    content_type="image/png",
    data=b"\x89PNG-logo",
)


def parse(message):
    return email.message_from_bytes(message.as_bytes(), policy=email.policy.default)


def test_text_and_html():
    mail = Mail(
        "ann@example.org",
        "Your order",
        "text",
        "<p>html</p>",
        reply_to="shop@example.org",
        tag="order",
    )
    message = parse(build_message(SENDER, mail))
    assert message["From"] == SENDER
    assert message["To"] == "ann@example.org"
    assert message["Subject"] == "Your order"
    assert message["Reply-To"] == "shop@example.org"
    assert message["X-Postal-Tag"] == "order"
    assert message["Message-ID"].endswith("@example.org>")
    assert message.get_content_type() == "multipart/alternative"
    assert (
        message.get_body(("plain",)).get_content().rstrip() == "text"
    )  # CRLF: as sent over SMTP
    assert message.get_body(("html",)).get_content().rstrip() == "<p>html</p>"


def test_without_reply_to_and_tag():
    message = parse(
        build_message(SENDER, Mail("ann@example.org", "Hello", "text", "<p>html</p>"))
    )
    assert "Reply-To" not in message
    assert "X-Postal-Tag" not in message


def test_text_only():
    message = parse(build_message(SENDER, Mail("ann@example.org", "Hello", "just text")))
    assert message.get_content_type() == "text/plain"
    assert message.get_content().rstrip() == "just text"


def test_date_is_utc():
    message = parse(build_message(SENDER, Mail("ann@example.org", "Hello", "text")))
    assert message["Date"].endswith(" +0000")
    assert (
        email.utils.parsedate_to_datetime(message["Date"]).utcoffset().total_seconds()
        == 0
    )


def test_every_message_its_own_message_id():
    mail = Mail("ann@example.org", "Hello", "text")
    first, second = build_message(SENDER, mail), build_message(SENDER, mail)
    assert first["Message-ID"] != second["Message-ID"]
    assert first["References"] is None


def test_an_inline_image():
    mail = Mail(
        "ann@example.org",
        "Hello",
        "text",
        '<p><img src="cid:logo@example.org"></p>',
        images=[LOGO],
    )
    assert mail.images == (LOGO,)
    message = parse(build_message(SENDER, mail))
    assert message.get_content_type() == "multipart/alternative"
    plain, related = message.get_payload()
    assert plain.get_content_type() == "text/plain"
    assert related.get_content_type() == "multipart/related"
    html, image = related.get_payload()
    assert html.get_content_type() == "text/html"
    assert (image.get_content_type(), image["Content-ID"]) == (
        "image/png",
        "<logo@example.org>",
    )
    assert image.get_content_disposition() == "inline"
    assert image.get_filename() == "logo.png"
    assert image.get_content() == b"\x89PNG-logo"


def test_images_need_html():
    with pytest.raises(ValueError, match="images need html"):
        Mail("ann@example.org", "Hello", "text", images=[LOGO])


@pytest.mark.parametrize(
    "subject", ["Hello\nBcc: eve@example.org", "Hello\rBcc: eve@example.org"]
)
def test_a_header_that_cannot_be_one_raises(subject):
    with pytest.raises(ValueError):
        build_message(SENDER, Mail("ann@example.org", subject, "text"))


def test_extra_headers():
    mail = Mail(
        "ann@example.org", "Hello", "text", headers={"Auto-Submitted": "auto-generated"}
    )
    assert mail.headers == (("Auto-Submitted", "auto-generated"),)
    assert parse(build_message(SENDER, mail))["Auto-Submitted"] == "auto-generated"


@pytest.mark.parametrize(
    "name", ["To", "subject", "Message-ID", "X-Postal-Tag", "content-type"]
)
def test_extra_headers_cannot_replace_its_own(name):
    with pytest.raises(ValueError, match="set by postduif"):
        Mail("ann@example.org", "Hello", "text", headers={name: "x"})


def test_html_with_images():
    html = '<img src="cid:logo@example.org" alt="">'
    data = base64.b64encode(b"\x89PNG-logo").decode()
    assert (
        html_with_images(html, [LOGO])
        == f'<img src="data:image/png;base64,{data}" alt="">'
    )


def test_inline_image_from_file(tmp_path):
    path = tmp_path / "logo.png"
    path.write_bytes(b"\x89PNG-logo")
    image = InlineImage.from_file(path, cid="logo@example.org")
    assert image == LOGO
    assert "PNG" not in repr(image)
    assert (
        InlineImage.from_file(
            str(path), cid="logo@example.org", content_type="image/x-test"
        ).content_type
        == "image/x-test"
    )


def test_inline_image_from_bytes():
    assert (
        InlineImage.from_bytes(
            bytearray(b"\x89PNG-logo"), cid="logo@example.org", filename="logo.png"
        )
        == LOGO
    )
    with pytest.raises(ValueError, match="no content type known"):
        InlineImage.from_bytes(b"x", cid="x@example.org", filename="logo")


@pytest.mark.parametrize(
    "cid", ["", "<logo@example.org>", "logo @example.org", "logo\n@example.org"]
)
def test_inline_image_bad_cid(cid):
    with pytest.raises(ValueError, match="cid"):
        InlineImage(cid=cid, filename="logo.png", content_type="image/png", data=b"")


def test_inline_image_bad_content_type():
    with pytest.raises(ValueError, match="content_type"):
        InlineImage(
            cid="logo@example.org", filename="logo.png", content_type="png", data=b""
        )


def test_as_dict():
    mail = Mail(
        "ann@example.org",
        "Hello",
        "text",
        "<p>html</p>",
        tag="order",
        images=[LOGO],
        headers={"Auto-Submitted": "auto-generated"},
    )
    assert mail.as_dict() == {
        "to": "ann@example.org",
        "subject": "Hello",
        "text": "text",
        "html": "<p>html</p>",
        "reply_to": "",
        "tag": "order",
        "images": [
            {
                "cid": "logo@example.org",
                "filename": "logo.png",
                "content_type": "image/png",
                "data": base64.b64encode(b"\x89PNG-logo").decode(),
            }
        ],
        "headers": {"Auto-Submitted": "auto-generated"},
    }
