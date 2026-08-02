from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from google.transit import gtfs_realtime_pb2
from datetime import datetime
import time
import csv
import io

app = Flask(__name__)
CORS(app)

# Simplify long direction labels to match MTA app style
LABEL_SIMPLIFY = {
    "Euclid - Lefferts - Rockaways":            "Queens",
    "Euclid - Lefferts - Rockaways - Coney Island": "Brooklyn/Queens",
    "Lefferts - Rockaways":                     "Queens",
    "Uptown & The Bronx":                       "Uptown",
    "Uptown & Queens":                          "Uptown",
    "Uptown - Queens":                          "Uptown",
    "Uptown & The Bronx - Queens":              "Uptown",
    "Downtown & Brooklyn":                      "Downtown",
    "Coney Island - Bay Ridge":                 "Brooklyn",
    "Brighton Beach & Coney Island":            "Brooklyn",
    "Bay Ridge - 95 St":                        "Bay Ridge",
    "Astoria - Ditmars Blvd":                   "Astoria",
    "Jamaica - Middle Village":                 "Jamaica",
    "Broad St (JZ) - Uptown (M)":               "Uptown",
    "Canarsie - Rockaway Parkway":              "Canarsie",
    "Manhattan & Franklin Av":                  "Manhattan",
    "Manhattan - Church Av":                    "Manhattan",
    "Manhattan - Queens":                       "Manhattan",
    "Euclid Av & Queens - Court Sq":            "Queens",
    "Forest Hills - Jamaica":                   "Queens",
    "Church Av - Coney Island":                 "Brooklyn",
    "Flatbush - New Lots":                      "Brooklyn",
    "Flatbush - Utica - New Lots":              "Brooklyn",
    "Flatbush - Utica":                         "Brooklyn",
    "Woodlawn - Eastchester Dyre Av":           "Bronx",
    "Wakefield - Eastchester":                  "Bronx",
    "Wakefield - 241 St":                       "Wakefield",
    "Eastchester - Dyre Av":                    "Eastchester",
    "Norwood - 205 St":                         "Norwood",
    "Bedford Pk Blvd & 205 St":                 "Norwood",
    "Pelham Bay Park":                          "Pelham Bay",
    "34 St - Hudson Yards":                     "Hudson Yards",
    "Astoria - Flushing":                       "Queens",
}

def simplify_label(label):
    return LABEL_SIMPLIFY.get(label, label)

# Load direction labels from MTA Stations.csv at startup
DIRECTION_LABELS = {}  # stop_id -> {"N": label, "S": label}
try:
    r = requests.get("http://web.mta.info/developers/data/nyct/subway/Stations.csv", timeout=10)
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        stop_id = row["GTFS Stop ID"].strip()
        n_label = simplify_label(row.get("North Direction Label", "").strip())
        s_label = simplify_label(row.get("South Direction Label", "").strip())
        if stop_id:
            DIRECTION_LABELS[stop_id] = {"N": n_label, "S": s_label}
except Exception:
    pass

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

    dir_labels = DIRECTION_LABELS.get(stop, {})
    directions = []
    for d in ("N", "S"):
        arr = arrivals[d]
        label = dir_labels.get(d, "").strip()
        if not label:
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


