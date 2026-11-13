# Changelog

## Unreleased

- Empty package: project layout, CI, publishing to PyPI on a version tag.
- `Mail`, `InlineImage`, `build_message` and `html_with_images` (`postduif.message`): the MIME
  message, text-only or text and HTML with inline `cid:` images, extra headers, `Date` in UTC,
  `Message-ID` on the sender's domain; a line break in a header raises `ValueError`.
- `MailConfig` and `MailConfigError` (`postduif.config`): `MailConfig.read(path)` (None when the
  file is missing), `from_dict` with checks per key, `describe()` for the log. `base_url` is
  optional (`can_link`).
