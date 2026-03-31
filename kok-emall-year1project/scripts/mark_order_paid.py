from __future__ import annotations

import sys

from dotenv import load_dotenv

from backend.store import confirm_order_payment, get_order_details


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

    load_dotenv()
    details = get_order_details(order_id)
    if not details:
        print("Error: order not found.", file=sys.stderr)
        return 1

    order = details["order"]
    if order.get("status") == "paid":
        print(f"Order #{order_id} is already paid.")
        return 0
    if order.get("status") != "pending_payment":
        print(f"Error: order is not payable (status={order.get('status')}).", file=sys.stderr)
        return 1

    confirm_order_payment(order_id, provider_ref=provider_ref)
    print(f"Marked Order #{order_id} as PAID.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
