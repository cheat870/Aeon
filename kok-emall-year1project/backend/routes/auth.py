from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from backend.emailer import EmailDeliveryError, send_registration_verification_email
from backend.store import append_auth_event, get_user_by_email, get_user_by_id, next_id, update_state, utcnow_iso
from backend.telegram_notify import send_auth_event, send_verification_code
from backend.utils import api_error, get_json, normalize_email

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
REGISTER_CODE_DIGITS = 8
REGISTER_CODE_EXPIRES_MINUTES = 10
REGISTER_CODE_MAX_ATTEMPTS = 5


def _user_to_dict(user: dict) -> dict:
    return {"id": int(user["id"]), "email": user["email"], "name": user.get("name")}


def _client_ip() -> str | None:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def _mask_email(email: str) -> str:
    local, _, domain = str(email or "").partition("@")
    if not local or not domain:
        return email
    visible = local[:2]
    masked_local = visible + "*" * max(1, len(local) - len(visible))
    return f"{masked_local}@{domain}"


def _purge_expired_register_verifications(state: dict) -> None:
    now = datetime.now(timezone.utc)
    fresh_rows = []
    for row in state.get("register_verifications", []):
        expires_at = str(row.get("expires_at") or "").strip()
        try:
            expiry = datetime.fromisoformat(expires_at)
        except ValueError:
            continue
        if expiry > now:
            fresh_rows.append(row)
    state["register_verifications"] = fresh_rows


@auth_bp.post("/register")
def register():
    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    email = normalize_email(str(payload.get("email", "")))
    password = str(payload.get("password", ""))
    name = str(payload.get("name", "")).strip() or None
    verification_code = str(payload.get("verification_code", "")).strip().replace(" ", "")

    if not email or "@" not in email:
        return api_error("Please provide a valid email.", 400)
    if len(password) < 6:
        return api_error("Password must be at least 6 characters.", 400)
    if get_user_by_email(email):
        return api_error("Email already registered.", 409)

    ip_address = _client_ip()

    if not verification_code:
        password_hash = generate_password_hash(password)
        code = f"{secrets.randbelow(10**REGISTER_CODE_DIGITS):0{REGISTER_CODE_DIGITS}d}"
        code_hash = generate_password_hash(code)
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=REGISTER_CODE_EXPIRES_MINUTES)).isoformat()

        def mutator(state: dict) -> dict:
            existing = next((row for row in state["users"] if row.get("email") == email), None)
            if existing:
                return {"error": "exists"}

            _purge_expired_register_verifications(state)
            state["register_verifications"] = [
                row for row in state.get("register_verifications", []) if row.get("email") != email
            ]
            timestamp = utcnow_iso()
            state["register_verifications"].append(
                {
                    "email": email,
                    "name": name,
                    "password_hash": password_hash,
                    "code_hash": code_hash,
                    "attempts": 0,
                    "expires_at": expires_at,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "ip_address": ip_address,
                }
            )
            return {"ok": True}

        result = update_state(mutator)
        if result.get("error") == "exists":
            return api_error("Email already registered.", 409)

        # Always notify via Telegram if configured
        send_verification_code(email, code, name=name)

        email_sent = True
        email_err_msg = ""
        try:
            send_registration_verification_email(
                to_email=email,
                code=code,
                expires_minutes=REGISTER_CODE_EXPIRES_MINUTES,
                recipient_name=name,
            )
        except EmailDeliveryError as exc:
            email_sent = False
            email_err_msg = str(exc)

        # If email delivery failed:
        if not email_sent:
            # If demo mode is active or debug is on, allow code in response
            demo_mode = os.environ.get("DEMO_MODE", "1") == "1" or os.environ.get("FLASK_DEBUG", "0") == "1"
            if demo_mode:
                return (
                    jsonify(
                        {
                            "verification_required": True,
                            "message": f"Code: {code} (Demo/testing mode. Email error: {email_err_msg})",
                            "email": email,
                            "code": code,
                            "masked_email": _mask_email(email),
                            "expires_in_minutes": REGISTER_CODE_EXPIRES_MINUTES,
                        }
                    ),
                    202,
                )

            def rollback(state: dict) -> None:
                state["register_verifications"] = [
                    row for row in state.get("register_verifications", []) if row.get("email") != email
                ]

            update_state(rollback)
            return api_error(email_err_msg, 503, code="EMAIL_SEND_FAILED")

        return (
            jsonify(
                {
                    "verification_required": True,
                    "message": f"We sent an 8-digit verification code to {_mask_email(email)}.",
                    "email": email,
                    "masked_email": _mask_email(email),
                    "expires_in_minutes": REGISTER_CODE_EXPIRES_MINUTES,
                }
            ),
            202,
        )

    if not verification_code.isdigit() or len(verification_code) != REGISTER_CODE_DIGITS:
        return api_error("Please enter the 8-digit verification code.", 400)

    def mutator(state: dict) -> dict:
        existing = next((row for row in state["users"] if row.get("email") == email), None)
        if existing:
            return {"error": "exists"}

        _purge_expired_register_verifications(state)
        verification = next((row for row in state.get("register_verifications", []) if row.get("email") == email), None)
        if not verification:
            return {"error": "missing_verification"}

        if not check_password_hash(str(verification.get("code_hash") or ""), verification_code):
            verification["attempts"] = int(verification.get("attempts", 0)) + 1
            verification["updated_at"] = utcnow_iso()
            if int(verification["attempts"]) >= REGISTER_CODE_MAX_ATTEMPTS:
                state["register_verifications"] = [
                    row for row in state.get("register_verifications", []) if row.get("email") != email
                ]
                return {"error": "too_many_attempts"}
            return {
                "error": "invalid_code",
                "remaining_attempts": REGISTER_CODE_MAX_ATTEMPTS - int(verification["attempts"]),
            }

        timestamp = utcnow_iso()
        user = {
            "id": next_id(state, "users"),
            "email": email,
            "name": name or verification.get("name"),
            "password_hash": generate_password_hash(password),
            "created_at": timestamp,
            "last_login_at": timestamp,
            "last_logout_at": None,
            "status": "online",
            "email_verified_at": timestamp,
        }
        state["users"].append(user)
        append_auth_event(state, event_name="register", user=user, ip_address=ip_address)
        state["register_verifications"] = [
            row for row in state.get("register_verifications", []) if row.get("email") != email
        ]
        return user

    user = update_state(mutator)
    if user.get("error") == "exists":
        return api_error("Email already registered.", 409)
    if user.get("error") == "missing_verification":
        return api_error("Please request a verification code first.", 409, code="VERIFICATION_REQUIRED")
    if user.get("error") == "too_many_attempts":
        return api_error("Too many wrong codes. Please request a new verification code.", 429, code="TOO_MANY_ATTEMPTS")
    if user.get("error") == "invalid_code":
        return api_error(
            f"Invalid verification code. {user.get('remaining_attempts', 0)} attempt(s) left.",
            400,
            code="INVALID_VERIFICATION_CODE",
        )

    send_auth_event("register", user, ip_address=ip_address)
    access_token = create_access_token(identity=str(user["id"]))
    return jsonify({"access_token": access_token, "user": _user_to_dict(user)}), 201


