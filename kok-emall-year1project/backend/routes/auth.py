from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from backend.store import append_auth_event, get_user_by_email, get_user_by_id, next_id, update_state, utcnow_iso
from backend.telegram_notify import send_auth_event
from backend.utils import api_error, get_json, normalize_email

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _user_to_dict(user: dict) -> dict:
    return {"id": int(user["id"]), "email": user["email"], "name": user.get("name")}


def _client_ip() -> str | None:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


@auth_bp.post("/register")
def register():
    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    email = normalize_email(str(payload.get("email", "")))
    password = str(payload.get("password", ""))
    name = str(payload.get("name", "")).strip() or None

    if not email or "@" not in email:
        return api_error("Please provide a valid email.", 400)
    if len(password) < 6:
        return api_error("Password must be at least 6 characters.", 400)
    if get_user_by_email(email):
        return api_error("Email already registered.", 409)

    password_hash = generate_password_hash(password)

    ip_address = _client_ip()

    def mutator(state: dict) -> dict:
        existing = next((row for row in state["users"] if row.get("email") == email), None)
        if existing:
            return {"error": "exists"}

        timestamp = utcnow_iso()
        user = {
            "id": next_id(state, "users"),
            "email": email,
            "name": name,
            "password_hash": password_hash,
            "created_at": timestamp,
            "last_login_at": timestamp,
            "last_logout_at": None,
            "status": "online",
        }
        state["users"].append(user)
        append_auth_event(state, event_name="register", user=user, ip_address=ip_address)
        return user

    user = update_state(mutator)
    if user.get("error") == "exists":
        return api_error("Email already registered.", 409)

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
