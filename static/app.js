// VegeLink SPA — vanilla JS, no build step.
const API = "";
const $ = (s, r = document) => r.querySelector(s);
const el = (h) => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstChild; };

const state = { tab: "dashboard", buyers: [], buyer: null, meta: null, ussd: { text: "", phone: "0249000001", lines: [] } };

async function api(path, opts) {
  const r = await fetch(API + path, opts);
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}
function modal(html) {
  $("#modalBody").innerHTML = `<button class="close-x" onclick="closeModal()">×</button>` + html;
  $("#modal").classList.remove("hidden");
}
window.closeModal = () => $("#modal").classList.add("hidden");
function stars(n) { const f = Math.round(n); return "★".repeat(f) + "☆".repeat(5 - f); }
const ghs = (n) => "GHS " + Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
const cap = (s) => (s || "").charAt(0).toUpperCase() + (s || "").slice(1);
const PAY_ICONS = { momo: "📱", bank: "🏦", card: "💳", cod: "💵" };
const DEFAULT_USER = "Lukman Kunveng";
function defaultActor(list) {
  return list.find(b => b.name === DEFAULT_USER && (b.role || "buyer") === "buyer")
      || list.find(b => b.name === DEFAULT_USER)
      || list[0];
}
function fillActorSelect() {
  const sel = $("#buyerSelect");
  sel.innerHTML = state.buyers.map(b =>
    `<option value="${b.id}">${b.name} (${cap(b.role || "buyer")}) · ${b.location}</option>`).join("");
  if (state.buyer) sel.value = state.buyer.id;
}

// ---------------------------------------------------------------- boot
async function boot() {
  state.meta = await api("/api/meta");
  state.buyers = await api("/api/buyers");
  state.buyer = defaultActor(state.buyers);
  fillActorSelect();
  $("#buyerSelect").onchange = (e) => { state.buyer = state.buyers.find(b => b.id == e.target.value); render(); };

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
  ({ dashboard: renderDashboard, market: renderMarket, nearby: renderNearby, orders: renderOrders,
     phone: renderPhone, transport: renderTransport, notifications: renderNotifs,
     register: renderRegister }[state.tab] || renderDashboard)(v);
}

// ---------------------------------------------------------------- dashboard
async function renderDashboard(v) {
  v.innerHTML = `<p class="muted">Loading…</p>`;
  const d = await api("/api/dashboard");
  v.innerHTML = `
    <div class="hint">💡 Impact dashboard — every sale through VegeLink is produce rescued from spoilage and income returned to a smallholder.</div>
    <div class="grid cols-4">
      <div class="stat tomato"><div class="v">${ghs(d.loss_avoided)}</div><div class="l">Produce value rescued from spoilage*</div></div>
      <div class="stat hl"><div class="v">${ghs(d.gmv)}</div><div class="l">Total marketplace volume (GMV)</div></div>
      <div class="stat"><div class="v">${d.orders}</div><div class="l">Orders (${d.completed} completed)</div></div>
      <div class="stat"><div class="v">${ghs(d.escrow_held)}</div><div class="l">Currently held in MoMo escrow</div></div>
    </div>
    <div class="grid" style="margin-top:16px;grid-template-columns:repeat(5,1fr)">
      <div class="stat"><div class="v">${d.farmers}</div><div class="l">Farmers</div></div>
      <div class="stat"><div class="v">${d.buyers}</div><div class="l">Buyers</div></div>
      <div class="stat"><div class="v">${d.retailers}</div><div class="l">Retailers</div></div>
      <div class="stat"><div class="v">${d.transport}</div><div class="l">Transport providers</div></div>
      <div class="stat"><div class="v">${d.active_listings}</div><div class="l">Active listings</div></div>
    </div>
    <p class="muted" style="font-size:12px;margin-top:14px">*Ghana loses 20–50% of perishables post-harvest. We apply the 35% midpoint to produce value transacted as a conservative estimate of loss avoided.</p>
    <div class="card" style="margin-top:22px">
      <div class="section-title">How VegeLink works</div>
      <div class="row">
        <div style="flex:1;min-width:180px"><b>1. Farmer lists 📱</b><br><span class="muted">Over USSD on any feature phone — no internet needed.</span></div>
        <div style="flex:1;min-width:180px"><b>2. Buyer orders 🛒</b><br><span class="muted">Smart-ranked by freshness + distance. Pays via MoMo.</span></div>
        <div style="flex:1;min-width:180px"><b>3. Transport matched 🚚</b><br><span class="muted">Nearest suitable vehicle, auto-priced.</span></div>
        <div style="flex:1;min-width:180px"><b>4. Delivered → paid ✅</b><br><span class="muted">Escrow releases to farmer on confirmation.</span></div>
      </div>
    </div>`;
}

