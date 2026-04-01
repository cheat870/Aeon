from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Any


class BakongApiError(RuntimeError):
    pass


def api_token() -> str:
    return (
        os.environ.get("BAKONG_API_TOKEN", "").strip()
        or os.environ.get("BAKONG_DEVELOPER_TOKEN", "").strip()
    )


def auto_confirm_enabled() -> bool:
    return bool(api_token())


def qr_md5(qr_payload: str) -> str:
    return hashlib.md5(qr_payload.encode("utf-8")).hexdigest()


def qr_short_hash(qr_payload: str) -> str:
    return qr_md5(qr_payload)[:8]


def amount_to_cents(value: Any) -> int:
    return int(round(float(value) * 100))


def check_transaction_by_md5(md5_hash: str) -> dict[str, Any]:
    token = api_token()
    if not token:
        raise BakongApiError("BAKONG_API_TOKEN is not configured.")

    payload = json.dumps({"md5": md5_hash}).encode("utf-8")
    request = urllib.request.Request(
        "https://api-bakong.nbc.gov.kh/v1/check_transaction_by_md5",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise BakongApiError(f"Bakong API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise BakongApiError(f"Bakong API network error: {exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BakongApiError("Bakong API returned invalid JSON.") from exc

    response_code = parsed.get("responseCode")
    data = parsed.get("data")
    message = str(parsed.get("responseMessage") or "")

    if response_code == 0 and isinstance(data, dict):
        return {"paid": True, "found": True, "data": data, "message": message}

    lowered = message.lower()
    if "could not be found" in lowered or "not found" in lowered:
        return {"paid": False, "found": False, "data": None, "message": message}
    if "failed" in lowered:
        return {"paid": False, "found": True, "data": None, "message": message}

    return {"paid": False, "found": False, "data": None, "message": message or "Unknown Bakong response."}
