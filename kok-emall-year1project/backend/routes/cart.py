from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend.extensions import db
from backend.models import CartItem
from backend.utils import api_error, get_json, parse_price_to_cents

cart_bp = Blueprint("cart", __name__, url_prefix="/api/cart")


def _cart_query(user_id: int):
    return CartItem.query.filter_by(user_id=user_id)


def _item_to_dict(item: CartItem) -> dict:
    return {
        "id": item.id,
        "product": {
            "name": item.product_name,
            "brand": item.product_brand,
            "image_url": item.product_image_url,
            "unit_price_cents": item.unit_price_cents,
        },
        "quantity": item.quantity,
        "line_total_cents": item.unit_price_cents * item.quantity,
    }


def _cart_summary(items: list[CartItem]) -> dict:
    subtotal_cents = sum(i.unit_price_cents * i.quantity for i in items)
    return {
        "items": [_item_to_dict(i) for i in items],
        "currency": "USD",
        "subtotal_cents": subtotal_cents,
        "total_cents": subtotal_cents,
    }


@cart_bp.get("")
@jwt_required()
def get_cart():
    user_id = int(get_jwt_identity())
    query = _cart_query(user_id)
    items = query.order_by(CartItem.created_at.asc()).all()
    return jsonify(_cart_summary(items))


@cart_bp.post("/items")
@jwt_required()
def add_item():
    user_id = int(get_jwt_identity())
    query = _cart_query(user_id)

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

    existing = query.filter_by(product_name=product_name).first()
    if existing:
        existing.quantity += quantity
        existing.unit_price_cents = unit_price_cents
        existing.product_brand = product_brand
        existing.product_image_url = product_image_url
    else:
        existing = CartItem(
            user_id=user_id,
            guest_id=None,
            product_name=product_name,
            product_brand=product_brand,
            product_image_url=product_image_url,
            unit_price_cents=unit_price_cents,
            quantity=quantity,
        )
        db.session.add(existing)

    db.session.commit()
    items = query.order_by(CartItem.created_at.asc()).all()
    return jsonify(_cart_summary(items)), 201


@cart_bp.patch("/items/<int:item_id>")
@jwt_required()
def update_item(item_id: int):
    user_id = int(get_jwt_identity())
    query = _cart_query(user_id)

    item = query.filter_by(id=item_id).first()
    if not item:
        return api_error("Cart item not found.", 404)

    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    try:
        quantity = int(payload.get("quantity", item.quantity))
    except Exception:
        return api_error("Quantity must be a number.", 400)
    if quantity < 1 or quantity > 99:
        return api_error("Quantity must be between 1 and 99.", 400)

    item.quantity = quantity
    db.session.commit()

    items = query.order_by(CartItem.created_at.asc()).all()
    return jsonify(_cart_summary(items))


@cart_bp.delete("/items/<int:item_id>")
@jwt_required()
def remove_item(item_id: int):
    user_id = int(get_jwt_identity())
    query = _cart_query(user_id)

    item = query.filter_by(id=item_id).first()
    if not item:
        return api_error("Cart item not found.", 404)

    db.session.delete(item)
    db.session.commit()

    items = query.order_by(CartItem.created_at.asc()).all()
    return jsonify(_cart_summary(items))


@cart_bp.post("/clear")
@jwt_required()
def clear_cart():
    user_id = int(get_jwt_identity())
    query = _cart_query(user_id)

    query.delete(synchronize_session=False)
    db.session.commit()
    return jsonify(_cart_summary([]))
