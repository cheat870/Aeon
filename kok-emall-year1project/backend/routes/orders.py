from __future__ import annotations

from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend.store import available_stock_for_product, get_product_row, next_id, read_state, sort_by_created, update_state, utcnow_iso
from backend.utils import api_error

orders_bp = Blueprint("orders", __name__, url_prefix="/api/orders")


def _order_to_dict(order: dict, items: list[dict] | None = None) -> dict:
    payload = {
        "id": int(order["id"]),
        "status": order.get("status"),
        "currency": order.get("currency") or "USD",
        "subtotal_cents": int(order.get("subtotal_cents", 0)),
        "shipping_cents": int(order.get("shipping_cents", 0)),
        "total_cents": int(order.get("total_cents", 0)),
        "created_at": order.get("created_at"),
        "paid_at": order.get("paid_at"),
    }
    if items is not None:
        payload["items"] = [
            {
                "id": int(item["id"]),
                "product": {
                    "id": int(item.get("product_id", 0)) or None,
                    "name": item.get("product_name"),
                    "brand": item.get("product_brand"),
                    "image_url": item.get("product_image_url"),
                    "unit_price_cents": int(item.get("unit_price_cents", 0)),
                },
                "quantity": int(item.get("quantity", 0)),
                "line_total_cents": int(item.get("line_total_cents", 0)),
            }
            for item in items
        ]
    return payload


@orders_bp.post("")
@jwt_required()
def create_order():
    user_id = int(get_jwt_identity())

    def mutator(state: dict) -> dict:
        existing_orders = [
            row
            for row in state["orders"]
            if int(row.get("user_id") or 0) == user_id and row.get("status") == "pending_payment"
        ]
        existing_orders = sort_by_created(existing_orders, reverse=True)
        if existing_orders:
            return {"error": "pending", "order_id": int(existing_orders[0]["id"])}

        cart_items = sort_by_created([row for row in state["cart_items"] if int(row.get("user_id") or 0) == user_id])
        if not cart_items:
            return {"error": "empty"}

        requested_quantities: dict[int, int] = {}
        for cart_item in cart_items:
            product_id = int(cart_item.get("product_id") or 0)
            if not product_id:
                continue
            requested_quantities[product_id] = requested_quantities.get(product_id, 0) + int(cart_item.get("quantity", 0))

        for product_id, requested_quantity in requested_quantities.items():
            product = get_product_row(state, product_id)
            if not product or not bool(product.get("is_active", True)):
                missing_item = next((item for item in cart_items if int(item.get("product_id") or 0) == product_id), None)
                return {"error": "missing", "product_name": missing_item.get("product_name") if missing_item else "Product"}
            available_stock = available_stock_for_product(state, product_id)
            if requested_quantity > available_stock:
                return {
                    "error": "stock",
                    "product_name": product.get("name"),
                    "available_stock": available_stock,
                }

        subtotal_cents = sum(int(item.get("unit_price_cents", 0)) * int(item.get("quantity", 0)) for item in cart_items)
        timestamp = utcnow_iso()
        order = {
            "id": next_id(state, "orders"),
            "user_id": user_id,
            "status": "pending_payment",
            "currency": "USD",
            "subtotal_cents": subtotal_cents,
            "shipping_cents": 0,
            "total_cents": subtotal_cents,
            "created_at": timestamp,
            "paid_at": None,
        }
        state["orders"].append(order)

        order_items: list[dict] = []
        for cart_item in cart_items:
            quantity = int(cart_item.get("quantity", 0))
            unit_price_cents = int(cart_item.get("unit_price_cents", 0))
            line_total = unit_price_cents * quantity
            order_item = {
                "id": next_id(state, "order_items"),
                "order_id": int(order["id"]),
                "product_id": int(cart_item.get("product_id", 0)) or None,
                "product_name": cart_item.get("product_name"),
                "product_brand": cart_item.get("product_brand"),
                "product_image_url": cart_item.get("product_image_url"),
                "unit_price_cents": unit_price_cents,
                "quantity": quantity,
                "line_total_cents": line_total,
                "created_at": timestamp,
            }
            order_items.append(order_item)

        state["order_items"].extend(order_items)
        state["cart_items"] = [row for row in state["cart_items"] if int(row.get("user_id") or 0) != user_id]
        return {"order": order, "items": order_items}

    result = update_state(mutator)
    if result.get("error") == "pending":
        return (
            jsonify(
                {
                    "error": {
                        "message": "Please complete payment for your existing order before creating a new one.",
                        "code": "PENDING_PAYMENT",
                        "order_id": result["order_id"],
                    }
                }
            ),
            409,
        )
    if result.get("error") == "empty":
        return api_error("Your cart is empty.", 400)
    if result.get("error") == "missing":
        return api_error(f"{result['product_name']} is no longer available.", 409, code="PRODUCT_UNAVAILABLE")
    if result.get("error") == "stock":
        return api_error(
            f"Only {result['available_stock']} item(s) left in stock for {result['product_name']}.",
            409,
            code="OUT_OF_STOCK",
        )

    return jsonify({"order": _order_to_dict(result["order"], result["items"])}), 201


@orders_bp.get("/<int:order_id>")
@jwt_required()
def get_order(order_id: int):
    user_id = int(get_jwt_identity())
    state = read_state()
    order = next(
        (
            row
            for row in state["orders"]
            if int(row.get("id") or 0) == order_id and int(row.get("user_id") or 0) == user_id
        ),
        None,
    )
    if not order:
        return api_error("Order not found.", 404)

    items = sort_by_created([row for row in state["order_items"] if int(row.get("order_id") or 0) == order_id])
    return jsonify({"order": _order_to_dict(order, items)})
