from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from urllib import error as urllib_error
from urllib import request as urllib_request


class EmailDeliveryError(RuntimeError):
    pass


def _env_flag(name: str, default: bool) -> bool:
    value = str(os.environ.get(name, "")).strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "no", "off"}


def _email_provider() -> str:
    configured = str(os.environ.get("EMAIL_PROVIDER", "")).strip().lower()
    if configured:
        return configured
    if str(os.environ.get("BREVO_API_KEY", "")).strip():
        return "brevo"
    if str(os.environ.get("RESEND_API_KEY", "")).strip():
        return "resend"
    return "smtp"


def _verification_subject() -> str:
    return "Your KOK-eMall verification code"


def _verification_text(*, code: str, expires_minutes: int, recipient_name: str | None = None) -> str:
    greeting_name = recipient_name or "there"
    return "\n".join(
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


def _verification_html(*, code: str, expires_minutes: int, recipient_name: str | None = None) -> str:
    greeting_name = recipient_name or "there"
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#111827;">
      <h2 style="margin:0 0 16px;color:#0f766e;">KOK-eMall verification</h2>
      <p style="font-size:16px;line-height:1.6;">Hello {greeting_name},</p>
      <p style="font-size:16px;line-height:1.6;">Use this 8-digit code to finish creating your account:</p>
      <div style="margin:24px 0;padding:18px 20px;background:#f0fdfa;border-radius:12px;border:1px solid #99f6e4;">
        <div style="font-size:32px;font-weight:700;letter-spacing:6px;color:#0f172a;text-align:center;">{code}</div>
      </div>
      <p style="font-size:15px;line-height:1.6;">This code expires in <strong>{expires_minutes} minutes</strong>.</p>
      <p style="font-size:14px;line-height:1.6;color:#6b7280;">If you did not request this code, you can ignore this email.</p>
    </div>
    """.strip()


def _send_via_resend(
    *,
    to_email: str,
    subject: str,
    text: str,
    html: str,
) -> None:
    api_key = str(os.environ.get("RESEND_API_KEY", "")).strip()
    from_email = str(
        os.environ.get("RESEND_FROM_EMAIL", "") or os.environ.get("SMTP_FROM_EMAIL", "")
    ).strip()
    from_name = str(
        os.environ.get("RESEND_FROM_NAME", "") or os.environ.get("SMTP_FROM_NAME", "KOK-eMall")
    ).strip() or "KOK-eMall"
    reply_to = str(os.environ.get("RESEND_REPLY_TO", "")).strip() or None

    # Resend requires onboarding@resend.dev unless sending from a verified custom domain
    if not from_email or "@gmail.com" in from_email.lower() or "@yahoo.com" in from_email.lower():
        from_email = "onboarding@resend.dev"

    if not api_key:
        raise EmailDeliveryError("Resend API key is not configured. Set RESEND_API_KEY first.")

    payload: dict[str, object] = {
        "from": formataddr((from_name, from_email)),
        "to": [to_email],
        "subject": subject,
        "text": text,
        "html": html,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    req = urllib_request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            response.read()
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {}
        message = str(parsed.get("message") or parsed.get("error") or "").strip()
        if exc.code == 403:
            raise EmailDeliveryError(
                "Resend Free restriction: You can only send to your own Resend account email (or verify a custom domain in Resend)."
            ) from exc
        raise EmailDeliveryError(message or "Failed to send verification email through Resend.") from exc
    except Exception as exc:
        raise EmailDeliveryError("Failed to send verification email through Resend.") from exc


def _send_via_brevo(
    *,
    to_email: str,
    subject: str,
    text: str,
    html: str,
) -> None:
    api_key = str(os.environ.get("BREVO_API_KEY", "")).strip()
    sender_email = str(
        os.environ.get("BREVO_SENDER_EMAIL", "") or os.environ.get("RESEND_FROM_EMAIL", "")
    ).strip()
    sender_name = str(os.environ.get("BREVO_SENDER_NAME", "KOK-eMall")).strip() or "KOK-eMall"

    if not api_key or not sender_email:
        raise EmailDeliveryError("Brevo email is not configured. Set BREVO_API_KEY and BREVO_SENDER_EMAIL.")

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    req = urllib_request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=20) as response:
            response.read()
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {}
        message = str(parsed.get("message") or "").strip()
        raise EmailDeliveryError(message or "Failed to send verification email through Brevo.") from exc
    except Exception as exc:
        raise EmailDeliveryError("Failed to send verification email through Brevo.") from exc


def _send_via_smtp(
    *,
    to_email: str,
    subject: str,
    text: str,
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
    message["Subject"] = subject
    message["From"] = formataddr((from_name, from_email))
    message["To"] = to_email
    message.set_content(text)

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
    except Exception as exc:
        raise EmailDeliveryError("Failed to send verification email. Please try again.") from exc


def send_registration_verification_email(
    *,
    to_email: str,
    code: str,
    expires_minutes: int,
    recipient_name: str | None = None,
) -> None:
    subject = _verification_subject()
    text = _verification_text(code=code, expires_minutes=expires_minutes, recipient_name=recipient_name)
    html = _verification_html(code=code, expires_minutes=expires_minutes, recipient_name=recipient_name)

    provider = _email_provider()
    if provider == "resend":
        _send_via_resend(to_email=to_email, subject=subject, text=text, html=html)
        return
    if provider == "brevo":
        _send_via_brevo(to_email=to_email, subject=subject, text=text, html=html)
        return
    if provider == "smtp":
        _send_via_smtp(to_email=to_email, subject=subject, text=text)
        return
    raise EmailDeliveryError("Unsupported email provider. Use EMAIL_PROVIDER=resend, brevo, or smtp.")
