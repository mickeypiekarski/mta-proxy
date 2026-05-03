from flask import Flask, jsonify, request
import requests
from google.transit import gtfs_realtime_pb2
from datetime import datetime
import time
import zipfile
import io
import csv
from collections import defaultdict

app = Flask(__name__)

FEED_URLS = {
    "ace":    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
    "bdfm":   "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
    "g":      "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",
    "jz":     "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",
    "nqrw":   "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
    "l":      "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",
    "123456": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
    "7":      "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-7",
    "sir":    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si",
}

TERMINAL_NAMES = {
    "G08N": "Court Sq",       "G22S": "Church Av",
    "A02N": "Inwood-207 St",  "H11N": "Far Rockaway",
    "H21N": "Rockaway Park",  "A65S": "Lefferts Blvd",
    "A55S": "Euclid Av",      "G05N": "Jamaica-179 St",
    "A27S": "World Trade Ctr",
    "D01N": "Norwood-205 St", "D43S": "Coney Island",
    "F01N": "Jamaica-179 St", "F35S": "Coney Island",
    "M01N": "Forest Hills",   "M22S": "Middle Village",
    "J12N": "Jamaica Ctr",    "J17S": "Broad St",
    "L01N": "8 Av",           "L29S": "Canarsie",
    "R01N": "Astoria",        "N10S": "Coney Island",
    "R44S": "Bay Ridge-95 St","R27S": "Whitehall St",
    "101N": "Van Cortlandt",  "142S": "South Ferry",
    "201N": "Wakefield",      "239S": "Flatbush Av",
    "301N": "Harlem-148 St",  "L24S": "New Lots Av",
    "401N": "Woodlawn",       "420S": "Bowling Green",
    "501N": "Eastchester",    "S03S": "Flatbush Av",
    "601N": "Pelham Bay",     "640S": "Brooklyn Bridge",
    "701N": "Flushing-Main St","726S": "Hudson Yards",
    "S01N": "St George",      "S31S": "Tottenville",
}

STATIC_GTFS_URL = "http://web.mta.info/developers/data/nyct/subway/google_transit.zip"

# stop_id (base, no N/S) -> sorted list of route letters
# e.g. {"A31": ["A", "C", "E"], "G10": ["G"], ...}
STOP_ROUTES = {}

def load_static_gtfs():
    """
    Download MTA static GTFS zip and build a stop_id -> [routes] map.
    MTA stop IDs in static GTFS include the N/S suffix, so we strip it.
    We use stop_times.txt + trips.txt to map stop -> route.
    """
    global STOP_ROUTES
    print("Downloading static GTFS...")
    try:
        resp = requests.get(STATIC_GTFS_URL, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to download static GTFS: {e}")
        return

    try:
        z = zipfile.ZipFile(io.BytesIO(resp.content))

        # Build trip_id -> route_id from trips.txt
        trip_route = {}
        with z.open("trips.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f))
            for row in reader:
                trip_route[row["trip_id"]] = row["route_id"].strip()

        # Build base_stop_id -> set of route_ids from stop_times.txt
        stop_routes_set = defaultdict(set)
        with z.open("stop_times.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f))
            for row in reader:
                trip_id = row["trip_id"]
                stop_id = row["stop_id"].strip()
                # Strip N/S suffix to get base stop ID
                base = stop_id[:-1] if stop_id and stop_id[-1] in ("N", "S") else stop_id
                route = trip_route.get(trip_id, "")
                if route:
                    stop_routes_set[base].add(route)

        # Convert sets to sorted lists
        STOP_ROUTES = {k: sorted(v) for k, v in stop_routes_set.items()}
        print(f"Static GTFS loaded: {len(STOP_ROUTES)} stops mapped.")

    except Exception as e:
        print(f"Failed to parse static GTFS: {e}")


# Load on startup
load_static_gtfs()


def get_arrivals_for_stop(feed_id, stop_id_base):
    feed_url = FEED_URLS.get(feed_id.lower())
    if not feed_url:
        return None, f"Unknown feed: {feed_id}"

    try:
        response = requests.get(feed_url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return None, str(e)

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

    now = time.time()
    arrivals = {"N": [], "S": []}
    stop_n = stop_id_base + "N"
    stop_s = stop_id_base + "S"

    trip_last_stop = {}
    for entity in feed.entity:
        if entity.HasField("trip_update"):
            stops = entity.trip_update.stop_time_update
            if stops:
                trip_last_stop[entity.trip_update.trip.trip_id] = stops[-1].stop_id

    for entity in feed.entity:
        if entity.HasField("trip_update"):
            trip = entity.trip_update.trip
            route = trip.route_id.strip() or "?"
            last_stop = trip_last_stop.get(trip.trip_id, "")
            terminal = TERMINAL_NAMES.get(last_stop, last_stop)

            for stop in entity.trip_update.stop_time_update:
                if stop.stop_id in (stop_n, stop_s):
                    t = stop.arrival.time if stop.arrival.time else stop.departure.time
                    mins = int((t - now) / 60)
                    if mins >= 0:
                        d = "N" if stop.stop_id == stop_n else "S"
                        arrivals[d].append({
                            "mins": mins,
                            "route": route,
                            "terminal": terminal
                        })

    for d in ("N", "S"):
        arrivals[d].sort(key=lambda x: x["mins"])
        arrivals[d] = arrivals[d][:5]

    return arrivals, None


@app.route("/arrivals")
def get_arrivals():
    stop = request.args.get("stop", "").strip().upper()
    feed = request.args.get("feed", "").strip().lower()

    if not stop or not feed:
        return jsonify({"error": "Missing required params: stop and feed"}), 400

    arrivals, err = get_arrivals_for_stop(feed, stop)
    if err:
        return jsonify({"error": err}), 500

    # Get all possible routes for this stop from static GTFS
    possible_routes = STOP_ROUTES.get(stop, [])

    # Also collect routes seen in live data (in case static is stale)
    live_routes = set()
    for d in ("N", "S"):
        for a in arrivals[d]:
            live_routes.add(a["route"])

    # Merge and sort
    all_routes = sorted(set(possible_routes) | live_routes)

    directions = []
    for d in ("N", "S"):
        arr = arrivals[d]
        label = arr[0]["terminal"] if arr else ("Northbound" if d == "N" else "Southbound")
        directions.append({
            "label": label,
            "arrivals": [{"mins": a["mins"], "route": a["route"]} for a in arr],
            "possible_routes": all_routes
        })

    return jsonify({
        "stop": stop,
        "feed": feed,
        "directions": directions,
        "updated": datetime.now().isoformat()
    })


@app.route("/routes")
def get_routes():
    """Return all possible routes for a stop, from static GTFS."""
    stop = request.args.get("stop", "").strip().upper()
    if not stop:
        return jsonify({"error": "Missing param: stop"}), 400
    routes = STOP_ROUTES.get(stop, [])
    return jsonify({"stop": stop, "routes": routes})


# Legacy endpoint
@app.route("/")
def get_trains_legacy():
    arrivals, err = get_arrivals_for_stop("g", "G26")
    if err:
        return jsonify({"error": err}), 500
    return jsonify({
        "stop": "Greenpoint G (Legacy)",
        "arrivals": [a["mins"] for a in arrivals["S"]],
        "updated": datetime.now().isoformat()
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
