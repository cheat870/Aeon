# KOK-eMall (Year 1 Project)

This project is a static HTML/CSS/JS frontend with a simple Flask backend API for:

- Login/Register (JWT)
- Cart (login required)
- Checkout (create order)
- Payment via ABA merchant KHQR (QR payload generation)
- Invoice (shown after payment confirmed)

## Quick start

### 1) Install backend deps

```bash
cd backend
pip install -r requirements.txt
```

### 2) Run the app

From the repo root:

```bash
python -m backend
```

Then open:

- http://127.0.0.1:5000/

## Notes

- You must **login/register** before you can view the cart, add items, checkout, or pay.
- The payment page shows an ABA KHQR QR code with the **order total**.
- The app does **not** automatically detect ABA incoming money. A merchant/admin must confirm the payment (manual/webhook) before the invoice is available.
- Login tokens expire after `JWT_ACCESS_TOKEN_EXPIRES_DAYS` (default: 7 days).

## ABA merchant QR (KHQR)

To generate a real ABA merchant KHQR with the **correct amount**, set `ABA_KHQR_BASE` in `.env` (copy from `.env.example`).

- `ABA_KHQR_BASE` should be your merchant QR payload string (usually starts with `000201...`).
- The backend injects the amount and recalculates the CRC automatically.

### Set from a QR image (offline)

1) Install the decoder dependency:

```bash
python -m pip install opencv-python
```

2) Save your ABA QR image (PNG/JPG) on your computer and run:

```bash
python scripts/set_aba_khqr_base_from_image.py path\\to\\aba_qr.png
```

Then restart the backend.

## Confirm payment (merchant/admin)

After you receive money in ABA, confirm the order as paid so the user can see the invoice:

Option A (recommended): Admin API (requires `.env` secret)

- Set `PAYMENT_CONFIRM_SECRET` in `.env`
- Call `POST /api/payments/admin/confirm` with header `X-Admin-Secret`

Option B: Local admin script (updates SQLite directly)

```bash
python scripts/mark_order_paid.py <order_id> [provider_ref]
```

## Telegram admin bot (view invoices)

The bot can list pending orders, show invoices, and confirm payments (after you verify money arrived in ABA).

1) Copy `.env.example` to `.env` and set:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_IDS` (comma-separated Telegram user IDs)

2) Run the bot:

```bash
python scripts/telegram_bot.py
```

3) In Telegram, chat with your bot:

- `/myid` to get your Telegram user id
- Add that id to `TELEGRAM_ADMIN_IDS` and restart the bot

Commands:

- `/pending`
- `/invoice <order_id>`
- `/confirm <order_id> [provider_ref]`
