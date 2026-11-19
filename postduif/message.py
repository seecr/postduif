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

"""The mail itself: what to send (Mail, InlineImage, Attachment) and the MIME message
made of it.

    mail = Mail(to="ann@example.org", subject="Your order", text="...", html="<p>...</p>",
                images=(InlineImage.from_file(path, cid="logo@example.org"),),
                attachments=(Attachment.from_bytes(pdf, "invoice.pdf"),))
    message = build_message("Example <noreply@example.org>", mail)   # an EmailMessage

A mail is text and, optionally, HTML as alternatives. Images go inside the mail
(InlineImage) and the HTML shows them with <img src="cid:...">: no links to images
elsewhere, so nothing to block and nothing that tells a server the mail was opened.
Attachments are files that come with the mail (a PDF, say), with or without HTML.
"""

import base64
import dataclasses
import datetime
import email.message
import email.policy
import email.utils
import mimetypes
import pathlib

# headers build_message sets itself; Mail.headers may not set them too
OWN_HEADERS = frozenset(
    name.lower()
    for name in (
        "From",
        "To",
        "Subject",
        "Date",
        "Message-ID",
        "Reply-To",
        "X-Postal-Tag",
        "MIME-Version",
        "Content-Type",
        "Content-Transfer-Encoding",
    )
)


@dataclasses.dataclass(frozen=True)
class InlineImage:
    """An image inside a mail; the HTML shows it with <img src="cid:{cid}">."""

    cid: str  # e.g. "logo@example.org"
    filename: str
    content_type: str  # e.g. "image/png"
    data: bytes = dataclasses.field(repr=False)

    def __post_init__(self):
        if not self.cid or any(c in self.cid for c in "<>\r\n \t"):
            raise ValueError(
                f"cid {self.cid!r}: not empty, without <, >, spaces or line breaks"
            )
        _check_content_type(self.content_type, "image/png")

    @classmethod
    def from_file(cls, path, cid, content_type=None):
        """The image in a file; the content type is guessed from its name if not given."""
        path = pathlib.Path(path)
        return cls.from_bytes(
            path.read_bytes(), cid=cid, filename=path.name, content_type=content_type
        )

    @classmethod
    def from_bytes(cls, data, cid, filename, content_type=None):
        return cls(
            cid=cid,
            filename=filename,
            content_type=content_type or _guess_content_type(filename),
            data=bytes(data),
        )

    @property
    def data_url(self):
        """The image as a data: URL, to show the mail in a browser."""
        return f"data:{self.content_type};base64,{base64.b64encode(self.data).decode()}"


def _guess_content_type(filename):
    content_type = mimetypes.guess_type(filename)[0]
    if content_type is None:
        raise ValueError(f"no content type known for {filename!r}; give content_type")
    return content_type


def _check_content_type(content_type, example):
    maintype, _, subtype = content_type.partition("/")
    if not (maintype and subtype):
        raise ValueError(f"content_type {content_type!r}: expected e.g. {example!r}")


@dataclasses.dataclass(frozen=True)
class Attachment:
    """A file that comes with a mail, e.g. a PDF."""

    filename: str  # what the addressee sees, e.g. "invoice-2026-001.pdf"
    content_type: str  # e.g. "application/pdf"
    data: bytes = dataclasses.field(repr=False)

    def __post_init__(self):
        if not self.filename or any(c in self.filename for c in "\r\n/\\"):
            raise ValueError(
                f"filename {self.filename!r}: not empty, without line breaks or slashes"
            )
        _check_content_type(self.content_type, "application/pdf")

    @classmethod
    def from_file(cls, path, filename=None, content_type=None):
        """The file at path, by default with its own name; the content type is guessed
        from the name if not given."""
        path = pathlib.Path(path)
        return cls.from_bytes(
            path.read_bytes(), filename=filename or path.name, content_type=content_type
        )

    @classmethod
    def from_bytes(cls, data, filename, content_type=None):
        return cls(
            filename=filename,
            content_type=content_type or _guess_content_type(filename),
            data=bytes(data),
        )


