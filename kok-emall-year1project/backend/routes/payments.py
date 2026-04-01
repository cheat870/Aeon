from __future__ import annotations

import os

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend.payments.emv_qr import EmvQrError, with_amount
from backend.store import confirm_order_payment, read_state
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

    state = read_state()
    order = next((row for row in state["orders"] if int(row.get("id") or 0) == order_id), None)
    if not order:
        return api_error("Order not found.", 404)
    if order.get("status") == "paid":
        return jsonify({"order": {"id": order_id, "status": "paid"}}), 200
    if order.get("status") != "pending_payment":
        return api_error("Order is not payable.", 409)

    result = confirm_order_payment(order_id, provider_ref=provider_ref)
    payment = result["payment"] if result else None
    order = result["order"] if result else None
    return jsonify(
        {
            "payment": {"id": int(payment["id"]), "status": payment.get("status")},
            "order": {"id": int(order["id"]), "status": order.get("status")},
        }
    )


def _khqr_base() -> str:
    return os.environ.get("BAKONG_KHQR_BASE", "").strip() or os.environ.get("ABA_KHQR_BASE", "").strip()


@payments_bp.post("/bakong/qr")
@payments_bp.post("/aba/qr")
@jwt_required()
def bakong_qr():
    user_id = int(get_jwt_identity())
    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    try:
        order_id = int(payload.get("order_id"))
    except Exception:
        return api_error("order_id is required.", 400)

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

    base = _khqr_base()
    if not base:
        return api_error("Bakong KHQR is not configured. Set BAKONG_KHQR_BASE in .env.", 501)
    if not base.startswith("000201"):
        return api_error(
            "BAKONG_KHQR_BASE must be a full EMV/KHQR payload string (it usually starts with 000201...). "
            "Do not set it to an account number. See README for how to set it from a QR image.",
            501,
        )

    currency = order.get("currency") or "USD"
    total_cents = int(order.get("total_cents", 0))
    if currency == "KHR":
        amount_str = str(int(round(total_cents / 100)))
    else:
        amount_str = f"{(total_cents / 100):.2f}"

    try:
        qr_payload = with_amount(base, amount=amount_str, point_of_initiation_method="12")
    except EmvQrError as e:
        return api_error(f"Invalid BAKONG_KHQR_BASE: {e}", 500)

    return jsonify({"qr_payload": qr_payload, "amount": amount_str, "currency": currency})
