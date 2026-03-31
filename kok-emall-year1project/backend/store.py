from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


StoreState = dict[str, Any]
StoreMutator = Callable[[StoreState], Any]

_LOCK = threading.RLock()
_DEFAULT_STATE: StoreState = {
    "meta": {
        "next_ids": {
            "users": 1,
            "cart_items": 1,
            "orders": 1,
            "order_items": 1,
            "payments": 1,
            "auth_events": 1,
        }
    },
    "users": [],
    "cart_items": [],
    "orders": [],
    "order_items": [],
    "payments": [],
    "auth_events": [],
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_path() -> Path:
    return Path(__file__).resolve().parent / "instance" / "store.json"


def _clone_default() -> StoreState:
    return json.loads(json.dumps(_DEFAULT_STATE))


def _ensure_shape(state: StoreState) -> StoreState:
    if not isinstance(state, dict):
        return _clone_default()

    state.setdefault("meta", {})
    state["meta"].setdefault("next_ids", {})
    for key, value in _DEFAULT_STATE["meta"]["next_ids"].items():
        state["meta"]["next_ids"].setdefault(key, value)

    for key in ("users", "cart_items", "orders", "order_items", "payments", "auth_events"):
        if not isinstance(state.get(key), list):
            state[key] = []
    return state


def _load_no_lock() -> StoreState:
    path = store_path()
    if not path.exists():
        return _clone_default()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _clone_default()
    return _ensure_shape(raw)


def _save_no_lock(state: StoreState) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def read_state() -> StoreState:
    with _LOCK:
        return deepcopy(_load_no_lock())


def update_state(mutator: StoreMutator) -> Any:
    with _LOCK:
        state = _load_no_lock()
        result = mutator(state)
        _save_no_lock(state)
        return deepcopy(result)


def next_id(state: StoreState, key: str) -> int:
    current = int(state["meta"]["next_ids"].get(key, 1))
    state["meta"]["next_ids"][key] = current + 1
    return current


def sort_by_created(rows: list[dict[str, Any]], *, reverse: bool = False) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (str(row.get("created_at") or ""), int(row.get("id") or 0)), reverse=reverse)


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    state = read_state()
    return next((deepcopy(user) for user in state["users"] if int(user.get("id", 0)) == int(user_id)), None)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    normalized = str(email or "").strip().lower()
    state = read_state()
    return next((deepcopy(user) for user in state["users"] if user.get("email") == normalized), None)


def append_auth_event(
    state: StoreState,
    *,
    event_name: str,
    user: dict[str, Any],
    ip_address: str | None = None,
) -> dict[str, Any]:
    event = {
        "id": next_id(state, "auth_events"),
        "event": event_name,
        "user_id": int(user.get("id", 0)),
        "email": user.get("email"),
        "name": user.get("name"),
        "status": user.get("status"),
        "ip_address": ip_address,
        "created_at": utcnow_iso(),
    }
    state["auth_events"].append(event)
    return event


def get_order_details(order_id: int) -> dict[str, Any] | None:
    state = read_state()
    order = next((deepcopy(row) for row in state["orders"] if int(row.get("id", 0)) == int(order_id)), None)
    if not order:
        return None

    items = sort_by_created(
        [deepcopy(row) for row in state["order_items"] if int(row.get("order_id", 0)) == int(order_id)]
    )
    user = next((deepcopy(row) for row in state["users"] if int(row.get("id", 0)) == int(order.get("user_id", 0))), None)
    payments = sort_by_created(
        [deepcopy(row) for row in state["payments"] if int(row.get("order_id", 0)) == int(order_id)],
        reverse=True,
    )
    payment = payments[0] if payments else None

    return {"order": order, "items": items, "user": user, "payment": payment}


def list_pending_orders(limit: int = 15) -> list[dict[str, Any]]:
    state = read_state()
    users_by_id = {int(user.get("id", 0)): deepcopy(user) for user in state["users"]}
    rows = sort_by_created(
        [deepcopy(order) for order in state["orders"] if order.get("status") == "pending_payment"],
        reverse=True,
    )
    return [{"order": order, "user": users_by_id.get(int(order.get("user_id", 0)))} for order in rows[:limit]]


def list_users(limit: int = 25) -> list[dict[str, Any]]:
    state = read_state()
    rows = sort_by_created([deepcopy(user) for user in state["users"]], reverse=True)
    return rows[:limit]


