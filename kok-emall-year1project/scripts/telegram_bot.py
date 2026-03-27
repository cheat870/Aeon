from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = _project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from backend import create_app  # noqa: E402
from backend.extensions import db  # noqa: E402
from backend.models import Order, OrderItem, Payment, User, utcnow  # noqa: E402


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return ids


def _money(amount_cents: int, currency: str) -> str:
    if currency.upper() == "KHR":
        # For display only; store stays cents.
        return f"{currency} {int(round(amount_cents / 100)):,}"
    return f"{currency} {amount_cents / 100:.2f}"


def _tg_api_base(token: str) -> str:
    return f"https://api.telegram.org/bot{token}"


def _tg_get(token: str, method: str, params: dict[str, object] | None = None, timeout_s: int = 80) -> dict:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params, doseq=True)
    url = f"{_tg_api_base(token)}/{method}{query}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _tg_post(token: str, method: str, data: dict[str, object], timeout_s: int = 20) -> dict:
    payload = urllib.parse.urlencode(data).encode("utf-8")
    url = f"{_tg_api_base(token)}/{method}"
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _split_message(text: str, limit: int = 3800) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(True):
        if current_len + len(line) > limit and current:
            parts.append("".join(current).rstrip())
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        parts.append("".join(current).rstrip())
    return parts


def _send_text(token: str, chat_id: int, text: str) -> None:
    for chunk in _split_message(text):
        _tg_post(token, "sendMessage", {"chat_id": chat_id, "text": chunk})


def _help_text() -> str:
    return "\n".join(
        [
            "KOK-eMall Admin Bot",
            "",
            "Commands:",
            "/myid - show your Telegram user id",
            "/pending - list latest pending_payment orders (admin)",
            "/invoice <order_id> - show invoice details (admin)",
            "/confirm <order_id> [provider_ref] - mark order as paid (admin)",
            "/help - show this help",
        ]
    )


def _ensure_admin(token: str, chat_id: int, user_id: int, admin_ids: set[int]) -> bool:
    if not admin_ids:
        _send_text(
            token,
            chat_id,
            "Admin is not configured. Set TELEGRAM_ADMIN_IDS in .env (comma-separated user IDs). Use /myid to get yours.",
        )
        return False
    if user_id not in admin_ids:
        _send_text(token, chat_id, "Unauthorized.")
        return False
    return True


def _cmd_pending() -> str:
    rows = (
        db.session.query(Order, User)
        .join(User, User.id == Order.user_id)
        .filter(Order.status == "pending_payment")
        .order_by(Order.created_at.desc())
        .limit(15)
        .all()
    )
    if not rows:
        return "No pending_payment orders."

    lines = ["Pending orders (latest):"]
    for order, user in rows:
        lines.append(
            f"- #{order.id} | {_money(order.total_cents, order.currency)} | {user.email} | created {order.created_at.isoformat()}"
        )
    return "\n".join(lines)


def _cmd_invoice(order_id: int) -> str:
    order = Order.query.filter_by(id=order_id).first()
    if not order:
        return "Order not found."

    user = User.query.filter_by(id=order.user_id).first()
    items = OrderItem.query.filter_by(order_id=order.id).order_by(OrderItem.id.asc()).all()
    payment = Payment.query.filter_by(order_id=order.id).order_by(Payment.created_at.desc()).first()

    lines: list[str] = []
    lines.append(f"Invoice: Order #{order.id}")
    lines.append(f"Status: {order.status}")
    if user:
        lines.append(f"Customer: {user.email}")
    lines.append(f"Created: {order.created_at.isoformat()}")
    if order.paid_at:
        lines.append(f"Paid: {order.paid_at.isoformat()}")
    lines.append("")
    lines.append(f"Subtotal: {_money(order.subtotal_cents, order.currency)}")
    lines.append(f"Shipping: {_money(order.shipping_cents, order.currency)}")
    lines.append(f"Total: {_money(order.total_cents, order.currency)}")
    lines.append("")
    lines.append("Items:")
    if not items:
        lines.append("- (none)")
    for i in items:
        unit = _money(i.unit_price_cents, order.currency)
        line_total = _money(i.line_total_cents, order.currency)
        brand = f" ({i.product_brand})" if i.product_brand else ""
        lines.append(f"- {i.product_name}{brand} x{i.quantity} @ {unit} = {line_total}")
    if payment:
        lines.append("")
        lines.append("Payment:")
        lines.append(f"- Provider: {payment.provider}")
        lines.append(f"- Amount: {_money(payment.amount_cents, payment.currency)}")
        if payment.provider_ref:
            lines.append(f"- Ref: {payment.provider_ref}")
        lines.append(f"- Status: {payment.status}")
        lines.append(f"- At: {payment.created_at.isoformat()}")
    else:
        lines.append("")
        lines.append("Payment: (none)")
    return "\n".join(lines)


