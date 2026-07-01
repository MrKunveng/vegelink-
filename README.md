# 🥬 VegeLink

**Farmer-to-Buyer digital marketplace for perishable vegetables & fruits — Bono supply corridor (Akumadan → Techiman).**
Built for the GDSS-PSInno AgriTech Innovation Challenge.

Connects feature-phone smallholder farmers to verified buyers over **USSD**, auto-matches
**transport**, secures payment in **Mobile Money escrow**, and uses **shelf-life-aware smart
matching** to cut post-harvest loss. Covers vegetables (tomatoes, peppers, garden eggs, okra,
leafy greens) and perishable fruits (avocado, mango, pawpaw, pineapple, watermelon).

## Run it (zero dependencies)

Requires only **Python 3** (uses the standard library — no pip install, no internet, no CDN).

```bash
cd vegelink
./run.sh                 # serves http://localhost:8000
./run.sh --reset         # reset demo data first, then serve
```

Then open **http://localhost:8000** in a browser.

**Log in** with phone + 4-digit PIN. All seeded demo accounts use PIN **`1234`**, e.g.
`0241000001` (farmer), `0551000001` (buyer), `0271000002` (transport).

## Deploy to Render.com

The app already reads the `$PORT` env var and binds `0.0.0.0`, so it runs on Render as-is.
Deploy files are included: `render.yaml`, `requirements.txt` (stdlib only), `.gitignore`.

**Important:** Render builds from a repo root, so push the **`vegelink/` folder itself** as the
repository (so `server.py` and `render.yaml` sit at the repo root).

### Option A — Blueprint (one click)
1. Create a new GitHub repo and push the contents of this `vegelink/` folder to it:
   ```bash
   cd vegelink
   git init && git add . && git commit -m "VegeLink"
   git branch -M main
   git remote add origin https://github.com/<you>/vegelink.git
   git push -u origin main
   ```
2. On Render: **New +** → **Blueprint** → select the repo. Render reads `render.yaml` and
   creates the web service automatically. Click **Apply**.

### Option B — Manual web service
1. Push the repo as above.
2. On Render: **New +** → **Web Service** → connect the repo, then set:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python server.py`
   - **Health Check Path:** `/api/health`
   - (If you pushed the whole project instead of just `vegelink/`, set **Root Directory** to `vegelink`.)
3. Create the service. Render gives you a public `https://vegelink-xxxx.onrender.com` URL.

### Notes
- **Data is ephemeral.** Render's free disk resets on each deploy/restart, so the app re-seeds
  clean demo data on startup (`server.py` seeds if the DB file is missing). Perfect for a demo;
  for persistent data, attach a Render Disk and point `DB_PATH` at it.
- **Free tier sleeps** after ~15 min idle; the first request after waking takes a few seconds.

## What's inside