// ---------------------------------------------------------------- marketplace
const filters = { crop: "", maxprice: "", location: "", sort: "smart" };
async function renderMarket(v) {
  const cropOpts = `<option value="">All crops</option>` + state.meta.crops.map(c => `<option ${filters.crop === c ? "selected" : ""}>${c}</option>`).join("");
  const locOpts = `<option value="">All locations</option>` + state.meta.locations.map(l => `<option ${filters.location === l ? "selected" : ""}>${l}</option>`).join("");
  v.innerHTML = `
    <div class="hint">🧠 <b>Smart match</b> ranks produce by spoilage urgency + distance to you (<b>${state.buyer.location}</b>) — surfacing what to buy first to cut waste.</div>
    <div class="filters">
      <select id="fCrop">${cropOpts}</select>
      <select id="fLoc">${locOpts}</select>
      <input id="fPrice" type="number" placeholder="Max price/crate" value="${filters.maxprice}" style="width:150px">
      <div class="seg" id="fSort">
        <button data-s="smart" class="${filters.sort==='smart'?'active':''}">🧠 Smart</button>
        <button data-s="urgency" class="${filters.sort==='urgency'?'active':''}">⏳ Urgency</button>
        <button data-s="price" class="${filters.sort==='price'?'active':''}">💰 Price</button>
      </div>
    </div>
    <div id="listings" class="grid cards"></div>`;
  $("#fCrop").onchange = e => { filters.crop = e.target.value; loadListings(); };
  $("#fLoc").onchange = e => { filters.location = e.target.value; loadListings(); };
  $("#fPrice").oninput = e => { filters.maxprice = e.target.value; loadListings(); };
  $("#fSort").onclick = e => { const b = e.target.closest("button"); if (!b) return; filters.sort = b.dataset.s; loadListings(); };
  loadListings();
}
async function loadListings() {
  const q = new URLSearchParams({ sort: filters.sort, buyer_location: state.buyer.location });
  if (filters.crop) q.set("crop", filters.crop);
  if (filters.location) q.set("location", filters.location);
  if (filters.maxprice) q.set("maxprice", filters.maxprice);
  const items = await api("/api/listings?" + q);
  const box = $("#listings");
  if (!items.length) { box.innerHTML = `<div class="empty">No produce matches your filters.</div>`; return; }
  box.innerHTML = "";
  items.forEach((x, i) => {
    const top = filters.sort !== "price" && i === 0;
    box.appendChild(el(`
      <div class="card listing">
        ${top ? `<span class="badge score">★ Best match</span>` : ``}
        <div class="img">${x.image}</div>
        <div class="crop">${x.crop} <span class="badge ${x.freshness_level}">${x.freshness}</span></div>
        <div class="price">${ghs(x.price)}<span class="muted" style="font-size:13px;font-weight:500"> / ${x.unit}</span></div>
        <div class="meta">
          <span>📦 ${x.quantity} crates available</span>
          <span>📍 ${x.location} · ${x.distance_km} km away</span>
          <span>👨‍🌾 ${x.farmer.name} ${x.farmer.verified ? '<span class="badge verify">✓ Verified</span>' : ''}</span>
          <span class="stars">${stars(x.farmer.rating)} <span class="muted">${x.farmer.rating} (${x.farmer.rating_count})</span></span>
        </div>
        <button class="btn" data-buy="${x.id}">Order now</button>
      </div>`));
  });
  box.querySelectorAll("[data-buy]").forEach(b => b.onclick = () => openOrder(b.dataset.buy, items.find(i => i.id == b.dataset.buy)));
}

