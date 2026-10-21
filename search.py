"""Weekly flight-price check via SerpAPI (Google Flights). Writes reports/latest.md."""
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
TOP_N = 5  # flights shown per destination

REPORTS = Path("reports")
HISTORY = Path("prices.csv")


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
            "depart": out_date.strftime("%a %d %b"),
            "route": f"{legs[0]['departure_airport']['id']} → {legs[-1]['arrival_airport']['id']}",
            "airline": " + ".join(dict.fromkeys(l.get("airline", "?") for l in legs)),
            "layover": ", ".join(f"{fmt(l['duration'])} {l.get('id', '')}" for l in layovers) or "Nonstop",
            "duration": fmt(opt.get("total_duration", 0)),
            "price": opt["price"],
            "link": link,
        })
    return rows


def last_price(dest, today):
    if not HISTORY.exists():
        return None
    with HISTORY.open() as f:
        old = [r for r in csv.DictReader(f) if r["destination"] == dest and r["run_date"] < today]
    return int(old[-1]["best_price"]) if old else None


def main():
    today = dt.date.today()
    dates = [d for d in DEPART_DATES if d >= today]
    lines = [
        f"# Flights · {today:%d %b %Y}",
        f"Depart {DEPART_DATES[0]:%d}–{DEPART_DATES[-1]:%d %b}, return {RETURN_DATE:%a %d %b} · "
        f"max 1 stop, layover ≤ {MAX_LAYOVER_MIN // 60}h · round-trip price in {CURRENCY}",
        "",
    ]
    if not dates:
        lines.append("All departure dates have passed. Update DEPART_DATES in search.py.")
    new_history = []

    for dest, ids in DESTINATIONS.items():
        rows, errors = [], []
        for d in dates:
            try:
                rows += parse(search(ids, d), d)
            except Exception as e:
                errors.append(f"{d}: {e}")
        rows.sort(key=lambda r: r["price"])

        if rows:
            best = rows[0]["price"]
            prev = last_price(dest, today.isoformat())
            change = ""
            if prev is not None and prev != best:
                change = f" ({'▼' if best < prev else '▲'} €{abs(best - prev)} vs last week)"
            lines.append(f"## {dest}: €{best}{change}")
            lines.append("| Price | Depart | Route | Airline | Layover | Duration | |")
            lines.append("|---|---|---|---|---|---|---|")
            for r in rows[:TOP_N]:
                lines.append(f"| €{r['price']} | {r['depart']} | {r['route']} | {r['airline']} | "
                             f"{r['layover']} | {r['duration']} | [Open]({r['link']}) |")
            new_history.append([today.isoformat(), dest, best])
        else:
            lines.append(f"## {dest}: no flights matched")
        if errors:
            lines.append("\nErrors: " + "; ".join(errors))
        lines.append("")

    REPORTS.mkdir(exist_ok=True)
    report = "\n".join(lines)
    (REPORTS / "latest.md").write_text(report, encoding="utf-8")
    (REPORTS / f"{today}.md").write_text(report, encoding="utf-8")

    first = not HISTORY.exists()
    with HISTORY.open("a", newline="") as f:
        w = csv.writer(f)
        if first:
            w.writerow(["run_date", "destination", "best_price"])
        w.writerows(new_history)
    print(report)


if __name__ == "__main__":
    main()