def _cmd_confirm(order_id: int, provider_ref: str | None) -> str:
    order = Order.query.filter_by(id=order_id).first()
    if not order:
        return "Order not found."
    if order.status == "paid":
        return f"Order #{order.id} is already paid."
    if order.status != "pending_payment":
        return f"Order #{order.id} is not payable (status={order.status})."

    order.status = "paid"
    order.paid_at = utcnow()
    payment = Payment(
        order_id=order.id,
        provider="aba_khqr",
        status="succeeded",
        amount_cents=order.total_cents,
        currency=order.currency,
        provider_ref=(provider_ref or "").strip() or f"aba-{order.id}",
    )
    db.session.add(payment)
    db.session.commit()
    return f"Confirmed paid: Order #{order.id}."


def _load_offset_state() -> tuple[Path, int]:
    state_path = PROJECT_ROOT / "backend" / "instance" / "telegram_bot_offset.txt"
    try:
        raw = state_path.read_text(encoding="utf-8").strip()
        if raw:
            return state_path, int(raw)
    except Exception:
        pass
    return state_path, 0


def _save_offset_state(state_path: Path, offset: int) -> None:
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(str(offset), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    app = create_app()
    app.app_context().push()

    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Missing TELEGRAM_BOT_TOKEN. Copy .env.example -> .env and set TELEGRAM_BOT_TOKEN.")
        return 2

    admin_ids = _parse_admin_ids(_env("TELEGRAM_ADMIN_IDS"))

    state_path, offset = _load_offset_state()
    print("Telegram bot running. Press Ctrl+C to stop.")

    while True:
        try:
            resp = _tg_get(token, "getUpdates", {"timeout": 60, "offset": offset}, timeout_s=80)
            if not resp.get("ok"):
                time.sleep(2)
                continue

            updates = resp.get("result") or []
            for upd in updates:
                try:
                    update_id = int(upd.get("update_id"))
                except Exception:
                    continue

                offset = max(offset, update_id + 1)
                _save_offset_state(state_path, offset)

                message = upd.get("message") or {}
                text = (message.get("text") or "").strip()
                if not text:
                    continue

                chat_id = int((message.get("chat") or {}).get("id"))
                user_id = int((message.get("from") or {}).get("id"))

                cmd, *args = text.split()
                if not cmd.startswith("/"):
                    continue
                cmd = cmd.split("@", 1)[0].lower()

                if cmd in ("/start", "/help"):
                    _send_text(token, chat_id, _help_text())
                    continue

                if cmd == "/myid":
                    username = (message.get("from") or {}).get("username") or ""
                    who = f"@{username} " if username else ""
                    _send_text(token, chat_id, f"Your Telegram user id: {user_id}\nChat id: {chat_id}\n{who}".strip())
                    continue

                if cmd == "/pending":
                    if not _ensure_admin(token, chat_id, user_id, admin_ids):
                        continue
                    _send_text(token, chat_id, _cmd_pending())
                    continue

                if cmd == "/invoice":
                    if not _ensure_admin(token, chat_id, user_id, admin_ids):
                        continue
                    if not args:
                        _send_text(token, chat_id, "Usage: /invoice <order_id>")
                        continue
                    try:
                        order_id = int(args[0])
                    except ValueError:
                        _send_text(token, chat_id, "order_id must be a number.")
                        continue
                    _send_text(token, chat_id, _cmd_invoice(order_id))
                    continue

                if cmd == "/confirm":
                    if not _ensure_admin(token, chat_id, user_id, admin_ids):
                        continue
                    if not args:
                        _send_text(token, chat_id, "Usage: /confirm <order_id> [provider_ref]")
                        continue
                    try:
                        order_id = int(args[0])
                    except ValueError:
                        _send_text(token, chat_id, "order_id must be a number.")
                        continue
                    provider_ref = args[1] if len(args) > 1 else None
                    _send_text(token, chat_id, _cmd_confirm(order_id, provider_ref))
                    continue

                _send_text(token, chat_id, "Unknown command. Use /help")

        except KeyboardInterrupt:
            print("Stopping.")
            return 0
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
                print(f"Telegram HTTPError: {e.code} {body}")
            except Exception:
                print(f"Telegram HTTPError: {e}")
            time.sleep(2)
        except urllib.error.URLError as e:
            print(f"Telegram URLError: {e}")
            time.sleep(2)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())

