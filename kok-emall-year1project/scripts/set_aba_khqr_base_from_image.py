from __future__ import annotations

import re
import sys
from pathlib import Path

from decode_qr import _decode_with_opencv


_KEY_RE = re.compile(r"^\s*ABA_KHQR_BASE\s*=")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines(keepends=False)


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _set_env_value(lines: list[str], key: str, value: str) -> list[str]:
    new_lines: list[str] = []
    replaced = False
    for line in lines:
        if _KEY_RE.match(line):
            new_lines.append(f"{key}={value}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append(f"{key}={value}")
    return new_lines


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python scripts/set_aba_khqr_base_from_image.py <path-to-qr-image>")
        return 2

    image_path = Path(argv[1]).expanduser().resolve()
    try:
        payload = _decode_with_opencv(image_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not payload.startswith("000201"):
        print("Error: Decoded QR payload does not look like an EMV/KHQR string (expected to start with 000201).", file=sys.stderr)
        return 1

    env_path = _repo_root() / ".env"
    example_path = _repo_root() / ".env.example"

    lines = _read_lines(env_path)
    if not lines and example_path.exists():
        lines = _read_lines(example_path)

    lines = _set_env_value(lines, "ABA_KHQR_BASE", payload)
    _write_lines(env_path, lines)

    print(f"Saved ABA_KHQR_BASE to {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

