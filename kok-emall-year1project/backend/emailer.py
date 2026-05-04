from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr


class EmailDeliveryError(RuntimeError):
    pass


def _env_flag(name: str, default: bool) -> bool:
    value = str(os.environ.get(name, "")).strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "no", "off"}


def send_registration_verification_email(
    *,
    to_email: str,
    code: str,
    expires_minutes: int,
    recipient_name: str | None = None,
) -> None:
    host = str(os.environ.get("SMTP_HOST", "")).strip()
    from_email = str(os.environ.get("SMTP_FROM_EMAIL", "")).strip()
    if not host or not from_email:
        raise EmailDeliveryError("Email verification is not configured yet. Set SMTP_HOST and SMTP_FROM_EMAIL first.")

    port = int(str(os.environ.get("SMTP_PORT", "587")).strip() or "587")
    username = str(os.environ.get("SMTP_USERNAME", "")).strip()
    password = str(os.environ.get("SMTP_PASSWORD", ""))
    from_name = str(os.environ.get("SMTP_FROM_NAME", "KOK-eMall")).strip() or "KOK-eMall"
    use_ssl = _env_flag("SMTP_USE_SSL", port == 465)
    use_tls = _env_flag("SMTP_USE_TLS", not use_ssl)

    message = EmailMessage()
    message["Subject"] = "Your KOK-eMall verification code"
    message["From"] = formataddr((from_name, from_email))
    message["To"] = to_email

    greeting_name = recipient_name or "there"
    message.set_content(
        "\n".join(
            [
                f"Hello {greeting_name},",
                "",
                "Your KOK-eMall verification code is:",
                code,
                "",
                f"This code expires in {expires_minutes} minutes.",
                "If you did not request this code, you can ignore this email.",
            ]
        )
    )

    context = ssl.create_default_context()
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                if username:
                    server.login(username, password)
                server.send_message(message)
            return

        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            if use_tls:
                server.starttls(context=context)
                server.ehlo()
            if username:
                server.login(username, password)
            server.send_message(message)
    except EmailDeliveryError:
        raise
    except Exception as exc:
        raise EmailDeliveryError("Failed to send verification email. Please try again.") from exc
