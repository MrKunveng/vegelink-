"""VegeLink database layer — SQLite (stdlib only).

Schema covers farmers, buyers, transport providers, produce listings,
orders (with MoMo escrow states), ratings and an SMS/notification log.
"""
import sqlite3
import os
import time
import math
import hashlib
import secrets

# DB_PATH is overridable so a persistent disk (e.g. a Render Disk) can be
# mounted and pointed at via the env var instead of the ephemeral repo dir.
DB_PATH = os.environ.get(
    "DB_PATH", os.path.join(os.path.dirname(__file__), "vegelink.db"))

# --- Geography: locations along the Akumadan -> Techiman tomato corridor,
#     plus major buyer cities. (lat, lon) used for haversine distance. ---
LOCATIONS = {
    "Akumadan":   (7.4000, -1.9500),
    "Tuobodom":   (7.6333, -1.9667),
    "Techiman":   (7.5833, -1.9333),
    "Offinso":    (6.9167, -1.6667),
    "Nkenkaasu":  (7.2500, -1.9000),
    "Kumasi":     (6.6885, -1.6244),
    "Accra":      (5.6037, -0.1870),
    "Tamale":     (9.4075, -0.8533),
}

# --- Perishability: default shelf life (hours) from harvest for each crop. ---
SHELF_LIFE_HOURS = {
    # Vegetables
    "Tomatoes":      96,    # ~4 days
    "Peppers":       168,   # ~7 days
    "Garden Eggs":   144,   # ~6 days
    "Okra":          72,    # ~3 days
    "Leafy Greens":  48,    # ~2 days (kontomire/ayoyo etc.)
    # Perishable fruits
    "Avocado":       120,   # ~5 days (ripe pear)
    "Mango":         120,   # ~5 days
    "Pawpaw":        96,    # ~4 days (papaya)
    "Pineapple":     192,   # ~8 days
    "Watermelon":    240,   # ~10 days
}

# Emoji used for listings created without an explicit image.
CROP_EMOJI = {
    "Tomatoes": "🍅", "Peppers": "🌶️", "Garden Eggs": "🍆", "Okra": "🌿",
    "Leafy Greens": "🥬", "Avocado": "🥑", "Mango": "🥭", "Pawpaw": "🍈",
    "Pineapple": "🍍", "Watermelon": "🍉",
}

CROPS = list(SHELF_LIFE_HOURS.keys())

# --- Payment methods. COD is collected on delivery (no escrow); the rest are
#     held in escrow and released to the farmer on delivery confirmation. ---
PAYMENT_LABELS = {
    "momo": "Mobile Money",
    "bank": "Bank Transfer",
    "card": "Card",
    "cod":  "Cash on Delivery",
}


