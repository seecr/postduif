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

import json
import re

import pytest

from .config import MailConfig, MailConfigError

POSTAL = {
    "postal_url": "https://postal.example.org/",
    "api_key": "secret",
    "sender": "Example <noreply@example.org>",
    "base_url": "https://example.org/",
    "timeout": 10,
}


def write(tmp_path, values):
    path = tmp_path / "mail.json"
    path.write_text(values if isinstance(values, str) else json.dumps(values))
    return path


def test_no_file_means_no_mail(tmp_path):
    assert MailConfig.read(tmp_path / "mail.json") is None


def test_postal(tmp_path):
    config = MailConfig.read(write(tmp_path, POSTAL))
    assert config == MailConfig(
        transport="postal",
        sender="Example <noreply@example.org>",
        base_url="https://example.org",
        postal_url="https://postal.example.org",
        api_key="secret",
        timeout=10,
    )
    assert config.can_link
    assert config.describe() == (
        "Mail: to Postal at https://postal.example.org,"
        " from Example <noreply@example.org>,"
        " links to https://example.org"
    )
    assert "secret" not in repr(config)


def test_timeout_is_optional():
    values = {key: value for key, value in POSTAL.items() if key != "timeout"}
    assert MailConfig.from_dict(values).timeout == 10


def test_base_url_is_optional():
    values = {key: value for key, value in POSTAL.items() if key != "base_url"}
    config = MailConfig.from_dict(values)
    assert (config.base_url, config.can_link) == ("", False)
    assert config.describe().endswith(", no links (no base_url)")


def test_outbox_and_redirect():
    config = MailConfig.from_dict(
        {
            "transport": "outbox",
            "sender": "noreply@example.org",
            "base_url": "http://127.0.0.1:8000",
            "redirect_to": "test@example.org",
        }
    )
    assert (config.transport, config.postal_url, config.api_key, config.redirect_to) == (
        "outbox",
        "",
        "",
        "test@example.org",
    )
    assert config.describe() == (
        "Mail: to the outbox (no mail is sent; the newest 50, at most 7 days),"
        " from noreply@example.org,"
        " links to http://127.0.0.1:8000,"
        " all mail redirected to test@example.org"
    )


def test_outbox_keep_and_days():
    config = MailConfig.from_dict(POSTAL)
    assert (config.outbox_keep, config.outbox_days) == (50, 7)
    config = MailConfig.from_dict(POSTAL | {"outbox_keep": 3, "outbox_days": 0.5})
    assert (config.outbox_keep, config.outbox_days) == (3, 0.5)


def without(key):
    return {k: v for k, v in POSTAL.items() if k != key}


@pytest.mark.parametrize(
    "values, message",
    [
        ("{not good", "not valid JSON"),
        ([], "expected a JSON object"),
        (POSTAL | {"server": "x"}, r"unknown keys \['server'\]"),
        (POSTAL | {"api_key": 12}, "'api_key' must be a string"),
        (POSTAL | {"transport": "smtp"}, "'transport' must be one of"),
        (POSTAL | {"sender": "Example"}, "'sender' must be an e-mail address"),
        (POSTAL | {"sender": "Example <noreply@>"}, "'sender' must be an e-mail address"),
        (
            POSTAL | {"sender": "noreply@example.org\nBcc: eve@example.org"},
            "'sender' must be an e-mail address",
        ),
        (without("sender"), "'sender' must be an e-mail address"),
        (POSTAL | {"base_url": "example.org"}, "'base_url' must be where the site is"),
        (
            POSTAL | {"base_url": "ftp://example.org"},
            "'base_url' must be where the site is",
        ),
        (POSTAL | {"base_url": "https://"}, "'base_url' must be where the site is"),
        (
            POSTAL | {"base_url": "https://example.org/?a=1"},
            "'base_url' must be where the site is",
        ),
        (POSTAL | {"base_url": 5}, "'base_url' must be a string"),
        (POSTAL | {"postal_url": "postal.example.org"}, "'postal_url' must be the URL"),
        (without("postal_url"), "'postal_url' must be the URL"),
        (POSTAL | {"api_key": " "}, "'api_key' is required"),
        (POSTAL | {"timeout": "10"}, "'timeout' must be a number of seconds"),
        (POSTAL | {"timeout": 0}, "'timeout' must be a number of seconds"),
        (POSTAL | {"timeout": True}, "'timeout' must be a number of seconds"),
        (POSTAL | {"redirect_to": "ann"}, "'redirect_to' must be an e-mail address"),
        (POSTAL | {"redirect_to": 42}, "'redirect_to' must be a string"),
        (POSTAL | {"outbox_keep": 0}, "'outbox_keep' must be a number of mails"),
        (POSTAL | {"outbox_keep": "10"}, "'outbox_keep' must be a number of mails"),
        (POSTAL | {"outbox_keep": 2.5}, "'outbox_keep' must be a number of mails"),
        (POSTAL | {"outbox_days": 0}, "'outbox_days' must be a number of days"),
        (POSTAL | {"outbox_days": True}, "'outbox_days' must be a number of days"),
    ],
)
def test_errors(tmp_path, values, message):
    path = write(tmp_path, values)
    with pytest.raises(MailConfigError) as error:
        MailConfig.read(path)
    assert str(error.value).startswith(f"{path}: ")
    assert re.search(message, str(error.value))
    assert "secret" not in str(error.value)


def test_from_dict_names_its_source():
    with pytest.raises(
        MailConfigError, match="^mail config: 'sender' must be an e-mail address"
    ):
        MailConfig.from_dict(POSTAL | {"sender": "x"})
    with pytest.raises(MailConfigError, match="^settings: "):
        MailConfig.from_dict(POSTAL | {"sender": "x"}, source="settings")


def test_mail_config_error_is_a_value_error():
    assert issubclass(MailConfigError, ValueError)


def test_outbox_needs_no_postal():
    config = MailConfig.from_dict(
        {"transport": "outbox", "sender": "noreply@example.org"}
    )
    assert (config.postal_url, config.api_key, config.can_link) == ("", "", False)
