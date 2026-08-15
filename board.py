#!/usr/bin/env python3
"""
board.py — DirtCheck + BathroomReport on a Divoom Pixoo-64.

Four screens, drawn at 64x64 with a built-in pixel font (no font file,
no anti-aliasing):

  flag      track status, or the countdown to the next green flag
  sites     BathroomReport location count and today's scans
  trend     7-day scan sparkline
  queue     FlushPanel moderation backlog

Screens rotate. On Friday and Saturday evenings the flag screen takes
most of the dwell time; the rest of the week it's mostly BathroomReport.

  pip3 install pixoo pillow
  python3 board.py --preview out/    # render PNGs, no device needed
  python3 board.py --once            # push one frame (good for cron)
  python3 board.py --loop            # rotate forever (good for systemd)
"""

import argparse
import datetime as dt
import json
import os
import sys
import time

import requests
from PIL import Image, ImageDraw

from config import (
    PIXOO_IP, LAT, LON, DIRTCHECK_BASE, DATA_DIR,
    JELLYFIN_URL, JELLYFIN_KEY, JELLYFIN_USER,
    DAY_BRIGHTNESS, NIGHT_BRIGHTNESS, NIGHT_START, NIGHT_END,
    MORNING, RACE_DAYS, RACE_WINDOW,
)

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
    "&forecast_days=4"
)
CALENDAR_URL = f"file://{DATA_DIR}/next.json"

# palette — same values as the wall dashboard
LOAM   = (28, 21, 18)
DUST   = (232, 220, 200)
SLATE  = (139, 122, 108)
RAIL   = (58, 44, 37)
SODIUM = (242, 167, 59)
GREEN  = (63, 163, 77)
RED    = (196, 52, 43)
YELLOW = (229, 195, 74)

# BathroomReport's own palette, from its stylesheet. The project screens use
# it so they read as a different place from the track and weather screens.
BR_TEAL  = (46, 161, 170)     # #2ea1aa  PWA theme colour
BR_NAVY  = (11, 25, 42)       # #0b192a  charcoal
BR_CREAM = (245, 247, 250)    # #f5f7fa
BR_MUTED = (147, 165, 184)    # #93a5b8
BR_LINE  = (42, 64, 86)       # #2a4056  panel border
BR_UP    = (143, 214, 148)    # #8fd694
BR_DOWN  = (240, 138, 134)    # #f08a86

# flag states: bar color, bar text color, word
STATES = {
    "racing":  (GREEN,  LOAM,  "RACING"),
    "rained":  (RED,    DUST,  "RAINOUT"),
    "watch":   (YELLOW, LOAM,  "WATCH"),
    "standby": (LOAM,   SLATE, "STANDBY"),
}

DEMO_DIRT = {
    "state": "racing",
    "track": "ALBANY-SARATOGA",
    "town": "MALTA NY",
    "countdown": "2:48",
    "label": "HOT LAPS",
    "rows": [
        {"code": "AS",  "when": "NOW", "state": "racing", "prob": 5},
        {"code": "LV",  "when": "SAT", "state": "dark",   "prob": 2},
        {"code": "FON", "when": "SAT", "state": "dark",   "prob": 2},
    ],
}

DEMO_WX = {
    "temp": 68, "feels": 66, "high": 84, "low": 61,
    "code": 1, "wind": 7, "rain": 20,
    "days": [("SAT", 84, 61), ("SUN", 79, 58), ("MON", 71, 55)],
}

DEMO_CAL = {
    "title": "CREW HUDDLE",
    "where": "ERIE ST SITE",
    "time": "7:30",
    "minutes": 48,
    "more": 3,
}

DEMO_JF = {
    "playing": True, "title": "The Bear", "sub": "S3E5", "user": "Dave",
    "paused": False, "pct": 42, "art_id": None, "transcoding": False,
    "streams": 1, "watchers": 1,
    "movies": 812, "episodes": 6104, "series": 137,
}