def haversine_km(a, b):
    """Great-circle distance in km between two (lat, lon) tuples."""
    if a is None or b is None:
        return 9999.0
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(h)), 1)


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL + a busy timeout let the threaded server handle concurrent writers
    # without intermittent "database is locked" errors.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    location TEXT NOT NULL,
    lat REAL,                         -- captured GPS (falls back to town centroid)
    lng REAL,
    pin_hash TEXT,                    -- PBKDF2 of the login PIN
    pin_salt TEXT,
    verified INTEGER DEFAULT 0,
    rating REAL DEFAULT 0,
    rating_count INTEGER DEFAULT 0,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS buyers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    type TEXT,            -- restaurant / processor / household / exporter / wholesaler
    role TEXT DEFAULT 'buyer',   -- buyer / retailer  (both purchase from farmers)
    location TEXT NOT NULL,
    lat REAL,
    lng REAL,
    pin_hash TEXT,
    pin_salt TEXT,
    rating REAL DEFAULT 0,
    rating_count INTEGER DEFAULT 0,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS transport (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    vehicle TEXT,         -- cargo tricycle (aboboyaa) / pickup / truck
    capacity_crates INTEGER,
    location TEXT NOT NULL,
    lat REAL,
    lng REAL,
    pin_hash TEXT,
    pin_salt TEXT,
    rate_per_km REAL,
    available INTEGER DEFAULT 1,
    rating REAL DEFAULT 0,
    rating_count INTEGER DEFAULT 0,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_id INTEGER NOT NULL,
    crop TEXT NOT NULL,
    quantity INTEGER NOT NULL,        -- crates available
    unit TEXT DEFAULT 'crate',
    price REAL NOT NULL,              -- GHS per crate
    location TEXT NOT NULL,
    harvested_at INTEGER,             -- epoch seconds
    image TEXT,                       -- emoji placeholder OR data: URL of an uploaded photo
    status TEXT DEFAULT 'active',     -- active / sold_out / unavailable
    created_at INTEGER,
    FOREIGN KEY (farmer_id) REFERENCES farmers(id)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    buyer_id INTEGER NOT NULL,
    farmer_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    produce_total REAL NOT NULL,
    transport_id INTEGER,
    transport_cost REAL DEFAULT 0,
    distance_km REAL DEFAULT 0,
    eta_minutes INTEGER DEFAULT 0,
    transport_status TEXT DEFAULT 'none',   -- none / proposed / accepted / rejected
    pickup_at INTEGER,                      -- scheduled pickup time (epoch seconds)
    total REAL NOT NULL,
    payment_method TEXT DEFAULT 'momo',     -- momo / bank / card / cod
    payment_status TEXT DEFAULT 'pending',  -- pending / held / released / cod_pending / paid / refunded
    payment_ref TEXT,                       -- gateway transaction reference
    status TEXT DEFAULT 'placed',           -- placed / matched / picked_up / delivered / completed
    buyer_rated INTEGER DEFAULT 0,
    farmer_rated INTEGER DEFAULT 0,
    transport_rated INTEGER DEFAULT 0,
    created_at INTEGER,
    delivered_at INTEGER,
    FOREIGN KEY (listing_id) REFERENCES listings(id)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT,        -- SMS / app
    recipient TEXT,      -- phone or role label (display)
    owner_kind TEXT,     -- account this notification belongs to (inbox routing)
    owner_id INTEGER,
    message TEXT,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread TEXT NOT NULL,          -- canonical key grouping the two parties (+ optional order)
    order_id INTEGER,             -- optional: message is about a specific order
    listing_id INTEGER,           -- optional: message is about a specific listing
    from_kind TEXT NOT NULL,      -- farmer / buyer / retailer / transport
    from_id INTEGER NOT NULL,
    from_name TEXT,
    to_kind TEXT NOT NULL,
    to_id INTEGER NOT NULL,
    to_name TEXT,
    body TEXT NOT NULL,
    read INTEGER DEFAULT 0,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_kind TEXT NOT NULL,    -- farmer / buyer / retailer / transport
    target_id INTEGER NOT NULL,
    author_kind TEXT,
    author_id INTEGER,
    author_name TEXT,
    order_id INTEGER,
    stars REAL NOT NULL,
    body TEXT,                    -- free-text review (optional)
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    kind TEXT NOT NULL,           -- farmer / buyer / retailer / transport
    account_id INTEGER NOT NULL,
    created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_listings_farmer ON listings(farmer_id);
CREATE INDEX IF NOT EXISTS idx_orders_buyer ON orders(buyer_id);
CREATE INDEX IF NOT EXISTS idx_orders_farmer ON orders(farmer_id);
CREATE INDEX IF NOT EXISTS idx_orders_transport ON orders(transport_id);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread);
CREATE INDEX IF NOT EXISTS idx_reviews_target ON reviews(target_kind, target_id);
CREATE INDEX IF NOT EXISTS idx_notifs_owner ON notifications(owner_kind, owner_id);
"""


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# ---------- Authentication (phone + PIN) ----------

def make_pin(pin):
    """Return (hash_hex, salt_hex) for a PIN using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_hex(16)
    return _pin_hash(pin, salt), salt