@app.route("/dodgers")
def get_dodgers():
    try:
        sched = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule"
            "?teamId=119&sportId=1&gameType=R&hydrate=linescore,team",
            timeout=10
        ).json()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    months = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    game = None
    lad_home = False
    for date_obj in reversed(sched.get("dates", [])):
        for g in reversed(date_obj.get("games", [])):
            status = g.get("status", {}).get("abstractGameState", "")
            if status not in ("Final", "Live"):
                continue
            home_abbr = g["teams"]["home"]["team"]["abbreviation"]
            away_abbr = g["teams"]["away"]["team"]["abbreviation"]
            lad_home = (home_abbr == "LAD")
            opp_abbr = away_abbr if lad_home else home_abbr
            lad_score = g["teams"]["home"]["score"] if lad_home else g["teams"]["away"]["score"]
            opp_score = g["teams"]["away"]["score"] if lad_home else g["teams"]["home"]["score"]
            ls = g.get("linescore", {})
            lad_side = "home" if lad_home else "away"
            opp_side = "away" if lad_home else "home"
            lad_h = ls.get("teams", {}).get(lad_side, {}).get("hits", 0)
            lad_e = ls.get("teams", {}).get(lad_side, {}).get("errors", 0)
            opp_h = ls.get("teams", {}).get(opp_side, {}).get("hits", 0)
            opp_e = ls.get("teams", {}).get(opp_side, {}).get("errors", 0)
            dt = date_obj["date"]
            mo, day = int(dt[5:7]), int(dt[8:10])
            game = {
                "gamePk": g["gamePk"],
                "status": status.upper(),
                "date": f"{months[mo]} {day}",
                "oppAbbr": opp_abbr,
                "ladScore": lad_score,
                "oppScore": opp_score,
                "ladH": lad_h, "ladE": lad_e,
                "oppH": opp_h, "oppE": opp_e,
                "ladHome": lad_home,
            }
            break
        if game:
            break

    if not game:
        return jsonify({"error": "no recent game"}), 404

    # Fetch boxscore for K, LOB, OBP, performers
    try:
        bs = requests.get(
            f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/boxscore",
            timeout=10
        ).json()
        lad_key = "home" if lad_home else "away"
        opp_key = "away" if lad_home else "home"
        teams = bs.get("teams", {})

        def team_stat(side, field):
            return teams.get(side, {}).get("teamStats", {}).get("batting", {}).get(field, 0)

        game["ladK"]   = team_stat(lad_key, "strikeOuts")
        game["ladLOB"] = team_stat(lad_key, "leftOnBase")
        game["ladOPS"] = teams.get(lad_key, {}).get("teamStats", {}).get("batting", {}).get("ops", "")
        game["oppK"]   = team_stat(opp_key, "strikeOuts")
        game["oppLOB"] = team_stat(opp_key, "leftOnBase")
        game["oppOPS"] = teams.get(opp_key, {}).get("teamStats", {}).get("batting", {}).get("ops", "")

        # Top 2 LAD batters by hits, tiebreak RBI
        batters = teams.get(lad_key, {}).get("batters", [])
        players = teams.get(lad_key, {}).get("players", {})
        top = []
        for pid in batters:
            p = players.get(f"ID{pid}", {})
            s = p.get("stats", {}).get("batting", {})
            h = s.get("hits", 0)
            if h == 0:
                continue
            full = p.get("person", {}).get("fullName", "")
            sp = full.find(" ")
            name = (full[0] + ". " + full[sp+1:]) if sp > 0 else p.get("person", {}).get("boxscoreName", "?")
            ab  = s.get("atBats", 0)
            rbi = s.get("rbi", 0)
            hr  = s.get("homeRuns", 0)
            db  = s.get("doubles", 0)
            tr  = s.get("triples", 0)
            line = f"{h}-{ab}"
            if hr: line += " HR"
            if tr: line += " 3B"
            if db: line += " 2B"
            if rbi: line += f" {rbi}RBI"
            top.append({"name": name, "h": h, "rbi": rbi, "line": line})
        top.sort(key=lambda x: (x["h"], x["rbi"]), reverse=True)
        if len(top) > 0:
            game["star1Name"] = top[0]["name"]
            game["star1Line"] = top[0]["line"]
        if len(top) > 1:
            game["star2Name"] = top[1]["name"]
            game["star2Line"] = top[1]["line"]

        # Winning pitcher
        for side in ("home", "away"):
            for pid in teams.get(side, {}).get("pitchers", []):
                p = teams[side]["players"].get(f"ID{pid}", {})
                if p.get("stats", {}).get("pitching", {}).get("wins", 0) > 0:
                    ip = p["stats"]["pitching"].get("inningsPitched", "")
                    er = p["stats"]["pitching"].get("earnedRuns", "")
                    name = p.get("person", {}).get("boxscoreName", "?")
                    game["winPitcher"] = f"W: {name} {ip}IP {er}ER"
                    break
            if "winPitcher" in game:
                break
    except Exception:
        pass  # team stats and performers are best-effort

    return jsonify(game)


# In-memory store for the surf_board pairing handoff: a device shows a
# short code + a link to a hosted map picker; the picker POSTs the chosen
# spot here; the device polls GET until it sees its code claimed. No
# database on purpose — if this process restarts, pending pairings are
# lost and the device just never finds its code, so the user reloads the
# device's page for a fresh one. Same "tolerate failure, retry" pattern as
# everything else this proxy already does (MTA feed fetch failures, etc).
PICKUP_TTL_SECONDS = 600
pickups = {}  # code (str) -> {"lat": float, "lon": float, "name": str, "expires": float}


def _prune_expired_pickups():
    now = time.time()
    expired = [c for c, v in pickups.items() if v["expires"] < now]
    for c in expired:
        del pickups[c]


@app.route("/pickup", methods=["POST"])
def post_pickup():
    data = request.get_json(silent=True) or {}
    code = str(data.get("code", "")).strip()
    lat = data.get("lat")
    lon = data.get("lon")
    name = data.get("name", "")

    if not code or lat is None or lon is None:
        return jsonify({"error": "Missing required fields: code, lat, lon"}), 400

    _prune_expired_pickups()
    pickups[code] = {
        "lat": float(lat),
        "lon": float(lon),
        "name": str(name)[:64],
        "expires": time.time() + PICKUP_TTL_SECONDS,
    }
    return jsonify({"ok": True})


@app.route("/pickup", methods=["GET"])
def get_pickup():
    code = request.args.get("code", "").strip()
    if not code:
        return jsonify({"error": "Missing required param: code"}), 400

    _prune_expired_pickups()
    entry = pickups.get(code)
    if not entry:
        return jsonify({"claimed": False})

    return jsonify({
        "claimed": True,
        "lat": entry["lat"],
        "lon": entry["lon"],
        "name": entry["name"],
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
