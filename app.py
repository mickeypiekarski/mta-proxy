from flask import Flask, jsonify, request
import requests
from google.transit import gtfs_realtime_pb2
from datetime import datetime
import time

app = Flask(__name__)

# MTA GTFS-RT feed URLs by feed ID
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

def get_arrivals_for_stop(feed_id, stop_id_base):
    """
    Fetch arrivals for both directions of a stop.
    stop_id_base: e.g. "G26" (without N/S suffix)
    Returns dict with "N" and "S" lists of minutes.
    """
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

    for entity in feed.entity:
        if entity.HasField("trip_update"):
            for stop in entity.trip_update.stop_time_update:
                if stop.stop_id in (stop_n, stop_s):
                    arr_time = stop.arrival.time if stop.arrival.time else stop.departure.time
                    mins = int((arr_time - now) / 60)
                    if mins >= 0:
                        direction = "N" if stop.stop_id == stop_n else "S"
                        arrivals[direction].append(mins)

    arrivals["N"].sort()
    arrivals["S"].sort()
    arrivals["N"] = arrivals["N"][:5]
    arrivals["S"] = arrivals["S"][:5]

    return arrivals, None


@app.route("/arrivals")
def get_arrivals():
    """
    Query params:
      stop  - stop ID base, e.g. "G26" (required)
      feed  - feed ID, e.g. "g", "ace", "bdfm" (required)

    Example: /arrivals?stop=G26&feed=g
    """
    stop = request.args.get("stop", "").strip().upper()
    feed = request.args.get("feed", "").strip().lower()

    if not stop or not feed:
        return jsonify({"error": "Missing required params: stop and feed"}), 400

    arrivals, err = get_arrivals_for_stop(feed, stop)
    if err:
        return jsonify({"error": err}), 500

    return jsonify({
        "stop": stop,
        "feed": feed,
        "northbound": arrivals["N"],
        "southbound": arrivals["S"],
        "updated": datetime.now().isoformat()
    })


# Legacy endpoint — keep working for backward compat
@app.route("/")
def get_trains_legacy():
    arrivals, err = get_arrivals_for_stop("g", "G26")
    if err:
        return jsonify({"error": err}), 500
    return jsonify({
        "stop": "Greenpoint G (Legacy)",
        "arrivals": arrivals["S"],
        "updated": datetime.now().isoformat()
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
