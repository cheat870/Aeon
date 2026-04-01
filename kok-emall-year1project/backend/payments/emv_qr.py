from __future__ import annotations

from dataclasses import dataclass
import time


class EmvQrError(ValueError):
    pass


@dataclass
class EmvTlv:
    tag: str
    value: bytes


def _crc16_ccitt_false(data: bytes) -> int:
    # CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF)
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def compute_crc_hex(payload_without_crc_value: bytes) -> str:
    crc = _crc16_ccitt_false(payload_without_crc_value)
    return f"{crc:04X}"


def parse_emv_tlv(payload: str) -> list[EmvTlv]:
    raw = payload.strip()
    if not raw:
        raise EmvQrError("Empty EMV payload.")

    data = raw.encode("utf-8")
    tlvs: list[EmvTlv] = []
    i = 0
    while i < len(data):
        if i + 4 > len(data):
            raise EmvQrError("Invalid TLV encoding.")
        try:
            tag = data[i : i + 2].decode("ascii")
            length = int(data[i + 2 : i + 4].decode("ascii"))
        except Exception as e:
            raise EmvQrError("Invalid TLV tag/length.") from e
        i += 4
        if length < 0 or i + length > len(data):
            raise EmvQrError(f"Invalid TLV length for tag {tag}.")
        value = data[i : i + length]
        i += length
        tlvs.append(EmvTlv(tag=tag, value=value))
    return tlvs


def serialize_emv_tlv(tlvs: list[EmvTlv]) -> bytes:
    out = bytearray()
    for tlv in tlvs:
        if len(tlv.tag) != 2:
            raise EmvQrError("TLV tag must be 2 characters.")
        length = len(tlv.value)
        if length > 99:
            raise EmvQrError(f"TLV value too long for tag {tlv.tag}.")
        out.extend(tlv.tag.encode("ascii"))
        out.extend(f"{length:02d}".encode("ascii"))
        out.extend(tlv.value)
    return bytes(out)


def _find_index(tlvs: list[EmvTlv], tag: str) -> int | None:
    for idx, tlv in enumerate(tlvs):
        if tlv.tag == tag:
            return idx
    return None


def remove_tag(tlvs: list[EmvTlv], tag: str) -> list[EmvTlv]:
    return [t for t in tlvs if t.tag != tag]


def upsert_tag(tlvs: list[EmvTlv], tag: str, value: bytes, *, after_tag: str | None = None) -> list[EmvTlv]:
    idx = _find_index(tlvs, tag)
    if idx is not None:
        tlvs[idx] = EmvTlv(tag=tag, value=value)
        return tlvs

    insert_at = len(tlvs)
    if after_tag:
        after_idx = _find_index(tlvs, after_tag)
        if after_idx is not None:
            insert_at = after_idx + 1
    tlvs.insert(insert_at, EmvTlv(tag=tag, value=value))
    return tlvs


def _timestamp_value(*, point_of_initiation_method: str, expiration_days: int = 1) -> bytes:
    timestamp_ms = str(int(time.time() * 1000))
    value = f"00{len(timestamp_ms):02d}{timestamp_ms}"

    if point_of_initiation_method == "12":
        if expiration_days < 1:
            raise EmvQrError("expiration_days must be at least 1 for dynamic KHQR payloads.")
        expiration_ms = str(int(time.time() * 1000) + (expiration_days * 86400 * 1000))
        value += f"01{len(expiration_ms):02d}{expiration_ms}"

    return value.encode("ascii")


def with_amount(
    base_payload: str,
    *,
    amount: str,
    point_of_initiation_method: str = "12",
    expiration_days: int = 1,
) -> str:
    """
    Takes a base EMV/KHQR payload, injects/updates:
    - Tag 01 (point of initiation method): "11" static or "12" dynamic
    - Tag 54 (transaction amount)
    - Tag 99 (timestamp/expiration for dynamic KHQR compatibility)
    Recomputes Tag 63 CRC.
    """
    tlvs = parse_emv_tlv(base_payload)
    tlvs = remove_tag(tlvs, "63")
    tlvs = remove_tag(tlvs, "99")

    upsert_tag(tlvs, "01", point_of_initiation_method.encode("ascii"), after_tag="00")
    upsert_tag(tlvs, "54", amount.encode("ascii"), after_tag="53")
    upsert_tag(
        tlvs,
        "99",
        _timestamp_value(point_of_initiation_method=point_of_initiation_method, expiration_days=expiration_days),
        after_tag="62",
    )

    payload_without_crc_value = serialize_emv_tlv(tlvs) + b"6304"
    crc_hex = compute_crc_hex(payload_without_crc_value)
    final_bytes = payload_without_crc_value + crc_hex.encode("ascii")
    return final_bytes.decode("utf-8")
