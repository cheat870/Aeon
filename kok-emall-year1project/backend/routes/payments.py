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
from backend.store import (
    confirm_order_payment,
    get_latest_payment,
    get_payment_by_merchant_ref,
    read_state,
    upsert_pending_payment,
    utcnow_iso,
)
from backend.telegram_notify import send_payment_event
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


def _aba_webhook_token() -> str:
    return (
        os.environ.get("ABA_WEBHOOK_TOKEN", "").strip()
        or os.environ.get("PAYWAY_WEBHOOK_TOKEN", "").strip()
    )


def _merchant_reference(order_id: int) -> str:
    return f"KOK-ORD-{int(order_id)}"


def _order_amount_string(order: dict) -> str:
    currency = order.get("currency") or "USD"
    total_cents = int(order.get("total_cents", 0))
    if currency == "KHR":
        return str(int(round(total_cents / 100)))
    return f"{(total_cents / 100):.2f}"


def _webhook_amount_to_cents(payload: dict) -> int:
    currency = str(payload.get("original_currency") or payload.get("payment_currency") or "USD").upper()
    raw_amount = payload.get("original_amount", payload.get("payment_amount", 0))
    amount_value = float(raw_amount)
    if currency == "KHR":
        return int(round(amount_value * 100))
    return int(round(amount_value * 100))


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
                qr_merchant_ref=str(existing_payment.get("qr_merchant_ref") or _merchant_reference(order_id)),
                auto_confirm_enabled=auto_enabled,
            )
            if refreshed and refreshed.get("payment"):
                existing_payment = refreshed["payment"]
        return jsonify(
            {
                "qr_payload": existing_payment.get("qr_payload"),
                "qr_md5": existing_payment.get("qr_md5"),
                "qr_short_hash": existing_payment.get("qr_short_hash"),
                "merchant_ref": existing_payment.get("qr_merchant_ref"),
                "amount": _order_amount_string(order),
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
    amount_str = _order_amount_string(order)
    merchant_reference = _merchant_reference(order_id)

    try:
        qr_payload = with_amount(
            base,
            amount=amount_str,
            point_of_initiation_method="12",
            merchant_reference=merchant_reference,
        )
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
        qr_merchant_ref=merchant_reference,
        auto_confirm_enabled=auto_enabled,
    )

    return jsonify(
        {
            "qr_payload": qr_payload,
            "qr_md5": md5_hash,
            "qr_short_hash": short_hash,
            "merchant_ref": merchant_reference,
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


@payments_bp.post("/aba/webhook/<webhook_token>")
@payments_bp.post("/payway/webhook/<webhook_token>")
def aba_webhook(webhook_token: str):
    expected_token = _aba_webhook_token()
    if not expected_token:
        return api_error("ABA_WEBHOOK_TOKEN is not configured.", 501)
    if webhook_token != expected_token:
        return api_error("Unauthorized.", 401)

    payload = request.get_json(silent=True) or {}
    merchant_ref = str(payload.get("merchant_ref") or "").strip()
    if not merchant_ref:
        return api_error("merchant_ref is required.", 400)

    payment = get_payment_by_merchant_ref(merchant_ref)
    if not payment:
        return jsonify({"ok": True, "ignored": True, "message": "Unknown merchant_ref."})

    order_id = int(payment.get("order_id", 0))
    state = read_state()
    order = next((row for row in state["orders"] if int(row.get("id", 0)) == order_id), None)
    if not order:
        return jsonify({"ok": True, "ignored": True, "message": "Order no longer exists."})

    if order.get("status") == "paid":
        return jsonify({"ok": True, "order": {"id": order_id, "status": "paid"}})

    status_code = int(payload.get("payment_status_code", -1))
    status_text = str(payload.get("payment_status") or "").upper()
    if status_code != 0 and status_text != "APPROVED":
        return jsonify({"ok": True, "ignored": True, "message": "Payment not approved."})

    webhook_currency = str(payload.get("original_currency") or payload.get("payment_currency") or "USD").upper()
    order_currency = str(order.get("currency") or "USD").upper()
    webhook_amount_cents = _webhook_amount_to_cents(payload)
    order_amount_cents = int(order.get("total_cents", 0))
    if webhook_currency != order_currency or webhook_amount_cents != order_amount_cents:
        return api_error("Webhook payment amount/currency does not match the order.", 409)

    confirmed = confirm_order_payment(
        order_id,
        provider_ref=str(payload.get("transaction_id") or payload.get("bank_ref") or merchant_ref),
        provider="aba_payway_webhook",
        payment_details={
            "payment_status_code": status_code,
            "payment_status": payload.get("payment_status"),
            "bank_ref": payload.get("bank_ref"),
            "transaction_id": payload.get("transaction_id"),
            "apv": payload.get("apv"),
            "payer_account": payload.get("payer_account"),
            "payer_name": payload.get("payer_name"),
            "bank_name": payload.get("bank_name"),
            "payment_type": payload.get("payment_type"),
            "merchant_ref": merchant_ref,
            "webhook_confirmed_at": utcnow_iso(),
            "auto_confirm_source": "aba_webhook",
        },
    )
    order_payload = confirmed["order"] if confirmed else {"id": order_id, "status": "paid"}
    payment_payload = confirmed["payment"] if confirmed else get_latest_payment(order_id)
    send_payment_event(
        "auto_confirmed",
        order=order_payload,
        payment=payment_payload or {},
        extra_lines=[
            f"Merchant Ref: {merchant_ref}",
            f"Bank Ref: {payload.get('bank_ref') or '-'}",
            f"Payment Type: {payload.get('payment_type') or '-'}",
        ],
    )
    return jsonify({"ok": True, "order": {"id": order_id, "status": "paid"}})
