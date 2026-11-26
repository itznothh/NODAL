import argparse
import os
import random
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

# Description templates per category
TEMPLATES = {
    "pothole": [
        "Huge pothole on the main road near {place}",
        "Deep pothole causing accidents near {place}",
        "Road surface damaged with large crater at {place}",
        "Potholes everywhere, two-wheelers skidding near {place}",
        "Broken road and pothole filled with water at {place}",
    ],
    "garbage": [
        "Garbage piled up and not collected near {place}",
        "Overflowing dustbin with foul smell at {place}",
        "Trash dumped on the roadside near {place}",
        "Waste not cleared for a week at {place}",
        "Illegal garbage dumping spot near {place}",
    ],
    "drainage": [
        "Blocked drain overflowing onto the road near {place}",
        "Sewage water flooding the street at {place}",
        "Clogged stormwater drain near {place}",
        "Open manhole and drainage overflow at {place}",
    ],
    "streetlight": [
        "Streetlight not working near {place}, area is dark",
        "Broken street lamp at {place}",
        "Street lights off for many days near {place}",
        "Flickering streetlight is unsafe at night near {place}",
    ],
    "water_leak": [
        "Water pipe leaking and wasting water near {place}",
        "Burst water main flooding road at {place}",
        "Continuous water leakage from pipeline at {place}",
        "Drinking water pipe broken near {place}",
    ],
}

HIGH_WORDS = ["accident", "overflowing", "flooding", "burst", "open manhole", "unsafe", "skidding"]

# (name, lat, lng) cluster centres: these become your hotspots
HOTSPOTS = [
    ("Silk Board", 12.9177, 77.6233),
    ("Majestic", 12.9767, 77.5713),
    ("Indiranagar", 12.9784, 77.6408),
    ("Whitefield", 12.9698, 77.7500),
]


def priority_for(text):
    t = text.lower()
    return "high" if any(w in t for w in HIGH_WORDS) else random.choice(["low", "medium", "medium"])


def make_doc(place, lat, lng):
    category = random.choice(list(TEMPLATES))
    description = random.choice(TEMPLATES[category]).format(place=place)
    return {
        "description": description,
        "category": category,
        "priority": priority_for(description),
        "status": random.choice(["open", "open", "in_progress", "resolved"]),
        "location": {"type": "Point", "coordinates": [lng, lat]},
        "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(0, 30)),
    }


def validate_seed_target(database_argument, environ):
    """Refuse implicit, mismatched, or production database targets."""
    target = database_argument.strip() if isinstance(database_argument, str) else ""
    configured = environ.get("NODAL_DB_NAME", "").strip()
    mongo_uri = environ.get("MONGO_URI", "").strip()
    if not target:
        raise ValueError("Pass an explicit --database target.")
    if target.casefold() == "nodal":
        raise ValueError("The destructive seed script refuses the production database 'nodal'.")
    if not configured:
        raise ValueError("NODAL_DB_NAME must be explicitly configured.")
    if configured != target:
        raise ValueError("--database must exactly match NODAL_DB_NAME.")
    if not mongo_uri:
        raise ValueError("MONGO_URI must be explicitly configured.")
    return target, mongo_uri


def generate_docs():
    docs = []
    # 30 complaints tightly packed around each hotspot (about 200 m spread).
    for name, lat, lng in HOTSPOTS:
        for _ in range(30):
            docs.append(make_doc(name, lat + random.gauss(0, 0.0012), lng + random.gauss(0, 0.0012)))
    # 30 scattered complaints across the city (noise).
    for _ in range(30):
        docs.append(make_doc("a nearby junction", random.uniform(12.88, 13.05), random.uniform(77.52, 77.76)))
    return docs


def main(argv=None, input_fn=input):
    load_dotenv()
    parser = argparse.ArgumentParser(description="Destructively replace complaints with synthetic development fixtures.")
    parser.add_argument("--database", required=True, help="Non-production database; must match NODAL_DB_NAME")
    args = parser.parse_args(argv)
    try:
        database_name, mongo_uri = validate_seed_target(args.database, os.environ)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"WARNING: this deletes every existing complaint in database '{database_name}'.")
    confirmation = f"DELETE ALL COMPLAINTS IN {database_name}"
    if input_fn(f"Type exactly '{confirmation}' to continue: ").strip() != confirmation:
        raise SystemExit("Destructive confirmation did not match; no data was changed.")
    docs = generate_docs()
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        complaints = client[database_name]["complaints"]
        complaints.delete_many({})
        complaints.insert_many(docs)
        print(f"Inserted {len(docs)} synthetic complaints into {database_name}.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