DEMO_BATH = {
    "health": ("ok", "CLEAN"), "day": "2026-08-11",
    "users": 3, "sessions": 4, "views": 5, "delta": -1,
    "series": [9, 13, 12, 1, 2, 4, 4],
    "series_days": ["2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08",
                    "2026-08-09", "2026-08-10", "2026-08-11"],
    "new_users": 1, "errors": 0, "dead": 0, "bots": 1,
    "bot_share": 100, "engage": 62, "clarity_day": "2026-08-11",
    "week_sessions": 45, "top_source": "facebook.com", "top_sessions": 8,
    "signups": 1,
}

# ---------------------------------------------------------------- 3x5 font

_GLYPHS = """
A ### #.# ### #.# #.#
B ##. #.# ##. #.# ##.
C ### #.. #.. #.. ###
D ##. #.# #.# #.# ##.
E ### #.. ##. #.. ###
F ### #.. ##. #.. #..
G ### #.. #.# #.# ###
H #.# #.# ### #.# #.#
I ### .#. .#. .#. ###
J ..# ..# ..# #.# ###
K #.# #.# ##. #.# #.#
L #.. #.. #.. #.. ###
M #..# #### #### #..# #..#
N #..# ##.# #.## #..# #..#
O ### #.# #.# #.# ###
P ### #.# ### #.. #..
Q ### #.# #.# ### ..#
R ### #.# ##. #.# #.#
S ### #.. ### ..# ###
T ### .#. .#. .#. .#.
U #.# #.# #.# #.# ###
V #.# #.# #.# #.# .#.
W #..# #..# #### #### #..#
X #.# #.# .#. #.# #.#
Y #.# #.# .#. .#. .#.
Z ### ..# .#. #.. ###
0 ### #.# #.# #.# ###
1 .#. ##. .#. .#. ###
2 ### ..# ### #.. ###
3 ### ..# ### ..# ###
4 #.# #.# ### ..# ..#
5 ### #.. ### ..# ###
6 ### #.. ### #.# ###
7 ### ..# ..# ..# ..#
8 ### #.# ### #.# ###
9 ### #.# ### ..# ###
- ... ... ### ... ...
. ... ... ... ... .#.
, ... ... ... .#. #..
: ... .#. ... .#. ...
/ ..# ..# .#. #.. #..
! .#. .#. .#. ... .#.
% #.# ..# .#. #.. #.#
+ ... .#. ### .#. ...
° ##. #.# ##. ... ...
"""

FONT = {}
for _line in _GLYPHS.strip().splitlines():
    _ch, *_rows = _line.split(" ")
    FONT[_ch] = _rows
FONT[" "] = ["..."] * 5

GH = 5                 # every glyph is 5 rows; width varies (M/N/W are 4)
GAP = 1


def glyph(ch):
    return FONT.get(ch, FONT[" "])


def text_width(s, scale):
    if not s:
        return 0
    return (sum(len(glyph(c)[0]) + GAP for c in s.upper()) - GAP) * scale


def text_height(scale):
    return GH * scale


def draw_text(d, s, x, y, color, scale=1):
    cx = x
    for ch in s.upper():
        rows = glyph(ch)
        for ry, row in enumerate(rows):
            for rx, cell in enumerate(row):
                if cell == "#":
                    px, py = cx + rx * scale, y + ry * scale
                    d.rectangle([px, py, px + scale - 1, py + scale - 1], fill=color)
        cx += (len(rows[0]) + GAP) * scale


