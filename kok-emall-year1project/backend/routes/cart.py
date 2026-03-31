from __future__ import annotations

from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend.store import next_id, read_state, sort_by_created, update_state, utcnow_iso
from backend.utils import api_error, get_json, parse_price_to_cents

cart_bp = Blueprint("cart", __name__, url_prefix="/api/cart")


def _user_cart_items(state: dict, user_id: int) -> list[dict]:
    rows = [item for item in state["cart_items"] if int(item.get("user_id") or 0) == user_id]
    return sort_by_created(rows)


def _item_to_dict(item: dict) -> dict:
    unit_price_cents = int(item.get("unit_price_cents", 0))
    quantity = int(item.get("quantity", 0))
    return {
        "id": int(item["id"]),
        "product": {
            "name": item.get("product_name"),
            "brand": item.get("product_brand"),
            "image_url": item.get("product_image_url"),
            "unit_price_cents": unit_price_cents,
        },
        "quantity": quantity,
        "line_total_cents": unit_price_cents * quantity,
    }


def _cart_summary(items: list[dict]) -> dict:
    subtotal_cents = sum(int(item.get("unit_price_cents", 0)) * int(item.get("quantity", 0)) for item in items)
    return {
        "items": [_item_to_dict(item) for item in items],
        "currency": "USD",
        "subtotal_cents": subtotal_cents,
        "total_cents": subtotal_cents,
    }


@cart_bp.get("")
@jwt_required()
def get_cart():
    user_id = int(get_jwt_identity())
    state = read_state()
    return jsonify(_cart_summary(_user_cart_items(state, user_id)))


@cart_bp.post("/items")
@jwt_required()
def add_item():
    user_id = int(get_jwt_identity())

    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    product = payload.get("product") or {}
    product_name = str(product.get("name", "")).strip()
    if not product_name:
        return api_error("Product name is required.", 400)

    try:
        unit_price_cents = parse_price_to_cents(product.get("unit_price_cents", product.get("price", "")))
    except ValueError:
        return api_error("Invalid product price.", 400)

    product_brand = str(product.get("brand", "")).strip() or None
    product_image_url = str(product.get("image_url", "")).strip() or None

    try:
        quantity = int(payload.get("quantity", 1))
    except Exception:
        return api_error("Quantity must be a number.", 400)
    if quantity < 1 or quantity > 99:
        return api_error("Quantity must be between 1 and 99.", 400)

    def mutator(state: dict) -> list[dict]:
        existing = next(
            (
                item
                for item in state["cart_items"]
                if int(item.get("user_id") or 0) == user_id and item.get("product_name") == product_name
            ),
            None,
        )
        timestamp = utcnow_iso()

        if existing:
            existing["quantity"] = int(existing.get("quantity", 0)) + quantity
            existing["unit_price_cents"] = unit_price_cents
            existing["product_brand"] = product_brand
            existing["product_image_url"] = product_image_url
            existing["updated_at"] = timestamp
        else:
            state["cart_items"].append(
                {
                    "id": next_id(state, "cart_items"),
                    "user_id": user_id,
                    "guest_id": None,
                    "product_name": product_name,
                    "product_brand": product_brand,
                    "product_image_url": product_image_url,
                    "unit_price_cents": unit_price_cents,
                    "quantity": quantity,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            )

        return _user_cart_items(state, user_id)

    items = update_state(mutator)
    return jsonify(_cart_summary(items)), 201


@cart_bp.patch("/items/<int:item_id>")
@jwt_required()
def update_item(item_id: int):
    user_id = int(get_jwt_identity())

    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    try:
        quantity = int(payload.get("quantity"))
    except Exception:
        return api_error("Quantity must be a number.", 400)
    if quantity < 1 or quantity > 99:
        return api_error("Quantity must be between 1 and 99.", 400)

    def mutator(state: dict) -> dict:
        item = next(
            (
                row
                for row in state["cart_items"]
                if int(row.get("id") or 0) == item_id and int(row.get("user_id") or 0) == user_id
            ),
            None,
        )
        if not item:
            return {"found": False, "items": _user_cart_items(state, user_id)}

        item["quantity"] = quantity
        item["updated_at"] = utcnow_iso()
        return {"found": True, "items": _user_cart_items(state, user_id)}

    result = update_state(mutator)
    if not result["found"]:
        return api_error("Cart item not found.", 404)
    return jsonify(_cart_summary(result["items"]))


@cart_bp.delete("/items/<int:item_id>")
@jwt_required()
def remove_item(item_id: int):
    user_id = int(get_jwt_identity())

    def mutator(state: dict) -> dict:
        before = len(state["cart_items"])
        state["cart_items"] = [
            row
            for row in state["cart_items"]
            if not (int(row.get("id") or 0) == item_id and int(row.get("user_id") or 0) == user_id)
        ]
        return {"found": len(state["cart_items"]) != before, "items": _user_cart_items(state, user_id)}

    result = update_state(mutator)
    if not result["found"]:
        return api_error("Cart item not found.", 404)
    return jsonify(_cart_summary(result["items"]))


@cart_bp.post("/clear")
@jwt_required()
def clear_cart():
    user_id = int(get_jwt_identity())

    def mutator(state: dict) -> None:
        state["cart_items"] = [row for row in state["cart_items"] if int(row.get("user_id") or 0) != user_id]
        return None

    update_state(mutator)
    return jsonify(_cart_summary([]))