def _pin_hash(pin, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", str(pin).encode(), bytes.fromhex(salt), 100_000).hex()


def verify_pin(pin, pin_hash, pin_salt):
    if not pin_hash or not pin_salt:
        return False
    return secrets.compare_digest(_pin_hash(pin, pin_salt), pin_hash)


# ---------- Payment gateway seam ----------
# initiate_payment / verify_payment are the single integration point for a real
# Mobile Money gateway (e.g. Paystack, Hubtel, MTN MoMo). With no API key
# configured they run in SIMULATED mode and return a deterministic mock ref so
# the full escrow workflow is demoable offline; set PAYMENT_API_KEY (and swap in
# the provider's HTTP call below) to go live without touching the callers.

PAYMENT_PROVIDER = os.environ.get("PAYMENT_PROVIDER", "simulated")
PAYMENT_API_KEY = os.environ.get("PAYMENT_API_KEY", "")


def initiate_payment(method, amount, phone):
    """Begin collecting `amount` from `phone` via `method`.
    Returns (ref, status) where status is 'held' (escrow funded) for online
    methods or 'cod_pending' for cash on delivery."""
    if method == "cod":
        return (f"COD-{secrets.token_hex(4).upper()}", "cod_pending")
    ref = f"VL-{secrets.token_hex(6).upper()}"
    if PAYMENT_PROVIDER != "simulated" and PAYMENT_API_KEY:
        # Live integration point — replace with the provider's charge call, e.g.:
        #   resp = _http_post(provider_url, {...}, key=PAYMENT_API_KEY)
        #   return resp["reference"], "held" if resp["status"] == "success" else "pending"
        raise RuntimeError("Live payment provider configured but not wired in.")
    return (ref, "held")  # simulated: funds immediately escrowed


def verify_payment(ref):
    """Confirm a previously initiated payment cleared. Simulated -> always True."""
    if PAYMENT_PROVIDER != "simulated" and PAYMENT_API_KEY:
        raise RuntimeError("Live payment provider configured but not wired in.")
    return True


def log_notification(conn, channel, recipient, message, owner_kind=None, owner_id=None):
    conn.execute(
        "INSERT INTO notifications (channel, recipient, owner_kind, owner_id, message, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (channel, recipient, owner_kind, owner_id, message, int(time.time())),
    )
    # SMS notifications are also pushed to the real gateway when configured;
    # otherwise they live only in the activity feed (simulated).
    if channel == "SMS":
        try:
            import notify
            notify.send_sms(recipient, message)
        except Exception:
            pass


# ---------- Sessions (bearer tokens) ----------

SESSION_TTL = 7 * 24 * 3600  # sessions valid for 7 days, then must re-login


def create_session(conn, kind, account_id):
    token = secrets.token_urlsafe(24)
    conn.execute(
        "INSERT INTO sessions (token, kind, account_id, created_at) VALUES (?,?,?,?)",
        (token, kind, account_id, int(time.time())))
    return token


def get_session(conn, token):
    if not token:
        return None
    row = conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
    if not row:
        return None
    if int(time.time()) - (row["created_at"] or 0) > SESSION_TTL:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))  # expire on read
        conn.commit()
        return None
    return row


def delete_session(conn, token):
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))


def thread_key(a_kind, a_id, b_kind, b_id, order_id=None):
    """Canonical, order-aware key so the same two parties share one thread."""
    ends = sorted([f"{a_kind}#{a_id}", f"{b_kind}#{b_id}"])
    base = "|".join(ends)
    return f"{base}@{order_id}" if order_id else base


# ---------- Smart matching / perishability helpers ----------

def shelf_life_for(crop):
    return SHELF_LIFE_HOURS.get(crop, 96)


def hours_remaining(crop, harvested_at):
    """Hours of shelf life left for a listing (can go negative = spoiled)."""
    total = shelf_life_for(crop)
    elapsed = (time.time() - (harvested_at or time.time())) / 3600.0
    return round(total - elapsed, 1)


def urgency_score(crop, harvested_at):
    """0..1 — higher means closer to spoiling (should be sold/moved first)."""
    total = shelf_life_for(crop)
    rem = hours_remaining(crop, harvested_at)
    if rem <= 0:
        return 1.0
    return round(max(0.0, min(1.0, 1.0 - (rem / total))), 3)


def freshness_label(crop, harvested_at):
    rem = hours_remaining(crop, harvested_at)
    if rem <= 0:
        return ("Spoiled", "spoiled")
    if rem <= 24:
        return (f"Sell within {int(rem)}h", "urgent")
    if rem <= 48:
        return (f"~{int(rem)}h fresh", "soon")
    return (f"~{int(rem/24)}d fresh", "fresh")


def smart_score(listing_row, buyer_location):
    """Rank score for buyer discovery: urgency-weighted + proximity.

    Prioritises produce about to spoil (cuts post-harvest loss) and that is
    near the buyer (cheaper, faster delivery -> less spoilage in transit).
    """
    urg = urgency_score(listing_row["crop"], listing_row["harvested_at"])
    dist = haversine_km(LOCATIONS.get(listing_row["location"]),
                        LOCATIONS.get(buyer_location))
    # proximity 1.0 (same place) -> ~0 far away; 300km reference
    prox = max(0.0, 1.0 - min(dist, 300) / 300.0)
    score = 0.6 * urg + 0.4 * prox
    return round(score, 4), urg, dist


def estimate_transport(from_loc, to_loc, rate_per_km):
    """Distance, cost (GHS) and ETA (minutes) for a delivery leg."""
    dist = haversine_km(LOCATIONS.get(from_loc), LOCATIONS.get(to_loc))
    cost = round(max(15.0, dist * (rate_per_km or 2.5)), 2)
    eta = int(max(20, dist / 45.0 * 60))  # avg 45 km/h on Ghanaian roads
    return dist, cost, eta
