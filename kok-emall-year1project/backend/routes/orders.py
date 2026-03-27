from __future__ import annotations

from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend.extensions import db
from backend.models import CartItem, Order, OrderItem
from backend.utils import api_error

orders_bp = Blueprint("orders", __name__, url_prefix="/api/orders")


def _order_to_dict(order: Order, items: list[OrderItem] | None = None) -> dict:
    payload = {
        "id": order.id,
        "status": order.status,
        "currency": order.currency,
        "subtotal_cents": order.subtotal_cents,
        "shipping_cents": order.shipping_cents,
        "total_cents": order.total_cents,
        "created_at": order.created_at.isoformat(),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
    }
    if items is not None:
        payload["items"] = [
            {
                "id": i.id,
                "product": {
                    "name": i.product_name,
                    "brand": i.product_brand,
                    "image_url": i.product_image_url,
                    "unit_price_cents": i.unit_price_cents,
                },
                "quantity": i.quantity,
                "line_total_cents": i.line_total_cents,
            }
            for i in items
        ]
    return payload


@orders_bp.post("")
@jwt_required()
def create_order():
    user_id = int(get_jwt_identity())
    existing = (
        Order.query.filter_by(user_id=user_id, status="pending_payment").order_by(Order.created_at.desc()).first()
    )
    if existing:
        return (
            jsonify(
                {
                    "error": {
                        "message": "Please complete payment for your existing order before creating a new one.",
                        "code": "PENDING_PAYMENT",
                        "order_id": existing.id,
                    }
                }
            ),
            409,
        )

    cart_items = CartItem.query.filter_by(user_id=user_id).order_by(CartItem.created_at.asc()).all()
    if not cart_items:
        return api_error("Your cart is empty.", 400)

    subtotal_cents = sum(i.unit_price_cents * i.quantity for i in cart_items)
    order = Order(
        user_id=user_id,
        status="pending_payment",
        currency="USD",
        subtotal_cents=subtotal_cents,
        shipping_cents=0,
        total_cents=subtotal_cents,
    )
    db.session.add(order)
    db.session.flush()

    order_items: list[OrderItem] = []
    for item in cart_items:
        line_total = item.unit_price_cents * item.quantity
        order_items.append(
            OrderItem(
                order_id=order.id,
                product_name=item.product_name,
                product_brand=item.product_brand,
                product_image_url=item.product_image_url,
                unit_price_cents=item.unit_price_cents,
                quantity=item.quantity,
                line_total_cents=line_total,
            )
        )

    db.session.add_all(order_items)

    CartItem.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    db.session.commit()

    return jsonify({"order": _order_to_dict(order, order_items)}), 201


@orders_bp.get("/<int:order_id>")
@jwt_required()
def get_order(order_id: int):
    user_id = int(get_jwt_identity())
    order = Order.query.filter_by(id=order_id, user_id=user_id).first()
    if not order:
        return api_error("Order not found.", 404)

    items = OrderItem.query.filter_by(order_id=order.id).order_by(OrderItem.id.asc()).all()
    return jsonify({"order": _order_to_dict(order, items)})
