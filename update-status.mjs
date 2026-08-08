/**
 * DirtCall — daily status pass
 *
 * One Open-Meteo request covers all three tracks. Writes data/status.json
 * (what the page reads) and data/trend.json (a short history of readings so
 * next week's numbers can show movement, not just a value).
 *
 * Pushes to ntfy only on a change: green -> yellow, or yellow -> green.
 * Never posts red. A cancellation is a human call and this script has no way
 * to know one happened.
 *
 * No dependencies. Node 20+ for built-in fetch.
 */

import { readFile, writeFile } from "node:fs/promises";

// ---- thresholds ----------------------------------------------------------
// Expect to move these after a season. Probability is the noisiest input, so
// if it cries yellow on nights that race fine, raise RACE_PROB first.
const ANTECEDENT_HOURS = 8;   // how far back to look for rain already down
const ANTECEDENT_MM    = 5;   // mm in that window that puts a track yellow
const RACE_MM          = 1;   // mm forecast during the race window
const RACE_PROB        = 50;  // % chance during the race window
const FEATURE_HOURS    = 3;   // how long after green to keep watching

const TREND_KEEP = 6;         // readings retained per event

const NTFY_TOPIC = process.env.NTFY_TOPIC;

// ---- helpers -------------------------------------------------------------
const key = (e) => `${e.date}|${e.track}`;
const mins = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};
const addDays = (iso, n) => {
  const d = new Date(iso + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
const pretty = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  const ampm = h >= 12 ? "pm" : "am";
  const h12 = h % 12 || 12;
  return m ? `${h12}:${String(m).padStart(2, "0")}${ampm}` : `${h12}${ampm}`;
};

async function loadJSON(path, fallback) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch {
    return fallback;
  }
}

// ---- weather -------------------------------------------------------------
async function fetchWeather(tracks, codes) {
  const lat = codes.map((c) => tracks[c].lat).join(",");
  const lon = codes.map((c) => tracks[c].lon).join(",");
  const url =
    "https://api.open-meteo.com/v1/forecast" +
    `?latitude=${lat}&longitude=${lon}` +
    "&hourly=precipitation,precipitation_probability" +
    "&past_days=1&forecast_days=16" +
    "&timezone=America%2FNew_York";

  const res = await fetch(url);
  if (!res.ok) throw new Error(`Open-Meteo ${res.status}`);
  const body = await res.json();

  // A single coordinate returns an object; several return an array.
  const list = Array.isArray(body) ? body : [body];
  if (list.length !== codes.length) {
    throw new Error(`expected ${codes.length} locations, got ${list.length}`);
  }

  // Timestamps come back already in America/New_York, so window math needs no
  // DST handling. Index them by "YYYY-MM-DDTHH" for direct lookup.
  const out = {};
  codes.forEach((code, i) => {
    const h = list[i].hourly;
    const byHour = new Map();
    h.time.forEach((t, j) => {
      byHour.set(t.slice(0, 13), {
        mm: h.precipitation[j] ?? 0,
        prob: h.precipitation_probability[j] ?? 0,
      });
    });
    out[code] = byHour;
  });
  return out;
}

/** Sum rain and peak probability across an inclusive span of local hours. */
function window(byHour, date, startMin, endMin) {
  let mm = 0, prob = 0, seen = 0;
  for (let m = startMin; m <= endMin; m += 60) {
    // Negative minutes roll back into the previous day, which past_days covers.
    const dayOffset = Math.floor(m / 1440);
    const hour = ((Math.floor(m / 60) % 24) + 24) % 24;
    const stamp = `${addDays(date, dayOffset)}T${String(hour).padStart(2, "0")}`;
    const cell = byHour.get(stamp);
    if (!cell) continue;
    mm += cell.mm;
    prob = Math.max(prob, cell.prob);
    seen++;
  }
  return { mm: Math.round(mm * 10) / 10, prob, seen };
}

