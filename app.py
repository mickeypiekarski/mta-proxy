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

# Last stop ID -> terminal name
TERMINAL_NAMES = {
    # G
    "G08N": "Court Sq",       "G22S": "Church Av",
    # A/C/E
    "A02N": "Inwood-207 St",  "H11N": "Far Rockaway",
    "H21N": "Rockaway Park",  "A65S": "Lefferts Blvd",
    "A55S": "Euclid Av",      "G05N": "Jamaica-179 St",
    "A27S": "World Trade Ctr",
    # B/D
    "D01N": "Norwood-205 St", "D43S": "Coney Island",
    # F/M
    "F01N": "Jamaica-179 St", "F35S": "Coney Island",
    "M01N": "Forest Hills",   "M22S": "Middle Village",
    # J/Z
    "J12N": "Jamaica Ctr",    "J17S": "Broad St",
    # L
    "L01N": "8 Av",           "L29S": "Canarsie",
    # N/Q/R/W
    "R01N": "Astoria",        "N10S": "Coney Island",
    "R44S": "Bay Ridge-95 St","R27S": "Whitehall St",
    # 1/2/3
    "101N": "Van Cortlandt",  "142S": "South Ferry",
    "201N": "Wakefield",      "239S": "Flatbush Av",
    "301N": "Harlem-148 St",  "L24S": "New Lots Av",
    # 4/5/6
    "401N": "Woodlawn",       "420S": "Bowling Green",
    "501N": "Eastchester",    "S03S": "Flatbush Av",
    "601N": "Pelham Bay",     "640S": "Brooklyn Bridge",
    # 7
    "701N": "Flushing-Main St","726S": "Hudson Yards",
    # SIR
    "S01N": "St George",      "S31S": "Tottenville",
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
    arrivals = {"N": [], "S": []}
    stop_n = stop_id_base + "N"
    stop_s = stop_id_base + "S"

    # Map trip_id -> last stop for terminal lookup
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

    directions = []
    for d in ("N", "S"):
        arr = arrivals[d]
        label = arr[0]["terminal"] if arr else ("Northbound" if d == "N" else "Southbound")
        directions.append({
            "label": label,
            "arrivals": [{"mins": a["mins"], "route": a["route"]} for a in arr]
        })

    return jsonify({
        "stop": stop,
        "feed": feed,
        "directions": directions,
        "updated": datetime.now().isoformat()
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
        "updated": datetime.now().isoformat()
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
