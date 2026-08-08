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
const ANTECEDENT_IN    = 0.20; // inches already down before pits open
const RACE_IN          = 0.04; // inches forecast while you're there
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
    "&past_days=1&forecast_days=16&precipitation_unit=inch" +
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
  let mm = 0, prob = 0, seen = 0, peakAt = null;
  for (let m = startMin; m <= endMin; m += 60) {
    // Negative minutes roll back into the previous day, which past_days covers.
    const dayOffset = Math.floor(m / 1440);
    const hour = ((Math.floor(m / 60) % 24) + 24) % 24;
    const stamp = `${addDays(date, dayOffset)}T${String(hour).padStart(2, "0")}`;
    const cell = byHour.get(stamp);
    if (!cell) continue;
    mm += cell.mm;
    if(cell.prob > prob){ prob = cell.prob; peakAt = hour; }
    seen++;
  }
  return { mm: Math.round(mm * 100) / 100, prob, seen, peakAt };
}

// ---- flag logic ----------------------------------------------------------
function assess(event, tracks, byHour) {
  const t = event.times;
  if (!t.gates || !t.race) return null;

  // The night starts when the pits open. Nothing between arrival and the
  // last lap falls outside a window.
  const start = mins(t.pits || t.gates);
  const end = mins(t.race) + FEATURE_HOURS * 60;

  const before = window(byHour, event.date, start - ANTECEDENT_HOURS * 60, start - 60);
  const during = window(byHour, event.date, start, end);

  if (!before.seen && !during.seen) return null; // no data — say nothing

  const reasons = [];
  if (before.mm >= ANTECEDENT_IN) reasons.push(`${before.mm}" before pits`);
  if (during.mm >= RACE_IN) reasons.push(`${during.mm}" once you're there`);
  if (during.prob >= RACE_PROB) {
    const peak = during.peakAt === null ? "" :
      ` at ${pretty(String(during.peakAt).padStart(2, "0") + ":00")}`;
    reasons.push(`${during.prob}%${peak}`);
  }

  const flag = reasons.length ? "yellow" : "green";
  const why = reasons.length
    ? reasons.join(" · ")
    : `Dry all day · ${during.prob}% through the feature`;

  return { flag, why, prob: during.prob, antecedentMm: before.mm };
}

// ---- notify --------------------------------------------------------------
/**
 * HTTP headers are Latin-1 only, so the title has to be plain ASCII.
 * Em dashes, curly quotes and the degree sign all break it otherwise.
 */
function ascii(s) {
  return String(s)
    .replace(/[\u2010-\u2015]/g, "-")   // dashes
    .replace(/[\u2018\u2019]/g, "'")    // curly single quotes
    .replace(/[\u201C\u201D]/g, '"')    // curly double quotes
    .replace(/\u00B7/g, "-")            // middle dot
    .replace(/\u00B0/g, " deg")
    .replace(/[^\x20-\x7E]/g, "");      // anything else non-printable-ASCII
}

async function notify(title, message, priority = "default") {
  if (!NTFY_TOPIC) {
    console.log(`  (would notify: ${ascii(title)})`);
    return;
  }
  try {
    const res = await fetch(`https://ntfy.sh/${NTFY_TOPIC}`, {
      method: "POST",
      headers: {
        Title: ascii(title),
        Priority: priority,
        Tags: "checkered_flag",
        "Content-Type": "text/plain; charset=utf-8",
      },
      body: message,
    });
    if (res.ok) {
      console.log(`  ntfy ok: ${ascii(title)}`);
    } else {
      console.error(`  ntfy rejected (${res.status}): ${await res.text()}`);
    }
  } catch (err) {
    console.error("  ntfy threw:", err.message);
  }
}

// ---- main ----------------------------------------------------------------
console.log("cwd:", process.cwd());
console.log("NTFY_TOPIC:", NTFY_TOPIC ? `set (${NTFY_TOPIC.length} chars)` : "NOT SET");
console.log("node:", process.version);

let data;
try {
  data = JSON.parse(await readFile("data/events.json", "utf8"));
} catch (err) {
  console.error("FATAL: could not read data/events.json —", err.message);
  process.exit(1);
}
console.log(`events.json: ${data.events.length} events, ${Object.keys(data.tracks).length} tracks`);
const prev = await loadJSON("data/status.json", { events: {} });
const trend = await loadJSON("data/trend.json", {});

const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const horizon = addDays(today, 15);
console.log(`window: ${today} through ${horizon}`);

const codes = Object.keys(data.tracks);
const upcoming = data.events.filter(
  (e) => e.date >= today && e.date <= horizon && (e.type === "race" || e.type === "raindate")
);

if (!upcoming.length) {
  console.log("Nothing scheduled in the next 16 days.");
  await writeFile("data/status.json", JSON.stringify(
    { generated: new Date().toISOString(), today, events: {} }, null, 2));
  await writeFile("data/trend.json", JSON.stringify(trend, null, 2));
  process.exit(0);
}

console.log(`${upcoming.length} event(s) in window`);

let weather;
try {
  weather = await fetchWeather(data.tracks, codes);
} catch (err) {
  console.error("Open-Meteo failed:", err.message);
  // Write a status file anyway so the page has something and the commit
  // step has a file to stage. Better a stale reading than a missing one.
  await writeFile("data/status.json", JSON.stringify(
    { generated: new Date().toISOString(), today, error: err.message,
      events: prev.events || {} }, null, 2));
  await writeFile("data/trend.json", JSON.stringify(trend, null, 2));
  process.exit(1);
}

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
        title: `${name}: YELLOW`,
        body: `${e.title}\n${read.why}`,
        priority: "high",
      });
    } else if (read.flag === "green" && was === "yellow") {
      alerts.push({ title: `${name}: back to green`, body: read.why });
    }
  }
}

await writeFile("data/status.json", JSON.stringify(status, null, 2));
await writeFile("data/trend.json", JSON.stringify(trend, null, 2));

for (const a of alerts) await notify(a.title, a.body, a.priority);

const flagged = Object.values(status.events).filter((s) => s.flag);
console.log(
  `${upcoming.length} events · ${flagged.length} flagged · ` +
  `${alerts.length} alert(s) ${NTFY_TOPIC ? "sent" : "suppressed (no NTFY_TOPIC set)"}`
);
console.log(`wrote data/status.json (${Object.keys(status.events).length} entries)`);
