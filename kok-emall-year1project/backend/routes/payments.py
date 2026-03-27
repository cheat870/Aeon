from __future__ import annotations

import os

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend.extensions import db
from backend.models import Order, Payment, utcnow
from backend.payments.emv_qr import EmvQrError, with_amount
from backend.utils import api_error, get_json

payments_bp = Blueprint("payments", __name__, url_prefix="/api/payments")


@payments_bp.post("/admin/confirm")
def admin_confirm():
    secret = os.environ.get("PAYMENT_CONFIRM_SECRET", "").strip()
    if not secret:
        return api_error("PAYMENT_CONFIRM_SECRET is not configured.", 501)

    provided = request.headers.get("X-Admin-Secret", "")
    if provided != secret:
        return api_error("Unauthorized.", 401)

    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    try:
        order_id = int(payload.get("order_id"))
    except Exception:
        return api_error("order_id is required.", 400)

    provider_ref = str(payload.get("provider_ref", "")).strip() or None

    order = Order.query.filter_by(id=order_id).first()
    if not order:
        return api_error("Order not found.", 404)
    if order.status == "paid":
        return jsonify({"order": {"id": order.id, "status": order.status}}), 200
    if order.status != "pending_payment":
        return api_error("Order is not payable.", 409)

    order.status = "paid"
    order.paid_at = utcnow()
    payment = Payment(
        order_id=order.id,
        provider="aba_khqr",
        status="succeeded",
        amount_cents=order.total_cents,
        currency=order.currency,
        provider_ref=provider_ref or f"aba-{order.id}",
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({"payment": {"id": payment.id, "status": payment.status}, "order": {"id": order.id, "status": order.status}})


@payments_bp.post("/aba/qr")
@jwt_required()
def aba_qr():
    user_id = int(get_jwt_identity())
    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    try:
        order_id = int(payload.get("order_id"))
    except Exception:
        return api_error("order_id is required.", 400)

    order = Order.query.filter_by(id=order_id, user_id=user_id).first()
    if not order:
        return api_error("Order not found.", 404)

    base = os.environ.get("ABA_KHQR_BASE", "").strip()
    if not base:
        return api_error("ABA merchant KHQR is not configured. Set ABA_KHQR_BASE in .env.", 501)
    if not base.startswith("000201"):
        return api_error(
            "ABA_KHQR_BASE must be a full EMV/KHQR payload string (it usually starts with 000201...). "
            "Do not set it to an account number. See README for how to set it from a QR image.",
            501,
        )

    if order.currency == "KHR":
        amount_str = str(int(round(order.total_cents / 100)))
    else:
        amount_str = f"{(order.total_cents / 100):.2f}"

    try:
        qr_payload = with_amount(base, amount=amount_str, point_of_initiation_method="12")
    except EmvQrError as e:
        return api_error(f"Invalid ABA_KHQR_BASE: {e}", 500)

    return jsonify({"qr_payload": qr_payload, "amount": amount_str, "currency": order.currency})
