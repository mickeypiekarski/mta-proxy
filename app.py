from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from google.transit import gtfs_realtime_pb2
from datetime import datetime
import time

app = Flask(__name__)
CORS(app)

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
    "G08N": "Court Sq",        "G22S": "Church Av",
    # A/C/E terminals
    # A/C/E
    "A02N": "Inwood-207 St",
    "A09N": "168 St",
    "A55S": "Euclid Av",
    "A65S": "Ozone Park-Lefferts Blvd",
    "E01S": "World Trade Center",
    "G05S": "Jamaica Center",
    "H11S": "Far Rockaway",
    "H15S": "Rockaway Park",
    # B/D/F/M
    "D01N": "Norwood-205 St",
    "D43S": "Coney Island",
    "F01N": "Jamaica-179 St",
    "F39S": "Coney Island",
    "M01N": "Forest Hills-71 Av",
    "M22S": "Middle Village-Metropolitan Av",
    # G
    "G22N": "Court Sq",
    "F27S": "Church Av",
    # J/Z
    "J12N": "Jamaica Center",
    "M23S": "Broad St",
    # L
    "L01N": "8 Av",
    "L29S": "Canarsie",
    # N/Q/R/W
    "R01N": "Astoria-Ditmars Blvd",
    "R27S": "Whitehall St",
    "R45S": "Bay Ridge-95 St",
    "N10S": "Coney Island",
    "Q05N": "96 St",
    # 1
    "101N": "Van Cortlandt Park-242 St",
    "142S": "South Ferry",
    # 2
    "201N": "Wakefield-241 St",
    "247S": "Flatbush Av",
    # 3
    "301N": "Harlem-148 St",
    "257S": "New Lots Av",
    # 4
    "401N": "Woodlawn",
    "640S": "Brooklyn Bridge-City Hall",
    # 5
    "501N": "Eastchester-Dyre Av",
    # 6
    "601N": "Pelham Bay Park",
    # 7
    "701N": "Flushing-Main St",
    "726S": "34 St-Hudson Yards",
    # S shuttles
    "901N": "Grand Central",
    "902S": "Times Sq",
    "S01N": "St George",
    "S31S": "Tottenville",
}


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
    stop_n = stop_id_base + "N"
    stop_s = stop_id_base + "S"
    arrivals = {"N": [], "S": []}

    # First pass: map trip_id -> terminal stop_id
    trip_last_stop = {}
    for entity in feed.entity:
        if entity.HasField("trip_update"):
            stops = entity.trip_update.stop_time_update
            if stops:
                trip_last_stop[entity.trip_update.trip.trip_id] = stops[-1].stop_id

    # Second pass: find arrivals at this stop
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        trip = entity.trip_update.trip
        route = trip.route_id.strip() or "?"

        for stop in entity.trip_update.stop_time_update:
            if stop.stop_id not in (stop_n, stop_s):
                continue
            t = stop.arrival.time if stop.arrival.time else stop.departure.time
            if not t:
                continue
            mins = int((t - now) / 60)
            if mins < 0:
                continue

            direction = "N" if stop.stop_id == stop_n else "S"
            last_stop = trip_last_stop.get(trip.trip_id, "")
            terminal = TERMINAL_NAMES.get(last_stop, last_stop)
            arrivals[direction].append({
                "mins": mins,
                "route": route,
                "terminal": terminal,
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

    directions = []
    for d in ("N", "S"):
        arr = arrivals[d]
        label = arr[0]["terminal"] if arr else ("Northbound" if d == "N" else "Southbound")
        directions.append({
            "label": label,
            "arrivals": [{"mins": a["mins"], "route": a["route"], "terminal": a["terminal"]} for a in arr],
        })

    return jsonify({
        "stop": stop,
        "feed": feed,
        "directions": directions,
        "updated": datetime.now().isoformat(),
    })


# Legacy endpoint
@app.route("/")
def get_trains_legacy():
    arrivals, err = get_arrivals_for_stop("g", "G26")
    if err:
        return jsonify({"error": err}), 500
    return jsonify({
        "stop": "Greenpoint G (Legacy)",
        "arrivals": [a["mins"] for a in arrivals["S"]],
        "updated": datetime.now().isoformat(),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
