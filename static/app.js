// VegeLink SPA — vanilla JS, no build step.
const API = "";
const $ = (s, r = document) => r.querySelector(s);
const el = (h) => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstChild; };

const state = { tab: "dashboard", buyers: [], buyer: null, token: null, meta: null, ussd: { text: "", phone: "0249000001", lines: [] } };

// Restore a session across reloads.
try {
  const saved = JSON.parse(localStorage.getItem("vegelink.session") || "null");
  if (saved && saved.token) { state.buyer = saved.acct; state.token = saved.token; }
} catch (e) {}

function authHeaders(extra) {
  const h = Object.assign({}, extra || {});
  if (state.token) h["Authorization"] = "Bearer " + state.token;
  return h;
}
async function api(path, opts) {
  opts = opts || {};
  opts.headers = authHeaders(opts.headers);
  let r;
  try {
    r = await fetch(API + path, opts);
  } catch (e) {                       // offline / network drop
    toast("You appear to be offline. Check your connection and try again.");
    return { error: "offline" };
  }
  if (r.status === 401 && state.token) { // session expired/invalid
    logout(true); toast("Session ended — please log in again");
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}
function modal(html) {
  $("#modalBody").innerHTML = `<button class="close-x" aria-label="Close" id="modalClose">×</button>` + html;
  $("#modalClose").onclick = closeModal;
  $("#modal").classList.remove("hidden");
}
function closeModal() { $("#modal").classList.add("hidden"); }
// Dismiss the modal on Escape or clicking the backdrop.
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
function stars(n) { const f = Math.round(n); return "★".repeat(f) + "☆".repeat(5 - f); }
const ghs = (n) => "GHS " + Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
const cap = (s) => (s || "").charAt(0).toUpperCase() + (s || "").slice(1);
const PAY_ICONS = { momo: "📱", bank: "🏦", card: "💳", cod: "💵" };
const myLocation = () => (state.buyer ? state.buyer.location : "Accra");
const KIND_META = {
  farmer:    { icon: "👨‍🌾", label: "Farmer",    group: "Farmers" },
  buyer:     { icon: "🛒",   label: "Buyer",     group: "Buyers" },
  retailer:  { icon: "🏪",   label: "Retailer",  group: "Retailers" },
  transport: { icon: "🚚",   label: "Transport", group: "Transport owners" },
};
const acctKey = (a) => `${a.kind}:${a.id}`;
const canPurchase = (u) => u && (u.kind === "buyer" || u.kind === "retailer");

// ---- role-based navigation: each role sees only the tabs it needs ----
const TAB_DEFS = {
  dashboard: "📊 Dashboard", market: "🛒 Marketplace", sell: "🧺 Sell", nearby: "📍 Nearby",
  orders: "📦 Orders", messages: "💬 Messages", phone: "📱 Farmer USSD",
  transport: "🚚 Transport", notifications: "🔔 Activity", register: "➕ Register",
};
const TABS_FOR = {
  guest:     ["dashboard", "market", "transport", "phone", "register"],
  farmer:    ["dashboard", "sell", "orders", "messages", "nearby", "phone", "notifications"],
  buyer:     ["dashboard", "market", "orders", "messages", "nearby", "notifications"],
  retailer:  ["dashboard", "market", "orders", "messages", "nearby", "notifications"],
  transport: ["dashboard", "orders", "messages", "nearby", "transport", "notifications"],
};
const homeTabFor = (kind) => ({ farmer: "sell", buyer: "market", retailer: "market", transport: "orders" }[kind] || "dashboard");
function buildTabs() {
  const kind = state.buyer ? state.buyer.kind : "guest";
  const allowed = TABS_FOR[kind] || TABS_FOR.guest;
  if (!allowed.includes(state.tab)) state.tab = allowed[0];
  $("#tabs").innerHTML = allowed.map(t =>
    `<button data-tab="${t}" class="${t === state.tab ? "active" : ""}">${TAB_DEFS[t]}</button>`).join("");
}

// ---------------------------------------------------------------- auth (login / register / logout)
function renderAuth() {
  const a = $("#authArea");
  if (state.buyer) {
    const km = KIND_META[state.buyer.kind] || KIND_META.buyer;
    a.innerHTML = `<div class="acct">${km.icon} <b>${escapeHtml(state.buyer.name)}</b><br>
        <span class="muted">${km.label} · ${state.buyer.location}</span></div>
      <button class="btn ghost sm" id="logoutBtn">Log out</button>`;
    $("#logoutBtn").onclick = logout;
  } else {
    a.innerHTML = `<button class="btn ghost sm" id="loginBtn">Log in</button>
      <button class="btn sm" id="regBtn">Register</button>`;
    $("#loginBtn").onclick = openLogin;
    $("#regBtn").onclick = () => gotoTab("register");
  }
}
function openLogin() {
  modal(`<h2>Log in</h2><p class="muted">Enter your phone number and 4-digit PIN.</p>
    <div class="form" style="margin-top:14px">
      <label>Phone number</label><input id="lPhone" placeholder="024…" inputmode="tel">
      <label>PIN</label><input id="lPin" type="password" placeholder="••••" inputmode="numeric" maxlength="8">
      <button class="btn" id="loginGo">Log in</button>
      <p class="err" id="lErr"></p>
      <p class="muted" style="font-size:13px">💡 Demo accounts use PIN <b>1234</b> (e.g. 0241000001 farmer, 0551000001 buyer, 0271000002 transport).</p>
      <p class="muted" style="font-size:13px">New here? <a href="#" id="goReg">Create an account →</a></p>
    </div>`);
  const go = async () => {
    const phone = val("lPhone").trim(), pin = val("lPin").trim();
    if (!phone || !pin) return $("#lErr").textContent = "Phone and PIN are required.";
    const r = await post("/api/login", { phone, pin });
    if (r.error) return $("#lErr").textContent = r.error;
    if (r.accounts.length === 1) return login(r.accounts[0]);
    // one phone, several roles (e.g. is both a farmer and a buyer) — let them pick
    pickAccount(r.accounts);
  };
  $("#loginGo").onclick = go;
  $("#lPin").onkeydown = (e) => { if (e.key === "Enter") go(); };
  $("#goReg").onclick = (e) => { e.preventDefault(); closeModal(); gotoTab("register"); };
}
function pickAccount(accounts) {
  const opts = accounts.map((a, i) =>
    `<button class="btn ghost" data-i="${i}" style="width:100%;text-align:left;margin-top:8px">
       ${(KIND_META[a.kind] || KIND_META.buyer).icon} <b>${a.name}</b> · ${(KIND_META[a.kind] || KIND_META.buyer).label} · ${a.location}
     </button>`).join("");
  modal(`<h2>Choose account</h2><p class="muted">This phone is registered for several roles.</p>${opts}`);
  $("#modalBody").querySelectorAll("[data-i]").forEach(b =>
    b.onclick = () => login(accounts[+b.dataset.i]));
}
function login(acct) {
  if (!acct) return;
  state.buyer = acct;
  state.token = acct.token || null;
  try { localStorage.setItem("vegelink.session", JSON.stringify({ token: state.token, acct })); } catch (e) {}
  if (acct.kind === "farmer" && acct.phone) state.ussd.phone = acct.phone; // greet farmer in USSD
  closeModal(); buildTabs(); renderAuth();
  toast(`Logged in as ${acct.name} (${KIND_META[acct.kind].label})`); gotoTab(homeTabFor(acct.kind));
}
function logout(silent) {
  if (state.token) post("/api/logout").catch(() => {});
  state.buyer = null; state.token = null;
  try { localStorage.removeItem("vegelink.session"); } catch (e) {}
  buildTabs(); renderAuth();
  if (!silent) toast("Logged out");
  gotoTab("dashboard");
}

// ---------------------------------------------------------------- boot
async function boot() {
  state.meta = await api("/api/meta");
  buildTabs();                 // tabs reflect the (possibly restored) session
  renderAuth();

  $("#tabs").addEventListener("click", e => {
    const b = e.target.closest("button[data-tab]"); if (!b) return;
    state.tab = b.dataset.tab;
    [...$("#tabs").children].forEach(x => x.classList.toggle("active", x === b));
    render();
  });
  render();
}

function render() {
  const v = $("#view");
  ({ dashboard: renderDashboard, market: renderMarket, sell: renderSell, nearby: renderNearby,
     orders: renderOrders, messages: renderMessages, phone: renderPhone, transport: renderTransport,
     notifications: renderNotifs, register: renderRegister }[state.tab] || renderDashboard)(v);
}

// ---------------------------------------------------------------- dashboard
async function renderDashboard(v) {
  v.innerHTML = `<p class="muted">Loading…</p>`;
  const d = await api("/api/dashboard");
  // Logged-out visitors get a clear "who are you?" entry, not investor KPIs.
  const landing = state.buyer ? "" : `
    <div class="landing">
      <h1>Sell &amp; buy fresh produce — before it spoils.</h1>
      <p class="muted">VegeLink links Bono-corridor farmers to buyers and transport. Choose how you'll use it:</p>
      <div class="role-cards">
        <button class="role-card" data-role="farmer"><div class="ic">👨‍🌾</div><b>I'm a Farmer</b><span>Sell my harvest</span></button>
        <button class="role-card" data-role="buyer"><div class="ic">🛒</div><b>I'm a Buyer</b><span>Buy produce</span></button>
        <button class="role-card" data-role="transport"><div class="ic">🚚</div><b>Transport</b><span>Carry goods</span></button>
      </div>
      <div class="row" style="justify-content:center;margin-top:12px">
        <button class="btn" id="landLogin">Log in</button>
        <button class="btn ghost" id="landBrowse">Browse the market →</button>
      </div>
    </div>`;
  v.innerHTML = landing + `
    <div class="hint">💡 What VegeLink achieves — perishable lots reaching buyers <b>before</b> they spoil, and money put back in a farmer's pocket.</div>
    <div class="grid cols-4">
      <div class="stat tomato"><div class="v">${d.urgent_rescued}</div><div class="l">Near-spoiling lots rescued in time*</div></div>
      <div class="stat hl"><div class="v">${d.avg_time_to_sale_hours}h</div><div class="l">Average time from listing to sale</div></div>
      <div class="stat"><div class="v">${ghs(d.loss_avoided)}</div><div class="l">Estimated produce value saved from waste*</div></div>
      <div class="stat"><div class="v">${ghs(d.gmv)}</div><div class="l">Total sales on VegeLink</div></div>
    </div>
    <div class="grid stat-row" style="margin-top:16px">
      <div class="stat"><div class="v">${d.orders}</div><div class="l">Orders (${d.completed} delivered)</div></div>
      <div class="stat"><div class="v">${ghs(d.escrow_held)}</div><div class="l">Money held safely for farmers**</div></div>
      <div class="stat"><div class="v">${d.farmers}</div><div class="l">Farmers</div></div>
      <div class="stat"><div class="v">${d.buyers + d.retailers}</div><div class="l">Buyers &amp; retailers</div></div>
      <div class="stat"><div class="v">${d.active_listings}</div><div class="l">Produce on sale now</div></div>
    </div>
    <p class="muted" style="font-size:12px;margin-top:14px">*Ghana loses 20–50% of fruits &amp; vegetables after harvest. Rather than a flat rate, we credit each <b>delivered</b> lot by how close to spoiling it was when sold (from its crop shelf-life), scaled by the 35% midpoint — so fresh lots count little and near-spoiling rescues count most. **Buyer's money is held by VegeLink and paid to the farmer only after delivery is confirmed (escrow).</p>
    <div class="card" style="margin-top:22px">
      <div class="section-title">How VegeLink works</div>
      <div class="row">
        <div style="flex:1;min-width:180px"><b>1. Farmer lists 📱</b><br><span class="muted">Over USSD on any phone — no internet needed.</span></div>
        <div style="flex:1;min-width:180px"><b>2. Buyer orders 🛒</b><br><span class="muted">Sees what to buy first (spoils soonest, nearest). Pays by Mobile Money.</span></div>
        <div style="flex:1;min-width:180px"><b>3. Transport matched 🚚</b><br><span class="muted">Nearest suitable vehicle, price worked out automatically.</span></div>
        <div style="flex:1;min-width:180px"><b>4. Delivered → paid ✅</b><br><span class="muted">Farmer gets paid once the buyer confirms delivery.</span></div>
      </div>
    </div>`;
  if (!state.buyer) {
    v.querySelectorAll("[data-role]").forEach(b => b.onclick = () => { regRole = b.dataset.role; gotoTab("register"); });
    $("#landLogin").onclick = openLogin;
    $("#landBrowse").onclick = () => gotoTab("market");
  }
}

// ---------------------------------------------------------------- marketplace
const filters = { crop: "", maxprice: "", minqty: "", location: "", sort: "smart" };
async function renderMarket(v) {
  const cropOpts = `<option value="">All crops</option>` + state.meta.crops.map(c => `<option ${filters.crop === c ? "selected" : ""}>${c}</option>`).join("");
  const locOpts = `<option value="">All locations</option>` + state.meta.locations.map(l => `<option ${filters.location === l ? "selected" : ""}>${l}</option>`).join("");
  v.innerHTML = `
    <div class="hint">🧠 <b>Best picks</b> shows produce that's freshest-to-sell-now and closest to <b>${escapeHtml(state.buyer ? state.buyer.location : "Accra")}</b>${state.buyer ? "" : " (log in to use your own town &amp; to order)"} — so you buy what to grab first and cut waste.</div>
    <div class="filters">
      <select id="fCrop">${cropOpts}</select>
      <select id="fLoc">${locOpts}</select>
      <input id="fPrice" type="number" placeholder="Max price/crate" value="${filters.maxprice}" style="width:150px">
      <input id="fQty" type="number" placeholder="Min crates" value="${filters.minqty}" style="width:120px">
      <div class="seg" id="fSort">
        <button data-s="smart" class="${filters.sort==='smart'?'active':''}">🧠 Best picks</button>
        <button data-s="urgency" class="${filters.sort==='urgency'?'active':''}">⏳ Spoils soonest</button>
        <button data-s="price" class="${filters.sort==='price'?'active':''}">💰 Cheapest</button>
      </div>
    </div>
    <div id="listings" class="grid cards"></div>`;
  $("#fCrop").onchange = e => { filters.crop = e.target.value; loadListings(); };
  $("#fLoc").onchange = e => { filters.location = e.target.value; loadListings(); };
  $("#fPrice").oninput = e => { filters.maxprice = e.target.value; loadListings(); };
  $("#fQty").oninput = e => { filters.minqty = e.target.value; loadListings(); };
  $("#fSort").onclick = e => { const b = e.target.closest("button"); if (!b) return; filters.sort = b.dataset.s; loadListings(); };
  loadListings();
}
async function loadListings() {
  const q = new URLSearchParams({ sort: filters.sort, buyer_location: myLocation() });
  if (filters.crop) q.set("crop", filters.crop);
  if (filters.location) q.set("location", filters.location);
  if (filters.maxprice) q.set("maxprice", filters.maxprice);
  if (filters.minqty) q.set("minqty", filters.minqty);
  const items = await api("/api/listings?" + q);
  const box = $("#listings");
  if (!items.length) { box.innerHTML = `<div class="empty">No produce matches your filters.</div>`; return; }
  box.innerHTML = "";
  items.forEach((x, i) => {
    const top = filters.sort !== "price" && i === 0;
    box.appendChild(el(`
      <div class="card listing">
        ${top ? `<span class="badge score">★ Best match</span>` : ``}
        <div class="img">${imgTag(x.image)}</div>
        <div class="crop">${escapeHtml(x.crop)} <span class="badge ${x.freshness_level}">${escapeHtml(x.freshness)}</span></div>
        <div class="price">${ghs(x.price)}<span class="muted" style="font-size:13px;font-weight:500"> / ${escapeHtml(x.unit)}</span></div>
        <div class="meta">
          <span>📦 ${x.quantity} crates available</span>
          <span>📍 ${escapeHtml(x.location)} · ${x.distance_km} km away</span>
          <span>👨‍🌾 ${escapeHtml(x.farmer.name)} ${x.farmer.verified ? '<span class="badge verify">✓ Verified</span>' : '<span class="badge soon">Unverified</span>'}</span>
          <span class="stars">${stars(x.farmer.rating)} <span class="muted">${x.farmer.rating} (${x.farmer.rating_count})</span>
            <a href="#" class="link" data-reviews="farmer:${x.farmer.id}:${escapeHtml(x.farmer.name)}">reviews</a></span>
        </div>
        <div class="row" style="gap:8px">
          <button class="btn" style="flex:1" data-buy="${x.id}">Order now</button>
          <button class="btn ghost" data-msg="farmer:${x.farmer.id}:${escapeHtml(x.farmer.name)}:${x.id}" title="Message farmer">💬</button>
        </div>
      </div>`));
  });
  box.querySelectorAll("[data-buy]").forEach(b => b.onclick = () => openOrder(b.dataset.buy, items.find(i => i.id == b.dataset.buy)));
  box.querySelectorAll("[data-reviews]").forEach(b => b.onclick = (e) => { e.preventDefault(); const [k,i,n]=b.dataset.reviews.split(":"); showReviews(k,i,n); });
  box.querySelectorAll("[data-msg]").forEach(b => b.onclick = () => { const [k,i,n,lid]=b.dataset.msg.split(":"); openComposeTo(k, +i, n, { listing_id: +lid }); });
}

// Render an uploaded photo (data: URL) or fall back to the emoji placeholder.
// Only emits an <img> for a strictly well-formed base64 image data URL — this
// prevents any attribute-breakout / onerror injection via a crafted image value.
const IMG_DATA_RE = /^data:image\/(png|jpeg|jpg|webp);base64,[A-Za-z0-9+/]+={0,2}$/;
function imgTag(image) {
  return IMG_DATA_RE.test(image || "")
    ? `<img src="${image}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:inherit">`
    : escapeHtml(image && image.startsWith("data:") ? "🧺" : (image || "🧺"));
}

function openOrder(id, x) {
  if (!state.buyer) { toast("Please log in to place an order"); return openLogin(); }
  if (!canPurchase(state.buyer)) { return toast(`Logged in as ${KIND_META[state.buyer.kind].label} — only Buyers & Retailers can order. Log out to switch.`); }
  const methods = state.meta.payment_methods || { momo: "Mobile Money", bank: "Bank Transfer", card: "Card", cod: "Cash on Delivery" };
  const payOpts = Object.entries(methods)
    .map(([k, l]) => `<option value="${k}">${PAY_ICONS[k] || "💳"} ${l}</option>`).join("");
  modal(`
    <h2>${x.image} Order ${x.crop}</h2>
    <p class="muted">From ${escapeHtml(x.farmer.name)} · ${escapeHtml(x.location)}</p>
    <div class="form" style="margin-top:16px">
      <label>Quantity (max ${x.quantity} crates)</label>
      <input id="oQty" type="number" min="1" max="${x.quantity}" value="${Math.min(20, x.quantity)}">
      <label>Payment method</label>
      <select id="oPay">${payOpts}</select>
      <div class="kv"><span class="k">Price / crate</span><b>${ghs(x.price)}</b></div>
      <div class="kv"><span class="k">Produce subtotal</span><b id="oSub">${ghs(x.price * Math.min(20, x.quantity))}</b></div>
      <div class="kv"><span class="k">Transport (auto-matched)</span><b class="muted">calculated on order</b></div>
      <button class="btn tomato" id="oPlace">🔒 Place order</button>
      <p class="muted" style="font-size:12px" id="oNote"></p>
    </div>`);
  const note = () => {
    const m = $("#oPay").value;
    $("#oNote").innerHTML = m === "cod"
      ? "💵 No money is held now — you pay <b>cash to the driver on delivery</b>."
      : `${PAY_ICONS[m]} Your payment is <b>held in escrow</b> and released to the farmer only when you confirm delivery.`;
    $("#oPlace").textContent = m === "cod" ? "📦 Place order (pay cash on delivery)" : `🔒 Place order & pay (${methods[m]})`;
  };
  note();
  $("#oPay").onchange = note;
  $("#oQty").oninput = e => $("#oSub").textContent = ghs(x.price * (+e.target.value || 0));
  $("#oPlace").onclick = async () => {
    const qty = +$("#oQty").value;
    if (qty < 1 || qty > x.quantity) return toast("Invalid quantity");
    const o = await post("/api/orders", { listing_id: x.id, buyer_id: state.buyer.id, quantity: qty, payment_method: $("#oPay").value });
    if (o.error) return toast(o.error || "Something went wrong");
    closeModal();
    showOrderResult(o);
  };
}
function showOrderResult(o) {
  const cod = o.payment_method === "cod";
  modal(`
    <h2>✅ Order placed!</h2>
    <p class="muted">Order #${o.id} — ${cod ? "cash on delivery" : "payment held in escrow"}.</p>
    <div style="margin-top:14px">
      <div class="kv"><span class="k">Produce (${o.quantity} crates ${o.crop})</span><b>${ghs(o.produce_total)}</b></div>
      <div class="kv"><span class="k">🚚 ${o.transport ? escapeHtml(o.transport.name) + ' — ' + escapeHtml(o.transport.vehicle) : 'No transport'}</span><b>${ghs(o.transport_cost)}</b></div>
      <div class="kv"><span class="k">Distance / ETA</span><b>${o.distance_km} km · ~${o.eta_minutes} min</b></div>
      <div class="kv"><span class="k">Payment method</span><b>${PAY_ICONS[o.payment_method] || ""} ${o.payment_label}</b></div>
      <div class="kv"><span class="k">${cod ? "Total payable on delivery (cash)" : "Total held in " + o.payment_label + " escrow"}</span><b style="color:var(--tomato-d)">${ghs(o.total)}</b></div>
    </div>
    <button class="btn" style="margin-top:16px;width:100%" id="trackOrderBtn">Track this order →</button>`);
  $("#trackOrderBtn").onclick = () => { closeModal(); gotoTab("orders"); };
}
window.gotoTab = (t) => { $(`#tabs button[data-tab="${t}"]`).click(); };

// ---------------------------------------------------------------- orders
async function renderOrders(v) {
  if (!state.buyer) {
    v.innerHTML = `<div class="empty">Please <a href="#" id="oLogin">log in</a> to see your orders.</div>`;
    $("#oLogin").onclick = (e) => { e.preventDefault(); openLogin(); };
    return;
  }
  if (state.buyer.kind === "farmer") return renderFarmerOrders(v, state.buyer);
  if (state.buyer.kind === "transport") return renderTransportOrders(v, state.buyer);
  v.innerHTML = `<p class="muted">Loading…</p>`;
  const orders = await api("/api/orders");
  if (!orders.length) { v.innerHTML = `<div class="empty">No orders yet for ${escapeHtml(state.buyer.name)}.<br>Go to the Marketplace to place one.</div>`; return; }
  v.innerHTML = `<div class="row" style="justify-content:space-between;align-items:center">
      <div class="section-title" style="margin:0">Orders for ${escapeHtml(state.buyer.name)}</div>
      <button class="btn ghost sm" id="csvBtn">⬇ Export CSV</button>
    </div><div id="orderList"></div>`;
  $("#csvBtn").onclick = exportOrdersCsv;
  const list = $("#orderList");
  const steps = ["placed", "matched", "picked_up", "delivered", "completed"];
  const labels = { placed: "Placed", matched: "Matched", picked_up: "Picked up", delivered: "Delivered", completed: "Paid" };
  orders.forEach(o => {
    const ci = steps.indexOf(o.status);
    const tl = steps.map((s, i) => `<div class="tl-step ${i <= ci ? 'done' : ''}">${labels[s]}</div>`).join("");
    const awaitingTransport = o.transport && o.transport_status === "proposed";
    const actions = [];
    if (o.status === "matched" && !awaitingTransport) actions.push(`<button class="btn sm" data-act="picked_up" data-id="${o.id}">Mark picked up</button>`);
    if (o.status === "picked_up") actions.push(`<button class="btn sm" data-act="delivered" data-id="${o.id}">Mark delivered</button>`);
    if (o.status === "delivered") actions.push(`<button class="btn tomato sm" data-confirm="${o.id}">${o.payment_method === 'cod' ? '✅ Confirm delivery & collect cash' : '✅ Confirm delivery & release payment'}</button>`);
    if (o.status === "completed" && !o.farmer_rated) actions.push(`<button class="btn ghost sm" data-rate="${o.id}">⭐ Rate farmer</button>`);
    if (o.status === "completed" && o.transport && !o.transport_rated) actions.push(`<button class="btn ghost sm" data-ratet="${o.id}">⭐ Rate transport</button>`);
    actions.push(`<button class="btn ghost sm" data-msgf="${o.farmer.id}:${escapeHtml(o.farmer.name)}:${o.id}">💬 Message farmer</button>`);
    const payLabels = { held: "Escrow held", released: "Released", cod_pending: "Cash on delivery", paid: "Paid (cash)", pending: "Pending" };
    const pickup = o.pickup_at ? new Date(o.pickup_at * 1000).toLocaleString() : null;
    list.appendChild(el(`
      <div class="order">
        <div class="order-head">
          <div><b>${imgEmoji(o.image)} ${o.quantity} crates ${escapeHtml(o.crop)}</b> <span class="muted">· #${o.id} · from ${escapeHtml(o.farmer.name)} (${escapeHtml(o.farmer.location)})</span></div>
          <div>
            <span class="pill" style="background:#eef2ef;color:#555">${PAY_ICONS[o.payment_method] || '💳'} ${o.payment_label}</span>
            <span class="pill ${o.payment_status}">${payLabels[o.payment_status] || o.payment_status}</span>
            <span class="pill ${o.status}">${o.status.replace('_', ' ')}</span>
          </div>
        </div>
        <div class="timeline">${tl}</div>
        <div class="kv"><span class="k">${o.transport ? '🚚 ' + escapeHtml(o.transport.name) + ' · ' + o.distance_km + 'km · ~' + o.eta_minutes + 'min' + (awaitingTransport ? ' · ⏳ awaiting driver' : '') : 'No transport'}</span><b>Total ${ghs(o.total)}</b></div>
        ${pickup ? `<div class="kv"><span class="k">🕒 Pickup scheduled</span><b>${pickup}</b></div>` : ""}
        ${o.transport && o.status !== 'completed' ? deliveryMapHtml(o) : ""}
        <div class="row" style="margin-top:10px">${actions.join("")}</div>
      </div>`));
  });
  list.querySelectorAll("[data-ratet]").forEach(b => b.onclick = () => rateModal(b.dataset.ratet, v, "transport"));
  list.querySelectorAll("[data-msgf]").forEach(b => b.onclick = () => { const [id,n,oid]=b.dataset.msgf.split(":"); openComposeTo("farmer", +id, n, { order_id: +oid }); });
  list.querySelectorAll("[data-act]").forEach(b => b.onclick = async () => {
    await post(`/api/orders/${b.dataset.id}/status`, { status: b.dataset.act });
    toast("Status updated: " + b.dataset.act.replace("_", " ")); renderOrders(v);
  });
  list.querySelectorAll("[data-confirm]").forEach(b => b.onclick = async () => {
    const o = await post(`/api/orders/${b.dataset.confirm}/confirm-delivery`);
    toast(o.payment_method === "cod"
      ? `Delivery confirmed — ${ghs(o.produce_total)} collected in cash 🎉`
      : `Delivery confirmed — ${ghs(o.produce_total)} released to farmer 🎉`);
    renderOrders(v);
  });
  list.querySelectorAll("[data-rate]").forEach(b => b.onclick = () => rateModal(b.dataset.rate, v));
}

// Farmer's view: incoming orders / sales for their produce (read-only).
async function renderFarmerOrders(v, u) {
  v.innerHTML = `<p class="muted">Loading…</p>`;
  const orders = await api("/api/orders");
  if (!orders.length) {
    v.innerHTML = `<div class="empty">No orders yet for ${escapeHtml(u.name)}.<br>List produce via the <b>📱 Farmer USSD</b> tab (dial *789#) and buyers will order.</div>`;
    return;
  }
  const payLabels = { held: "Escrow held", released: "Released", cod_pending: "Cash on delivery", paid: "Paid (cash)", pending: "Pending" };
  v.innerHTML = `<div class="hint">👨‍🌾 Incoming orders &amp; sales for <b>${escapeHtml(u.name)}</b>. Buyers confirm delivery to release your payment.</div><div></div>`;
  const list = v.lastChild;
  orders.forEach(o => {
    list.appendChild(el(`
    <div class="order">
      <div class="order-head">
        <div><b>${imgEmoji(o.image)} ${o.quantity} crates ${escapeHtml(o.crop)}</b> <span class="muted">· #${o.id} · buyer: ${o.buyer ? escapeHtml(o.buyer.name) + ' (' + escapeHtml(o.buyer.location) + ')' : '—'}</span></div>
        <div>
          <span class="pill" style="background:#eef2ef;color:#555">${PAY_ICONS[o.payment_method] || '💳'} ${o.payment_label}</span>
          <span class="pill ${o.payment_status}">${payLabels[o.payment_status] || o.payment_status}</span>
          <span class="pill ${o.status}">${o.status.replace('_', ' ')}</span>
        </div>
      </div>
      <div class="kv"><span class="k">${o.transport ? '🚚 ' + escapeHtml(o.transport.name) + ' · ' + o.distance_km + 'km' : 'No transport'}</span><b>You earn ${ghs(o.produce_total)}</b></div>
      ${o.buyer ? `<div class="row" style="margin-top:8px"><button class="btn ghost sm" data-msgb="${o.buyer.id}:${escapeHtml(o.buyer.name)}:${o.id}">💬 Message buyer</button></div>` : ""}
    </div>`));
  });
  list.querySelectorAll("[data-msgb]").forEach(b => b.onclick = () => { const [id,n,oid]=b.dataset.msgb.split(":"); openComposeTo("buyer", +id, n, { order_id: +oid }); });
}

// Transport owner's view: assigned delivery jobs (read-only).
async function renderTransportOrders(v, u) {
  v.innerHTML = `<p class="muted">Loading…</p>`;
  const orders = await api("/api/orders");
  if (!orders.length) {
    v.innerHTML = `<div class="empty">No delivery jobs assigned to ${escapeHtml(u.name)} yet.<br>Jobs are auto-matched when buyers order produce near you.</div>`;
    return;
  }
  v.innerHTML = `<div class="row" style="justify-content:space-between;align-items:center">
      <div class="hint" style="margin:0;flex:1">🚚 Delivery jobs for <b>${escapeHtml(u.name)}</b>, auto-matched by distance &amp; capacity. Accept a job to schedule pickup, or decline to release it to another provider.</div>
      <button class="btn ghost sm" id="csvBtn" style="margin-left:10px">⬇ Export CSV</button>
    </div><div></div>`;
  $("#csvBtn").onclick = exportOrdersCsv;
  const list = v.lastChild;
  const tsLabel = { proposed: "Awaiting your response", accepted: "Accepted", rejected: "Declined", none: "" };
  orders.forEach(o => {
    const pickup = o.pickup_at ? new Date(o.pickup_at * 1000).toLocaleString() : null;
    const actions = [];
    if (o.transport_status === "proposed")
      actions.push(`<button class="btn sm" data-accept="${o.id}">✅ Accept &amp; schedule</button>
                    <button class="btn ghost sm" data-reject="${o.id}">✕ Decline</button>`);
    list.appendChild(el(`
      <div class="order">
        <div class="order-head">
          <div><b>${imgEmoji(o.image)} ${o.quantity} crates ${escapeHtml(o.crop)}</b> <span class="muted">· job #${o.id}</span></div>
          <div>
            ${o.transport_status && o.transport_status !== 'none' ? `<span class="pill ${o.transport_status==='accepted'?'released':o.transport_status==='proposed'?'held':'spoiled'}">${tsLabel[o.transport_status]}</span>` : ""}
            <span class="pill ${o.status}">${o.status.replace('_', ' ')}</span>
          </div>
        </div>
        <div class="kv"><span class="k">📍 ${o.farmer ? escapeHtml(o.farmer.location) : '?'} → ${o.buyer ? escapeHtml(o.buyer.location) : '?'} · ${o.distance_km}km · ~${o.eta_minutes}min</span><b>Fee ${ghs(o.transport_cost)}</b></div>
        ${pickup ? `<div class="kv"><span class="k">🕒 Pickup scheduled</span><b>${pickup}</b></div>` : ""}
        ${o.status !== 'completed' ? deliveryMapHtml(o) : ""}
        <div class="row" style="margin-top:10px">${actions.join("") || '<span class="muted">No action needed.</span>'}</div>
      </div>`));
  });
  list.querySelectorAll("[data-accept]").forEach(b => b.onclick = () => schedulePickup(b.dataset.accept, v));
  list.querySelectorAll("[data-reject]").forEach(b => b.onclick = async () => {
    await post(`/api/orders/${b.dataset.reject}/transport-response`, { action: "reject" });
    toast("Job declined — re-matching another provider"); renderTransportOrders(v, u);
  });
}
function imgEmoji(image) { return (image || "").startsWith("data:") ? "🧺" : (image || "🧺"); }

function schedulePickup(id, v) {
  const now = new Date(Date.now() + 2 * 3600 * 1000);
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  modal(`<h2>✅ Accept job</h2><p class="muted">Set a pickup time for this delivery.</p>
    <div class="form" style="max-width:100%;margin-top:10px">
      <label>Pickup date &amp; time</label><input id="pTime" type="datetime-local" value="${local}">
      <button class="btn" id="pGo">Confirm &amp; accept</button>
    </div>`);
  $("#pGo").onclick = async () => {
    const ts = Math.floor(new Date(val("pTime")).getTime() / 1000);
    await post(`/api/orders/${id}/transport-response`, { action: "accept", pickup_at: ts });
    closeModal(); toast("Job accepted — pickup scheduled"); renderTransportOrders($("#view"), state.buyer);
  };
}

function rateModal(id, v, target = "farmer") {
  modal(`<h2>⭐ Rate this ${target}</h2><p class="muted">How was the produce & transaction?</p>
    <div style="font-size:34px;text-align:center;margin:14px 0" id="rStars"></div>
    <div class="form" style="max-width:100%">
      <label>Review (optional)</label>
      <textarea id="rText" rows="3" placeholder="Share a few words for other users…"></textarea>
      <button class="btn" style="width:100%" id="rSubmit">Submit review</button>
    </div>`);
  let chosen = 5;
  const draw = () => $("#rStars").innerHTML = [1,2,3,4,5].map(n => `<span data-n="${n}" style="cursor:pointer;color:${n<=chosen?'#f0a500':'#ddd'}">★</span>`).join("");
  draw();
  $("#rStars").onclick = e => { const s = e.target.closest("[data-n]"); if (s) { chosen = +s.dataset.n; draw(); } };
  $("#rSubmit").onclick = async () => {
    await post(`/api/orders/${id}/rate`, { target, stars: chosen, body: val("rText"),
      author_kind: state.buyer.kind, author_id: state.buyer.id, author_name: state.buyer.name });
    closeModal(); toast("Thanks for your review!"); renderOrders(v);
  };
}

// Reviews list for any actor (farmer / buyer / transport).
async function showReviews(kind, id, name) {
  modal(`<h2>⭐ Reviews — ${escapeHtml(name)}</h2><p class="muted">Loading…</p>`);
  const rows = await api(`/api/reviews?target_kind=${encodeURIComponent(kind)}&target_id=${encodeURIComponent(id)}`);
  const body = rows.length ? rows.map(r => `
    <div class="review">
      <div class="stars" style="color:#f0a500">${stars(r.stars)} <span class="muted">${escapeHtml(r.author_name || "User")}</span></div>
      ${r.body ? `<div class="msg">${escapeHtml(r.body)}</div>` : `<div class="muted" style="font-size:13px">No comment.</div>`}
    </div>`).join("") : `<div class="empty">No reviews yet.</div>`;
  modal(`<h2>⭐ Reviews — ${escapeHtml(name)}</h2><div style="margin-top:10px">${body}</div>`);
}
const escapeHtml = (s) => (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------------------------------------------------------------- messaging
async function renderMessages(v) {
  if (!state.buyer) {
    v.innerHTML = `<div class="empty">Please <a href="#" id="mLogin">log in</a> to see your messages.</div>`;
    $("#mLogin").onclick = (e) => { e.preventDefault(); openLogin(); };
    return;
  }
  v.innerHTML = `<p class="muted">Loading…</p>`;
  const threads = await api("/api/messages");
  if (!threads.length) {
    v.innerHTML = `<div class="hint">💬 In-app messaging. Start a conversation from a listing (💬 button) or an order.</div>
      <div class="empty">No conversations yet.</div>`;
    return;
  }
  v.innerHTML = `<div class="section-title">Your conversations</div><div id="threadList"></div>`;
  const list = $("#threadList");
  threads.forEach(t => {
    const km = KIND_META[t.other_kind] || KIND_META.buyer;
    list.appendChild(el(`
      <div class="order msg-thread" style="cursor:pointer">
        <div class="order-head">
          <div><b>${km.icon} ${escapeHtml(t.other_name || km.label)}</b> <span class="muted">· ${km.label}${t.order_id ? " · order #" + t.order_id : ""}</span></div>
          ${t.unread ? `<span class="pill held">${t.unread} new</span>` : ""}
        </div>
        <div class="muted" style="font-size:13px">${t.last.mine ? "You: " : ""}${escapeHtml(t.last.body)}</div>
      </div>`));
    list.lastChild.onclick = () => openThread(t.thread, t.other_kind, t.other_id, t.other_name, t.order_id);
  });
}

function openThread(thread, oKind, oId, oName, orderId) {
  const km = KIND_META[oKind] || KIND_META.buyer;
  modal(`<h2>${km.icon} ${escapeHtml(oName || km.label)}</h2>
    <div id="thread" class="thread-box"><p class="muted">Loading…</p></div>
    <div class="form" style="max-width:100%;margin-top:10px">
      <div class="row" style="gap:8px">
        <input id="mBody" placeholder="Type a message…" style="flex:1">
        <button class="btn" id="mSend">Send</button>
      </div>
    </div>`);
  const load = async () => {
    const msgs = await api("/api/messages?thread=" + encodeURIComponent(thread));
    $("#thread").innerHTML = msgs.map(m => {
      const mine = m.from_kind === state.buyer.kind && m.from_id === state.buyer.id;
      return `<div class="bubble ${mine ? "mine" : "theirs"}">${escapeHtml(m.body)}</div>`;
    }).join("") || `<p class="muted">No messages yet — say hello!</p>`;
    const box = $("#thread"); box.scrollTop = box.scrollHeight;
  };
  await0(load);
  const send = async () => {
    const body = val("mBody").trim(); if (!body) return;
    $("#mBody").value = "";
    await post("/api/messages", { from_kind: state.buyer.kind, from_id: state.buyer.id,
      from_name: state.buyer.name, to_kind: oKind, to_id: oId, to_name: oName,
      order_id: orderId || null, body });
    load();
  };
  $("#mSend").onclick = send;
  $("#mBody").onkeydown = (e) => { if (e.key === "Enter") send(); };
}
const await0 = (fn) => fn();

// Start a new message to someone (from a listing card or order).
function openComposeTo(kind, id, name, opts = {}) {
  if (!state.buyer) { toast("Log in to send a message"); return openLogin(); }
  if (state.buyer.kind === kind && state.buyer.id === id) return toast("That's you 🙂");
  modal(`<h2>💬 Message ${escapeHtml(name)}</h2>
    <div class="form" style="max-width:100%;margin-top:10px">
      <textarea id="cBody" rows="4" placeholder="Write your message…"></textarea>
      <button class="btn" id="cSend">Send message</button>
    </div>`);
  $("#cSend").onclick = async () => {
    const body = val("cBody").trim(); if (!body) return toast("Write a message first");
    const r = await post("/api/messages", { from_kind: state.buyer.kind, from_id: state.buyer.id,
      from_name: state.buyer.name, to_kind: kind, to_id: id, to_name: name,
      order_id: opts.order_id || null, listing_id: opts.listing_id || null, body });
    if (r.error) return toast(r.error || "Something went wrong");
    openThread(r.thread, kind, id, name, opts.order_id);
  };
}

// ---------------------------------------------------------------- sell (farmer produce management)
async function renderSell(v) {
  if (!state.buyer || state.buyer.kind !== "farmer") {
    v.innerHTML = `<div class="hint">🧺 The <b>Sell</b> area is for farmers — list produce, upload a photo, and manage stock.</div>
      <div class="empty">Log in as a farmer to manage produce.${state.buyer ? "" : ` <a href="#" id="sLogin">Log in</a>`}</div>`;
    const l = $("#sLogin"); if (l) l.onclick = (e) => { e.preventDefault(); openLogin(); };
    return;
  }
  v.innerHTML = `<p class="muted">Loading…</p>`;
  const mine = await api(`/api/listings?status=all&farmer_id=${state.buyer.id}&buyer_location=${encodeURIComponent(state.buyer.location)}`);
  v.innerHTML = `
    <div class="hint">🧺 Manage your produce, <b>${escapeHtml(state.buyer.name)}</b>. Add a listing with a real photo, then update stock or price anytime.</div>
    <div class="row" style="justify-content:space-between;align-items:center">
      <div class="section-title" style="margin:0">My listings (${mine.length})</div>
      <button class="btn" id="newListing">➕ New listing</button>
    </div>
    <div id="myListings" class="grid cards" style="margin-top:12px"></div>`;
  $("#newListing").onclick = () => listingForm();
  const box = $("#myListings");
  if (!mine.length) { box.innerHTML = `<div class="empty">No listings yet. Click “New listing”.</div>`; return; }
  mine.forEach(x => {
    box.appendChild(el(`
      <div class="card listing">
        <div class="img">${imgTag(x.image)}</div>
        <div class="crop">${x.crop} <span class="badge ${x.status === 'active' ? x.freshness_level : 'spoiled'}">${x.status === 'active' ? x.freshness : x.status.replace('_',' ')}</span></div>
        <div class="price">${ghs(x.price)}<span class="muted" style="font-size:13px;font-weight:500"> / ${x.unit}</span></div>
        <div class="meta">
          <span>📦 ${x.quantity} crates</span>
          <span>📍 ${x.location}</span>
        </div>
        <button class="btn ghost sm" data-edit="${x.id}">✏️ Edit / update stock</button>
      </div>`));
  });
  box.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => listingForm(mine.find(i => i.id == b.dataset.edit)));
}

let pendingImage = null;  // base64 data URL captured for the listing form
function listingForm(existing) {
  pendingImage = null;
  const edit = !!existing;
  const cropOpts = state.meta.crops.map(c => `<option ${edit && existing.crop === c ? "selected" : ""}>${c}</option>`).join("");
  const locOpts = state.meta.locations.map(l => `<option ${edit && existing.location === l ? "selected" : ""}>${l}</option>`).join("");
  modal(`<h2>${edit ? "✏️ Update listing" : "➕ New produce listing"}</h2>
    <div class="form" style="max-width:100%;margin-top:8px">
      <label>Photo (optional)</label>
      <div class="row" style="align-items:center;gap:12px">
        <div class="img" id="lPreview" style="width:72px;height:72px;font-size:34px;border-radius:12px;display:flex;align-items:center;justify-content:center;background:#f0f4f0">${edit ? imgTag(existing.image) : "🧺"}</div>
        <input type="file" id="lFile" accept="image/*">
      </div>
      ${edit ? "" : `<label>Crop</label><select id="lCrop">${cropOpts}</select>`}
      <label>Quantity (crates)</label><input id="lQty" type="number" min="0" value="${edit ? existing.quantity : 20}">
      <label>Price per crate (GHS)</label><input id="lPrice" type="number" step="1" value="${edit ? existing.price : 60}">
      ${edit ? `<label>Status</label><select id="lStatus">
          <option value="active" ${existing.status==='active'?'selected':''}>Active (visible to buyers)</option>
          <option value="unavailable" ${existing.status==='unavailable'?'selected':''}>Unavailable (hidden)</option>
        </select>` : `<label>Pickup location</label><select id="lLoc">${locOpts}</select>
        <label>Harvested how many hours ago?</label><input id="lAge" type="number" value="6">`}
      <button class="btn" id="lSave">${edit ? "Save changes" : "Publish listing"}</button>
    </div>`);
  $("#lFile").onchange = (e) => {
    const f = e.target.files[0]; if (!f) return;
    if (f.size > 1.5 * 1024 * 1024) return toast("Image too large (max ~1.5MB)");
    const fr = new FileReader();
    fr.onload = () => { pendingImage = downscale(fr.result, () => { $("#lPreview").innerHTML = imgTag(pendingImage); }); };
    fr.readAsDataURL(f);
  };
  $("#lSave").onclick = async () => {
    if (edit) {
      const body = { quantity: +val("lQty"), price: +val("lPrice"), status: val("lStatus") };
      if (pendingImage) body.image = pendingImage;
      const r = await post(`/api/listings/${existing.id}/update`, body);
      if (r.error) return toast(r.error || "Something went wrong");
      closeModal(); toast("Listing updated"); renderSell($("#view"));
    } else {
      const body = { farmer_id: state.buyer.id, crop: val("lCrop"), quantity: +val("lQty"),
        price: +val("lPrice"), location: val("lLoc"), harvested_hours_ago: +val("lAge") };
      if (pendingImage) body.image = pendingImage;
      const r = await post("/api/listings", body);
      if (r.error) return toast(r.error || "Something went wrong");
      closeModal(); toast("Listing published 🌱"); renderSell($("#view"));
    }
  };
}

// Downscale an uploaded image client-side to keep the stored data URL small.
function downscale(dataUrl, done) {
  const img = new Image();
  img.onload = () => {
    const max = 600, scale = Math.min(1, max / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = img.width * scale; c.height = img.height * scale;
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    pendingImage = c.toDataURL("image/jpeg", 0.78);
    done();
  };
  img.src = dataUrl;
  return dataUrl; // immediate value; pendingImage replaced once downscaled
}

// ---------------------------------------------------------------- nearby (proximity discovery)
const nearby = { origin: null, find: "buyers", radius: "" };
function renderNearby(v) {
  if (!requireLoginView(v, "discover nearby buyers, farmers & transport")) return;
  if (!nearby.origin) nearby.origin = myLocation();
  const locOpts = state.meta.locations.map(l => `<option ${nearby.origin === l ? "selected" : ""}>${l}</option>`).join("");
  v.innerHTML = `
    <div class="hint">📍 <b>Proximity search</b> — any actor can discover who's around them. A farmer in Akumadan finds the nearest buyers; a buyer finds nearby farms; anyone finds nearby transport. Sorted by real distance (great-circle, haversine).</div>
    <div class="filters">
      <label class="muted" style="font-weight:600">I'm in</label>
      <select id="nOrigin">${locOpts}</select>
      <label class="muted" style="font-weight:600">Find</label>
      <div class="seg" id="nFind">
        <button data-f="buyers" class="${nearby.find==='buyers'?'active':''}">🛒 Buyers</button>
        <button data-f="retailers" class="${nearby.find==='retailers'?'active':''}">🏪 Retailers</button>
        <button data-f="farmers" class="${nearby.find==='farmers'?'active':''}">👨‍🌾 Farmers</button>
        <button data-f="transport" class="${nearby.find==='transport'?'active':''}">🚚 Transport</button>
      </div>
      <input id="nRadius" type="number" placeholder="Within … km (optional)" value="${nearby.radius}" style="width:190px">
    </div>
    <div id="nearbyMap" class="map-box"></div>
    <div id="nearbyResults" class="grid cards"></div>`;
  $("#nOrigin").onchange = e => { nearby.origin = e.target.value; loadNearby(); };
  $("#nFind").onclick = e => { const b = e.target.closest("button"); if (!b) return; nearby.find = b.dataset.f; renderNearby(v); };
  $("#nRadius").oninput = e => { nearby.radius = e.target.value; loadNearby(); };
  loadNearby();
}
async function loadNearby() {
  const q = new URLSearchParams({ find: nearby.find, origin: nearby.origin });
  if (nearby.radius) q.set("radius", nearby.radius);
  const data = await api("/api/nearby?" + q);
  const box = $("#nearbyResults");
  const res = data.results || [];
  drawMap(data);
  if (!res.length) { box.innerHTML = `<div class="empty">No ${nearby.find} found${nearby.radius ? " within " + nearby.radius + " km" : ""} of ${nearby.origin}.</div>`; return; }
  const maxD = Math.max(...res.map(r => r.distance_km), 1);
  box.innerHTML = "";
  res.forEach((r, i) => {
    const icon = nearby.find === "buyers" ? "🛒" : nearby.find === "retailers" ? "🏪" : nearby.find === "farmers" ? "👨‍🌾"
      : (r.vehicle || "").toLowerCase().includes("truck") ? "🚛" : (r.vehicle || "").toLowerCase().includes("pickup") ? "🛻" : "🛺";
    let detail = "";
    if (nearby.find === "buyers" || nearby.find === "retailers") detail = `<span>🏷️ ${escapeHtml(r.type)}</span>`;
    else if (nearby.find === "farmers") detail = `<span>${r.verified ? '<span class="badge verify">✓ Verified</span>' : '<span class="badge soon">Unverified</span>'}</span><span>📦 ${r.active_listings} active listing(s)</span>`;
    else detail = `<span>${escapeHtml(r.vehicle)}</span><span>📦 ${r.capacity_crates} crates · ${ghs(r.rate_per_km)}/km</span><span><span class="badge ${r.available ? 'fresh' : 'spoiled'}">${r.available ? 'Available' : 'Busy'}</span></span>`;
    const pct = Math.round((1 - r.distance_km / maxD) * 100);
    box.appendChild(el(`
      <div class="card listing">
        ${i === 0 ? `<span class="badge score">📍 Nearest</span>` : ``}
        <div class="img">${icon}</div>
        <div class="crop">${escapeHtml(r.name)}</div>
        <div class="price" style="font-size:18px">${r.distance_km} km<span class="muted" style="font-size:13px;font-weight:500"> from ${escapeHtml(nearby.origin)}</span></div>
        <div style="height:6px;background:#eef2ef;border-radius:6px;overflow:hidden"><div style="height:100%;width:${pct}%;background:var(--green)"></div></div>
        <div class="meta">
          <span>📍 ${escapeHtml(r.location)}</span>
          ${detail}
          <span class="stars">${stars(r.rating)} <span class="muted">${r.rating} (${r.rating_count})</span>
            <a href="#" class="link" data-rev="${nKind()}:${r.id}:${escapeHtml(r.name)}">reviews</a></span>
          <span class="muted">📞 ${escapeHtml(r.phone)}</span>
        </div>
        <button class="btn ghost sm" data-nmsg="${nKind()}:${r.id}:${escapeHtml(r.name)}">💬 Message</button>
      </div>`));
  });
  box.querySelectorAll("[data-rev]").forEach(b => b.onclick = (e) => { e.preventDefault(); const [k,i,n]=b.dataset.rev.split(":"); showReviews(k,i,n); });
  box.querySelectorAll("[data-nmsg]").forEach(b => b.onclick = () => { const [k,i,n]=b.dataset.nmsg.split(":"); openComposeTo(k, +i, n, {}); });
}
// The review/message target kind for the current Nearby filter.
function nKind() { return nearby.find === "retailers" ? "retailer" : nearby.find === "farmers" ? "farmer" : nearby.find === "transport" ? "transport" : "buyer"; }

// Lightweight inline map (no tiles, no CDN): projects lat/lng to an SVG so it
// works fully offline. Plots the origin (★) and each nearby actor (●).
function drawMap(data) {
  const box = $("#nearbyMap"); if (!box) return;
  const pts = (data.results || []).filter(r => r.lat != null && r.lng != null)
    .map(r => ({ lat: r.lat, lng: r.lng, name: r.name, km: r.distance_km }));
  const origin = (data.origin_lat != null) ? { lat: data.origin_lat, lng: data.origin_lng } : null;
  const all = pts.concat(origin ? [origin] : []);
  if (all.length < 1) { box.innerHTML = `<div class="muted" style="padding:14px">No mappable points.</div>`; return; }
  const lats = all.map(p => p.lat), lngs = all.map(p => p.lng);
  let minLat = Math.min(...lats), maxLat = Math.max(...lats), minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const padLat = (maxLat - minLat) * 0.15 || 0.2, padLng = (maxLng - minLng) * 0.15 || 0.2;
  minLat -= padLat; maxLat += padLat; minLng -= padLng; maxLng += padLng;
  const W = 100, H = 60;
  const X = (lng) => ((lng - minLng) / (maxLng - minLng || 1)) * W;
  const Y = (lat) => H - ((lat - minLat) / (maxLat - minLat || 1)) * H;  // north up
  const dots = pts.map(p => `
    <circle cx="${X(p.lng).toFixed(2)}" cy="${Y(p.lat).toFixed(2)}" r="1.5" class="map-dot"></circle>
    <text x="${(X(p.lng)+2).toFixed(2)}" y="${(Y(p.lat)+1).toFixed(2)}" class="map-lbl">${escapeHtml(p.name)} · ${p.km}km</text>`).join("");
  const star = origin ? `<text x="${(X(origin.lng)-1.6).toFixed(2)}" y="${(Y(origin.lat)+1.6).toFixed(2)}" class="map-star">★</text>` : "";
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="map-svg">
    <rect x="0" y="0" width="${W}" height="${H}" class="map-bg"></rect>${dots}${star}
  </svg><div class="map-cap">📍 ${escapeHtml(data.origin)} (★) and ${pts.length} nearby ${nearby.find} — offline projection of real coordinates.</div>`;
}

// Inline offline delivery map for one order: farm (●) → buyer (●),
// with a moving truck marker positioned by the order's progress.
function deliveryMapHtml(o) {
  const coords = (state.meta && state.meta.location_coords) || {};
  const a = o.farmer && coords[o.farmer.location], b = o.buyer && coords[o.buyer.location];
  if (!a || !b) return "";
  const progress = { placed: 0, matched: 0.08, picked_up: 0.5, delivered: 1, completed: 1 }[o.status] ?? 0;
  const lats = [a.lat, b.lat], lngs = [a.lng, b.lng];
  let minLat = Math.min(...lats), maxLat = Math.max(...lats), minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const padLat = (maxLat - minLat) * 0.25 || 0.3, padLng = (maxLng - minLng) * 0.25 || 0.3;
  minLat -= padLat; maxLat += padLat; minLng -= padLng; maxLng += padLng;
  const W = 100, H = 42;
  const X = (lng) => ((lng - minLng) / (maxLng - minLng || 1)) * W;
  const Y = (lat) => H - ((lat - minLat) / (maxLat - minLat || 1)) * H;
  const ax = X(a.lng), ay = Y(a.lat), bx = X(b.lng), by = Y(b.lat);
  const tx = ax + (bx - ax) * progress, ty = ay + (by - ay) * progress;
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="map-svg" style="margin-top:8px">
    <rect x="0" y="0" width="${W}" height="${H}" class="map-bg"></rect>
    <line x1="${ax.toFixed(1)}" y1="${ay.toFixed(1)}" x2="${bx.toFixed(1)}" y2="${by.toFixed(1)}" stroke="#9bbf9b" stroke-width="0.7" stroke-dasharray="2 1.5"></line>
    <circle cx="${ax.toFixed(1)}" cy="${ay.toFixed(1)}" r="1.6" class="map-dot"></circle>
    <text x="${(ax+2).toFixed(1)}" y="${(ay+1).toFixed(1)}" class="map-lbl">🌱 ${escapeHtml(o.farmer.location)}</text>
    <circle cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="1.6" style="fill:#2e7d32"></circle>
    <text x="${(bx+2).toFixed(1)}" y="${(by+1).toFixed(1)}" class="map-lbl">🏠 ${escapeHtml(o.buyer.location)}</text>
    <text x="${(tx-1.6).toFixed(1)}" y="${(ty+1.4).toFixed(1)}" style="font-size:4px">🚚</text>
  </svg>`;
}

// Download the caller's orders as CSV (sends the auth token, then saves a Blob).
async function exportOrdersCsv() {
  const r = await fetch(API + "/api/export.csv", { headers: authHeaders() });
  if (!r.ok) return toast("Export failed");
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "vegelink-orders.csv"; a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------- feature phone (USSD)
function renderPhone(v) {
  v.innerHTML = `
    <div class="phone-wrap">
      <div class="phone">
        <div class="phone-net"><span>📶 MTN GH</span><span>USSD</span><span>🔋 84%</span></div>
        <div class="phone-screen" id="screen">Dial *789# and press SEND to start.\n\n(Simulating a feature phone with no internet — exactly how a farmer in Akumadan uses VegeLink.)</div>
        <div class="phone-input">
          <input id="ussdInput" placeholder="*789#" value="*789#">
        </div>
        <div class="keypad" id="keypad">
          ${[1,2,3,4,5,6,7,8,9].map(n=>`<div class="key" data-k="${n}">${n}</div>`).join("")}
          <div class="key end" data-k="end">END</div>
          <div class="key" data-k="0">0</div>
          <div class="key send" data-k="send">SEND</div>
        </div>
      </div>
      <div class="phone-explain">
        <h3>📱 The killer feature: USSD-first</h3>
        <p class="muted">Most agri-apps assume a smartphone + data. Real smallholders use feature phones on patchy networks. VegeLink onboards them over USSD — no app, no internet.</p>
        <div class="hint" style="margin-top:14px">This emulator hits the <b>same backend endpoint</b> (<code>/api/ussd</code>) that the live Africa's Talking gateway calls — Africa's-Talking-compatible <code>CON</code>/<code>END</code> protocol.</div>
        <h3 style="margin-top:16px">Try it</h3>
        <ol>
          <li>Press <b>SEND</b> to dial *789#</li>
          <li>Choose language: <b>1</b> English / <b>2</b> Twi</li>
          <li>Type <b>1</b> SEND → list produce</li>
          <li>Pick crop → qty → price → location → confirm</li>
          <li>Watch the SMS appear under <b>🔔 Activity</b></li>
        </ol>
        <button class="btn ghost sm" id="ussdReset" style="margin-top:8px">↺ Reset session</button>
      </div>
    </div>`;
  const screen = $("#screen");
  const reset = () => { state.ussd.text = ""; state.ussd.started = false; screen.textContent = "Dial *789# and press SEND to start."; };
  reset();
  $("#ussdReset").onclick = reset;
  $("#keypad").onclick = async e => {
    const k = e.target.closest("[data-k]"); if (!k) return;
    const key = k.dataset.k;
    if (key === "end") { reset(); return; }
    if (key === "send") return ussdSend(screen);
    $("#ussdInput").value = (state.ussd.started ? ($("#ussdInput").value === "*789#" ? "" : $("#ussdInput").value) : "*789#" );
    if (state.ussd.started) $("#ussdInput").value += key;
  };
}
async function ussdSend(screen) {
  const input = $("#ussdInput");
  if (!state.ussd.started) {
    state.ussd.started = true; state.ussd.text = ""; input.value = "";
  } else {
    state.ussd.text = state.ussd.text ? state.ussd.text + "*" + input.value : input.value;
    input.value = "";
  }
  const r = await api("/api/ussd", { method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ phoneNumber: state.ussd.phone, text: state.ussd.text }) });
  const ended = r.startsWith("END");
  screen.textContent = r.replace(/^(CON|END)\s*/, "") + (ended ? "\n\n— session ended —" : "\n\n> type reply, press SEND");
  if (ended) { state.ussd.started = false; state.ussd.text = ""; }
}

// ---------------------------------------------------------------- transport
async function renderTransport(v) {
  const t = await api("/api/transport");
  v.innerHTML = `<div class="hint">🚚 Registered transport providers. Orders auto-match the cheapest suitable vehicle (tricycles for local hauls, trucks for long distance).</div>
    <div class="grid cards">${t.map(x => `
      <div class="card listing">
        <div class="img">${(x.vehicle||'').toLowerCase().includes('truck') ? '🚛' : (x.vehicle||'').toLowerCase().includes('pickup') ? '🛻' : '🛺'}</div>
        <div class="crop">${escapeHtml(x.name)}</div>
        <div class="meta">
          <span>${escapeHtml(x.vehicle)}</span>
          <span>📦 ${x.capacity_crates} crates capacity</span>
          <span>📍 Based in ${escapeHtml(x.location)} · ${ghs(x.rate_per_km)}/km</span>
          <span class="stars">${stars(x.rating)} <span class="muted">${x.rating} (${x.rating_count})</span></span>
          <span><span class="badge ${x.available ? 'fresh' : 'spoiled'}">${x.available ? 'Available' : 'Busy'}</span></span>
        </div>
      </div>`).join("")}</div>`;
}

// ---------------------------------------------------------------- notifications
async function renderNotifs(v) {
  if (!requireLoginView(v, "see your activity")) return;
  v.innerHTML = `<p class="muted">Loading…</p>`;
  const n = await api("/api/notifications");
  v.innerHTML = `<div class="section-title">Your activity — alerts & SMS for ${escapeHtml(state.buyer.name)}</div>
    <div class="card">${n.length ? n.map(x => `
      <div class="notif">
        <span class="chan ${x.channel}">${x.channel === 'SMS' ? '✉ SMS' : '🔔 APP'}</span>
        <div><div class="msg">${escapeHtml(x.message)}</div><div class="who">→ ${escapeHtml(x.recipient)}</div></div>
      </div>`).join("") : '<div class="empty">No activity yet.</div>'}</div>`;
}

// Shared "please log in" gate for views that need a session.
function requireLoginView(v, what) {
  if (state.buyer) return true;
  v.innerHTML = `<div class="empty">Please <a href="#" id="rlLogin">log in</a> to ${what}.</div>`;
  $("#rlLogin").onclick = (e) => { e.preventDefault(); openLogin(); };
  return false;
}

// ---------------------------------------------------------------- register (role dropdown -> form)
const ROLES = {
  farmer:    { icon: "👨‍🌾", label: "Farmer" },
  buyer:     { icon: "🛒",   label: "Buyer" },
  retailer:  { icon: "🏪",   label: "Retailer" },
  transport: { icon: "🚚",   label: "Transport owner" },
};
let regRole = "";  // remembered across re-renders
function renderRegister(v) {
  const opts = Object.entries(ROLES)
    .map(([k, r]) => `<option value="${k}" ${regRole === k ? "selected" : ""}>${r.icon} ${r.label}</option>`).join("");
  v.innerHTML = `
    <div class="hint">➕ Choose how you want to register, then fill the form. Farmers sell produce; Buyers &amp; Retailers purchase; Transport owners move goods.</div>
    <div class="card" style="max-width:520px">
      <div class="form" style="max-width:100%">
        <label>I want to register as…</label>
        <select id="regRole">
          <option value="" ${regRole ? "" : "selected"} disabled>— Select a role —</option>
          ${opts}
        </select>
      </div>
      <div id="regForm" style="margin-top:8px"></div>
    </div>`;
  $("#regRole").onchange = e => { regRole = e.target.value; renderRegForm(); };
  if (regRole) renderRegForm();
}

// captured GPS for the registration in progress
const reg = { lat: null, lng: null };
// Shared location + GPS-capture + PIN block reused by every registration form.
function locSecBlock() {
  const locOpts = state.meta.locations.map(l => `<option>${l}</option>`).join("");
  return `
    <label>Location (nearest town)</label><select id="rLoc">${locOpts}</select>
    <label>GPS location (optional but recommended)</label>
    <div class="row" style="align-items:center;gap:10px">
      <button type="button" class="btn ghost sm" id="rGps">📍 Use my GPS</button>
      <span class="muted" id="rGpsStatus" style="font-size:13px">Uses your town centre if not set.</span>
    </div>
    <label>Choose a 4-digit PIN</label>
    <input id="rPin" type="password" inputmode="numeric" maxlength="8" placeholder="•••• (you'll log in with phone + PIN)">
    <label>Confirm PIN</label>
    <input id="rPin2" type="password" inputmode="numeric" maxlength="8" placeholder="re-enter your PIN">`;
}
function wireGps() {
  reg.lat = reg.lng = null;
  const btn = $("#rGps"), status = $("#rGpsStatus");
  if (!btn) return;
  btn.onclick = () => {
    if (!navigator.geolocation) return status.textContent = "GPS not available on this device.";
    status.textContent = "Locating…";
    navigator.geolocation.getCurrentPosition(
      p => { reg.lat = +p.coords.latitude.toFixed(5); reg.lng = +p.coords.longitude.toFixed(5);
             status.innerHTML = `✅ Captured: ${reg.lat}, ${reg.lng}`; },
      () => { status.textContent = "Couldn't get GPS — we'll use your town centre."; });
  };
}

function renderRegForm() {
  const box = $("#regForm");
  if (regRole === "farmer") {
    box.innerHTML = `<div class="section-title" style="margin-top:14px">👨‍🌾 Farmer details</div>
      <div class="form" style="max-width:100%">
        <label>Full name</label><input id="rName" placeholder="e.g. Kojo Asante">
        <label>Phone</label><input id="rPhone" placeholder="024…">
        ${locSecBlock()}
        <button class="btn" id="rSubmit">Register farmer</button>
      </div>`;
    $("#rSubmit").onclick = () => submitReg("/api/farmers",
      { name: val("rName"), phone: val("rPhone"), location: val("rLoc") }, "Farmer", "farmer");
  } else if (regRole === "buyer" || regRole === "retailer") {
    const isRet = regRole === "retailer";
    const typeOpts = isRet
      ? `<option>retailer</option><option>wholesaler</option><option>market stall</option>`
      : `<option>restaurant</option><option>processor</option><option>exporter</option><option>household</option><option>wholesaler</option>`;
    box.innerHTML = `<div class="section-title" style="margin-top:14px">${ROLES[regRole].icon} ${ROLES[regRole].label} details</div>
      <div class="form" style="max-width:100%">
        <label>${isRet ? "Shop / business name" : "Business name"}</label><input id="rName" placeholder="${isRet ? 'e.g. Tamale Fresh Mart' : 'e.g. Osu Food Market'}">
        <label>Phone</label><input id="rPhone" placeholder="055…">
        <label>${isRet ? "Shop type" : "Buyer type"}</label><select id="rType">${typeOpts}</select>
        ${locSecBlock()}
        <button class="btn" id="rSubmit">Register ${ROLES[regRole].label.toLowerCase()}</button>
      </div>`;
    $("#rSubmit").onclick = () => submitReg("/api/buyers",
      { name: val("rName"), phone: val("rPhone"), type: val("rType"), role: regRole, location: val("rLoc") },
      ROLES[regRole].label, regRole);
  } else if (regRole === "transport") {
    box.innerHTML = `<div class="section-title" style="margin-top:14px">🚚 Transport owner details</div>
      <div class="form" style="max-width:100%">
        <label>Provider name</label><input id="rName" placeholder="e.g. Sika Cargo">
        <label>Phone</label><input id="rPhone" placeholder="027…">
        <label>Vehicle</label><select id="rVeh"><option>Cargo tricycle (aboboyaa)</option><option>Pickup truck</option><option>Cargo truck</option></select>
        <label>Capacity (crates)</label><input id="rCap" type="number" value="80">
        ${locSecBlock()}
        <label>Rate per km (GHS)</label><input id="rRate" type="number" step="0.1" value="2.5">
        <button class="btn" id="rSubmit">Register transport</button>
      </div>`;
    $("#rSubmit").onclick = () => submitReg("/api/transport",
      { name: val("rName"), phone: val("rPhone"), vehicle: val("rVeh"),
        capacity_crates: val("rCap"), location: val("rLoc"), rate_per_km: val("rRate") }, "Transport", "transport");
  }
  wireGps();
}

const val = (id) => $("#" + id).value;
async function submitReg(endpoint, body, label, kind) {
  if (!body.name || !body.phone) return toast("Name and phone are required");
  const pin = val("rPin").trim();
  if (!/^\d{4,8}$/.test(pin)) return toast("Choose a 4–8 digit PIN");
  if (pin !== val("rPin2").trim()) return toast("PINs don't match — please re-enter");
  body.pin = pin;
  if (reg.lat != null && reg.lng != null) { body.lat = reg.lat; body.lng = reg.lng; }
  const r = await post(endpoint, body);
  if (r.error) return toast(r.error);
  // log the new account in via the real auth path (phone + the PIN just set)
  const lr = await post("/api/login", { phone: body.phone, pin });
  if (lr.error || !lr.accounts) { toast(`${label} registered ✓ — please log in`); return openLogin(); }
  const acct = lr.accounts.find(a => a.kind === kind) || lr.accounts[0];
  login(acct);
  toast(`${label} registered ✓ — you're now logged in`);
}

boot();