| File | Role |
|---|---|
| `server.py` | HTTP server: REST API + static frontend + USSD endpoint |
| `db.py` | SQLite schema, geography/distance, shelf-life & smart-match scoring, PIN auth & payment seam |
| `ussd.py` | USSD menu engine (Africa's Talking `CON`/`END` compatible) |
| `notify.py` | Pluggable SMS sender (Africa's Talking live, else simulated) |
| `seed.py` | Demo data for the tomato corridor |
| `static/` | Single-page web app (vanilla JS + custom CSS, no build step) |

## Features (mapped to the challenge rubric)

- **Accessibility / offline (bonus):** USSD-first farmer onboarding + listing — works on any
  feature phone, no internet. On-screen emulator hits the *same* `/api/ussd` endpoint the real
  Africa's Talking gateway calls.
- **Smart matching (bonus):** listings ranked by spoilage **urgency** + **proximity** to buyer.
- **Accounts / auth:** phone + **PIN** login (PBKDF2-hashed) issuing a **bearer-token session**;
  every state-changing API enforces authentication + **ownership** (you can only act on your own
  orders/listings, release your own escrow, message as yourself). Register as farmer, buyer,
  retailer or transport owner, with optional **GPS capture**.
- **Role-based UI:** each role sees only the tabs it needs; logged-out visitors get a
  "I'm a Farmer / Buyer / Transport" landing, and plain-language copy (no GMV/escrow jargon).
- **Bilingual USSD:** English **and Twi** menus, chosen on first dial — built for low-literacy
  feature-phone farmers.
- **Marketplace:** search/filter by crop, location, **price and minimum quantity**; smart /
  urgency / price sort.
- **Farmer tools (Sell tab):** create listings with a **real uploaded photo**, edit price,
  update stock, or mark produce unavailable.
- **Logistics:** **proximity-aware** transport auto-matching (prefers the nearest suitable
  vehicle; tricycle local, truck long-haul), cost + ETA estimation. Providers **accept/decline**
  jobs and **schedule pickup**; declines auto-rematch the next vehicle. Pickup/drop-off
  notifications. A live **offline delivery map** tracks farm → buyer per order.
- **Messaging:** in-app **buyer ↔ farmer ↔ transport** conversations, threaded per order/contact.
- **Geolocation:** offline **inline map** (no tiles/CDN) plotting nearby actors by real coords.
- **Payments / trust:** Mobile Money **escrow** via a pluggable gateway seam (held → released on
  delivery confirmation, with transaction refs), verified profiles, two-way **ratings + written
  reviews**.
- **Impact dashboard:** GMV, escrow held, and estimated **produce value rescued from spoilage**.

### Going live (optional integrations)
The app runs fully **simulated/offline** by default. Set env vars to switch on real services
without touching app code — SMS via `SMS_PROVIDER=africastalking` (+ `AT_USERNAME`, `AT_API_KEY`);
payments via `PAYMENT_PROVIDER` + `PAYMENT_API_KEY` (seam in `db.initiate_payment`); persistence
via `DB_PATH` pointed at a mounted disk.

## API quick reference

`POST /api/login` · `POST /api/logout` · `GET /api/listings?sort=smart&minqty=10&buyer_location=Accra` ·
`POST /api/listings/:id/update` · `POST /api/orders` · `POST /api/orders/:id/status` ·
`POST /api/orders/:id/transport-response` · `POST /api/orders/:id/confirm-delivery` ·
`POST /api/orders/:id/rate` · `GET/POST /api/messages` · `GET /api/reviews` ·
`GET /api/nearby` · `GET /api/dashboard` · `GET /api/export.csv` · `POST /api/ussd`

Authenticated requests pass `Authorization: Bearer <token>` (returned by `/api/login`).
State-changing endpoints derive the actor from the token and enforce ownership.

## Security & testing

- **Auth:** PBKDF2 phone+PIN, bearer-token sessions with a 7-day TTL, per-phone login
  rate-limiting (brute-force protection), ownership enforced on every mutating route.
- **XSS defence-in-depth:** all user-controlled strings escaped on render; uploaded images
  validated against a strict base64 data-URL regex (server + client); a **Content-Security-Policy**
  (`script-src 'self'`, no inline handlers) plus `X-Frame-Options`, `X-Content-Type-Options`.
- **Integrity:** atomic stock claim (no overselling), one-rating-per-party (no review gaming),
  positive-price/quantity validation, idempotent delivery confirmation.
- **Tests:** `./run.sh test` (stdlib `unittest`) — domain math, auth, oversell guard, escrow
  release, rating idempotency, and the USSD flow, driven over real HTTP.

### Impact methodology
"Produce value saved from waste" is **not** a flat % of sales. Each *delivered* lot is credited by
how close to spoiling it was when sold (from its crop shelf-life via `urgency_score`), scaled by
Ghana's 20–50% post-harvest-loss midpoint (35%) — so fresh lots count little and near-spoiling
rescues count most. The dashboard also leads with **near-spoiling lots rescued** and **time-to-sale**.

## Demo path (≈3 min)

1. **Farmer USSD** tab → press SEND → `1` → list produce on the feature phone.
2. **Marketplace** tab → see smart-ranked listings (urgent tomatoes float to top) → **Order now**.
3. Pay → **MoMo escrow held**. **Orders** tab → mark picked up → delivered → **confirm** → escrow released.
4. **Activity** tab → SMS trail. **Dashboard** → impact numbers.
