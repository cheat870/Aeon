from __future__ import annotations

import os

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend.payments.bakong_api import (
    BakongApiError,
    amount_to_cents,
    auto_confirm_enabled,
    check_transaction_by_md5,
    qr_md5,
    qr_short_hash,
)
from backend.payments.emv_qr import EmvQrError, with_amount
from backend.store import confirm_order_payment, get_latest_payment, read_state, upsert_pending_payment, utcnow_iso
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


def _order_for_user(user_id: int, order_id: int, state: dict) -> dict | None:
    return next(
        (
            row
            for row in state["orders"]
            if int(row.get("id") or 0) == order_id and int(row.get("user_id") or 0) == user_id
        ),
        None,
    )


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
    order = _order_for_user(user_id, order_id, state)
    if not order:
        return api_error("Order not found.", 404)

    existing_payment = get_latest_payment(order_id)
    if existing_payment and existing_payment.get("status") in {"pending", "processing", "created"}:
        auto_enabled = auto_confirm_enabled()
        if bool(existing_payment.get("auto_confirm_enabled")) != auto_enabled:
            refreshed = upsert_pending_payment(
                order_id,
                provider=str(existing_payment.get("provider") or "bakong_khqr"),
                amount_cents=int(order.get("total_cents", 0)),
                currency=order.get("currency") or "USD",
                qr_payload=str(existing_payment.get("qr_payload") or ""),
                qr_md5=str(existing_payment.get("qr_md5") or ""),
                qr_short_hash=str(existing_payment.get("qr_short_hash") or ""),
                auto_confirm_enabled=auto_enabled,
            )
            if refreshed and refreshed.get("payment"):
                existing_payment = refreshed["payment"]
        return jsonify(
            {
                "qr_payload": existing_payment.get("qr_payload"),
                "qr_md5": existing_payment.get("qr_md5"),
                "qr_short_hash": existing_payment.get("qr_short_hash"),
                "amount": f"{(int(order.get('total_cents', 0)) / 100):.2f}" if (order.get("currency") or "USD") != "KHR" else str(int(round(int(order.get("total_cents", 0)) / 100))),
                "currency": order.get("currency") or "USD",
                "auto_confirm_enabled": bool(existing_payment.get("auto_confirm_enabled")),
            }
        )

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

    md5_hash = qr_md5(qr_payload)
    short_hash = qr_short_hash(qr_payload)
    auto_enabled = auto_confirm_enabled()
    upsert_pending_payment(
        order_id,
        provider="bakong_khqr",
        amount_cents=int(order.get("total_cents", 0)),
        currency=currency,
        qr_payload=qr_payload,
        qr_md5=md5_hash,
        qr_short_hash=short_hash,
        auto_confirm_enabled=auto_enabled,
    )

    return jsonify(
        {
            "qr_payload": qr_payload,
            "qr_md5": md5_hash,
            "qr_short_hash": short_hash,
            "amount": amount_str,
            "currency": currency,
            "auto_confirm_enabled": auto_enabled,
        }
    )


@payments_bp.post("/bakong/check")
@payments_bp.post("/aba/check")
@jwt_required()
def bakong_check():
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
    order = _order_for_user(user_id, order_id, state)
    if not order:
        return api_error("Order not found.", 404)

    if order.get("status") == "paid":
        payment = get_latest_payment(order_id)
        return jsonify(
            {
                "order": {"id": order_id, "status": "paid"},
                "payment": payment,
                "auto_confirm_enabled": auto_confirm_enabled(),
            }
        )

    payment = get_latest_payment(order_id)
    if not payment or not payment.get("qr_md5"):
        return api_error("QR payment has not been generated for this order yet.", 409)

    if not auto_confirm_enabled():
        return jsonify(
            {
                "order": {"id": order_id, "status": order.get("status")},
                "payment": payment,
                "auto_confirm_enabled": False,
                "message": "Auto-confirm is disabled. Set BAKONG_API_TOKEN to enable payment verification.",
            }
        )

    try:
        status = check_transaction_by_md5(str(payment.get("qr_md5") or ""))
    except BakongApiError as e:
        return api_error(str(e), 502)

    if not status.get("paid"):
        return jsonify(
            {
                "order": {"id": order_id, "status": order.get("status")},
                "payment": payment,
                "auto_confirm_enabled": True,
                "message": status.get("message") or "Payment not found yet.",
            }
        )

    transaction = status.get("data") or {}
    transaction_currency = str(transaction.get("currency") or "").upper() or (order.get("currency") or "USD")
    expected_currency = str(order.get("currency") or "USD").upper()
    transaction_amount_cents = amount_to_cents(transaction.get("amount", 0))
    expected_amount_cents = int(order.get("total_cents", 0))

    if transaction_currency != expected_currency or transaction_amount_cents != expected_amount_cents:
        return api_error("Bakong reported a transaction, but the amount or currency does not match this order.", 409)

    confirmed = confirm_order_payment(
        order_id,
        provider_ref=str(transaction.get("hash") or payment.get("qr_short_hash") or f"bakong-{order_id}"),
        provider="bakong_api",
        payment_details={
            "bakong_md5": payment.get("qr_md5"),
            "bakong_transaction_hash": transaction.get("hash"),
            "from_account_id": transaction.get("fromAccountId"),
            "to_account_id": transaction.get("toAccountId"),
            "description": transaction.get("description"),
            "auto_confirm_enabled": True,
            "checked_at": utcnow_iso(),
        },
    )
    latest = confirmed["payment"] if confirmed else get_latest_payment(order_id)
    return jsonify(
        {
            "order": {"id": order_id, "status": "paid"},
            "payment": latest,
            "auto_confirm_enabled": True,
            "message": "Payment confirmed automatically.",
        }
    )
