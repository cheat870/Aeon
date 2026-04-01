from __future__ import annotations

from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend.store import (
    available_stock_for_product,
    get_product_row,
    next_id,
    read_state,
    sort_by_created,
    update_state,
    utcnow_iso,
)
from backend.utils import api_error, get_json, parse_price_to_cents

cart_bp = Blueprint("cart", __name__, url_prefix="/api/cart")


def _user_cart_items(state: dict, user_id: int) -> list[dict]:
    rows = [item for item in state["cart_items"] if int(item.get("user_id") or 0) == user_id]
    return sort_by_created(rows)


def _with_live_stock(state: dict, items: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for item in items:
        row = dict(item)
        product_id = int(row.get("product_id") or 0)
        if product_id:
            row["available_stock"] = available_stock_for_product(state, product_id)
        enriched.append(row)
    return enriched


def _item_to_dict(item: dict) -> dict:
    unit_price_cents = int(item.get("unit_price_cents", 0))
    quantity = int(item.get("quantity", 0))
    return {
        "id": int(item["id"]),
        "product": {
            "id": int(item.get("product_id", 0)) or None,
            "name": item.get("product_name"),
            "brand": item.get("product_brand"),
            "image_url": item.get("product_image_url"),
            "unit_price_cents": unit_price_cents,
            "available_stock": item.get("available_stock"),
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
    return jsonify(_cart_summary(_with_live_stock(state, _user_cart_items(state, user_id))))


@cart_bp.post("/items")
@jwt_required()
def add_item():
    user_id = int(get_jwt_identity())

    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    try:
        quantity = int(payload.get("quantity", 1))
    except Exception:
        return api_error("Quantity must be a number.", 400)
    if quantity < 1 or quantity > 99:
        return api_error("Quantity must be between 1 and 99.", 400)

    try:
        product_id = int(payload.get("product_id")) if payload.get("product_id") is not None else None
    except Exception:
        return api_error("product_id must be a number.", 400)

    product = payload.get("product") or {}
    product_name = str(product.get("name", "")).strip()
    product_brand = str(product.get("brand", "")).strip() or None
    product_image_url = str(product.get("image_url", "")).strip() or None

    if product_id is None:
        if not product_name:
            return api_error("Product name is required.", 400)
        try:
            unit_price_cents = parse_price_to_cents(product.get("unit_price_cents", product.get("price", "")))
        except ValueError:
            return api_error("Invalid product price.", 400)
    else:
        unit_price_cents = 0

    def mutator(state: dict) -> dict:
        canonical_product = None
        stock_limit = None
        if product_id is not None:
            canonical_product = get_product_row(state, product_id)
            if not canonical_product or not bool(canonical_product.get("is_active", True)):
                return {"error": "missing"}
            stock_limit = available_stock_for_product(state, product_id)

        existing = next(
            (
                item
                for item in state["cart_items"]
                if int(item.get("user_id") or 0) == user_id
                and (
                    (product_id is not None and int(item.get("product_id") or 0) == product_id)
                    or (product_id is None and item.get("product_name") == product_name)
                )
            ),
            None,
        )
        timestamp = utcnow_iso()
        final_quantity = quantity + int(existing.get("quantity", 0)) if existing else quantity

        if canonical_product is not None and final_quantity > int(stock_limit or 0):
            return {
                "error": "stock",
                "name": canonical_product.get("name"),
                "available_stock": int(stock_limit or 0),
            }

        if existing:
            existing["quantity"] = final_quantity
            if canonical_product is not None:
                existing["product_id"] = int(canonical_product["id"])
                existing["product_name"] = canonical_product.get("name")
                existing["product_brand"] = canonical_product.get("brand")
                existing["product_image_url"] = canonical_product.get("image_url")
                existing["unit_price_cents"] = int(canonical_product.get("unit_price_cents", 0))
                existing["available_stock"] = int(stock_limit or 0)
            else:
                existing["unit_price_cents"] = unit_price_cents
                existing["product_brand"] = product_brand
                existing["product_image_url"] = product_image_url
            existing["updated_at"] = timestamp
        else:
            row = {
                "id": next_id(state, "cart_items"),
                "user_id": user_id,
                "guest_id": None,
                "product_id": product_id,
                "product_name": product_name,
                "product_brand": product_brand,
                "product_image_url": product_image_url,
                "unit_price_cents": unit_price_cents,
                "quantity": quantity,
                "available_stock": stock_limit,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            if canonical_product is not None:
                row["product_name"] = canonical_product.get("name")
                row["product_brand"] = canonical_product.get("brand")
                row["product_image_url"] = canonical_product.get("image_url")
                row["unit_price_cents"] = int(canonical_product.get("unit_price_cents", 0))
                row["available_stock"] = int(stock_limit or 0)
            state["cart_items"].append(
                row
            )

        return {"items": _with_live_stock(state, _user_cart_items(state, user_id))}

    result = update_state(mutator)
    if result.get("error") == "missing":
        return api_error("Product not found.", 404)
    if result.get("error") == "stock":
        return api_error(
            f"Only {result['available_stock']} item(s) left in stock for {result['name']}.",
            409,
            code="OUT_OF_STOCK",
        )
    return jsonify(_cart_summary(result["items"])), 201


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
            return {"found": False, "items": _with_live_stock(state, _user_cart_items(state, user_id))}
        product_id = int(item.get("product_id") or 0)
        if product_id:
            available_stock = available_stock_for_product(state, product_id)
            if quantity > available_stock:
                return {
                    "found": True,
                    "error": "stock",
                    "name": item.get("product_name"),
                    "available_stock": available_stock,
                    "items": _with_live_stock(state, _user_cart_items(state, user_id)),
                }
            item["available_stock"] = available_stock

        item["quantity"] = quantity
        item["updated_at"] = utcnow_iso()
        return {"found": True, "items": _with_live_stock(state, _user_cart_items(state, user_id))}

    result = update_state(mutator)
    if not result["found"]:
        return api_error("Cart item not found.", 404)
    if result.get("error") == "stock":
        return api_error(
            f"Only {result['available_stock']} item(s) left in stock for {result['name']}.",
            409,
            code="OUT_OF_STOCK",
        )
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
        return {"found": len(state["cart_items"]) != before, "items": _with_live_stock(state, _user_cart_items(state, user_id))}

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
