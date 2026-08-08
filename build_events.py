#!/usr/bin/env python3
"""
Builds data/events.json from the 2026 schedule.

Every time field carries a source: "published" (came off the schedule) or
"estimated" (derived from the track's standard pattern). The app shows
estimated times with a tilde so a guessed hot-laps time never gets trusted
like a published one.
"""
import json

# ---- track defaults ------------------------------------------------------
# AS never publishes hot laps anywhere on the schedule. Its green is 19:00 and
# both other tracks run hot laps roughly an hour before green, so 18:00 is the
# working estimate until Dave confirms at the gate.
TRACKS = {
    "AS": {
        "name": "Albany-Saratoga Speedway",
        "short": "Albany-Saratoga",
        "lat": 42.98794, "lon": -73.78403,
        "defaults": {"pits": "15:00", "gates": "17:00", "hotlaps": "18:00", "race": "19:00"},
        "published": ["pits", "gates", "race"],
    },
    "LV": {
        "name": "Lebanon Valley Speedway",
        "short": "Lebanon Valley",
        "lat": 42.49054, "lon": -73.48698,
        "defaults": {"pits": "14:00", "gates": "15:00", "hotlaps": "17:00", "race": "18:00"},
        "published": ["pits", "gates", "hotlaps", "race"],
    },
    "FON": {
        "name": "Fonda Speedway",
        "short": "Fonda",
        "lat": 42.95252, "lon": -74.36631,
        # Fonda only publishes times on a handful of nights and they move.
        # Verified nights this season: 14:00/15:00/17:00/18:00 (Apr 18),
        # 16:00/16:00/17:30/19:00 (Jun 27), 16:00/16:00/18:00/19:00 (Aug 8).
        # Defaulting to the most recent pattern; all four fields estimated.
        "defaults": {"pits": "16:00", "gates": "16:00", "hotlaps": "18:00", "race": "19:00"},
        "published": [],
    },
}

