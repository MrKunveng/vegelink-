"""Seed VegeLink with demo data for the Akumadan->Techiman tomato corridor.

Run directly (`python3 seed.py`) to reset the database to a clean demo state.
Every demo account logs in with phone + PIN  ****1234****.
"""
import os
import time

import db

DEMO_PIN = "1234"  # all seeded accounts share this PIN for an easy demo login


def _coords(location):
    """Town centroid as the stand-in GPS fix for seeded accounts."""
    lat, lng = db.LOCATIONS.get(location, (None, None))
    return lat, lng


def reset():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()
    conn = db.connect()
    now = int(time.time())
    H = 3600
    pin_hash, pin_salt = db.make_pin(DEMO_PIN)

    farmers = [
        # name, phone, location, verified, rating, rating_count
        ("Kwame Mensah",     "0241000001", "Akumadan",  1, 4.7, 23),
        ("Adwoa Boateng",    "0241000002", "Tuobodom",  1, 4.5, 14),
        ("Yaw Owusu",        "0241000003", "Nkenkaasu", 0, 4.2, 6),
        ("Abena Sarpong",    "0241000004", "Offinso",   1, 4.8, 31),
        ("Lukman Kunveng",   "0249111001", "Tamale",    1, 4.7, 9),   # Lukman — Farmer
    ]
    for (name, phone, loc, verified, rating, rc) in farmers:
        lat, lng = _coords(loc)
        conn.execute(
            "INSERT INTO farmers (name,phone,location,lat,lng,pin_hash,pin_salt,"
            "verified,rating,rating_count,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (name, phone, loc, lat, lng, pin_hash, pin_salt, verified, rating, rc, now))

    # buyers table holds both 'buyer' and 'retailer' roles (both purchase from farmers)
    buyers = [
        # name, phone, type, role, location, rating, rating_count
        ("Maa Akosua's Kitchen", "0551000001", "restaurant", "buyer",    "Accra",    4.6, 12),
        ("GreenLeaf Processors", "0551000003", "processor",  "buyer",    "Techiman", 4.9, 19),
        ("Lukman Kunveng",       "0249111002", "wholesaler", "buyer",    "Tamale",   4.5, 7),  # Lukman — Buyer
        ("Kumasi Central Retail","0551000002", "retailer",   "retailer", "Kumasi",   4.3, 8),
        ("Lukman Kunveng",       "0249111003", "retailer",   "retailer", "Tamale",   4.6, 5),  # Lukman — Retailer
    ]
    for (name, phone, typ, role, loc, rating, rc) in buyers:
        lat, lng = _coords(loc)
        conn.execute(
            "INSERT INTO buyers (name,phone,type,role,location,lat,lng,pin_hash,pin_salt,"
            "rating,rating_count,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, phone, typ, role, loc, lat, lng, pin_hash, pin_salt, rating, rc, now))

    transport = [
        # name, phone, vehicle, capacity, location, rate_per_km, available, rating, rating_count
        ("Yaw Tricycle",   "0271000001", "Cargo tricycle (aboboyaa)", 40,  "Akumadan", 2.0, 1, 4.4, 17),
        ("Kofi Pickup",    "0271000002", "Pickup truck",              80,  "Techiman", 2.8, 1, 4.6, 22),
        ("Adom Cargo Ltd", "0271000003", "Cargo truck",               300, "Kumasi",   3.5, 1, 4.8, 40),
        ("Lukman Kunveng", "0249111004", "Pickup truck",              80,  "Tamale",   2.7, 1, 4.6, 11),  # Lukman — Transport
    ]
    for (name, phone, veh, cap, loc, rate, avail, rating, rc) in transport:
        lat, lng = _coords(loc)
        conn.execute(
            "INSERT INTO transport (name,phone,vehicle,capacity_crates,location,lat,lng,"
            "pin_hash,pin_salt,rate_per_km,available,rating,rating_count,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, phone, veh, cap, loc, lat, lng, pin_hash, pin_salt, rate, avail, rating, rc, now))

    # Listings with varied harvest times so urgency ranking is visible.
    listings = [
        # farmer_id, crop, qty, price, location, harvested_hours_ago, image
        (1, "Tomatoes",     50, 80.0, "Akumadan",  18, "🍅"),  # fresh-ish
        (2, "Tomatoes",     30, 75.0, "Tuobodom",  80, "🍅"),  # URGENT (96h shelf life)
        (3, "Peppers",      25, 120.0,"Nkenkaasu", 20, "🌶️"),
        (4, "Leafy Greens", 40, 35.0, "Offinso",   30, "🥬"),  # URGENT (48h shelf life)
        (1, "Garden Eggs",  35, 60.0, "Akumadan",  12, "🍆"),
        (4, "Okra",         20, 50.0, "Offinso",   10, "🌿"),
        # Perishable fruits
        (3, "Avocado",      40, 90.0, "Nkenkaasu", 100,"🥑"),  # URGENT (120h shelf life)
        (2, "Mango",        60, 70.0, "Tuobodom",  20, "🥭"),
        (1, "Pineapple",    25, 55.0, "Akumadan",  16, "🍍"),
        (4, "Pawpaw",       30, 40.0, "Offinso",   60, "🍈"),  # urgent-ish (96h)
    ]
    for (fid, crop, qty, price, loc, ago, img) in listings:
        conn.execute(
            "INSERT INTO listings (farmer_id,crop,quantity,unit,price,location,harvested_at,"
            "image,status,created_at) VALUES (?,?,?,?,?,?,?,?, 'active', ?)",
            (fid, crop, qty, "crate", price, loc, now - ago * H, img, now))

    # A couple of seeded text reviews so profiles aren't empty.
    reviews = [
        # target_kind, target_id, author_kind, author_id, author_name, stars, body
        ("farmer", 1, "buyer", 1, "Maa Akosua's Kitchen", 5,
         "Tomatoes arrived firm and fresh. Kwame is reliable — will buy again."),
        ("farmer", 4, "buyer", 2, "GreenLeaf Processors", 5,
         "Great leafy greens, well packed. Fast pickup."),
        ("transport", 2, "buyer", 1, "Maa Akosua's Kitchen", 4,
         "Kofi was on time and careful with the crates."),
    ]
    for (tk, tid, ak, aid, an, st, body) in reviews:
        conn.execute(
            "INSERT INTO reviews (target_kind,target_id,author_kind,author_id,author_name,"
            "stars,body,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (tk, tid, ak, aid, an, st, body, now))

    db.log_notification(conn, "app", "system", "VegeLink demo data loaded.")
    conn.commit()
    conn.close()
    print(f"Seeded database at {db.DB_PATH}")
    print(f"  {len(farmers)} farmers, {len(buyers)} buyers, {len(transport)} transport, "
          f"{len(listings)} listings.  Demo login PIN: {DEMO_PIN}")


if __name__ == "__main__":
    reset()