def list_auth_events(limit: int = 25, query: str | None = None) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip().lower()
    state = read_state()
    rows = sort_by_created([deepcopy(event) for event in state["auth_events"]], reverse=True)

    if normalized_query:
        rows = [
            event
            for event in rows
            if normalized_query in str(event.get("email") or "").lower()
            or normalized_query in str(event.get("event") or "").lower()
            or normalized_query in str(event.get("user_id") or "")
            or normalized_query in str(event.get("name") or "").lower()
        ]
    return rows[:limit]


def list_orders(limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
    normalized_status = str(status or "").strip().lower()
    state = read_state()
    users_by_id = {int(user.get("id", 0)): deepcopy(user) for user in state["users"]}
    payments_by_order: dict[int, dict[str, Any]] = {}
    for payment in sort_by_created([deepcopy(row) for row in state["payments"]], reverse=True):
        order_id = int(payment.get("order_id", 0))
        payments_by_order.setdefault(order_id, payment)

    rows = [deepcopy(order) for order in state["orders"]]
    if normalized_status:
        rows = [order for order in rows if str(order.get("status") or "").lower() == normalized_status]
    rows = sort_by_created(rows, reverse=True)
    return [
        {
            "order": order,
            "user": users_by_id.get(int(order.get("user_id", 0))),
            "payment": payments_by_order.get(int(order.get("id", 0))),
        }
        for order in rows[:limit]
    ]


def get_user_admin_details(query: str | int) -> dict[str, Any] | None:
    normalized_query = str(query).strip()
    if not normalized_query:
        return None

    state = read_state()
    user: dict[str, Any] | None = None
    if normalized_query.isdigit():
        user_id = int(normalized_query)
        user = next((deepcopy(row) for row in state["users"] if int(row.get("id", 0)) == user_id), None)
    else:
        email = normalized_query.lower()
        user = next((deepcopy(row) for row in state["users"] if str(row.get("email") or "").lower() == email), None)
    if not user:
        return None

    user_id = int(user.get("id", 0))
    orders = sort_by_created(
        [deepcopy(row) for row in state["orders"] if int(row.get("user_id", 0)) == user_id],
        reverse=True,
    )
    auth_events = sort_by_created(
        [deepcopy(row) for row in state["auth_events"] if int(row.get("user_id", 0)) == user_id],
        reverse=True,
    )
    return {
        "user": user,
        "orders": orders[:10],
        "auth_events": auth_events[:10],
        "stats": {
            "orders_total": len(orders),
            "orders_pending": sum(1 for order in orders if order.get("status") == "pending_payment"),
            "orders_paid": sum(1 for order in orders if order.get("status") == "paid"),
        },
    }


def get_store_stats() -> dict[str, int]:
    state = read_state()
    return {
        "users_total": len(state["users"]),
        "users_online": sum(1 for user in state["users"] if user.get("status") == "online"),
        "orders_total": len(state["orders"]),
        "orders_pending": sum(1 for order in state["orders"] if order.get("status") == "pending_payment"),
        "orders_paid": sum(1 for order in state["orders"] if order.get("status") == "paid"),
        "payments_total": len(state["payments"]),
        "auth_events_total": len(state["auth_events"]),
    }


def confirm_order_payment(order_id: int, provider_ref: str | None = None) -> dict[str, Any] | None:
    def mutator(state: StoreState) -> dict[str, Any] | None:
        order = next((row for row in state["orders"] if int(row.get("id", 0)) == int(order_id)), None)
        if not order:
            return None

        if order.get("status") == "paid":
            payment = next(
                (deepcopy(row) for row in reversed(state["payments"]) if int(row.get("order_id", 0)) == int(order_id)),
                None,
            )
            return {"order": deepcopy(order), "payment": payment}

        timestamp = utcnow_iso()
        order["status"] = "paid"
        order["paid_at"] = timestamp

        payment = {
            "id": next_id(state, "payments"),
            "order_id": int(order_id),
            "provider": "aba_khqr",
            "status": "succeeded",
            "amount_cents": int(order.get("total_cents", 0)),
            "currency": order.get("currency") or "USD",
            "provider_ref": (provider_ref or "").strip() or f"aba-{order_id}",
            "created_at": timestamp,
        }
        state["payments"].append(payment)
        return {"order": deepcopy(order), "payment": deepcopy(payment)}

    return update_state(mutator)
