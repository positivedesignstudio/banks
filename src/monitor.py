#!/usr/bin/env python3
"""
Tender Monitor for Banks Constructions
--------------------------------------
Polls tender sources, filters for civil plumbing / civil water work in
Victoria, de-dupes against previously seen items, and writes new leads
to a CSV.

Run locally:   python src/monitor.py
Run in CI:     handled by .github/workflows/monitor.yml

Sources are configured in config.yaml. Nothing here scrapes anything
behind a login or against a site's terms - it uses public APIs, RSS
feeds you register for, and (optionally) public HTML pages you opt in.
"""

import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
import yaml
import feedparser

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")
USER_AGENT = "BanksConstructions-TenderMonitor/1.0 (contact: admin@banksconstructions.com.au)"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_seen(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(path, seen):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def matches_keywords(text, keywords):
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords)


def matches_region(text, regions):
    if not regions:
        return True
    t = (text or "").lower()
    return any(r.lower() in t for r in regions)


def make_id(source, ref, title):
    base = f"{source}|{ref}|{title}".lower()
    return re.sub(r"\s+", " ", base).strip()


# ----------------------------------------------------------------------
# Source: AusTender OCDS API
# ----------------------------------------------------------------------
def fetch_austender(cfg, keywords, regions):
    leads = []
    url = cfg.get("api_url")
    if not url:
        return leads
    # AusTender OCDS wants a date range; pull a recent window.
    today = datetime.now(timezone.utc).date()
    params = {
        "dateType": "publishDate",
        "startDate": today.replace(day=1).isoformat(),
        "endDate": today.isoformat(),
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT},
                         timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[austender] error: {e}", file=sys.stderr)
        return leads

    for release in data.get("releases", []):
        tender = release.get("tender", {}) or {}
        title = tender.get("title", "")
        desc = tender.get("description", "")
        blob = f"{title} {desc}"
        # region text can live in a few places; concatenate what we have
        region_blob = json.dumps(tender.get("items", [])) + " " + blob
        if matches_keywords(blob, keywords) and matches_region(region_blob, regions):
            leads.append({
                "source": "AusTender",
                "title": title,
                "reference": tender.get("id", ""),
                "close_date": (tender.get("tenderPeriod", {}) or {}).get("endDate", ""),
                "url": (release.get("tender", {}).get("documents", [{}])[0] or {}).get("url", "")
                       or "https://www.tenders.gov.au/",
                "description": desc[:500],
                "found_at": datetime.now(timezone.utc).isoformat(),
            })
    print(f"[austender] {len(leads)} matches")
    return leads


# ----------------------------------------------------------------------
# Source: RSS / Atom feeds
# ----------------------------------------------------------------------
def fetch_rss(cfg, keywords, regions):
    leads = []
    for feed in cfg.get("feeds", []):
        url = feed.get("url", "")
        name = feed.get("name", "RSS")
        if not url or url.startswith("REPLACE_WITH"):
            print(f"[rss] skipping unconfigured feed: {name}")
            continue
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"[rss:{name}] error: {e}", file=sys.stderr)
            continue
        for entry in parsed.entries:
            title = entry.get("title", "")
            desc = entry.get("summary", "")
            blob = f"{title} {desc}"
            if matches_keywords(blob, keywords) and matches_region(blob, regions):
                leads.append({
                    "source": name,
                    "title": title,
                    "reference": entry.get("id", entry.get("link", "")),
                    "close_date": entry.get("published", ""),
                    "url": entry.get("link", ""),
                    "description": desc[:500],
                    "found_at": datetime.now(timezone.utc).isoformat(),
                })
        print(f"[rss:{name}] scanned {len(parsed.entries)} entries")
    return leads


# ----------------------------------------------------------------------
# Source: public HTML pages (opt-in, polite)
# ----------------------------------------------------------------------
def fetch_html(cfg, keywords, regions):
    leads = []
    delay = cfg.get("request_delay_seconds", 5)
    for page in cfg.get("pages", []):
        url = page.get("url", "")
        name = page.get("name", "HTML")
        if not url or url.startswith("REPLACE_WITH"):
            continue
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            r.raise_for_status()
            text = r.text
        except Exception as e:
            print(f"[html:{name}] error: {e}", file=sys.stderr)
            continue
        # Very light heuristic: only surface the page if it hits keywords.
        # Real per-site parsing (link extraction) should be added per source.
        if matches_keywords(text, keywords) and matches_region(text, regions):
            leads.append({
                "source": name,
                "title": f"Keyword match on {name} - review manually",
                "reference": url,
                "close_date": "",
                "url": url,
                "description": "Page contained target keywords. Open to review.",
                "found_at": datetime.now(timezone.utc).isoformat(),
            })
        time.sleep(delay)
    return leads


# ----------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------
def write_csv(path, leads):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = ["found_at", "source", "title", "reference", "close_date", "url", "description"]
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new_file:
            w.writeheader()
        for lead in leads:
            w.writerow({k: lead.get(k, "") for k in fields})


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    cfg = load_config(CONFIG_PATH)
    keywords = cfg["keywords"]
    regions = cfg.get("regions", [])
    sources = cfg["sources"]
    out = cfg["output"]

    seen = load_seen(out["seen_db"])
    all_leads = []

    if sources.get("austender", {}).get("enabled"):
        all_leads += fetch_austender(sources["austender"], keywords, regions)
    if sources.get("rss_feeds", {}).get("enabled"):
        all_leads += fetch_rss(sources["rss_feeds"], keywords, regions)
    if sources.get("html_pages", {}).get("enabled"):
        all_leads += fetch_html(sources["html_pages"], keywords, regions)

    # De-dupe
    new_leads = []
    for lead in all_leads:
        uid = make_id(lead["source"], lead["reference"], lead["title"])
        if uid not in seen:
            seen.add(uid)
            new_leads.append(lead)

    if new_leads:
        write_csv(out["csv_path"], new_leads)
        save_seen(out["seen_db"], seen)
        print(f"\n{len(new_leads)} NEW lead(s) written to {out['csv_path']}")
    else:
        print("\nNo new leads this run.")

    # Emit a summary for the GitHub Actions log / email step
    with open("output/summary.txt", "w", encoding="utf-8") as f:
        f.write(f"{len(new_leads)} new lead(s) - {datetime.now(timezone.utc).isoformat()}\n\n")
        for l in new_leads:
            f.write(f"- [{l['source']}] {l['title']} (closes {l['close_date']})\n  {l['url']}\n")


if __name__ == "__main__":
    os.makedirs("output", exist_ok=True)
    main()
