"""Real outbound email -- the ONLY module in this codebase that actually
sends anything over the network. Plain stdlib `smtplib` + `email.mime`;
there's no existing mail infra anywhere else in this repo to reuse (see
app/services/correction_email.py's old docstring, which explicitly said so
before this module existed).

Every caller must go through `send_email` below -- never construct/send a
message anywhere else, so there's exactly one place that knows how SMTP
auth/TLS/attachments work, and exactly one place a future real provider
swap (SES, SendGrid SMTP relay, etc.) would touch.
"""
from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.config import settings


class MailerNotConfigured(RuntimeError):
    """Raised before any network call is attempted -- `settings.smtp_host`
    is unset, meaning no real mail server has ever been configured in this
    environment. Distinct from MailerSendFailed (below) so a caller/UI can
    tell "nobody's set this up yet" apart from "we tried and the real
    server rejected it" -- those need different responses to a user."""


class MailerSendFailed(RuntimeError):
    """Raised when SMTP is configured but the actual send failed (auth
    rejected, connection refused, recipient rejected, etc.) -- wraps
    whatever smtplib raised, with its message preserved so the real cause
    is visible to whoever reads send_error, not swallowed into a generic
    string."""


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime_type: str = "application/pdf"


def send_email(
    *,
    to_addr: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    from_addr: str | None = None,
    from_name: str | None = None,
    attachments: list[Attachment] | None = None,
) -> None:
    """Sends one real email via SMTP. Raises MailerNotConfigured if
    `settings.smtp_host` is unset -- never silently no-ops, since a caller
    treating "didn't raise" as "sent" would otherwise be lied to. Raises
    MailerSendFailed on any real SMTP-level failure (auth, connection,
    recipient rejection). Returns normally only when the message was
    actually handed to the SMTP server and accepted.

    `to_addr` is required and must be non-empty -- there is nobody to
    reject as a recipient at the SMTP layer if it's blank, which would
    otherwise look like a successful send of nothing to nobody.

    `html_body` (deployment round): optional real HTML alternative.
    `body` (plain text) is ALWAYS sent regardless -- `None` here just
    means "plain-text only," the exact behavior every pre-existing caller
    still gets unchanged. When given, `EmailMessage.add_alternative`
    turns this into a real multipart/alternative message (plain text +
    HTML, same content, client picks whichever it can render) -- every
    real email client honors this standard MIME structure; there's no
    plain-text-only client left that would be worse off than before,
    since the plain part is identical to what was already being sent.
    """
    if not settings.smtp_host:
        raise MailerNotConfigured(
            "No SMTP server configured (settings.smtp_host is unset) -- outbound email has never been set up "
            "in this environment. Set smtp_host/smtp_port/smtp_username/smtp_password in .env to enable real "
            "sending."
        )
    if not to_addr or not to_addr.strip():
        raise MailerSendFailed("Cannot send: no recipient (\"to\" address) was provided.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>" if from_name and from_addr else (from_addr or settings.smtp_username or "no-reply@localhost")
    msg["To"] = to_addr
    if cc:
        msg["Cc"] = cc
    msg.set_content(body)
    if html_body:
        # Must come AFTER set_content and BEFORE any add_attachment calls
        # below -- this is what makes the message multipart/alternative
        # (plain + HTML) with attachments layered on top as multipart/mixed,
        # the standard MIME shape every real client expects.
        msg.add_alternative(html_body, subtype="html")

    for att in attachments or []:
        maintype, _, subtype = att.mime_type.partition("/")
        msg.add_attachment(att.content, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=att.filename)

    all_recipients = [to_addr] + ([a.strip() for a in cc.split(",") if a.strip()] if cc else []) + \
        ([a.strip() for a in bcc.split(",") if a.strip()] if bcc else [])

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg, to_addrs=all_recipients)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailerSendFailed(f"{type(exc).__name__}: {exc}") from exc
