# KOK-eMall (Year 1 Project)

This project is a static HTML/CSS/JS frontend with a Flask backend API for:

- Login/Register/Logout (JWT)
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

## Storage

- The backend stores users, carts, orders, and payments in `backend/instance/store.json`.
- No SQL/MySQL/SQLite server is required for app data anymore.
- If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ADMIN_IDS` are configured, register/login/logout events are sent to Telegram automatically.

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

Option B: Local admin script (updates the JSON store directly)

```bash
python scripts/mark_order_paid.py <order_id> [provider_ref]
```

## Telegram admin bot (orders + users + auth history)

The bot can list recent users, show one user summary, show auth/login history, list orders, show invoices, and confirm payments (after you verify money arrived in ABA).

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

- `/stats`
- `/users`
- `/user <id|email>`
- `/history [query]`
- `/orders [status]`
- `/pending`
- `/invoice <order_id>`
- `/confirm <order_id> [provider_ref]`

## Render deploy (public backend + frontend)

This repo now includes `render.yaml` at the Git repo root so you can deploy the whole Flask app to Render. Because this app stores data in `backend/instance/store.json`, the Render service should use a persistent disk so users, orders, and invoices survive restarts.

The Render setup runs the Telegram admin bot inside the same web service process (`RUN_TELEGRAM_BOT_IN_WEB=1`) so both the bot and the web app share the same JSON store.

After you push the repo, open this Blueprint link and connect your GitHub repo in Render:

```text
https://dashboard.render.com/blueprint/new?repo=https://github.com/cheat870/Aeon
```

Fill these secrets in the Render Dashboard when prompted:

- `ABA_KHQR_BASE`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_IDS`

The Blueprint also generates:

- `SECRET_KEY`
- `JWT_SECRET_KEY`
- `PAYMENT_CONFIRM_SECRET`