# ---- raw schedule --------------------------------------------------------
# (date, track, title, type, override_times)
# type: race | practice | dark | raindate | offtrack
# override_times: dict of field -> "HH:MM", these are published
R = [
    ("2026-01-01", "FON", "Chill Factor Enduro", "race",
     {"pits": "10:00", "gates": "11:00", "race": "13:00"}),

    ("2026-03-20", "FON", "Fonda Speedway Car Show — Via Port Rotterdam", "offtrack", {}),
    ("2026-03-21", "FON", "Fonda Speedway Car Show — Via Port Rotterdam", "offtrack", {}),
    ("2026-03-22", "FON", "Fonda Speedway Car Show — Via Port Rotterdam", "offtrack", {}),

    ("2026-04-03", "AS", "Early tech inspection", "offtrack", {"gates": "15:00", "race": "19:00"}),
    ("2026-04-04", "LV", "Warm-ups", "practice", {}),
    ("2026-04-10", "AS", "Open practice, any division", "practice", {"gates": "18:00", "race": "22:00"}),
    ("2026-04-11", "FON", "Open practice", "practice",
     {"pits": "13:00", "gates": "13:00", "hotlaps": "15:00"}),
    ("2026-04-11", "LV", "$4,000-to-win Sportsman / $1,000-to-win 4 Cylinder", "race", {}),
    ("2026-04-17", "AS", "61st season opener — Super DIRTcar Series", "race", {}),
    ("2026-04-18", "FON", "Opening day — remembering Jack Johnson (12A)", "race",
     {"pits": "14:00", "gates": "15:00", "hotlaps": "17:00", "race": "18:00"}),
    ("2026-04-18", "LV", "DIRTcar 358 and Sportsman Series", "race", {}),
    ("2026-04-24", "AS", "Regular-season opener — DiCarlo's 358 Modified Shootout", "race", {}),
    ("2026-04-25", "FON", "All divisions plus vintage cars", "race", {}),
    ("2026-04-25", "LV", "Big Block opener", "race", {}),

    ("2026-05-01", "AS", "Sportsman / Twister Pro Stocks / Croteau Street Stocks", "race", {}),
    ("2026-05-02", "FON", "Bill Ag Memorial — Modified elimination races", "race", {}),
    ("2026-05-02", "LV", "Weekly racing + Cannonball", "race", {}),
    ("2026-05-08", "AS", "\u201cHoosier Mama\u201d — DiCarlo's 358 Modified Shootout", "race", {}),
    ("2026-05-09", "FON", "All divisions plus Enduro", "race", {}),
    ("2026-05-09", "LV", "Weekly racing + Vintage Modifieds", "race", {}),
    ("2026-05-15", "AS", "Law Enforcement Night — DIRTcar Pro Stock Series", "race", {}),
    ("2026-05-16", "FON", "Metro Ford Dollar Night", "race", {}),
    ("2026-05-16", "LV", "Weekly racing", "race", {}),
    ("2026-05-20", "LV", "STSS practice", "practice", {}),
    ("2026-05-21", "LV", "Short Track Super Series", "race", {}),
    ("2026-05-22", "AS", "HICO Fabrication Sportsman / Street Stocks", "race", {}),
    ("2026-05-23", "FON", "Memorial Day Spectacular", "race", {}),
    ("2026-05-23", "LV", "Weekly racing + Andrew Sherman Memorial", "race", {}),
    ("2026-05-29", "AS", "DiCarlo's 358 Modified Shootout", "race", {}),
    ("2026-05-30", "FON", "CRSA Sprint Cars", "race", {}),
    ("2026-05-30", "LV", "Weekly racing + Guy Madsen event", "race", {}),

    ("2026-06-05", "AS", "Xtreme DIRTcar DMA Midgets", "race", {}),
    ("2026-06-06", "FON", "Shepherd Communication & Security Night", "race", {}),
    ("2026-06-06", "LV", "Weekly racing + JC Flach Memorial", "race", {}),
    ("2026-06-12", "AS", "SCoNE Sprints", "race", {}),
    ("2026-06-13", "FON", "Legends Night — 75 years of Fonda Speedway", "race", {}),
    ("2026-06-13", "LV", "Weekly racing + Powderpuff & Cannonball", "race", {}),
    ("2026-06-16", "LV", "MR. DIRT TRACK USA", "race", {}),
    ("2026-06-19", "AS", "\u201cHoosier Daddy\u201d — DiCarlo's 358 Modified Shootout", "race", {}),
    ("2026-06-20", "FON", "Parks Companies Night", "race", {}),
    ("2026-06-20", "LV", "Weekly racing + Bobby Chalmers Pro Stock Memorial", "race", {}),
    ("2026-06-26", "AS", "Bonus Bucks / Native Pride Limited Sportsman special", "race", {}),
    ("2026-06-27", "FON", "$5 grandstand admission — meet & greet", "race",
     {"pits": "16:00", "gates": "16:00", "hotlaps": "17:30", "race": "19:00"}),
    ("2026-06-27", "LV", "Weekly racing + George Marcus Memorial", "race", {}),

    ("2026-07-01", "FON", "Firecracker 50", "race", {}),
    ("2026-07-03", "AS", "Fireworks / honoring our military", "race", {}),
    ("2026-07-04", "FON", "No racing", "dark", {}),
    ("2026-07-04", "LV", "Weekly racing + Jason Herrington 358 Memorial + fireworks", "race", {}),
    ("2026-07-10", "AS", "DiCarlo's 358 Modified Shootout", "race", {}),
    ("2026-07-11", "FON", "Modified Twin 20s", "race", {}),
    ("2026-07-11", "LV", "Weekly racing + Twin 20s HC $8,200", "race", {}),
    ("2026-07-14", "LV", "Eve of Destruction", "race", {}),
    ("2026-07-17", "AS", "ESS Sprints", "race", {}),
    ("2026-07-18", "FON", "ESS Sprint Cars", "race", {}),
    ("2026-07-18", "LV", "Weekly racing", "race", {}),
    ("2026-07-24", "AS", "6th annual Stan Da' Man Night", "race", {}),
    ("2026-07-25", "FON", "Autism Awareness Night", "race", {}),
    ("2026-07-25", "LV", "Weekly racing + IVRA Vintage Mod", "race", {}),
    ("2026-07-31", "AS", "A Legacy Laid in Clay — honoring Lyle DeVore", "race", {}),
    ("2026-07-31", "LV", "Monsters & Megas", "race", {}),

    ("2026-08-01", "FON", "Fonda/LV Challenge — Hondo & BOBCO", "race", {}),
    ("2026-08-01", "LV", "Monsters & Megas", "race", {}),
    ("2026-08-07", "AS", "Native Pride Night / SCoNE Sprints", "race", {}),
    ("2026-08-08", "FON", "Doug's Pool and Hot Tub Night", "race",
     {"pits": "16:00", "gates": "16:00", "hotlaps": "18:00", "race": "19:00"}),
    ("2026-08-08", "LV", "Weekly racing", "race", {}),
    ("2026-08-14", "AS", "The Flying Farmer 31", "race", {}),
    ("2026-08-15", "FON", "Benjamin Moore Paints Championship Night", "race", {}),
    ("2026-08-15", "LV", "Weekly racing + Steven LaRochelle Memorial Pro Stock", "race", {}),
    ("2026-08-21", "AS", "Kids giveaway / weekly program", "race", {}),
    ("2026-08-22", "LV", "Weekly racing + Old Buzzard Pro Stock Series", "race", {}),
    ("2026-08-28", "AS", "DiCarlo's 358 Modified Shootout — final DIRTcar points night", "race", {}),

    ("2026-09-04", "AS", "5th Annual Pro Stock Autism Awareness Event / SCoNE Sprints (rescheduled) / all divisions incl. 4 Cylinders", "race", {}),
    ("2026-09-05", "LV", "Final night of points", "race", {}),
    ("2026-09-10", "LV", "Syracuse 200 Reunion practice", "practice", {}),
    ("2026-09-11", "AS", "No racing", "dark", {}),
    ("2026-09-11", "LV", "Syracuse 200 Reunion", "race", {}),
    ("2026-09-12", "LV", "Syracuse 200 Reunion", "race", {}),
    ("2026-09-13", "LV", "Syracuse 200 Reunion — rain date", "raindate", {}),
    ("2026-09-17", "FON", "Fonda 200 weekend — Underdog 33", "race", {}),
    ("2026-09-18", "AS", "Fire & Rescue / EMS Night, Grady Memorial, IVRA Vintage Mod Open", "race", {}),
    ("2026-09-18", "FON", "Fonda 200 weekend — qualifying night", "race", {}),
    ("2026-09-19", "FON", "THE FONDA 200 / Championship Saturday", "race", {}),
    ("2026-09-20", "FON", "2026 awards banquet", "offtrack", {}),
    ("2026-09-25", "AS", "Malta Massive Weekend — opener", "race", {}),
    ("2026-09-26", "AS", "Malta Massive Weekend — finale", "race", {}),

    ("2026-10-10", "FON", "Versus Monster Trucks Epicenter", "race", {}),
]

