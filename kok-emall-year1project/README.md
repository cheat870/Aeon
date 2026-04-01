# KOK-eMall (Year 1 Project)

This project is a static HTML/CSS/JS frontend with a Flask backend API for:

- Login/Register/Logout (JWT)
- Cart (login required)
- Checkout (create order)
- Payment via Bakong merchant KHQR (QR payload generation)
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
- The payment page shows a Bakong KHQR QR code with the **order total**.
- The app does **not** automatically detect Bakong incoming money. A merchant/admin must confirm the payment (manual/webhook) before the invoice is available.
- Login tokens expire after `JWT_ACCESS_TOKEN_EXPIRES_DAYS` (default: 7 days).

## Bakong merchant QR (KHQR)

To generate a real Bakong merchant KHQR with the **correct amount**, set `BAKONG_KHQR_BASE` in `.env` (copy from `.env.example`).

- `BAKONG_KHQR_BASE` should be your merchant QR payload string (usually starts with `000201...`).
- The backend injects the amount and recalculates the CRC automatically.
- If you also set `BAKONG_API_TOKEN`, the app can auto-confirm paid orders by calling Bakong's `check_transaction_by_md5` API with the exact QR string MD5.

### Set from a QR image (offline)

1) Install the decoder dependency:

```bash
python -m pip install opencv-python
```

2) Save your Bakong QR image (PNG/JPG) on your computer and run:

```bash
python scripts/set_bakong_khqr_base_from_image.py path\\to\\bakong_qr.png
```

Then restart the backend.

## Confirm payment (merchant/admin)

### Auto-confirm after scan/payment

If you want the order to switch to `paid` automatically after the customer scans and pays, set:

- `BAKONG_API_TOKEN`

Then the payment page will poll Bakong's transaction-status API and auto-confirm the order when the transaction is found and the amount/currency match the order total.

If `BAKONG_API_TOKEN` is missing, the app falls back to manual confirmation below.

After you receive money in Bakong, confirm the order as paid so the user can see the invoice:

Option A (recommended): Admin API (requires `.env` secret)

- Set `PAYMENT_CONFIRM_SECRET` in `.env`
- Call `POST /api/payments/admin/confirm` with header `X-Admin-Secret`

Option B: Local admin script (updates the JSON store directly)

```bash
python scripts/mark_order_paid.py <order_id> [provider_ref]
```

## Telegram admin bot (orders + users + auth history)

The bot can list recent users, show one user summary, show auth/login history, list orders, show invoices, and confirm payments (after you verify money arrived in Bakong).

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

This repo now includes `render.yaml` at the Git repo root so you can deploy the whole Flask app to Render.

The Render setup runs the Telegram admin bot inside the same web service process (`RUN_TELEGRAM_BOT_IN_WEB=1`) so both the bot and the web app share the same JSON store.

Demo note: the current `render.yaml` uses Render's `free` plan and does not attach a persistent disk. That means users, orders, invoices, and auth history may reset after a redeploy/restart/sleep cycle.

After you push the repo, open this Blueprint link and connect your GitHub repo in Render:

```text
https://dashboard.render.com/blueprint/new?repo=https://github.com/cheat870/Aeon
```

Fill these secrets in the Render Dashboard when prompted:

- `BAKONG_KHQR_BASE`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_IDS`

The Blueprint also generates:

- `SECRET_KEY`
- `JWT_SECRET_KEY`
- `PAYMENT_CONFIRM_SECRET`
