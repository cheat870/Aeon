from __future__ import annotations

import sys

from backend import create_app
from backend.extensions import db
from backend.models import Order, Payment, utcnow


def main(argv: list[str]) -> int:
    if len(argv) < 2 or len(argv) > 3:
        print("Usage: python scripts/mark_order_paid.py <order_id> [provider_ref]")
        return 2

    try:
        order_id = int(argv[1])
    except Exception:
        print("Error: order_id must be a number.", file=sys.stderr)
        return 2

    provider_ref = argv[2].strip() if len(argv) == 3 else None

    app = create_app()
    with app.app_context():
        order = Order.query.get(order_id)
        if not order:
            print("Error: order not found.", file=sys.stderr)
            return 1

        if order.status == "paid":
            print(f"Order #{order.id} is already paid.")
            return 0

        if order.status != "pending_payment":
            print(f"Error: order is not payable (status={order.status}).", file=sys.stderr)
            return 1

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

        print(f"Marked Order #{order.id} as PAID.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

