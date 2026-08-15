"""
config.py — the only file you should need to edit.

Everything else in this repo reads from here. Change a value on GitHub,
then `git pull` on the Pi. No SSH editing.
"""

# ---------------------------------------------------------------- device

# Divoom app -> your device -> settings. Give it a DHCP reservation in your
# router so it doesn't move.
#
# Left blank on purpose. A placeholder IP here fails as "host is down", which
# looks like a network problem rather than an unset value.
PIXOO_IP = ""

# ---------------------------------------------------------------- location

LAT, LON = 42.8142, -73.9396          # Schenectady

# ---------------------------------------------------------------- jellyfin

# The board runs on the Jellyfin box itself, so this stays local. If you move
# the board to another machine, use http://192.168.1.163:8096 instead.
JELLYFIN_URL = "http://localhost:8096"

# The API key is NOT stored here — this repo is public. Put it in
# local_config.py on the machine itself, which .gitignore keeps out of git:
#
#   echo 'JELLYFIN_KEY = "your-key-here"' > ~/board/local_config.py
#
try:
    from local_config import JELLYFIN_KEY
except ImportError:
    JELLYFIN_KEY = ""

# Leave as None to show any stream in the house; set a username to show only
# yours.
JELLYFIN_USER = None

# ---------------------------------------------------------------- sources

# DirtCheck publishes events.json (schedule) and status.json (flags, rain).
# Note: renaming a repo breaks its GitHub Pages URL — git redirects, Pages
# does not. If you rename again, this line has to change.
DIRTCHECK_BASE = "https://dschmiedel25.github.io/dirtcheck/data"

# Apple Calendar -> right-click the calendar -> Share Calendar -> Public
# Calendar -> copy link, then change webcal:// to https://
ICS_URL = "https://p00-caldav.icloud.com/published/2/REPLACE-WITH-YOURS"

# RSS feeds for the wall dashboard's wire panel. Add or remove freely.
NEWS_FEEDS = [
    "https://feeds.npr.org/1001/rss.xml",
    "https://feeds.washingtonpost.com/rss/national",
]

# Calendar entries containing any of these are dropped — races already have
# their own screen on the Pixoo.
CALENDAR_SKIP = ("albany-saratoga", "fonda", "lebanon valley")

# ---------------------------------------------------------------- behavior

DAY_BRIGHTNESS = 75                   # 0-100
NIGHT_BRIGHTNESS = 12
NIGHT_START, NIGHT_END = 22, 6        # 24h clock

MORNING = (5, 10)                     # calendar and weather lead
RACE_DAYS = (4, 5)                    # Mon=0, so Fri and Sat
RACE_WINDOW = (15, 23)                # flag screen dominates in here

# ---------------------------------------------------------------- paths

# Where fetched data lands. Defaults are sensible per platform; override
# only if you want it somewhere specific.
import sys as _sys, os as _os

if _sys.platform == "darwin":
    DATA_DIR = _os.path.expanduser("~/Library/Application Support/board/data")
else:
    DATA_DIR = "/var/www/html/data"
