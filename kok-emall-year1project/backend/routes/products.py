from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.store import get_product, list_products
from backend.utils import api_error

products_bp = Blueprint("products", __name__, url_prefix="/api/products")


@products_bp.get("")
def get_products():
    query = request.args.get("q", "").strip() or None
    limit = request.args.get("limit", "").strip()
    limit_value: int | None = None
    if limit:
        try:
            limit_value = max(1, min(int(limit), 100))
        except ValueError:
            return api_error("limit must be a number.", 400)

    return jsonify({"products": list_products(limit_value, query=query)})


@products_bp.get("/<int:product_id>")
def get_product_by_id(product_id: int):
    product = get_product(product_id)
    if not product:
        return api_error("Product not found.", 404)
    return jsonify({"product": product})
