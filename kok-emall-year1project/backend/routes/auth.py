from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from backend.extensions import db
from backend.models import CartItem, User
from backend.utils import api_error, get_json, normalize_email

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _user_to_dict(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name}


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

    if User.query.filter_by(email=email).first():
        return api_error("Email already registered.", 409)

    user = User(email=email, name=name, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()

    access_token = create_access_token(identity=str(user.id))
    return jsonify({"access_token": access_token, "user": _user_to_dict(user)}), 201


@auth_bp.post("/login")
def login():
    try:
        payload = get_json()
    except ValueError as e:
        return api_error(str(e), 400)

    email = normalize_email(str(payload.get("email", "")))
    password = str(payload.get("password", ""))

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return api_error("Invalid email or password.", 401)

    access_token = create_access_token(identity=str(user.id))
    return jsonify({"access_token": access_token, "user": _user_to_dict(user)})


@auth_bp.get("/me")
@jwt_required()
def me():
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    if not user:
        return api_error("User not found.", 404)
    return jsonify({"user": _user_to_dict(user)})


@auth_bp.post("/merge-guest-cart")
@jwt_required()
def merge_guest_cart():
    user_id = int(get_jwt_identity())
    guest_id = request.headers.get("X-Guest-Id")
    if not guest_id:
        return api_error("Missing X-Guest-Id header.", 400)

    guest_items = CartItem.query.filter_by(guest_id=guest_id).all()
    if not guest_items:
        return jsonify({"merged": 0})

    merged = 0
    for item in guest_items:
        existing = CartItem.query.filter_by(user_id=user_id, product_name=item.product_name).first()
        if existing:
            existing.quantity += item.quantity
            existing.unit_price_cents = item.unit_price_cents
            existing.product_brand = item.product_brand
            existing.product_image_url = item.product_image_url
            db.session.delete(item)
        else:
            item.user_id = user_id
            item.guest_id = None
        merged += 1

    db.session.commit()
    return jsonify({"merged": merged})

