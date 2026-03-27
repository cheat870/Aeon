from __future__ import annotations

import sys
from pathlib import Path


def _decode_with_opencv(image_path: Path) -> str:
    try:
        import cv2  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency. Install with: python -m pip install opencv-python"
        ) from e

    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"Unable to read image: {image_path}")

    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(image)

    if not data:
        try:
            ok, decoded_infos, _, _ = detector.detectAndDecodeMulti(image)
            if ok and decoded_infos:
                data = next((d for d in decoded_infos if d), "")
        except Exception:
            data = ""

    if not data:
        raise RuntimeError("No QR code found or unable to decode.")

    return data


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python scripts/decode_qr.py <path-to-qr-image>")
        return 2

    image_path = Path(argv[1]).expanduser().resolve()
    try:
        payload = _decode_with_opencv(image_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