FIELDS = ["pits", "gates", "hotlaps", "race"]

# What actually happened on nights that didn't go as scheduled. Keyed
# "YYYY-MM-DD|TRACK". Add a line here when a show gets called off and the
# card stops claiming it ran.
RESULTS = {
    "2026-08-07|AS": "rainout",   # SCoNE Sprints moved to Sep 4
}


def build():
    out = []
    for date, code, title, kind, override in R:
        t = TRACKS[code]
        times, source = {}, {}
        if kind in ("race", "practice", "raindate"):
            for f in FIELDS:
                if f in override:
                    times[f] = override[f]
                    source[f] = "published"
                elif kind == "practice":
                    continue  # practice nights get no defaults; too variable
                else:
                    times[f] = t["defaults"][f]
                    source[f] = "published" if f in t["published"] else "estimated"
        entry = {
            "date": date,
            "track": code,
            "title": title,
            "type": kind,
            "times": times,
            "timeSource": source,
        }
        result = RESULTS.get(f"{date}|{code}")
        if result:
            entry["result"] = result
        out.append(entry)

    out.sort(key=lambda e: (e["date"], e["track"]))
    return {
        "season": 2026,
        "home": "Schenectady, NY",
        "tracks": {
            k: {
                "name": v["name"],
                "short": v["short"],
                "lat": v["lat"], "lon": v["lon"],
                "defaults": v["defaults"],
                "publishesHotLaps": "hotlaps" in v["published"],
            } for k, v in TRACKS.items()
        },
        "events": out,
    }


if __name__ == "__main__":
    data = build()
    with open("data/events.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"{len(data['events'])} events written")
