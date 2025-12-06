# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

Project overview
- Purpose: Scrape eSIM plan data from esimdb.com for specific countries/providers via multiple strategies (Next.js JSON endpoints, Playwright-driven DOM scraping, response interception), then post-process and analyze results to identify affordable plans for trip requirements.
- Primary runtime: Python scripts (no package/pyproject; no explicit test or lint tooling configured).

Environment setup
- Python 3.10+ recommended
- Install dependencies (requests, beautifulsoup4, playwright, pandas, numpy):
```bash path=null start=null
python -m venv .venv
# PowerShell
. .venv/Scripts/Activate.ps1
pip install --upgrade pip
pip install requests beautifulsoup4 playwright pandas numpy
# Install Playwright browser binaries
python -m playwright install
```

Common commands
- Scrape USA plans by auto-scrolling and parsing DOM (saves JSON/CSV under scraped_data/):
```bash path=null start=null
# Headed (default)
python "esim usa plans scraper test.py"
# Headless mode
python "esim usa plans scraper test.py" --headless
```
- Scrape via provider pages with Playwright JSON-response interception (aggregates plans into scraped_data/esimdb_plans.json):
```bash path=null start=null
python "esimdb scraper playwright.py"
```
- Scrape Turkey page via Playwright + BeautifulSoup (writes scraped_data/esimdb_plans.json):
```bash path=null start=null
python "esim turkey scraper playwright.py"
```
- Scrape France via public API and write CSV (flattens price fields):
```bash path=null start=null
python scripts/esim_scraper_api_france.py
```
- Scrape all USA providers using Next.js buildId API (fastest, if endpoint remains stable):
```bash path=null start=null
python esimdb_api_scraper.py
```
- Analyze USA CSV for trip cost given duration and daily data need (reads esim_plans_usa.csv, writes analyzed_esim_plans_usa.csv):
```bash path=null start=null
python analyze_esim_plans.py
```
- Convert consolidated JSON to CSV and compute cost metrics (expects scraped_data/esimdb_plans.json, writes scraped_data/esim_plans_consolidated_6days.csv):
```bash path=null start=null
python "pandas json to csv test.py"
```

Notes on outputs and paths
- scraped_data/: canonical output location for JSON/CSV artifacts in most scripts.
- Some experimental scripts may write to the user Downloads folder (e.g., esim scrape test.py writes esimdb_data.csv). Prefer scraped_data/ for reproducibility.

High-level architecture
- Scraping strategies (choose based on stability/speed):
  1) Next.js JSON API (esimdb_api_scraper.py)
     - get_provider_slugs(): parses country page to discover provider slugs
     - get_build_id(): parses __NEXT_DATA__ to extract buildId
     - fetch_provider_plans(): fetches /_next/data/{buildId}/usa/{slug}.json, recursively locates plan arrays, normalizes fields
     - Outputs aggregated JSON to scraped_data/esimdb_plans.json
  2) Playwright JSON interception per provider (esimdb scraper playwright.py)
     - Navigates to each provider URL, captures application/json responses, flattens candidate lists, normalizes and de-dupes
     - Useful when API shape varies or requires client-side requests
  3) Playwright DOM scroll-and-parse (esim usa plans scraper test.py, esim turkey scraper playwright.py)
     - Scroll loop with controlled delays, parses visible cards via BeautifulSoup
     - De-duplication by signature composed of provider | plan | data | price

- Data processing
  - pandas json to csv test.py: normalizes JSON into CSV, computes derived columns: data_mb, validity_days, cost_per_day, data_per_day, total_plan_cost_for_trip, overall_cost_per_day; filters by trip_length and de-duplicates via signature_check
  - analyze_esim_plans.py: robust parsing helpers (parse_data, parse_validity) and trip-aware total cost model
    - calculate_total_cost(): determines purchases needed based on data and validity constraints (supports unlimited via np.inf)
    - Sorts by total_trip_cost and writes analyzed CSV; prints top 5

- Typical pipeline
```bash path=null start=null
# Option A (fast, API-based)
python esimdb_api_scraper.py
python "pandas json to csv test.py"
# Option B (UI-based)
python "esim usa plans scraper test.py" --headless
python analyze_esim_plans.py
```

Build, lint, and tests
- Build: not applicable (pure Python scripts; no packaging configured).
- Lint: no linter configured in this repo.
- Tests: no test framework or test files present. If tests are added later, prefer pytest and document single-test invocation here.

Operational tips specific to this repo
- Playwright prerequisites: after installing the Python package, you must run `python -m playwright install` once per environment to fetch browser binaries; re-run after upgrades.
- Performance vs. completeness: the Next.js buildId approach is fastest but relies on page structure; if it breaks, fall back to the Playwright interception or DOM parsing variants.
- De-duplication: when modifying scrapers, preserve or update signature logic to avoid duplicate plans across scroll iterations or providers.
