# Tender Monitor — Banks Constructions

Automated daily monitor for **civil plumbing** and **civil water management**
tenders in **Victoria, Australia**. Pulls from public tender APIs and the RSS
feeds you register for, filters by keyword + region, de-dupes, and writes new
leads to `output/leads.csv`. Runs itself every weekday morning via GitHub Actions.

## What it does NOT do
It does not scrape sites behind logins or against their terms (Tenders VIC,
VendorPanel, Estimate One, water-corp portals). For those you register a free
account, create a saved/filtered search, and paste that search's **RSS feed URL**
into `config.yaml`. That's the compliant, reliable path.

## Setup (10 minutes)

1. **Create a GitHub repo** and push these files:
   ```bash
   git init
   git add .
   git commit -m "Initial tender monitor"
   git branch -M main
   git remote add origin https://github.com/YOURNAME/tender-monitor.git
   git push -u origin main
   ```

2. **Register on the portals** and grab your filtered RSS feed URLs:
   - **Tenders VIC** (tenders.vic.gov.au): register → create a saved search
     for category *Civil / Water / Drainage*, region *Victoria* → copy its RSS URL.
   - Any council on **Tenderlink / VendorPanel** that offers a feed.
   Paste each URL into `config.yaml` under `sources.rss_feeds.feeds`.

3. **AusTender** (federal) works out of the box — no login. Leave it enabled
   to catch federal water-infrastructure ATMs.

4. **Tune keywords/regions** in `config.yaml` if you want them narrower or broader.

5. **Enable Actions**: the workflow runs Mon–Fri 07:00 AEST automatically, and
   you can trigger it any time from the repo's **Actions** tab → *Run workflow*.

6. **(Optional) Email digest**: add repo secrets `MAIL_USERNAME`, `MAIL_PASSWORD`
   (a Gmail app password), `MAIL_TO`, then uncomment the "Email digest" block in
   `.github/workflows/monitor.yml`.

## Run it locally to test
```bash
pip install -r requirements.txt
python src/monitor.py
cat output/leads.csv
```

## Output
- `output/leads.csv` — running log of all new leads (open in Excel/Sheets).
- `output/seen.json` — de-dupe memory so you only ever see new tenders.
- `output/summary.txt` — the latest run's new leads (used for the email).

## Extending it
Each source is a function in `src/monitor.py`. To add a new public listing page,
add proper link-extraction parsing in `fetch_html` for that specific site
(check its `robots.txt` first) and enable `html_pages` in the config.
