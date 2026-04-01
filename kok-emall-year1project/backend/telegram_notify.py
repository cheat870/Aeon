from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


def _token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _chat_ids() -> list[str]:
    raw = os.environ.get("TELEGRAM_ADMIN_IDS", "").strip()
    if not raw:
        return []

    values: list[str] = []
    for part in raw.split(","):
        part = part.strip().strip('"').strip("'")
        if part:
            values.append(part)
    return values


def _post_message(token: str, chat_id: str, text: str) -> None:
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        json.loads(resp.read().decode("utf-8"))


def send_auth_event(event_name: str, user: dict[str, Any], *, ip_address: str | None = None) -> None:
    token = _token()
    chat_ids = _chat_ids()
    if not token or not chat_ids:
        return

    lines = [
        "KOK-eMall auth event",
        f"Event: {event_name}",
        f"User ID: {user.get('id')}",
        f"Email: {user.get('email')}",
        f"Name: {user.get('name') or '-'}",
        f"Status: {user.get('status') or '-'}",
        f"At: {user.get('last_login_at') or user.get('last_logout_at') or user.get('created_at') or '-'}",
    ]
    if ip_address:
        lines.append(f"IP: {ip_address}")
    message = "\n".join(lines)

    for chat_id in chat_ids:
        try:
            _post_message(token, chat_id, message)
        except Exception:
            continue


def send_payment_event(
    event_name: str,
    *,
    order: dict[str, Any],
    payment: dict[str, Any],
    extra_lines: list[str] | None = None,
) -> None:
    token = _token()
    chat_ids = _chat_ids()
    if not token or not chat_ids:
        return

    lines = [
        "KOK-eMall payment event",
        f"Event: {event_name}",
        f"Order ID: {order.get('id')}",
        f"Status: {order.get('status') or '-'}",
        f"Amount: {((int(payment.get('amount_cents', 0)) / 100) if payment.get('currency', 'USD') != 'KHR' else int(round(int(payment.get('amount_cents', 0)) / 100)))} {payment.get('currency') or order.get('currency') or 'USD'}",
        f"Provider: {payment.get('provider') or '-'}",
        f"Ref: {payment.get('provider_ref') or '-'}",
        f"At: {order.get('paid_at') or payment.get('updated_at') or payment.get('created_at') or '-'}",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    message = "\n".join(lines)

    for chat_id in chat_ids:
        try:
            _post_message(token, chat_id, message)
        except Exception:
            continue
