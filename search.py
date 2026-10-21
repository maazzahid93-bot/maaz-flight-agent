"""Weekly flight-price check via SerpAPI (Google Flights).
Writes reports/latest.md, prices.csv (history) and docs/data.json (for the website)."""
import csv
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

# ---- Settings: edit these to change routes or dates ----
ORIGINS = "BRU,CRL,AMS,CDG"
DESTINATIONS = {"New York": "JFK,EWR", "Karachi": "KHI"}
DEPART_DATES = [dt.date(2026, 12, d) for d in range(18, 25)]  # 18-24 Dec
RETURN_DATE = dt.date(2027, 1, 4)
MAX_LAYOVER_MIN = 300  # 5 hours
CURRENCY = "EUR"
TOP_N = 5  # flights per destination in the markdown report

REPORTS = Path("reports")
HISTORY = Path("prices.csv")
SITE_DATA = Path("docs/data.json")


def fmt(minutes):
    return f"{minutes // 60}h{minutes % 60:02d}"


def search(dest_ids, out_date):
    params = {
        "engine": "google_flights",
        "departure_id": ORIGINS,
        "arrival_id": dest_ids,
        "outbound_date": out_date.isoformat(),
        "return_date": RETURN_DATE.isoformat(),
        "type": "1",   # round trip
        "stops": "2",  # 1 stop or fewer
        "currency": CURRENCY,
        "hl": "en",
        "api_key": os.environ["SERPAPI_KEY"],
    }
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def parse(data, out_date):
    link = data.get("search_metadata", {}).get("google_flights_url", "")
    rows = []
    for opt in data.get("best_flights", []) + data.get("other_flights", []):
        legs, layovers = opt.get("flights", []), opt.get("layovers", [])
        if not legs or "price" not in opt or len(legs) > 2:
            continue
        if any(l.get("duration", 0) > MAX_LAYOVER_MIN for l in layovers):
            continue
        rows.append({
            "depart": out_date.isoformat(),
            "depart_label": out_date.strftime("%a %d %b"),
            "origin": legs[0]["departure_airport"]["id"],
            "arrival": legs[-1]["arrival_airport"]["id"],
            "airline": " + ".join(dict.fromkeys(l.get("airline", "?") for l in legs)),
            "stops": len(legs) - 1,
            "layover": ", ".join(f"{fmt(l['duration'])} {l.get('id', '')}" for l in layovers) or "Nonstop",
            "duration_min": opt.get("total_duration", 0),
            "price": opt["price"],
            "link": link,
        })
    return rows


def read_history():
    if not HISTORY.exists():
        return []
    with HISTORY.open() as f:
        return [{"date": r["run_date"], "destination": r["destination"], "price": int(r["best_price"])}
                for r in csv.DictReader(f)]


def main():
    today = dt.date.today()
    dates = [d for d in DEPART_DATES if d >= today]
    history = read_history()
    results, errors, new_history = {}, [], []

    for dest, ids in DESTINATIONS.items():
        rows = []
        for d in dates:
            try:
                rows += parse(search(ids, d), d)
            except Exception as e:
                errors.append(f"{dest} {d}: {e}")
        rows.sort(key=lambda r: r["price"])
        results[dest] = rows
        if rows:
            new_history.append([today.isoformat(), dest, rows[0]["price"]])

    # Markdown report
    lines = [
        f"# Flights · {today:%d %b %Y}",
        f"Depart {DEPART_DATES[0]:%d}–{DEPART_DATES[-1]:%d %b}, return {RETURN_DATE:%a %d %b} · "
        f"max 1 stop, layover ≤ {MAX_LAYOVER_MIN // 60}h · round-trip price in {CURRENCY}",
        "",
    ]
    if not dates:
        lines.append("All departure dates have passed. Update DEPART_DATES in search.py.")
    for dest, rows in results.items():
        if not rows:
            lines += [f"## {dest}: no flights matched", ""]
            continue
        best = rows[0]["price"]
        prev = [h["price"] for h in history if h["destination"] == dest and h["date"] < today.isoformat()]
        change = ""
        if prev and prev[-1] != best:
            change = f" ({'▼' if best < prev[-1] else '▲'} €{abs(best - prev[-1])} vs last week)"
        lines += [f"## {dest}: €{best}{change}",
                  "| Price | Depart | Route | Airline | Layover | Duration | |",
                  "|---|---|---|---|---|---|---|"]
        for r in rows[:TOP_N]:
            lines.append(f"| €{r['price']} | {r['depart_label']} | {r['origin']} → {r['arrival']} | "
                         f"{r['airline']} | {r['layover']} | {fmt(r['duration_min'])} | [Open]({r['link']}) |")
        lines.append("")
    if errors:
        lines.append("Errors: " + "; ".join(errors))

    REPORTS.mkdir(exist_ok=True)
    report = "\n".join(lines)
    (REPORTS / "latest.md").write_text(report, encoding="utf-8")
    (REPORTS / f"{today}.md").write_text(report, encoding="utf-8")

    # Price history
    first = not HISTORY.exists()
    with HISTORY.open("a", newline="") as f:
        w = csv.writer(f)
        if first:
            w.writerow(["run_date", "destination", "best_price"])
        w.writerows(new_history)

    # Website data
    SITE_DATA.parent.mkdir(exist_ok=True)
    SITE_DATA.write_text(json.dumps({
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "currency": CURRENCY,
        "window": {"depart_from": DEPART_DATES[0].isoformat(), "depart_to": DEPART_DATES[-1].isoformat(),
                   "return": RETURN_DATE.isoformat(), "max_layover_h": MAX_LAYOVER_MIN // 60},
        "results": results,
        "history": read_history(),
        "errors": errors,
    }, indent=1), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
