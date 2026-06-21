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
| `db.py` | SQLite schema, geography/distance, shelf-life & smart-match scoring |
| `ussd.py` | USSD menu engine (Africa's Talking `CON`/`END` compatible) |
| `seed.py` | Demo data for the tomato corridor |
| `static/` | Single-page web app (vanilla JS + custom CSS, no build step) |

## Features (mapped to the challenge rubric)

- **Accessibility / offline (bonus):** USSD-first farmer onboarding + listing — works on any
  feature phone, no internet. On-screen emulator hits the *same* `/api/ussd` endpoint the real
  Africa's Talking gateway calls.
- **Smart matching (bonus):** listings ranked by spoilage **urgency** + **proximity** to buyer.
- **Marketplace:** search/filter by crop, location, price; smart / urgency / price sort.
- **Logistics:** distance-aware transport auto-matching (tricycle local, truck long-haul),
  cost + ETA estimation, delivery status timeline, pickup/drop-off notifications.
- **Payments / trust:** Mobile Money **escrow** (held → released on delivery confirmation),
  verified profiles, two-way **ratings**.
- **Impact dashboard:** GMV, escrow held, and estimated **produce value rescued from spoilage**.

## API quick reference

`GET /api/listings?sort=smart&buyer_location=Accra` · `POST /api/orders` ·
`POST /api/orders/:id/status` · `POST /api/orders/:id/confirm-delivery` ·
`POST /api/orders/:id/rate` · `GET /api/dashboard` · `POST /api/ussd`

## Demo path (≈3 min)

1. **Farmer USSD** tab → press SEND → `1` → list produce on the feature phone.
2. **Marketplace** tab → see smart-ranked listings (urgent tomatoes float to top) → **Order now**.
3. Pay → **MoMo escrow held**. **Orders** tab → mark picked up → delivered → **confirm** → escrow released.
4. **Activity** tab → SMS trail. **Dashboard** → impact numbers.