def draw_centered(d, s, y, color, scale=1, width=64):
    draw_text(d, s, (width - text_width(s, scale)) // 2, y, color, scale)


def fit_scale(s, max_scale, width=64, pad=2):
    for sc in range(max_scale, 0, -1):
        if text_width(s, sc) <= width - pad * 2:
            return sc
    return 1


def commas(n):
    return f"{n:,}"


# ---------------------------------------------------------------- sprites

# 11x11, drawn on the same grid as the font so they sit level with the type
SPRITES = {
"CLEAR": """
.....#.....
.#...#...#.
..#.....#..
....###....
...#####...
#..#####..#
...#####...
....###....
..#.....#..
.#...#...#.
.....#.....""",
"CLOUDY": """
...........
...........
....###....
..##...##..
.#.......#.
#.........#
#.........#
.#########.
...........
...........
...........""",
"RAIN": """
...........
....###....
..##...##..
.#.......#.
#.........#
.#########.
...........
..#..#..#..
.#..#..#...
..#..#..#..
.#..#..#...""",
"SNOW": """
...........
....###....
..##...##..
.#.......#.
#.........#
.#########.
...........
..#.#.#.#..
...#.#.#...
..#.#.#.#..
...........""",
"STORMS": """
...........
....###....
..##...##..
.#.......#.
#.........#
.#########.
.....###...
....##.....
...#####...
.....##....
....#......""",
}
SPRITE_W = 11


def draw_sprite(d, key, x, y, color):
    rows = SPRITES[key].strip("\n").split("\n")
    for ry, row in enumerate(rows):
        for rx, c in enumerate(row):
            if c == "#":
                d.point((x + rx, y + ry), fill=color)


# ---------------------------------------------------------------- chrome

BAR_H = 16
LABEL_Y = 58

# bar text is drawn at one fixed scale so it never jitters between screens
BAR_SCALE = 2


def draw_bar(d, color, text, text_color, rule=False):
    d.rectangle([0, 0, 63, BAR_H], fill=color)
    if rule:
        d.line([0, BAR_H, 63, BAR_H], fill=SLATE)
    sc = min(BAR_SCALE, fit_scale(text, BAR_SCALE, pad=1))
    draw_centered(d, text, (BAR_H - text_height(sc)) // 2 + 1, text_color, sc)


def queue_bar(bath):
    """The bar always answers 'is there something happening'. On project
    screens that's whether the nightly analytics bake is healthy."""
    kind, word = bath["health"]
    if kind == "bad":
        return RED, DUST, word
    if kind == "stale":
        return YELLOW, LOAM, word
    return GREEN, LOAM, word


# WMO weather codes, collapsed to words short enough for the bar
def wx_word(code):
    """Four buckets. A wall board doesn't need drizzle-versus-showers; it
    needs to know whether water is falling."""
    if code in (0, 1):
        return "CLEAR"
    if code in (2, 3) or code in (45, 48):
        return "CLOUDY"
    if 71 <= code <= 77 or code in (85, 86):
        return "SNOW"
    if code >= 95:
        return "STORMS"
    if code >= 51:
        return "RAIN"
    return "CLEAR"


def wx_bar(wx):
    """Same question as every other bar: is something happening. Here that's
    whether the sky is about to interfere with anything."""
    word = wx_word(wx["code"])
    wet = wx["code"] >= 51
    if wet:
        return RED, DUST, word
    if wx["rain"] >= 50:
        return YELLOW, LOAM, word
    return GREEN, LOAM, word


def cal_bar(cal):
    if cal["minutes"] is None:
        return LOAM, SLATE, "CLEAR"
    if cal["minutes"] <= 60:
        return SODIUM, LOAM, f"IN {cal['minutes']}M"
    return LOAM, SLATE, "NEXT UP"


def clock_str(now=None):
    now = now or dt.datetime.now()
    h = now.hour % 12 or 12
    return f"{h}:{now.minute:02d}"


def draw_footer(d, label):
    """Bottom row: clock hard left, context hard right. The clock is the same
    on every screen, so it reads as chrome rather than data. If the label
    won't fit alongside it, the label gets trimmed — the time always wins."""
    t = clock_str()
    draw_text(d, t, 2, LABEL_Y, SLATE, 1)

    avail = 62 - (2 + text_width(t, 1) + 4)
    if text_width(label, 1) > avail and " " in label:
        while label and text_width(label, 1) > avail:   # shed whole words first
            label = label[:label.rfind(" ")] if " " in label else ""
    while label and text_width(label, 1) > avail:
        label = label[:-1].rstrip(" ,.")
    if label:
        draw_text(d, label, 62 - text_width(label, 1), LABEL_Y, SLATE, 1)


def stack(d, title, sub, big, label, big_color=DUST, title_scale_max=2):
    """The shared layout: title, subtitle, one big number, one footer.
    Positions are computed so nothing ever collides."""
    y = BAR_H + 5
    tsc = fit_scale(title, title_scale_max)
    draw_centered(d, title, y, DUST, tsc)
    y += text_height(tsc) + 3
    draw_centered(d, sub, y, SLATE, 1)
    y += text_height(1)

    sc = fit_scale(big, 4)
    top, bottom = y + 2, LABEL_Y - 2
    draw_centered(d, big, top + (bottom - top - text_height(sc)) // 2, big_color, sc)

    draw_footer(d, label)


def canvas():
    img = Image.new("RGB", (64, 64), LOAM)
    return img, ImageDraw.Draw(img)


# ---------------------------------------------------------------- project screens

BR_COL_W = 24        # usable width per column, keeps digits off the divider


def br_canvas():
    img = Image.new("RGB", (64, 64), BR_NAVY)
    return img, ImageDraw.Draw(img)


def br_bar(d, color, word):
    d.rectangle([0, 0, 63, BAR_H], fill=color)
    sc = min(BAR_SCALE, fit_scale(word, BAR_SCALE))
    draw_centered(d, word, (BAR_H - text_height(sc)) // 2 + 1, BR_NAVY, sc)


def br_pair(d, left, right):
    """Two labelled numbers either side of a rule. Both take the same scale so
    they read as a pair rather than one long number."""
    d.line([32, 20, 32, 55], fill=BR_LINE)

    def fits(v):
        for sc in range(4, 0, -1):
            if text_width(v, sc) <= BR_COL_W:
                return sc
        return 1

    vals = [str(left[1]), str(right[1])]
    nsc = min(fits(v) for v in vals)
    y = 28 + (20 - text_height(nsc)) // 2
    for (label, _), val, cx in zip((left, right), vals, (16, 48)):
        draw_text(d, label, cx - text_width(label, 1) // 2, 21, BR_MUTED, 1)
        draw_text(d, val, cx - text_width(val, nsc) // 2, y, BR_CREAM, nsc)


def br_footer(d, label):
    t = clock_str()
    draw_text(d, t, 2, LABEL_Y, BR_MUTED, 1)
    avail = 62 - (2 + text_width(t, 1) + 4)
    while label and text_width(label, 1) > avail:
        label = label[:label.rfind(" ")] if " " in label else label[:-1]
    if label:
        draw_text(d, label, 62 - text_width(label, 1), LABEL_Y, BR_MUTED, 1)


# ---------------------------------------------------------------- screens

def screen_flag(dirt, bath, wx, cal):
    """All three tracks at once. The bar carries tonight's headline; the rows
    say what each track is doing, so a dark Fonda is as visible as a green
    Albany. When nothing is running, the soonest track is lit — three equally
    dim rows make you read all of them to find the one that matters."""
    bar_color, bar_text, word = STATES.get(dirt["state"], STATES["standby"])
    img, d = canvas()

    standby = dirt["state"] == "standby"
    if standby:
        draw_bar(d, SODIUM, "DIRT CHK", LOAM)
    else:
        draw_bar(d, bar_color, word, bar_text)

    rows = dirt.get("rows") or []
    ROW_H, y0 = 12, BAR_H + 4

    def risk_chip(r):
        """The chip is rain risk, not race state — that way it carries
        information every day of the week rather than only on race nights.
        'Is it happening now' is answered by NOW in the day column and by the
        bar going green."""
        if r["state"] == "rained":
            return RED
        p = r["prob"]
        if p is None:
            return RAIL
        if p >= 60:
            return RED
        if p >= 30:
            return YELLOW
        return GREEN

    # on a standby screen the first row is the next race, so highlight it
    lit = 0 if standby and rows else -1

    for i, r in enumerate(rows[:3]):
        y = y0 + i * ROW_H
        live = r["state"] != "dark"
        hot = (i == lit)

        d.rectangle([0, y, 2, y + ROW_H - 3], fill=risk_chip(r))
        draw_text(d, r["code"], 6, y + 1, DUST if (live or hot) else SLATE, 2)

        # two fixed columns so a 3-char code and a 3-char day never collide
        draw_text(d, r["when"], 34, y + 3,
                  SODIUM if (live or hot) else SLATE, 1)
        if r["prob"] is not None:
            p = f"{r['prob']}%"
            draw_text(d, p, 62 - text_width(p, 1), y + 3,
                      DUST if (live or hot) else SLATE, 1)

    draw_footer(d, dirt["label"])
    return img


def screen_weather(dirt, bath, wx, cal):
    """Now on top, the next three days underneath. The big number is what it
    is outside right now; everything below is planning."""
    img, d = canvas()
    c, tc, word = wx_bar(wx)

    # sprite and word travel together as one centred group
    d.rectangle([0, 0, 63, BAR_H], fill=c)
    tw = text_width(word, BAR_SCALE)
    x = (64 - (SPRITE_W + 3 + tw)) // 2
    draw_sprite(d, word, x, 3, tc)
    draw_text(d, word, x + SPRITE_W + 3, 4, tc, BAR_SCALE)

    draw_centered(d, f"{wx['temp']}\u00b0", 20, DUST, 4)

    d.line([2, 43, 61, 43], fill=RAIL)
    days = wx.get("days") or []
    for i, (name, hi, lo) in enumerate(days[:3]):
        cx = 11 + i * 21
        draw_text(d, name, cx - text_width(name, 1) // 2, 45, SLATE, 1)
        t = f"{hi}/{lo}"
        draw_text(d, t, cx - text_width(t, 1) // 2, 51, DUST, 1)

    draw_footer(d, f"{wx['rain']}% {wx['wind']}MPH")
    return img


def screen_jellyfin(dirt, bath, wx, cal):
    """Poster art full-bleed, title and who's watching along the bottom. At
    64x64 the art is more recognisable than any amount of text, so it gets
    the whole panel and the type sits on a scrim over it.

    This screen is skipped entirely when nothing is playing — see the loop.
    """
    jf = bath              # the jellyfin bag rides in the same slot
    img, d = canvas()
    art = jf.get("art")

    if art is not None:
        img.paste(art, (0, 0))
        d = ImageDraw.Draw(img)
        # darken the lower third so type survives a bright poster
        scrim = Image.new("RGB", (64, 26), LOAM)
        img.paste(Image.blend(img.crop((0, 38, 64, 64)), scrim, 0.74), (0, 38))
        d = ImageDraw.Draw(img)
        ty = 40
    else:
        draw_bar(d, RAIL if jf["paused"] else SODIUM,
                 "PAUSED" if jf["paused"] else "PLAYING",
                 SLATE if jf["paused"] else LOAM)
        ty = 26

    title = jf["title"]
    tsc = fit_scale(title, 2)
    draw_centered(d, title, ty, DUST, tsc)

    who = jf.get("user", "")
    sub = jf.get("sub", "")
    line2 = f"{sub}  {who}".strip() if sub else who
    draw_centered(d, line2, ty + text_height(tsc) + 2, SLATE, 1)

    # progress rule sits just above the footer
    pct = jf.get("pct")
    if pct is not None:
        d.line([2, 55, 61, 55], fill=RAIL)
        d.line([2, 55, 2 + int(59 * pct / 100), 55],
               fill=SLATE if jf["paused"] else SODIUM)

    draw_footer(d, "PAUSED" if jf["paused"] else
                (f"{pct}%" if pct is not None else ""))
    return img


SCREENS = {
    "flag": screen_flag,
    "weather": screen_weather,
    "jellyfin": screen_jellyfin,
}


# ---------------------------------------------------------------- rotation

def is_race_night(now=None):
    now = now or dt.datetime.now()
    return now.weekday() in RACE_DAYS and RACE_WINDOW[0] <= now.hour < RACE_WINDOW[1]


def poll_secs(now=None):
    """How often to re-fetch. A rainout called at 5:55 shouldn't wait five
    minutes to reach the wall, so race nights poll hard."""
    return 60 if is_race_night(now) else 300


def rotation(now=None):
    """(screen, seconds) pairs. Race nights hand most of the time to the
    tracks; mornings lead with the sky; otherwise it spreads evenly."""
    now = now or dt.datetime.now()
    if is_race_night(now):
        return [("flag", 30), ("weather", 10), ("jellyfin", 10)]
    if MORNING[0] <= now.hour < MORNING[1]:
        return [("weather", 18), ("flag", 12), ("jellyfin", 10)]
    return [("flag", 14), ("weather", 14), ("jellyfin", 14)]


# ---------------------------------------------------------------- data

def _get(url, fallback, name):
    """Uses requests rather than urllib. The python.org macOS build ships
    without a wired-up CA bundle, so urllib fails every HTTPS call with
    CERTIFICATE_VERIFY_FAILED until you run Install Certificates.command.
    requests carries its own bundle and just works."""
    try:
        if url.startswith("file://"):
            with open(url[7:], "r") as f:
                return json.load(f)
        r = requests.get(url, timeout=10, headers={"User-Agent": "board/1.0"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"{name} fetch failed ({e}); using demo data", file=sys.stderr)
        return fallback


def fetch():
    """Adjust the two mappings below to match your real JSON.
    Nothing else in the file needs to change."""
    ev_doc = _get(f"{DIRTCHECK_BASE}/events.json", None, "dirtcheck events")
    st_doc = _get(f"{DIRTCHECK_BASE}/status.json", None, "dirtcheck status")
    raw_w = _get(WEATHER_URL, None, "weather")

    if ev_doc and st_doc:
        import dirtcheck
        dirt = dirtcheck.build(ev_doc, st_doc)
        dirt["rows"] = dirtcheck.track_rows(ev_doc, st_doc)
    else:
        dirt = DEMO_DIRT
    bath = fetch_jellyfin()
    if raw_w and "current" in raw_w:
        cur, day = raw_w["current"], raw_w["daily"]
        wx = {
            "temp": round(cur["temperature_2m"]),
            "feels": round(cur["apparent_temperature"]),
            "high": round(day["temperature_2m_max"][0]),
            "low": round(day["temperature_2m_min"][0]),
            "code": cur["weather_code"],
            "wind": round(cur["wind_speed_10m"]),
            "rain": day["precipitation_probability_max"][0] or 0,
            "days": [
                (_day_name(raw_w["daily"]["time"][i]),
                 round(day["temperature_2m_max"][i]),
                 round(day["temperature_2m_min"][i]))
                for i in range(1, min(4, len(day["temperature_2m_max"])))
            ],
        }
    else:
        wx = DEMO_WX

    return dirt, bath, wx, {}


def fetch_jellyfin():
    """Split out from fetch() because it's a call to a box on the same LAN —
    cheap enough to run every rotation step, so the screen appears within
    seconds of someone pressing play rather than at the next remote poll."""
    if not JELLYFIN_KEY:
        return DEMO_JF
    import jellyfin
    sess = jellyfin.sessions(JELLYFIN_URL, JELLYFIN_KEY)
    cnts = jellyfin.counts(JELLYFIN_URL, JELLYFIN_KEY)
    jf = jellyfin.build(sess, cnts, user=JELLYFIN_USER)
    jf["art"] = (jellyfin.poster(JELLYFIN_URL, JELLYFIN_KEY, jf["art_id"])
                 if jf.get("art_id") else None)
    return jf


def _day_name(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return dt.date(y, m, d).strftime("%a").upper()


def brightness_now():
    h = dt.datetime.now().hour
    return NIGHT_BRIGHTNESS if (h >= NIGHT_START or h < NIGHT_END) else DAY_BRIGHTNESS


# ---------------------------------------------------------------- main

def connect():
    if not PIXOO_IP:
        sys.exit("PIXOO_IP is not set in config.py. Find it in the Divoom app "
                 "under your device's settings, or run:\n"
                 "  curl -s -X POST https://app.divoom-gz.com/Device/ReturnSameLANDevice")
    from pixoo_client import Pixoo
    return Pixoo(PIXOO_IP)


def push(dev, img):
    dev.set_brightness(brightness_now())
    dev.push_image(img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", metavar="DIR", help="render PNGs, no device")
    ap.add_argument("--once", action="store_true", help="push one frame and exit")
    ap.add_argument("--loop", action="store_true", help="rotate screens forever")
    ap.add_argument("--screen", choices=list(SCREENS), help="force one screen")
    args = ap.parse_args()

    if args.preview:
        os.makedirs(args.preview, exist_ok=True)
        dirt, bath, wx, cal = DEMO_DIRT, DEMO_JF, DEMO_WX, {}
        dark = {**dirt, "state": "standby", "countdown": "1D 17H",
                "label": "TO GREEN",
                "rows": [{"code": "AS",  "when": "FRI", "state": "dark", "prob": 5},
                         {"code": "LV",  "when": "SAT", "state": "dark", "prob": 2},
                         {"code": "FON", "when": "SAT", "state": "dark", "prob": 2}]}
        sat = {**dirt, "state": "racing", "label": "HOT LAPS",
               "rows": [{"code": "AS",  "when": "FRI",    "state": "dark",   "prob": 18},
                        {"code": "LV",  "when": "NOW", "state": "racing", "prob": 2},
                        {"code": "FON", "when": "NOW", "state": "watch",  "prob": 45}]}
        rain = {**dirt, "state": "rained", "countdown": "4:12", "label": "CALLED",
                "rows": [{"code": "AS",  "when": "NOW", "state": "rained", "prob": 85},
                         {"code": "LV",  "when": "SAT",    "state": "dark",   "prob": 2},
                         {"code": "FON", "when": "SAT",    "state": "dark",   "prob": 2}]}
        for name, dd in (("flag-friday", dirt), ("flag-dark", dark),
                         ("flag-saturday", sat), ("flag-rainout", rain)):
            SCREENS["flag"](dd, bath, wx, cal).save(
                os.path.join(args.preview, f"{name}.png"))
            print(name)
        for name in ("weather", "jellyfin"):
            SCREENS[name](dirt, bath, wx, cal).save(
                os.path.join(args.preview, f"{name}.png"))
            print(name)
        return

    dirt, bath, wx, cal = fetch()

    if args.screen:
        push(connect(), SCREENS[args.screen](dirt, bath, wx, cal))
        return

    if args.once:
        name = next((n for n, _ in rotation()
                     if n != "jellyfin" or bath.get("playing")), "flag")
        push(connect(), SCREENS[name](dirt, bath, wx, cal))
        return

    if args.loop:
        dev = connect()
        dirt, bath, wx, cal = fetch()
        last_fetch = time.time()
        last_state = dirt.get("state")

        while True:
            for name, dwell in rotation():
                # Jellyfin is a LAN call, so refresh it every step rather than
                # on the remote poll. Playback shows up within a few seconds.
                bath = fetch_jellyfin()

                # nothing playing means no Jellyfin screen at all
                if name == "jellyfin" and not bath.get("playing"):
                    continue

                push(dev, SCREENS[name](dirt, bath, wx, cal))

                # Sleep in slices rather than one long block, so a state
                # change can cut in instead of waiting out the dwell.
                waited = 0
                while waited < dwell:
                    nap = min(5, dwell - waited)
                    time.sleep(nap)
                    waited += nap

                    if time.time() - last_fetch < poll_secs():
                        continue

                    dirt, _, wx, cal = fetch()
                    last_fetch = time.time()

                    state = dirt.get("state")
                    if state == last_state:
                        continue

                    # something changed — show it now, whatever screen is up
                    last_state = state
                    push(dev, SCREENS["flag"](dirt, bath, wx, cal))
                    time.sleep(20)
                    waited = dwell

    ap.print_help()


if __name__ == "__main__":
    main()
