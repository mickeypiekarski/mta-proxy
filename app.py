from flask import Flask, jsonify
import requests
from google.transit import gtfs_realtime_pb2
from datetime import datetime
import time

app = Flask(__name__)

MTA_FEED_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g"
GREENPOINT_STOP_ID = "G26S"  # Southbound

@app.route("/")
def get_trains():
    try:
        response = requests.get(MTA_FEED_URL)
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        
        now = time.time()
        arrivals = []
        
        for entity in feed.entity:
            if entity.HasField("trip_update"):
                for stop in entity.trip_update.stop_time_update:
                    if stop.stop_id == GREENPOINT_STOP_ID:
                        arr_time = stop.arrival.time
                        mins = int((arr_time - now) / 60)
                        if mins >= 0:
                            arrivals.append(mins)
        
        arrivals.sort()
        return jsonify({
            "stop": "Greenpoint G (Southbound)",
            "arrivals": arrivals[:5],
            "updated": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