function openOrder(id, x) {
  const methods = state.meta.payment_methods || { momo: "Mobile Money", bank: "Bank Transfer", card: "Card", cod: "Cash on Delivery" };
  const payOpts = Object.entries(methods)
    .map(([k, l]) => `<option value="${k}">${PAY_ICONS[k] || "💳"} ${l}</option>`).join("");
  modal(`
    <h2>${x.image} Order ${x.crop}</h2>
    <p class="muted">From ${x.farmer.name} · ${x.location}</p>
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
    if (o.error) return toast("Error: " + o.error);
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
      <div class="kv"><span class="k">🚚 ${o.transport ? o.transport.name + ' — ' + o.transport.vehicle : 'No transport'}</span><b>${ghs(o.transport_cost)}</b></div>
      <div class="kv"><span class="k">Distance / ETA</span><b>${o.distance_km} km · ~${o.eta_minutes} min</b></div>
      <div class="kv"><span class="k">Payment method</span><b>${PAY_ICONS[o.payment_method] || ""} ${o.payment_label}</b></div>
      <div class="kv"><span class="k">${cod ? "Total payable on delivery (cash)" : "Total held in " + o.payment_label + " escrow"}</span><b style="color:var(--tomato-d)">${ghs(o.total)}</b></div>
    </div>
    <button class="btn" style="margin-top:16px;width:100%" onclick="closeModal();gotoTab('orders')">Track this order →</button>`);
}
window.gotoTab = (t) => { $(`#tabs button[data-tab="${t}"]`).click(); };

