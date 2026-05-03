from flask import Flask, jsonify, request
import requests
from google.transit import gtfs_realtime_pb2
from datetime import datetime
import time

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
    "G08N": "Court Sq",        "G22S": "Church Av",
    # A/C/E terminals
    "A02N": "Inwood-207 St",   "A02S": "Inwood-207 St",
    "A09N": "168 St",          "A09S": "168 St",
    "A55S": "Euclid Av",       "A65S": "Lefferts Blvd",
    "A27S": "World Trade Ctr", "E01S": "World Trade Ctr",
    "H11N": "Far Rockaway",    "H11S": "Far Rockaway",
    "H15N": "Rockaway Park",   "H15S": "Rockaway Park",
    "H21N": "Rockaway Park",   "H21S": "Rockaway Park",
    "G05N": "Jamaica Ctr",     "G05S": "Jamaica Ctr",
    # B/D/F/M terminals
    "D01N": "Norwood-205 St",  "D43S": "Coney Island",
    "F01N": "Jamaica-179 St",  "F39S": "Coney Island",
    "F35S": "Coney Island",
    "B08N": "Lexington Av/63 St",
    # G terminal
    "G08N": "Court Sq",        "G08S": "Court Sq",
    "G22S": "Church Av",       "G22N": "Church Av",
    # M terminals
    "M01N": "Forest Hills",    "M01S": "Forest Hills",
    "M22S": "Middle Village",  "M22N": "Middle Village",
    # J/Z terminals
    "J12N": "Jamaica Ctr",     "J17S": "Broad St",
    # L terminals
    "L01N": "8 Av",            "L01S": "8 Av",
    "L29S": "Canarsie",        "L29N": "Canarsie",
    # N/Q/R/W terminals
    "R01N": "Astoria",         "R01S": "Astoria",
    "R44S": "Bay Ridge-95 St", "R27S": "Whitehall St",
    "N10S": "Coney Island",    "D43S": "Coney Island",
    "Q03S": "72 St",           "Q05N": "96 St",
    # 1/2/3 terminals
    "101N": "Van Cortlandt",   "142S": "South Ferry",
    "201N": "Wakefield",       "239S": "Flatbush Av",
    "301N": "Harlem-148 St",   "247S": "Flatbush Av",
    # 4/5/6 terminals
    "401N": "Woodlawn",        "420S": "Bowling Green",
    "501N": "Eastchester",     "640S": "Brooklyn Bridge",
    "601N": "Pelham Bay",      "423S": "Borough Hall",
    # 7 terminals
    "701N": "Flushing-Main St","726S": "Hudson Yards",
    "701S": "Flushing-Main St","726N": "Hudson Yards",
    # 3 train
    "257S": "New Lots Av",     "257N": "New Lots Av",
    # L
    "L24S": "New Lots Av",
    # 2/5 shared
    "S03S": "Flatbush Av",
    # SIR
    "S01N": "St George",       "S31S": "Tottenville",
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
            "arrivals": [{"mins": a["mins"], "route": a["route"]} for a in arr],
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