// ---- flag logic ----------------------------------------------------------
function assess(event, tracks, byHour) {
  const t = event.times;
  if (!t.gates || !t.race) return null;

  const gates = mins(t.gates);
  const anchor = mins(t.hotlaps || t.race);
  const end = mins(t.race) + FEATURE_HOURS * 60;

  const before = window(byHour, event.date, gates - ANTECEDENT_HOURS * 60, gates - 60);
  const during = window(byHour, event.date, anchor, end);

  if (!before.seen && !during.seen) return null; // no data — say nothing

  const reasons = [];
  if (before.mm >= ANTECEDENT_MM) reasons.push(`${before.mm} mm before gates`);
  if (during.mm >= RACE_MM) reasons.push(`${during.mm} mm during the show`);
  if (during.prob >= RACE_PROB) reasons.push(`${during.prob}% at ${pretty(t.hotlaps || t.race)}`);

  const flag = reasons.length ? "yellow" : "green";
  const why = reasons.length
    ? reasons.join(" · ")
    : `Dry before gates · ${during.prob}% through the feature`;

  return { flag, why, prob: during.prob, antecedentMm: before.mm };
}

// ---- notify --------------------------------------------------------------
async function notify(title, message, priority = "default") {
  if (!NTFY_TOPIC) return;
  try {
    await fetch(`https://ntfy.sh/${NTFY_TOPIC}`, {
      method: "POST",
      headers: { Title: title, Priority: priority, Tags: "checkered_flag" },
      body: message,
    });
  } catch (err) {
    console.error("ntfy failed:", err.message);
  }
}

// ---- main ----------------------------------------------------------------
const data = JSON.parse(await readFile("data/events.json", "utf8"));
const prev = await loadJSON("data/status.json", { events: {} });
const trend = await loadJSON("data/trend.json", {});

const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const horizon = addDays(today, 15);

const codes = Object.keys(data.tracks);
const upcoming = data.events.filter(
  (e) => e.date >= today && e.date <= horizon && (e.type === "race" || e.type === "raindate")
);

if (!upcoming.length) {
  console.log("Nothing scheduled in the next 16 days.");
  await writeFile("data/status.json", JSON.stringify({ generated: new Date().toISOString(), events: {} }, null, 2));
  process.exit(0);
}

const weather = await fetchWeather(data.tracks, codes);

const status = { generated: new Date().toISOString(), today, events: {} };
const alerts = [];

for (const e of upcoming) {
  const k = key(e);
  const read = assess(e, data.tracks, weather[e.track]);
  if (!read) continue;

  // Trend: one reading per day, capped.
  const hist = (trend[k] || []).filter((r) => r.on !== today);
  hist.push({ on: today, prob: read.prob });
  trend[k] = hist.slice(-TREND_KEEP);

  const first = trend[k][0]?.prob ?? read.prob;
  const delta = read.prob - first;
  const direction = trend[k].length < 2 ? "flat" : delta >= 10 ? "up" : delta <= -10 ? "down" : "flat";

  // Flags are only asserted for the next two days. Past that it's a reading,
  // not a claim about whether racing happens.
  const near = e.date <= addDays(today, 1);

  status.events[k] = {
    flag: near ? read.flag : null,
    why: near ? read.why : null,
    prob: read.prob,
    trend: trend[k].map((r) => r.prob),
    direction,
  };

  // Notify only on a change, and only for near events.
  const was = prev.events?.[k]?.flag ?? null;
  if (near && was && was !== read.flag) {
    const name = data.tracks[e.track].short;
    if (read.flag === "yellow") {
      alerts.push({
        title: `${name} — yellow`,
        body: `${e.title}\n${read.why}`,
        priority: "high",
      });
    } else if (read.flag === "green" && was === "yellow") {
      alerts.push({ title: `${name} — back to green`, body: read.why });
    }
  }
}

await writeFile("data/status.json", JSON.stringify(status, null, 2));
await writeFile("data/trend.json", JSON.stringify(trend, null, 2));

for (const a of alerts) await notify(a.title, a.body, a.priority);

const flagged = Object.values(status.events).filter((s) => s.flag);
console.log(
  `${upcoming.length} events · ${flagged.length} flagged · ${alerts.length} alert(s) sent`
);
