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
_ID_COLLECTIONS = {
    "users": "users",
    "cart_items": "cart_items",
    "orders": "orders",
    "order_items": "order_items",
    "payments": "payments",
    "auth_events": "auth_events",
    "products": "products",
}
_DEFAULT_PRODUCT_ROWS = [
    {
        "id": 1,
        "name": "Supreme x Nike Air Max 1 Releasing In 2025",
        "brand": "nike",
        "description": "Limited sneaker drop with bold streetwear styling.",
        "image_url": "eMall-photo/nike.webp",
        "unit_price_cents": 100,
        "stock_quantity": 20,
        "is_active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    },
    {
        "id": 2,
        "name": "Air Jordan 5 Fire Red",
        "brand": "nike",
        "description": "Classic Jordan silhouette with iconic Fire Red colorway.",
        "image_url": "eMall-photo/jordan.jpg",
        "unit_price_cents": 100,
        "stock_quantity": 20,
        "is_active": True,
        "created_at": "2026-01-01T00:01:00+00:00",
        "updated_at": "2026-01-01T00:01:00+00:00",
    },
    {
        "id": 3,
        "name": "Nike Air Max 95 OG",
        "brand": "nike",
        "description": "Retro Air Max design with everyday comfort.",
        "image_url": "eMall-photo/nike1.jpg",
        "unit_price_cents": 100,
        "stock_quantity": 20,
        "is_active": True,
        "created_at": "2026-01-01T00:02:00+00:00",
        "updated_at": "2026-01-01T00:02:00+00:00",
    },
    {
        "id": 4,
        "name": "Nike Kobe Release Dates 2025",
        "brand": "nike",
        "description": "Basketball-inspired sneaker built for standout looks.",
        "image_url": "eMall-photo/sneaker.webp",
        "unit_price_cents": 100,
        "stock_quantity": 20,
        "is_active": True,
        "created_at": "2026-01-01T00:03:00+00:00",
        "updated_at": "2026-01-01T00:03:00+00:00",
    },
    {
        "id": 5,
        "name": "Summer Shirt",
        "brand": "T-shirt",
        "description": "Lightweight shirt for hot weather and daily wear.",
        "image_url": "eMall-photo/summer.webp",
        "unit_price_cents": 100,
        "stock_quantity": 20,
        "is_active": True,
        "created_at": "2026-01-01T00:04:00+00:00",
        "updated_at": "2026-01-01T00:04:00+00:00",
    },
    {
        "id": 6,
        "name": "Men's Summer Shirt",
        "brand": "T-shirt",
        "description": "Soft casual shirt for relaxed summer styling.",
        "image_url": "eMall-photo/summer2.webp",
        "unit_price_cents": 100,
        "stock_quantity": 20,
        "is_active": True,
        "created_at": "2026-01-01T00:05:00+00:00",
        "updated_at": "2026-01-01T00:05:00+00:00",
    },
    {
        "id": 7,
        "name": "Hottest T-shirt for All Generation",
        "brand": "T-shirt",
        "description": "Comfort-fit tee made for all-day wear.",
        "image_url": "eMall-photo/summer3.webp",
        "unit_price_cents": 100,
        "stock_quantity": 20,
        "is_active": True,
        "created_at": "2026-01-01T00:06:00+00:00",
        "updated_at": "2026-01-01T00:06:00+00:00",
    },
    {
        "id": 8,
        "name": "Christmas Summer Shirt",
        "brand": "T-shirt",
        "description": "Festive shirt with a bright seasonal look.",
        "image_url": "eMall-photo/summer4.webp",
        "unit_price_cents": 100,
        "stock_quantity": 20,
        "is_active": True,
        "created_at": "2026-01-01T00:07:00+00:00",
        "updated_at": "2026-01-01T00:07:00+00:00",
    },
]
_DEFAULT_STATE: StoreState = {
    "meta": {
        "next_ids": {
            "users": 1,
            "cart_items": 1,
            "orders": 1,
            "order_items": 1,
            "payments": 1,
            "auth_events": 1,
            "products": 1,
        }
    },
    "users": [],
    "cart_items": [],
    "orders": [],
    "order_items": [],
    "payments": [],
    "auth_events": [],
    "products": [],
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_path() -> Path:
    return Path(__file__).resolve().parent / "instance" / "store.json"


def _clone_default() -> StoreState:
    return json.loads(json.dumps(_DEFAULT_STATE))


def _clone_default_products() -> list[dict[str, Any]]:
    return json.loads(json.dumps(_DEFAULT_PRODUCT_ROWS))


def _ensure_shape(state: StoreState) -> StoreState:
    if not isinstance(state, dict):
        state = _clone_default()

    state.setdefault("meta", {})
    state["meta"].setdefault("next_ids", {})
    for key in _DEFAULT_STATE["meta"]["next_ids"]:
        state["meta"]["next_ids"].setdefault(key, 1)

    for key in ("users", "cart_items", "orders", "order_items", "payments", "auth_events"):
        if not isinstance(state.get(key), list):
            state[key] = []
    if not isinstance(state.get("products"), list) or not state.get("products"):
        state["products"] = _clone_default_products()

    for product in state["products"]:
        product["id"] = int(product.get("id", 0))
        product["name"] = str(product.get("name") or "").strip()
        product["brand"] = str(product.get("brand") or "").strip() or None
        product["description"] = str(product.get("description") or "").strip() or None
        product["image_url"] = str(product.get("image_url") or "").strip() or None
        product["unit_price_cents"] = int(product.get("unit_price_cents", 0))
        product["stock_quantity"] = max(0, int(product.get("stock_quantity", 0)))
        product["is_active"] = bool(product.get("is_active", True))
        product["created_at"] = str(product.get("created_at") or utcnow_iso())
        product["updated_at"] = str(product.get("updated_at") or product["created_at"])

    for key, collection_name in _ID_COLLECTIONS.items():
        rows = state.get(collection_name) or []
        max_existing = max((int(row.get("id", 0)) for row in rows if isinstance(row, dict)), default=0)
        state["meta"]["next_ids"][key] = max(int(state["meta"]["next_ids"].get(key, 1)), max_existing + 1)

    return state


def _load_no_lock() -> StoreState:
    path = store_path()
    if not path.exists():
        return _ensure_shape(_clone_default())
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _ensure_shape(_clone_default())
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


def get_product_row(state: StoreState, product_id: int) -> dict[str, Any] | None:
    return next((row for row in state["products"] if int(row.get("id", 0)) == int(product_id)), None)


def reserved_stock_for_product(state: StoreState, product_id: int, *, exclude_order_id: int | None = None) -> int:
    product = get_product_row(state, product_id)
    product_name = str(product.get("name") or "").strip() if product else ""
    reserved_order_ids = {
        int(order.get("id", 0))
        for order in state["orders"]
        if order.get("status") in {"pending_payment", "paid"} and int(order.get("id", 0)) != int(exclude_order_id or 0)
    }
    return sum(
        int(item.get("quantity", 0))
        for item in state["order_items"]
        if int(item.get("order_id", 0)) in reserved_order_ids
        and (
            int(item.get("product_id", 0)) == int(product_id)
            or (not int(item.get("product_id", 0)) and product_name and str(item.get("product_name") or "").strip() == product_name)
        )
    )


def available_stock_for_product(state: StoreState, product_id: int, *, exclude_order_id: int | None = None) -> int:
    product = get_product_row(state, product_id)
    if not product:
        return 0
    return max(0, int(product.get("stock_quantity", 0)) - reserved_stock_for_product(state, product_id, exclude_order_id=exclude_order_id))


def serialize_product(state: StoreState, product: dict[str, Any], *, admin: bool = False) -> dict[str, Any]:
    product_id = int(product.get("id", 0))
    reserved_stock = reserved_stock_for_product(state, product_id)
    available_stock = max(0, int(product.get("stock_quantity", 0)) - reserved_stock)
    payload = {
        "id": product_id,
        "name": product.get("name"),
        "brand": product.get("brand"),
        "description": product.get("description"),
        "image_url": product.get("image_url"),
        "unit_price_cents": int(product.get("unit_price_cents", 0)),
        "stock_quantity": int(product.get("stock_quantity", 0)),
        "available_stock": available_stock,
        "is_active": bool(product.get("is_active", True)),
        "created_at": product.get("created_at"),
        "updated_at": product.get("updated_at"),
    }
    if admin:
        payload["reserved_stock"] = reserved_stock
    return payload


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    state = read_state()
    return next((deepcopy(user) for user in state["users"] if int(user.get("id", 0)) == int(user_id)), None)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    normalized = str(email or "").strip().lower()
    state = read_state()
    return next((deepcopy(user) for user in state["users"] if user.get("email") == normalized), None)


def list_products(limit: int | None = None, *, include_inactive: bool = False, query: str | None = None, admin: bool = False) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip().lower()
    state = read_state()
    rows = sort_by_created([deepcopy(product) for product in state["products"]], reverse=True)

    if not include_inactive:
        rows = [product for product in rows if bool(product.get("is_active", True))]
    if normalized_query:
        rows = [
            product
            for product in rows
            if normalized_query in str(product.get("name") or "").lower()
            or normalized_query in str(product.get("brand") or "").lower()
            or normalized_query in str(product.get("description") or "").lower()
            or normalized_query in str(product.get("id") or "")
        ]
    if limit is not None:
        rows = rows[:limit]
    return [serialize_product(state, product, admin=admin) for product in rows]


def get_product(product_id: int, *, include_inactive: bool = False, admin: bool = False) -> dict[str, Any] | None:
    state = read_state()
    product = next((deepcopy(row) for row in state["products"] if int(row.get("id", 0)) == int(product_id)), None)
    if not product:
        return None
    if not include_inactive and not bool(product.get("is_active", True)):
        return None
    return serialize_product(state, product, admin=admin)


def add_product(
    *,
    name: str,
    unit_price_cents: int,
    stock_quantity: int,
    brand: str | None = None,
    image_url: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    def mutator(state: StoreState) -> dict[str, Any]:
        timestamp = utcnow_iso()
        product = {
            "id": next_id(state, "products"),
            "name": name.strip(),
            "brand": str(brand or "").strip() or None,
            "description": str(description or "").strip() or None,
            "image_url": str(image_url or "").strip() or None,
            "unit_price_cents": int(unit_price_cents),
            "stock_quantity": max(0, int(stock_quantity)),
            "is_active": True,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        state["products"].append(product)
        return serialize_product(state, product, admin=True)

    return update_state(mutator)


def set_product_stock(product_id: int, stock_quantity: int) -> dict[str, Any] | None:
    def mutator(state: StoreState) -> dict[str, Any] | None:
        product = get_product_row(state, product_id)
        if not product:
            return None
        product["stock_quantity"] = max(0, int(stock_quantity))
        product["updated_at"] = utcnow_iso()
        return serialize_product(state, product, admin=True)

    return update_state(mutator)


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


def get_latest_payment(order_id: int) -> dict[str, Any] | None:
    state = read_state()
    return next(
        (deepcopy(row) for row in reversed(state["payments"]) if int(row.get("order_id", 0)) == int(order_id)),
        None,
    )


def get_payment_by_merchant_ref(merchant_ref: str) -> dict[str, Any] | None:
    normalized_ref = str(merchant_ref or "").strip()
    if not normalized_ref:
        return None

    state = read_state()
    return next(
        (
            deepcopy(row)
            for row in reversed(state["payments"])
            if str(row.get("qr_merchant_ref") or "").strip() == normalized_ref
        ),
        None,
    )


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
        "products_total": len([product for product in state["products"] if bool(product.get("is_active", True))]),
        "orders_total": len(state["orders"]),
        "orders_pending": sum(1 for order in state["orders"] if order.get("status") == "pending_payment"),
        "orders_paid": sum(1 for order in state["orders"] if order.get("status") == "paid"),
        "payments_total": len(state["payments"]),
        "auth_events_total": len(state["auth_events"]),
    }


def upsert_pending_payment(
    order_id: int,
    *,
    provider: str,
    amount_cents: int,
    currency: str,
    qr_payload: str,
    qr_md5: str,
    qr_short_hash: str,
    qr_merchant_ref: str | None,
    auto_confirm_enabled: bool,
) -> dict[str, Any] | None:
    def mutator(state: StoreState) -> dict[str, Any] | None:
        order = next((row for row in state["orders"] if int(row.get("id", 0)) == int(order_id)), None)
        if not order:
            return None

        payment = next((row for row in reversed(state["payments"]) if int(row.get("order_id", 0)) == int(order_id)), None)
        timestamp = utcnow_iso()

        if payment and payment.get("status") == "succeeded":
            return {"order": deepcopy(order), "payment": deepcopy(payment)}

        if payment and payment.get("status") in {"pending", "processing", "created"}:
            payment["provider"] = provider
            payment["amount_cents"] = int(amount_cents)
            payment["currency"] = currency
            payment["provider_ref"] = qr_short_hash
            payment["qr_payload"] = qr_payload
            payment["qr_md5"] = qr_md5
            payment["qr_short_hash"] = qr_short_hash
            payment["qr_merchant_ref"] = (qr_merchant_ref or "").strip() or None
            payment["auto_confirm_enabled"] = bool(auto_confirm_enabled)
            payment["updated_at"] = timestamp
        else:
            payment = {
                "id": next_id(state, "payments"),
                "order_id": int(order_id),
                "provider": provider,
                "status": "pending",
                "amount_cents": int(amount_cents),
                "currency": currency,
                "provider_ref": qr_short_hash,
                "qr_payload": qr_payload,
                "qr_md5": qr_md5,
                "qr_short_hash": qr_short_hash,
                "qr_merchant_ref": (qr_merchant_ref or "").strip() or None,
                "auto_confirm_enabled": bool(auto_confirm_enabled),
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            state["payments"].append(payment)

        return {"order": deepcopy(order), "payment": deepcopy(payment)}

    return update_state(mutator)


def confirm_order_payment(
    order_id: int,
    provider_ref: str | None = None,
    *,
    provider: str | None = None,
    payment_details: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    def mutator(state: StoreState) -> dict[str, Any] | None:
        order = next((row for row in state["orders"] if int(row.get("id", 0)) == int(order_id)), None)
        if not order:
            return None

        latest_payment = next(
            (row for row in reversed(state["payments"]) if int(row.get("order_id", 0)) == int(order_id)),
            None,
        )
        if order.get("status") == "paid":
            return {"order": deepcopy(order), "payment": deepcopy(latest_payment) if latest_payment else None}

        timestamp = utcnow_iso()
        order["status"] = "paid"
        order["paid_at"] = timestamp

        if latest_payment and latest_payment.get("status") in {"pending", "processing", "created"}:
            payment = latest_payment
            payment["provider"] = (provider or "").strip() or payment.get("provider") or "bakong_khqr"
            payment["status"] = "succeeded"
            payment["amount_cents"] = int(order.get("total_cents", 0))
            payment["currency"] = order.get("currency") or "USD"
            payment["provider_ref"] = (provider_ref or "").strip() or payment.get("provider_ref") or f"bakong-{order_id}"
            payment["updated_at"] = timestamp
        else:
            payment = {
                "id": next_id(state, "payments"),
                "order_id": int(order_id),
                "provider": (provider or "").strip() or "bakong_khqr",
                "status": "succeeded",
                "amount_cents": int(order.get("total_cents", 0)),
                "currency": order.get("currency") or "USD",
                "provider_ref": (provider_ref or "").strip() or f"bakong-{order_id}",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            state["payments"].append(payment)

        if payment_details:
            for key, value in payment_details.items():
                payment[key] = value
        payment["updated_at"] = timestamp
        payment.setdefault("created_at", timestamp)
        return {"order": deepcopy(order), "payment": deepcopy(payment)}

    return update_state(mutator)