@dataclasses.dataclass(frozen=True)
class Mail:
    """One mail to one addressee.

    html is optional: without it the mail is only text (and can have no images). tag is
    for the mail server, to find mails of one kind (Postal's X-Postal-Tag). headers are
    extra headers, e.g. {"Auto-Submitted": "auto-generated"} or a List-Unsubscribe."""

    to: str
    subject: str
    text: str
    html: str = ""
    reply_to: str = ""
    tag: str = ""
    images: tuple = ()  # InlineImage
    headers: tuple = ()  # (name, value) pairs; a dict is accepted
    attachments: tuple = ()  # Attachment

    def __post_init__(self):
        object.__setattr__(self, "images", tuple(self.images))
        object.__setattr__(self, "attachments", tuple(self.attachments))
        headers = self.headers.items() if hasattr(self.headers, "items") else self.headers
        object.__setattr__(
            self, "headers", tuple((str(name), str(value)) for name, value in headers)
        )
        if self.images and not self.html:
            raise ValueError("images need html to show them")
        for name, _ in self.headers:
            if name.lower() in OWN_HEADERS:
                raise ValueError(
                    f"header {name!r} is set by postduif; use the Mail field instead"
                )

    def as_dict(self):
        """As JSON, e.g. for an outbox, with the images base64-encoded."""
        values = {
            field.name: getattr(self, field.name) for field in dataclasses.fields(self)
        }
        values["images"] = [
            dict(
                cid=image.cid,
                filename=image.filename,
                content_type=image.content_type,
                data=base64.b64encode(image.data).decode(),
            )
            for image in self.images
        ]
        values["headers"] = dict(self.headers)
        values["attachments"] = [
            dict(
                filename=attachment.filename,
                content_type=attachment.content_type,
                data=base64.b64encode(attachment.data).decode(),
            )
            for attachment in self.attachments
        ]
        return values

    @classmethod
    def from_dict(cls, values):
        """The Mail of as_dict(); other keys are left out, so a mail from the outbox (with
        from, message_id and sent_at) can be given as it is."""
        fields = {f.name for f in dataclasses.fields(cls)}
        values = {key: value for key, value in values.items() if key in fields}
        values["images"] = [
            InlineImage(**image | {"data": base64.b64decode(image["data"])})
            for image in values.get("images", ())
        ]
        values["attachments"] = [
            Attachment(**attachment | {"data": base64.b64decode(attachment["data"])})
            for attachment in values.get("attachments", ())
        ]
        return cls(**values)


def build_message(sender, mail):
    """The MIME message of a mail.

    Text only: text/plain. With HTML: multipart/alternative with the text and the HTML,
    and the HTML with its images in a multipart/related. With attachments, that is the
    first part of a multipart/mixed, the attachments the next. The Message-ID is on the
    domain of the sender; the Date is in UTC, whatever the time zone of the server.

    Raises ValueError for a header that cannot be one (a line break in the subject, say),
    so a value from a visitor cannot add headers of its own."""
    message = email.message.EmailMessage(policy=email.policy.SMTP)
    message["From"] = sender
    message["To"] = mail.to
    message["Subject"] = mail.subject
    message["Date"] = email.utils.format_datetime(
        datetime.datetime.now(datetime.timezone.utc)
    )
    domain = email.utils.parseaddr(sender)[1].rpartition("@")[2]
    message["Message-ID"] = email.utils.make_msgid(domain=domain or None)
    if mail.reply_to:
        message["Reply-To"] = mail.reply_to
    if mail.tag:
        message["X-Postal-Tag"] = mail.tag
    for name, value in mail.headers:
        message[name] = value
    message.set_content(mail.text)
    if mail.html:
        message.add_alternative(mail.html, subtype="html")
        html_part = message.get_payload()[1]
        for image in mail.images:
            maintype, _, subtype = image.content_type.partition("/")
            html_part.add_related(
                image.data,
                maintype=maintype,
                subtype=subtype,
                cid=f"<{image.cid}>",
                filename=image.filename,
                disposition="inline",
            )
    for attachment in mail.attachments:
        maintype, _, subtype = attachment.content_type.partition("/")
        message.add_attachment(
            attachment.data,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )
    return message


def html_with_images(html, images):
    """The HTML of a mail with its cid: images as data: URLs, to show it in a browser."""
    for image in images:
        html = html.replace(f"cid:{image.cid}", image.data_url)
    return html