@auth_bp.post("/login")
def login():
    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    email = normalize_email(str(payload.get("email", "")))
    password = str(payload.get("password", ""))

    user = get_user_by_email(email)
    if not user or not check_password_hash(user.get("password_hash", ""), password):
        return api_error("Invalid email or password.", 401)

    ip_address = _client_ip()

    def mutator(state: dict) -> dict | None:
        for row in state["users"]:
            if int(row.get("id", 0)) == int(user["id"]):
                row["last_login_at"] = utcnow_iso()
                row["status"] = "online"
                append_auth_event(state, event_name="login", user=row, ip_address=ip_address)
                return row
        return None

    fresh_user = update_state(mutator)
    if not fresh_user:
        return api_error("User not found.", 404)

    send_auth_event("login", fresh_user, ip_address=ip_address)
    access_token = create_access_token(identity=str(fresh_user["id"]))
    return jsonify({"access_token": access_token, "user": _user_to_dict(fresh_user)})


@auth_bp.get("/me")
@jwt_required()
def me():
    user_id = int(get_jwt_identity())
    user = get_user_by_id(user_id)
    if not user:
        return api_error("User not found.", 404)
    return jsonify({"user": _user_to_dict(user)})


@auth_bp.post("/logout")
@jwt_required()
def logout():
    user_id = int(get_jwt_identity())

    ip_address = _client_ip()

    def mutator(state: dict) -> dict | None:
        for row in state["users"]:
            if int(row.get("id", 0)) == user_id:
                row["last_logout_at"] = utcnow_iso()
                row["status"] = "offline"
                append_auth_event(state, event_name="logout", user=row, ip_address=ip_address)
                return row
        return None

    user = update_state(mutator)
    if not user:
        return api_error("User not found.", 404)

    send_auth_event("logout", user, ip_address=ip_address)
    return jsonify({"ok": True})


@auth_bp.post("/merge-guest-cart")
@jwt_required()
def merge_guest_cart():
    user_id = int(get_jwt_identity())
    guest_id = request.headers.get("X-Guest-Id")
    if not guest_id:
        return api_error("Missing X-Guest-Id header.", 400)

    def mutator(state: dict) -> int:
        guest_items = [item for item in state["cart_items"] if item.get("guest_id") == guest_id]
        if not guest_items:
            return 0

        merged = 0
        for guest_item in guest_items:
            existing = next(
                (
                    item
                    for item in state["cart_items"]
                    if int(item.get("user_id") or 0) == user_id and item.get("product_name") == guest_item.get("product_name")
                ),
                None,
            )
            if existing:
                existing["quantity"] = int(existing.get("quantity", 0)) + int(guest_item.get("quantity", 0))
                existing["unit_price_cents"] = int(guest_item.get("unit_price_cents", 0))
                existing["product_brand"] = guest_item.get("product_brand")
                existing["product_image_url"] = guest_item.get("product_image_url")
                existing["updated_at"] = utcnow_iso()
            else:
                guest_item["user_id"] = user_id
                guest_item["guest_id"] = None
                guest_item["updated_at"] = utcnow_iso()
            merged += 1

        state["cart_items"] = [item for item in state["cart_items"] if item.get("guest_id") != guest_id]
        for guest_item in guest_items:
            if int(guest_item.get("user_id") or 0) == user_id:
                state["cart_items"].append(guest_item)
        return merged

    merged = update_state(mutator)
    return jsonify({"merged": merged})