// ---------------------------------------------------------------- orders
async function renderOrders(v) {
  v.innerHTML = `<p class="muted">Loading…</p>`;
  const orders = await api("/api/orders?buyer_id=" + state.buyer.id);
  if (!orders.length) { v.innerHTML = `<div class="empty">No orders yet for ${state.buyer.name}.<br>Go to the Marketplace to place one.</div>`; return; }
  v.innerHTML = `<div class="section-title">Orders for ${state.buyer.name}</div><div id="orderList"></div>`;
  const list = $("#orderList");
  const steps = ["placed", "matched", "picked_up", "delivered", "completed"];
  const labels = { placed: "Placed", matched: "Matched", picked_up: "Picked up", delivered: "Delivered", completed: "Paid" };
  orders.forEach(o => {
    const ci = steps.indexOf(o.status);
    const tl = steps.map((s, i) => `<div class="tl-step ${i <= ci ? 'done' : ''}">${labels[s]}</div>`).join("");
    const actions = [];
    if (o.status === "matched") actions.push(`<button class="btn sm" data-act="picked_up" data-id="${o.id}">Mark picked up</button>`);
    if (o.status === "picked_up") actions.push(`<button class="btn sm" data-act="delivered" data-id="${o.id}">Mark delivered</button>`);
    if (o.status === "delivered") actions.push(`<button class="btn tomato sm" data-confirm="${o.id}">${o.payment_method === 'cod' ? '✅ Confirm delivery & collect cash' : '✅ Confirm delivery & release payment'}</button>`);
    if (o.status === "completed" && !o.farmer_rated) actions.push(`<button class="btn ghost sm" data-rate="${o.id}">⭐ Rate farmer</button>`);
    const payLabels = { held: "Escrow held", released: "Released", cod_pending: "Cash on delivery", paid: "Paid (cash)", pending: "Pending" };
    list.appendChild(el(`
      <div class="order">
        <div class="order-head">
          <div><b>${o.image} ${o.quantity} crates ${o.crop}</b> <span class="muted">· #${o.id} · from ${o.farmer.name} (${o.farmer.location})</span></div>
          <div>
            <span class="pill" style="background:#eef2ef;color:#555">${PAY_ICONS[o.payment_method] || '💳'} ${o.payment_label}</span>
            <span class="pill ${o.payment_status}">${payLabels[o.payment_status] || o.payment_status}</span>
            <span class="pill ${o.status}">${o.status.replace('_', ' ')}</span>
          </div>
        </div>
        <div class="timeline">${tl}</div>
        <div class="kv"><span class="k">${o.transport ? '🚚 ' + o.transport.name + ' · ' + o.distance_km + 'km · ~' + o.eta_minutes + 'min' : 'No transport'}</span><b>Total ${ghs(o.total)}</b></div>
        <div class="row" style="margin-top:10px">${actions.join("") || '<span class="muted">Order complete. Thank you!</span>'}</div>
      </div>`));
  });
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
function rateModal(id, v) {
  modal(`<h2>⭐ Rate this farmer</h2><p class="muted">How was the produce & transaction?</p>
    <div style="font-size:34px;text-align:center;margin:18px 0" id="rStars"></div>
    <button class="btn" style="width:100%" id="rSubmit">Submit rating</button>`);
  let chosen = 5;
  const draw = () => $("#rStars").innerHTML = [1,2,3,4,5].map(n => `<span data-n="${n}" style="cursor:pointer;color:${n<=chosen?'#f0a500':'#ddd'}">★</span>`).join("");
  draw();
  $("#rStars").onclick = e => { const s = e.target.closest("[data-n]"); if (s) { chosen = +s.dataset.n; draw(); } };
  $("#rSubmit").onclick = async () => { await post(`/api/orders/${id}/rate`, { target: "farmer", stars: chosen }); closeModal(); toast("Thanks for rating!"); renderOrders(v); };
}

// ---------------------------------------------------------------- nearby (proximity discovery)
const nearby = { origin: null, find: "buyers", radius: "" };
function renderNearby(v) {
  if (!nearby.origin) nearby.origin = state.buyer.location;
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
  if (!res.length) { box.innerHTML = `<div class="empty">No ${nearby.find} found${nearby.radius ? " within " + nearby.radius + " km" : ""} of ${nearby.origin}.</div>`; return; }
  const maxD = Math.max(...res.map(r => r.distance_km), 1);
  box.innerHTML = "";
  res.forEach((r, i) => {
    const icon = nearby.find === "buyers" ? "🛒" : nearby.find === "retailers" ? "🏪" : nearby.find === "farmers" ? "👨‍🌾"
      : (r.vehicle || "").toLowerCase().includes("truck") ? "🚛" : (r.vehicle || "").toLowerCase().includes("pickup") ? "🛻" : "🛺";
    let detail = "";
    if (nearby.find === "buyers" || nearby.find === "retailers") detail = `<span>🏷️ ${r.type}</span>`;
    else if (nearby.find === "farmers") detail = `<span>${r.verified ? '<span class="badge verify">✓ Verified</span>' : '<span class="badge soon">Unverified</span>'}</span><span>📦 ${r.active_listings} active listing(s)</span>`;
    else detail = `<span>${r.vehicle}</span><span>📦 ${r.capacity_crates} crates · ${ghs(r.rate_per_km)}/km</span><span><span class="badge ${r.available ? 'fresh' : 'spoiled'}">${r.available ? 'Available' : 'Busy'}</span></span>`;
    const pct = Math.round((1 - r.distance_km / maxD) * 100);
    box.appendChild(el(`
      <div class="card listing">
        ${i === 0 ? `<span class="badge score">📍 Nearest</span>` : ``}
        <div class="img">${icon}</div>
        <div class="crop">${r.name}</div>
        <div class="price" style="font-size:18px">${r.distance_km} km<span class="muted" style="font-size:13px;font-weight:500"> from ${nearby.origin}</span></div>
        <div style="height:6px;background:#eef2ef;border-radius:6px;overflow:hidden"><div style="height:100%;width:${pct}%;background:var(--green)"></div></div>
        <div class="meta">
          <span>📍 ${r.location}</span>
          ${detail}
          <span class="stars">${stars(r.rating)} <span class="muted">${r.rating} (${r.rating_count})</span></span>
          <span class="muted">📞 ${r.phone}</span>
        </div>
      </div>`));
  });
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
        <div class="img">${x.vehicle.toLowerCase().includes('truck') ? '🚛' : x.vehicle.toLowerCase().includes('pickup') ? '🛻' : '🛺'}</div>
        <div class="crop">${x.name}</div>
        <div class="meta">
          <span>${x.vehicle}</span>
          <span>📦 ${x.capacity_crates} crates capacity</span>
          <span>📍 Based in ${x.location} · ${ghs(x.rate_per_km)}/km</span>
          <span class="stars">${stars(x.rating)} <span class="muted">${x.rating} (${x.rating_count})</span></span>
          <span><span class="badge ${x.available ? 'fresh' : 'spoiled'}">${x.available ? 'Available' : 'Busy'}</span></span>
        </div>
      </div>`).join("")}</div>`;
}

// ---------------------------------------------------------------- notifications
async function renderNotifs(v) {
  v.innerHTML = `<p class="muted">Loading…</p>`;
  const n = await api("/api/notifications");
  v.innerHTML = `<div class="section-title">Activity feed — SMS sent to farmers/drivers & in-app buyer alerts</div>
    <div class="card">${n.length ? n.map(x => `
      <div class="notif">
        <span class="chan ${x.channel}">${x.channel === 'SMS' ? '✉ SMS' : '🔔 APP'}</span>
        <div><div class="msg">${x.message}</div><div class="who">→ ${x.recipient}</div></div>
      </div>`).join("") : '<div class="empty">No activity yet.</div>'}</div>`;
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

function renderRegForm() {
  const locOpts = state.meta.locations.map(l => `<option>${l}</option>`).join("");
  const box = $("#regForm");
  if (regRole === "farmer") {
    box.innerHTML = `<div class="section-title" style="margin-top:14px">👨‍🌾 Farmer details</div>
      <div class="form" style="max-width:100%">
        <label>Full name</label><input id="rName" placeholder="e.g. Kojo Asante">
        <label>Phone</label><input id="rPhone" placeholder="024…">
        <label>Location</label><select id="rLoc">${locOpts}</select>
        <button class="btn" id="rSubmit">Register farmer</button>
      </div>`;
    $("#rSubmit").onclick = () => submitReg("/api/farmers",
      { name: val("rName"), phone: val("rPhone"), location: val("rLoc"), verified: 1 }, "Farmer");
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
        <label>Location</label><select id="rLoc">${locOpts}</select>
        <button class="btn" id="rSubmit">Register ${ROLES[regRole].label.toLowerCase()}</button>
      </div>`;
    $("#rSubmit").onclick = () => submitReg("/api/buyers",
      { name: val("rName"), phone: val("rPhone"), type: val("rType"), role: regRole, location: val("rLoc") },
      ROLES[regRole].label, true);
  } else if (regRole === "transport") {
    box.innerHTML = `<div class="section-title" style="margin-top:14px">🚚 Transport owner details</div>
      <div class="form" style="max-width:100%">
        <label>Provider name</label><input id="rName" placeholder="e.g. Sika Cargo">
        <label>Phone</label><input id="rPhone" placeholder="027…">
        <label>Vehicle</label><select id="rVeh"><option>Cargo tricycle (aboboyaa)</option><option>Pickup truck</option><option>Cargo truck</option></select>
        <label>Capacity (crates)</label><input id="rCap" type="number" value="80">
        <label>Location</label><select id="rLoc">${locOpts}</select>
        <label>Rate per km (GHS)</label><input id="rRate" type="number" step="0.1" value="2.5">
        <button class="btn" id="rSubmit">Register transport</button>
      </div>`;
    $("#rSubmit").onclick = () => submitReg("/api/transport",
      { name: val("rName"), phone: val("rPhone"), vehicle: val("rVeh"),
        capacity_crates: val("rCap"), location: val("rLoc"), rate_per_km: val("rRate") }, "Transport");
  }
}

const val = (id) => $("#" + id).value;
async function submitReg(endpoint, body, label, refreshActors) {
  if (!body.name || !body.phone) return toast("Name and phone are required");
  const r = await post(endpoint, body);
  if (r.error) return toast("Error: " + r.error);
  if (refreshActors) { state.buyers = await api("/api/buyers"); fillActorSelect(); }
  toast(`${label} registered ✓` + (refreshActors ? " (now selectable up top)" : ""));
  ["rName", "rPhone"].forEach(id => { const e = $("#" + id); if (e) e.value = ""; });
}

boot();
