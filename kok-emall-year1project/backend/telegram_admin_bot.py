from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from backend.store import (
    confirm_order_payment,
    get_order_details,
    get_store_stats,
    get_user_admin_details,
    list_auth_events,
    list_orders,
    list_pending_orders,
    list_users,
)

_BOT_THREAD: threading.Thread | None = None
_BOT_LOCK = threading.Lock()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = _project_root()


def _env(name: str) -> str:
    return os.environ.get(name, "").strip().strip('"').strip("'")


def _parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip().strip('"').strip("'")
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return ids


def _money(amount_cents: int, currency: str) -> str:
    if currency.upper() == "KHR":
        return f"{currency} {int(round(amount_cents / 100)):,}"
    return f"{currency} {amount_cents / 100:.2f}"


def _tg_api_base(token: str) -> str:
    return f"https://api.telegram.org/bot{token}"


def _tg_get(token: str, method: str, params: dict[str, object] | None = None, timeout_s: int = 80) -> dict:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(f"{_tg_api_base(token)}/{method}{query}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _tg_post(token: str, method: str, data: dict[str, object], timeout_s: int = 20) -> dict:
    payload = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(f"{_tg_api_base(token)}/{method}", data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _split_message(text: str, limit: int = 3800) -> list[str]:
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(True):
        if current and current_len + len(line) > limit:
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
            "/stats - show store totals (admin)",
            "/users - list recent users (admin)",
            "/user <id|email> - show one user summary (admin)",
            "/history [query] - list recent auth events (admin)",
            "/orders [status] - list recent orders (admin)",
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
    rows = list_pending_orders(limit=15)
    if not rows:
        return "No pending_payment orders."

    lines = ["Pending orders (latest):"]
    for row in rows:
        order = row["order"]
        user = row.get("user") or {}
        lines.append(
            f"- #{order['id']} | {_money(int(order.get('total_cents', 0)), order.get('currency') or 'USD')} | "
            f"{user.get('email') or 'unknown'} | created {order.get('created_at')}"
        )
    return "\n".join(lines)


def _cmd_users() -> str:
    users = list_users(limit=20)
    if not users:
        return "No users found."

    lines = ["Users (latest):"]
    for user in users:
        lines.append(
            f"- #{user['id']} | {user.get('email')} | {user.get('status') or '-'} | "
            f"joined {user.get('created_at')} | last login {user.get('last_login_at') or '-'}"
        )
    return "\n".join(lines)


def _cmd_user(query: str) -> str:
    details = get_user_admin_details(query)
    if not details:
        return "User not found."

    user = details["user"]
    stats = details["stats"]
    auth_events = details["auth_events"]

    lines = [
        f"User #{user['id']}",
        f"Email: {user.get('email') or '-'}",
        f"Name: {user.get('name') or '-'}",
        f"Status: {user.get('status') or '-'}",
        f"Joined: {user.get('created_at') or '-'}",
        f"Last login: {user.get('last_login_at') or '-'}",
        f"Last logout: {user.get('last_logout_at') or '-'}",
        f"Orders: {stats['orders_total']} total | {stats['orders_pending']} pending | {stats['orders_paid']} paid",
    ]
    if auth_events:
        lines.extend(["", "Recent auth:"])
        for event in auth_events[:5]:
            lines.append(
                f"- {event.get('created_at')} | {event.get('event')} | IP {event.get('ip_address') or '-'}"
            )
    return "\n".join(lines)


def _cmd_history(query: str | None = None) -> str:
    events = list_auth_events(limit=25, query=query)
    if not events:
        return "No auth history found."

    heading = "Auth history"
    if query:
        heading += f" for '{query}'"
    lines = [heading + ":"]
    for event in events:
        lines.append(
            f"- #{event['id']} | {event.get('event')} | user #{event.get('user_id')} | "
            f"{event.get('email') or '-'} | {event.get('created_at')} | IP {event.get('ip_address') or '-'}"
        )
    return "\n".join(lines)


def _cmd_orders(status: str | None = None) -> str:
    rows = list_orders(limit=20, status=status)
    if not rows:
        return "No orders found."

    label = f"Orders ({status})" if status else "Orders"
    lines = [label + ":"]
    for row in rows:
        order = row["order"]
        user = row.get("user") or {}
        payment = row.get("payment") or {}
        lines.append(
            f"- #{order['id']} | {order.get('status')} | {_money(int(order.get('total_cents', 0)), order.get('currency') or 'USD')} | "
            f"{user.get('email') or 'unknown'} | created {order.get('created_at')} | payment {payment.get('status') or '-'}"
        )
    return "\n".join(lines)


def _cmd_stats() -> str:
    stats = get_store_stats()
    return "\n".join(
        [
            "Store stats:",
            f"- Users: {stats['users_total']} total | {stats['users_online']} online",
            f"- Orders: {stats['orders_total']} total | {stats['orders_pending']} pending | {stats['orders_paid']} paid",
            f"- Payments: {stats['payments_total']}",
            f"- Auth events: {stats['auth_events_total']}",
        ]
    )


def _cmd_invoice(order_id: int) -> str:
    details = get_order_details(order_id)
    if not details:
        return "Order not found."

    order = details["order"]
    items = details["items"]
    user = details.get("user") or {}
    payment = details.get("payment")

    lines: list[str] = [
        f"Invoice: Order #{order['id']}",
        f"Status: {order.get('status')}",
        f"Customer: {user.get('email') or 'unknown'}",
        f"Created: {order.get('created_at')}",
    ]
    if order.get("paid_at"):
        lines.append(f"Paid: {order.get('paid_at')}")

    lines.extend(
        [
            "",
            f"Subtotal: {_money(int(order.get('subtotal_cents', 0)), order.get('currency') or 'USD')}",
            f"Shipping: {_money(int(order.get('shipping_cents', 0)), order.get('currency') or 'USD')}",
            f"Total: {_money(int(order.get('total_cents', 0)), order.get('currency') or 'USD')}",
            "",
            "Items:",
        ]
    )

    if not items:
        lines.append("- (none)")
    for item in items:
        brand = f" ({item.get('product_brand')})" if item.get("product_brand") else ""
        lines.append(
            f"- {item.get('product_name')}{brand} x{int(item.get('quantity', 0))} @ "
            f"{_money(int(item.get('unit_price_cents', 0)), order.get('currency') or 'USD')} = "
            f"{_money(int(item.get('line_total_cents', 0)), order.get('currency') or 'USD')}"
        )

    if payment:
        lines.extend(
            [
                "",
                "Payment:",
                f"- Provider: {payment.get('provider')}",
                f"- Amount: {_money(int(payment.get('amount_cents', 0)), payment.get('currency') or 'USD')}",
                f"- Ref: {payment.get('provider_ref') or '-'}",
                f"- Status: {payment.get('status')}",
                f"- At: {payment.get('created_at')}",
            ]
        )
    else:
        lines.extend(["", "Payment: (none)"])
    return "\n".join(lines)


def _cmd_confirm(order_id: int, provider_ref: str | None) -> str:
    details = get_order_details(order_id)
    if not details:
        return "Order not found."

    order = details["order"]
    if order.get("status") == "paid":
        return f"Order #{order_id} is already paid."
    if order.get("status") != "pending_payment":
        return f"Order #{order_id} is not payable (status={order.get('status')})."

    confirm_order_payment(order_id, provider_ref)
    return f"Confirmed paid: Order #{order_id}."


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


def run_forever(*, verbose: bool = True, stop_event: threading.Event | None = None) -> int:
    load_dotenv()

    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        if verbose:
            print("Missing TELEGRAM_BOT_TOKEN. Copy .env.example -> .env and set TELEGRAM_BOT_TOKEN.")
        return 2

    admin_ids = _parse_admin_ids(_env("TELEGRAM_ADMIN_IDS"))
    state_path, offset = _load_offset_state()
    if verbose:
        print("Telegram bot running. Press Ctrl+C to stop.")

    while stop_event is None or not stop_event.is_set():
        try:
            resp = _tg_get(token, "getUpdates", {"timeout": 60, "offset": offset}, timeout_s=80)
            if not resp.get("ok"):
                time.sleep(2)
                continue

            for update in resp.get("result") or []:
                try:
                    update_id = int(update.get("update_id"))
                except Exception:
                    continue

                offset = max(offset, update_id + 1)
                _save_offset_state(state_path, offset)

                message = update.get("message") or {}
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

                if cmd == "/stats":
                    if _ensure_admin(token, chat_id, user_id, admin_ids):
                        _send_text(token, chat_id, _cmd_stats())
                    continue

                if cmd == "/users":
                    if _ensure_admin(token, chat_id, user_id, admin_ids):
                        _send_text(token, chat_id, _cmd_users())
                    continue

                if cmd == "/user":
                    if not _ensure_admin(token, chat_id, user_id, admin_ids):
                        continue
                    query = " ".join(args).strip()
                    if not query:
                        _send_text(token, chat_id, "Usage: /user <id|email>")
                        continue
                    _send_text(token, chat_id, _cmd_user(query))
                    continue

                if cmd == "/history":
                    if not _ensure_admin(token, chat_id, user_id, admin_ids):
                        continue
                    query = " ".join(args).strip() or None
                    _send_text(token, chat_id, _cmd_history(query))
                    continue

                if cmd == "/orders":
                    if not _ensure_admin(token, chat_id, user_id, admin_ids):
                        continue
                    status = (args[0] if args else "").strip().lower() or None
                    _send_text(token, chat_id, _cmd_orders(status))
                    continue

                if cmd == "/pending":
                    if _ensure_admin(token, chat_id, user_id, admin_ids):
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
            if verbose:
                print("Stopping.")
            return 0
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
                if verbose:
                    print(f"Telegram HTTPError: {e.code} {body}")
            except Exception:
                if verbose:
                    print(f"Telegram HTTPError: {e}")
            time.sleep(2)
        except urllib.error.URLError as e:
            if verbose:
                print(f"Telegram URLError: {e}")
            time.sleep(2)
        except Exception as e:
            if verbose:
                print(f"Error: {e}")
            time.sleep(2)
    return 0


def start_background_bot() -> bool:
    global _BOT_THREAD
    if _env("RUN_TELEGRAM_BOT_IN_WEB") != "1":
        return False
    if not _env("TELEGRAM_BOT_TOKEN"):
        return False

    with _BOT_LOCK:
        if _BOT_THREAD and _BOT_THREAD.is_alive():
            return False
        thread = threading.Thread(target=run_forever, kwargs={"verbose": False}, name="telegram-admin-bot", daemon=True)
        thread.start()
        _BOT_THREAD = thread
        return True


def main() -> int:
    return run_forever(verbose=True)
