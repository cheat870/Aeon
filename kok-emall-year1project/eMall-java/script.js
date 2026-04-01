(function () {
  const STORAGE_TOKEN_KEY = 'emall_access_token';
  const STORAGE_USER_KEY = 'emall_user';
  const STORAGE_GUEST_ID_KEY = 'emall_guest_id';

  let paymentPollTimer = null;

  function getAccessToken() {
    return localStorage.getItem(STORAGE_TOKEN_KEY);
  }

  function setAccessToken(token) {
    if (!token) return;
    localStorage.setItem(STORAGE_TOKEN_KEY, token);
  }

  function clearAccessToken() {
    localStorage.removeItem(STORAGE_TOKEN_KEY);
    localStorage.removeItem(STORAGE_USER_KEY);
  }

  function getStoredUser() {
    try {
      const raw = localStorage.getItem(STORAGE_USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  function setStoredUser(user) {
    if (!user) return;
    localStorage.setItem(STORAGE_USER_KEY, JSON.stringify(user));
  }

  function ensureGuestId() {
    let guestId = localStorage.getItem(STORAGE_GUEST_ID_KEY);
    if (guestId) return guestId;

    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      guestId = crypto.randomUUID();
    } else {
      guestId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    localStorage.setItem(STORAGE_GUEST_ID_KEY, guestId);
    return guestId;
  }

  function formatMoney(cents, currency = 'USD') {
    const amount = (cents || 0) / 100;
    try {
      return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount);
    } catch {
      return `$${amount.toFixed(2)}`;
    }
  }

  function parsePriceTextToCents(text) {
    const cleaned = String(text || '').replace(/[^\d.]/g, '');
    const dollars = Number.parseFloat(cleaned);
    if (Number.isNaN(dollars)) return 0;
    return Math.round(dollars * 100);
  }

  async function apiFetch(path, options = {}) {
    const headers = {
      Accept: 'application/json',
      ...(options.headers || {}),
    };

    const token = getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    headers['X-Guest-Id'] = ensureGuestId();

    const hasBody = options.body !== undefined && options.body !== null;
    if (hasBody && !(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }

    const res = await fetch(path, {
      ...options,
      headers,
      body: hasBody && !(options.body instanceof FormData) ? JSON.stringify(options.body) : options.body,
    });

    const contentType = res.headers.get('content-type') || '';
    const data = contentType.includes('application/json') ? await res.json().catch(() => null) : null;
    if (!res.ok) {
      const message = data?.error?.message || data?.msg || `Request failed (${res.status})`;
      const err = new Error(message);
      err.status = res.status;
      err.data = data;
      if (res.status === 401 || res.status === 422) {
        clearAccessToken();
      }
      throw err;
    }
    return data;
  }

  function ensureToastStyles() {
    if (document.getElementById('emall-toast-styles')) return;
    const style = document.createElement('style');
    style.id = 'emall-toast-styles';
    style.textContent = `
      .emall-toast {
        position: fixed;
        left: 50%;
        bottom: 24px;
        transform: translateX(-50%);
        background: rgba(0,0,0,0.85);
        color: #fff;
        padding: 10px 14px;
        border-radius: 10px;
        font-size: 14px;
        z-index: 2000;
        max-width: min(520px, calc(100% - 40px));
        box-shadow: 0 10px 24px rgba(0,0,0,0.25);
      }
    `;
    document.head.appendChild(style);
  }

  function toast(message) {
    ensureToastStyles();
    const el = document.createElement('div');
    el.className = 'emall-toast';
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2400);
  }

  function setFlash(message) {
    try {
      sessionStorage.setItem('emall_flash', message);
    } catch {
      // ignore
    }
  }

  function showFlashIfAny() {
    try {
      const message = sessionStorage.getItem('emall_flash');
      if (!message) return;
      sessionStorage.removeItem('emall_flash');
      toast(message);
    } catch {
      // ignore
    }
  }

  async function refreshMeIfNeeded() {
    const token = getAccessToken();
    if (!token) return;

    try {
      const data = await apiFetch('/api/auth/me');
      if (data?.user) setStoredUser(data.user);
    } catch {
      // Ignore network errors; apiFetch already clears on 401/422.
    }
  }

  function currentPagePath() {
    const path = window.location.pathname || '';
    const file = path.split('/').pop() || 'index.html';
    return file;
  }

  function currentPageWithQuery() {
    return `${currentPagePath()}${window.location.search || ''}`;
  }

  function insertNavItem(navbar, li) {
    const closeEl = document.getElementById('close');
    if (closeEl && closeEl.parentElement === navbar) {
      navbar.insertBefore(li, closeEl);
    } else {
      navbar.appendChild(li);
    }
  }

  async function updateNavbarAuth() {
    const navbar = document.getElementById('navbar');
    if (!navbar) return;

    await refreshMeIfNeeded();

    const token = getAccessToken();
    const user = getStoredUser();

    let existing = document.getElementById('nav-account');
    if (existing) existing.remove();
    existing = document.getElementById('nav-logout');
    if (existing) existing.remove();

    if (!token) {
      const li = document.createElement('li');
      li.id = 'nav-account';
      const a = document.createElement('a');
      const next = encodeURIComponent(currentPagePath());
      a.href = `login.html?next=${next}`;
      a.textContent = 'Login';
      li.appendChild(a);
      insertNavItem(navbar, li);
      return;
    }

    const li = document.createElement('li');
    li.id = 'nav-account';
    const a = document.createElement('a');
    a.href = '#';
    a.textContent = user?.name ? `Hi, ${user.name}` : 'My Account';
    li.appendChild(a);
    insertNavItem(navbar, li);

    const liLogout = document.createElement('li');
    liLogout.id = 'nav-logout';
    const logoutLink = document.createElement('a');
    logoutLink.href = '#';
    logoutLink.textContent = 'Logout';
    logoutLink.addEventListener('click', async (e) => {
      e.preventDefault();
      try {
        await apiFetch('/api/auth/logout', { method: 'POST' });
      } catch {
      }
      clearAccessToken();
      toast('Logged out');
      window.location.href = 'index.html';
    });
    liLogout.appendChild(logoutLink);
    insertNavItem(navbar, liLogout);
  }

  function ensureCartCountStyles() {
    if (document.getElementById('emall-cart-count-styles')) return;
    const style = document.createElement('style');
    style.id = 'emall-cart-count-styles';
    style.textContent = `
      .emall-cart-link {
        position: relative;
        display: inline-block;
      }
      .emall-cart-count {
        position: absolute;
        top: -10px;
        right: -12px;
        background: rgb(24, 145, 145);
        color: #fff;
        border-radius: 999px;
        font-size: 12px;
        line-height: 1;
        padding: 4px 6px;
        min-width: 20px;
        text-align: center;
        border: 2px solid #fff;
      }
    `;
    document.head.appendChild(style);
  }

  function attachCartBadge(anchorEl) {
    if (!anchorEl) return null;
    ensureCartCountStyles();
    anchorEl.classList.add('emall-cart-link');
    let badge = anchorEl.querySelector('.emall-cart-count');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'emall-cart-count';
      badge.textContent = '0';
      anchorEl.appendChild(badge);
    }
    return badge;
  }

  async function refreshCartCount() {
    const desktopCart = document.querySelector('#lg-bag a');
    const mobileCart = document.querySelector('#mobile a');
    const desktopBadge = attachCartBadge(desktopCart);
    const mobileBadge = attachCartBadge(mobileCart);

    if (!getAccessToken()) {
      if (desktopBadge) desktopBadge.textContent = '0';
      if (mobileBadge) mobileBadge.textContent = '0';
      return;
    }

    try {
      const cart = await apiFetch('/api/cart');
      const count = (cart?.items || []).reduce((sum, i) => sum + (i.quantity || 0), 0);
      if (desktopBadge) desktopBadge.textContent = String(count);
      if (mobileBadge) mobileBadge.textContent = String(count);
    } catch {
      if (desktopBadge) desktopBadge.textContent = '0';
      if (mobileBadge) mobileBadge.textContent = '0';
    }
  }

  function productFromProCard(proEl) {
    const img = proEl.querySelector('img');
    const brand = proEl.querySelector('.des span');
    const name = proEl.querySelector('.des h3');
    const price = proEl.querySelector('.des h2');

    return {
      name: name ? name.textContent.trim() : 'Item',
      brand: brand ? brand.textContent.trim() : null,
      image_url: img ? img.getAttribute('src') : null,
      unit_price_cents: parsePriceTextToCents(price ? price.textContent : ''),
    };
  }

  function productFromSingleProductPage() {
    const name = document.querySelector('.single-pro-details h4');
    const price = document.querySelector('.single-pro-details h2');
    const img = document.getElementById('MainImg');
    return {
      name: name ? name.textContent.trim() : 'Item',
      brand: null,
      image_url: img ? img.getAttribute('src') : null,
      unit_price_cents: parsePriceTextToCents(price ? price.textContent : ''),
    };
  }

  async function addToCart(product, quantity = 1) {
    if (!getAccessToken()) {
      const next = encodeURIComponent(currentPageWithQuery());
      window.location.href = `login.html?next=${next}`;
      return;
    }
    try {
      await apiFetch('/api/cart/items', {
        method: 'POST',
        body: { product, quantity },
      });
    } catch (err) {
      if (err?.status === 401 || err?.status === 422) {
        const next = encodeURIComponent(currentPageWithQuery());
        window.location.href = `login.html?next=${next}`;
        return;
      }
      throw err;
    }
    toast('Added to cart');
    await refreshCartCount();
  }

  function bindAddToCartButtons() {
    const productCards = document.querySelectorAll('.pro');
    for (const card of productCards) {
      const cartLink = card.querySelector('a');
      if (!cartLink) continue;

      cartLink.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        try {
          await addToCart(productFromProCard(card), 1);
        } catch (err) {
          toast(err?.message || 'Failed to add to cart');
        }
      });
    }

    const addBtn = document.querySelector('.single-pro-details button.normal');
    if (addBtn) {
      addBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        const qtyInput = document.querySelector('.single-pro-details input[type="number"]');
        const qty = qtyInput ? Number.parseInt(qtyInput.value, 10) || 1 : 1;
        try {
          await addToCart(productFromSingleProductPage(), qty);
        } catch (err) {
          toast(err?.message || 'Failed to add to cart');
        }
      });
    }
  }

  function setText(el, text) {
    if (!el) return;
    el.textContent = text;
  }

  function cartRowHtml(item, currency) {
    const imageUrl = item?.product?.image_url || '';
    const productName = item?.product?.name || 'Item';
    const unit = formatMoney(item?.product?.unit_price_cents || 0, currency);
    const subtotal = formatMoney(item?.line_total_cents || 0, currency);

    return `
      <tr data-item-id="${item.id}">
        <td><button class="normal emall-remove" style="padding:8px 12px;">Remove</button></td>
        <td>${imageUrl ? `<img src="${imageUrl}" alt="">` : ''}</td>
        <td>${productName}</td>
        <td>${unit}</td>
        <td><input class="emall-qty" type="number" min="1" max="99" value="${item.quantity}"></td>
        <td class="emall-line-total">${subtotal}</td>
      </tr>
    `;
  }

  async function renderCartPage() {
    const tbody = document.getElementById('cart-items');
    const subtotalCell = document.getElementById('cart-subtotal');
    const totalCell = document.getElementById('cart-total');
    const checkoutBtn = document.getElementById('checkout-btn');
    const emptyEl = document.getElementById('cart-empty');

    if (!tbody) return;

    if (!getAccessToken()) {
      const next = encodeURIComponent('cart.html');
      window.location.href = `login.html?next=${next}`;
      return;
    }

    try {
      const cart = await apiFetch('/api/cart');
      const items = cart?.items || [];
      const currency = cart?.currency || 'USD';

      if (emptyEl) emptyEl.style.display = items.length === 0 ? 'block' : 'none';

      tbody.innerHTML = items.map((i) => cartRowHtml(i, currency)).join('');
      setText(subtotalCell, formatMoney(cart?.subtotal_cents || 0, currency));
      setText(totalCell, formatMoney(cart?.total_cents || 0, currency));

      tbody.querySelectorAll('.emall-remove').forEach((btn) => {
        btn.addEventListener('click', async (e) => {
          e.preventDefault();
          const tr = btn.closest('tr');
          const itemId = tr?.getAttribute('data-item-id');
          if (!itemId) return;
          try {
            await apiFetch(`/api/cart/items/${itemId}`, { method: 'DELETE' });
            await renderCartPage();
            await refreshCartCount();
          } catch (err) {
            toast(err?.message || 'Failed to remove item');
          }
        });
      });

      tbody.querySelectorAll('.emall-qty').forEach((input) => {
        input.addEventListener('change', async () => {
          const tr = input.closest('tr');
          const itemId = tr?.getAttribute('data-item-id');
          if (!itemId) return;
          const quantity = Number.parseInt(input.value, 10) || 1;
          try {
            await apiFetch(`/api/cart/items/${itemId}`, { method: 'PATCH', body: { quantity } });
            await renderCartPage();
            await refreshCartCount();
          } catch (err) {
            toast(err?.message || 'Failed to update quantity');
          }
        });
      });

      if (checkoutBtn) {
        checkoutBtn.disabled = items.length === 0;
        if (!checkoutBtn.dataset.emallBound) {
          checkoutBtn.dataset.emallBound = '1';
          checkoutBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            const token = getAccessToken();
            if (!token) {
              const next = encodeURIComponent('cart.html');
              window.location.href = `login.html?next=${next}`;
              return;
            }

            try {
              const data = await apiFetch('/api/orders', { method: 'POST' });
              const orderId = data?.order?.id;
              if (!orderId) throw new Error('Order creation failed');
              window.location.href = `payment.html?order_id=${encodeURIComponent(orderId)}`;
            } catch (err) {
              if (err?.status === 401 || err?.status === 422) {
                const next = encodeURIComponent('cart.html');
                window.location.href = `login.html?next=${next}`;
                return;
              }
              if (err?.status === 409 && err?.data?.error?.code === 'PENDING_PAYMENT' && err?.data?.error?.order_id) {
                setFlash('Please pay your existing order first.');
                window.location.href = `payment.html?order_id=${encodeURIComponent(err.data.error.order_id)}`;
                return;
              }
              toast(err?.message || 'Checkout failed');
            }
          });
        }
      }
    } catch (err) {
      if (err?.status === 401 || err?.status === 422) {
        const next = encodeURIComponent('cart.html');
        window.location.href = `login.html?next=${next}`;
        return;
      }
      toast(err?.message || 'Failed to load cart');
    }
  }

  async function bindAuthForms() {
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');

    if (loginForm) {
      loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('login-email')?.value || '';
        const password = document.getElementById('login-password')?.value || '';
        try {
          const data = await apiFetch('/api/auth/login', { method: 'POST', body: { email, password } });
          setAccessToken(data.access_token);
          setStoredUser(data.user);
          const next = new URLSearchParams(window.location.search).get('next') || 'index.html';
          window.location.href = next;
        } catch (err) {
          toast(err?.message || 'Login failed');
        }
      });
    }

    if (registerForm) {
      registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('register-name')?.value || '';
        const email = document.getElementById('register-email')?.value || '';
        const password = document.getElementById('register-password')?.value || '';
        try {
          const data = await apiFetch('/api/auth/register', { method: 'POST', body: { name, email, password } });
          setAccessToken(data.access_token);
          setStoredUser(data.user);
          const next = new URLSearchParams(window.location.search).get('next') || 'index.html';
          window.location.href = next;
        } catch (err) {
          toast(err?.message || 'Register failed');
        }
      });
    }
  }

  function preserveNextParamInAuthLinks() {
    const next = new URLSearchParams(window.location.search).get('next');
    if (!next) return;

    document.querySelectorAll('a[href="login.html"], a[href="register.html"]').forEach((a) => {
      const href = a.getAttribute('href');
      if (!href) return;
      const url = new URL(href, window.location.href);
      url.searchParams.set('next', next);
      const page = url.pathname.split('/').pop();
      a.href = `${page}?${url.searchParams.toString()}`;
    });
  }

  async function renderPaymentPage() {
    const root = document.getElementById('payment-root');
    if (!root) return;

    const token = getAccessToken();
    if (!token) {
      const next = encodeURIComponent('payment.html' + window.location.search);
      window.location.href = `login.html?next=${next}`;
      return;
    }

    const params = new URLSearchParams(window.location.search);
    const orderId = params.get('order_id');
    if (!orderId) {
      root.innerHTML = '<h2>Missing order_id</h2>';
      return;
    }

    try {
      const data = await apiFetch(`/api/orders/${encodeURIComponent(orderId)}`);
      const order = data?.order;
      const currency = order?.currency || 'USD';
      const items = order?.items || [];
      const isPaid = order?.status === 'paid';

      let qrPayload = null;
      try {
        const qrData = await apiFetch('/api/payments/bakong/qr', { method: 'POST', body: { order_id: order.id } });
        qrPayload = qrData?.qr_payload || null;
      } catch (err) {
        qrPayload = null;
      }

      const statusHtml = isPaid
        ? `<p class="payment-status paid">Status: Paid</p>`
        : `<p class="payment-status pending">Status: Waiting for payment confirmation…</p>`;

      const invoiceButtonHtml = isPaid
        ? `<button id="view-invoice" class="normal" style="margin-top:12px;">View invoice</button>`
        : `<button id="refresh-status" class="normal" style="margin-top:12px;">Refresh status</button>`;

      root.innerHTML = `
        <h2>Payment</h2>
        <p>Order #${order.id}</p>
        ${statusHtml}

        <div class="payment-grid" style="margin-top:12px;">
          <div class="payment-qr">
            <h3>Scan QR to pay</h3>
            <canvas id="payment-qr-canvas"></canvas>
            <p id="payment-qr-fallback" style="display:none;color:gray;">Bakong QR not configured. Set BAKONG_KHQR_BASE in .env.</p>
            <p style="margin-top:8px;color:gray;">Amount: <strong>${formatMoney(order.total_cents, currency)}</strong></p>
          </div>

          <div>
            <table width="100%">
              <thead>
                <tr>
                  <td>Item</td>
                  <td>Qty</td>
                  <td>Price</td>
                </tr>
              </thead>
              <tbody>
                ${items
                  .map(
                    (i) => `
                  <tr>
                    <td>${i.product?.name || 'Item'}</td>
                    <td>${i.quantity}</td>
                    <td>${formatMoney(i.line_total_cents, currency)}</td>
                  </tr>
                `
                  )
                  .join('')}
              </tbody>
            </table>

            <h3 style="margin-top:16px;">Total: ${formatMoney(order.total_cents, currency)}</h3>
            ${invoiceButtonHtml}
            <p style="margin-top:10px;color:gray;">After paying, please wait until the merchant confirms your payment.</p>
          </div>
        </div>
      `;

      const canvas = document.getElementById('payment-qr-canvas');
      const fallback = document.getElementById('payment-qr-fallback');
      if (qrPayload && canvas && typeof QRCode !== 'undefined' && typeof QRCode.toCanvas === 'function') {
        try {
          await new Promise((resolve, reject) => {
            QRCode.toCanvas(canvas, qrPayload, { width: 220, margin: 2 }, (err) => {
              if (err) reject(err);
              else resolve();
            });
          });
        } catch {
          if (fallback) fallback.style.display = 'block';
        }
      } else if (fallback) {
        fallback.style.display = 'block';
      }

      const viewInvoiceBtn = document.getElementById('view-invoice');
      if (viewInvoiceBtn) {
        viewInvoiceBtn.addEventListener('click', (e) => {
          e.preventDefault();
          window.location.href = `invoice.html?order_id=${encodeURIComponent(order.id)}`;
        });
      }

      const refreshBtn = document.getElementById('refresh-status');
      if (refreshBtn) {
        refreshBtn.addEventListener('click', async (e) => {
          e.preventDefault();
          try {
            const refreshed = await apiFetch(`/api/orders/${encodeURIComponent(order.id)}`);
            if (refreshed?.order?.status === 'paid') {
              window.location.href = `invoice.html?order_id=${encodeURIComponent(order.id)}`;
            } else {
              toast('Payment not confirmed yet.');
            }
          } catch (err) {
            if (err?.status === 401 || err?.status === 422) {
              const next = encodeURIComponent(`payment.html?order_id=${encodeURIComponent(order.id)}`);
              window.location.href = `login.html?next=${next}`;
              return;
            }
            toast(err?.message || 'Failed to refresh status');
          }
        });
      }

      if (!isPaid) {
        if (paymentPollTimer) clearInterval(paymentPollTimer);
        paymentPollTimer = setInterval(async () => {
          try {
            const refreshed = await apiFetch(`/api/orders/${encodeURIComponent(order.id)}`);
            if (refreshed?.order?.status === 'paid') {
              if (paymentPollTimer) clearInterval(paymentPollTimer);
              paymentPollTimer = null;
              window.location.href = `invoice.html?order_id=${encodeURIComponent(order.id)}`;
            }
          } catch (err) {
            if (err?.status === 401 || err?.status === 422) {
              if (paymentPollTimer) clearInterval(paymentPollTimer);
              paymentPollTimer = null;
              const next = encodeURIComponent(`payment.html?order_id=${encodeURIComponent(order.id)}`);
              window.location.href = `login.html?next=${next}`;
            }
          }
        }, 3000);
      }
    } catch (err) {
      if (err?.status === 401 || err?.status === 422) {
        const next = encodeURIComponent(`payment.html?order_id=${encodeURIComponent(orderId)}`);
        window.location.href = `login.html?next=${next}`;
        return;
      }
      root.innerHTML = `<h2>${err?.message || 'Failed to load order'}</h2>`;
    }
  }

  async function renderInvoicePage() {
    const root = document.getElementById('invoice-root');
    if (!root) return;

    const token = getAccessToken();
    if (!token) {
      const next = encodeURIComponent('invoice.html' + window.location.search);
      window.location.href = `login.html?next=${next}`;
      return;
    }

    const params = new URLSearchParams(window.location.search);
    const orderId = params.get('order_id');
    if (!orderId) {
      root.innerHTML = '<h2>Missing order_id</h2>';
      return;
    }

    try {
      const data = await apiFetch(`/api/orders/${encodeURIComponent(orderId)}`);
      const order = data?.order;
      const currency = order?.currency || 'USD';
      const items = order?.items || [];
      const user = getStoredUser();

      if (order?.status !== 'paid') {
        root.innerHTML = `
          <h2>Invoice</h2>
          <p style="color:gray;">This order is not paid yet.</p>
          <button id="back-to-payment" class="normal" style="margin-top:12px;">Back to payment</button>
        `;
        const btn = document.getElementById('back-to-payment');
        if (btn) {
          btn.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.href = `payment.html?order_id=${encodeURIComponent(order.id)}`;
          });
        }
        return;
      }

      const paidAt = order?.paid_at ? new Date(order.paid_at).toLocaleString() : '';

      root.innerHTML = `
        <div class="invoice">
          <div class="invoice-head">
            <div>
              <h2>Invoice</h2>
              <p class="invoice-muted">KOK-eMall</p>
            </div>
            <div class="invoice-meta">
              <div><strong>Invoice #</strong> ${order.id}</div>
              <div><strong>Date</strong> ${paidAt}</div>
              <div><strong>Status</strong> Paid</div>
            </div>
          </div>

          <div class="invoice-billto">
            <div>
              <strong>Bill to</strong>
              <div>${user?.name ? user.name : 'Customer'}</div>
              <div class="invoice-muted">${user?.email ? user.email : ''}</div>
            </div>
            <div style="text-align:right;">
              <strong>Payment</strong>
              <div>Bakong KHQR</div>
            </div>
          </div>

          <table class="invoice-table" width="100%">
            <thead>
              <tr>
                <td>Item</td>
                <td style="text-align:right;">Qty</td>
                <td style="text-align:right;">Unit</td>
                <td style="text-align:right;">Total</td>
              </tr>
            </thead>
            <tbody>
              ${items
                .map((i) => {
                  const unit = formatMoney(i.product?.unit_price_cents || 0, currency);
                  const line = formatMoney(i.line_total_cents || 0, currency);
                  return `
                    <tr>
                      <td>${i.product?.name || 'Item'}</td>
                      <td style="text-align:right;">${i.quantity}</td>
                      <td style="text-align:right;">${unit}</td>
                      <td style="text-align:right;">${line}</td>
                    </tr>
                  `;
                })
                .join('')}
            </tbody>
          </table>

          <div class="invoice-totals">
            <div class="invoice-muted">Subtotal</div>
            <div>${formatMoney(order.subtotal_cents || 0, currency)}</div>
            <div class="invoice-muted">Shipping</div>
            <div>${formatMoney(order.shipping_cents || 0, currency)}</div>
            <div><strong>Total</strong></div>
            <div><strong>${formatMoney(order.total_cents || 0, currency)}</strong></div>
          </div>

          <div class="invoice-actions">
            <button id="print-invoice" class="normal">Print</button>
            <button id="invoice-home" class="normal" style="background:rgb(24, 145, 145);color:white;">Home</button>
          </div>
        </div>
      `;

      const printBtn = document.getElementById('print-invoice');
      if (printBtn) {
        printBtn.addEventListener('click', (e) => {
          e.preventDefault();
          window.print();
        });
      }

      const homeBtn = document.getElementById('invoice-home');
      if (homeBtn) {
        homeBtn.addEventListener('click', (e) => {
          e.preventDefault();
          window.location.href = 'index.html';
        });
      }
    } catch (err) {
      if (err?.status === 401 || err?.status === 422) {
        const next = encodeURIComponent(`invoice.html?order_id=${encodeURIComponent(orderId)}`);
        window.location.href = `login.html?next=${next}`;
        return;
      }
      root.innerHTML = `<h2>${err?.message || 'Failed to load invoice'}</h2>`;
    }
  }

  function bindCartLinksAuthGate() {
    const cartLinks = [document.querySelector('#lg-bag a'), document.querySelector('#mobile a')].filter(Boolean);
    for (const a of cartLinks) {
      if (a.dataset.emallCartGate) continue;
      a.dataset.emallCartGate = '1';
      a.addEventListener('click', (e) => {
        if (getAccessToken()) return;
        e.preventDefault();
        const next = encodeURIComponent('cart.html');
        window.location.href = `login.html?next=${next}`;
      });
    }
  }

  // Existing mobile navbar toggle
  const bar = document.getElementById('bar');
  const close = document.getElementById('close');
  const nav = document.getElementById('navbar');

  if (bar && nav) {
    bar.addEventListener('click', () => {
      nav.classList.add('active');
    });
  }
  if (close && nav) {
    close.addEventListener('click', () => {
      nav.classList.remove('active');
    });
  }

  document.addEventListener('DOMContentLoaded', async () => {
    showFlashIfAny();
    ensureGuestId();
    await updateNavbarAuth();
    await refreshCartCount();
    bindCartLinksAuthGate();
    bindAddToCartButtons();
    await bindAuthForms();
    preserveNextParamInAuthLinks();
    await renderCartPage();
    await renderPaymentPage();
    await renderInvoicePage();
  });

  window.emall = {
    apiFetch,
    getAccessToken,
    setAccessToken,
    clearAccessToken,
    ensureGuestId,
  };
})();
