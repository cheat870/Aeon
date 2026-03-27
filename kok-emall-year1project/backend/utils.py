from __future__ import annotations

import re
from dataclasses import dataclass

from flask import Request, jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request


def api_error(message: str, status_code: int = 400, *, code: str | None = None):
    payload = {"error": {"message": message}}
    if code:
        payload["error"]["code"] = code
    return jsonify(payload), status_code


def get_json(required: bool = True) -> dict:
    if not request.is_json:
        if required:
            raise ValueError("Expected JSON body.")
        return {}
    return request.get_json(silent=True) or {}


def normalize_email(email: str) -> str:
    return email.strip().lower()


_PRICE_RE = re.compile(r"[^\d.]")


def parse_price_to_cents(value: str | int | float) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value * 100))
    if not isinstance(value, str):
        raise ValueError("Invalid price.")
    cleaned = _PRICE_RE.sub("", value)
    if cleaned == "":
        raise ValueError("Invalid price.")
    dollars = float(cleaned)
    return int(round(dollars * 100))


@dataclass(frozen=True)
class Actor:
    user_id: int | None
    guest_id: str | None


def get_actor(req: Request) -> Actor:
    verify_jwt_in_request(optional=True)
    user_id = get_jwt_identity()
    guest_id = req.headers.get("X-Guest-Id")
    if isinstance(user_id, str) and user_id.isdigit():
        user_id = int(user_id)
    if isinstance(user_id, int):
        return Actor(user_id=user_id, guest_id=None)
    if guest_id:
        return Actor(user_id=None, guest_id=guest_id)
    return Actor(user_id=None, guest_id=None)

