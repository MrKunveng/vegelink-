"""VegeLink database layer — SQLite (stdlib only).

Schema covers farmers, buyers, transport providers, produce listings,
orders (with MoMo escrow states), ratings and an SMS/notification log.
"""
import sqlite3
import os
import time
import math

DB_PATH = os.path.join(os.path.dirname(__file__), "vegelink.db")

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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    location TEXT NOT NULL,
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
    image TEXT,                       -- emoji / placeholder
    status TEXT DEFAULT 'active',     -- active / sold_out
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
    total REAL NOT NULL,
    payment_method TEXT DEFAULT 'momo',     -- momo / bank / card / cod
    payment_status TEXT DEFAULT 'pending',  -- pending / held / released / cod_pending / paid / refunded
    status TEXT DEFAULT 'placed',           -- placed / matched / picked_up / delivered / completed
    buyer_rated INTEGER DEFAULT 0,
    farmer_rated INTEGER DEFAULT 0,
    created_at INTEGER,
    delivered_at INTEGER,
    FOREIGN KEY (listing_id) REFERENCES listings(id)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT,        -- SMS / app
    recipient TEXT,      -- phone or role label
    message TEXT,
    created_at INTEGER
);
"""


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def log_notification(conn, channel, recipient, message):
    conn.execute(
        "INSERT INTO notifications (channel, recipient, message, created_at) VALUES (?,?,?,?)",
        (channel, recipient, message, int(time.time())),
    )


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
