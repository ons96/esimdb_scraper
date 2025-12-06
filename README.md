# eSIM Plan Optimizer - Project Handoff

## Project Overview
This project is an **eSIM Plan Optimizer** for European travel. It scrapes data from `esimdb.com`, handles complex provider-specific rules (promo recurrence, new user limits), and uses a combinatorial optimizer to find the cheapest set of eSIM plans to cover a trip's duration and data requirements.

## Current Status (Dec 6, 2025)
- **Scraper (`scrape_europe_plans.py`)**: Functional. Fetches plans from API.
- **Promo Scraper (`scrape_promo_recurrence.py`)**: Functional & Optimized. Uses BeautifulSoup to detect "One-time" vs "Unlimited" badges on provider pages. Multithreaded. Caches results to `promo_recurrence_cache.json`.
- **Optimizer (`optimize_esim_plans.py`)**: Functional.
    - Reads cached promo data.
    - Handles "one-time" promos (only applies promo price to first plan from that provider).
    - Hides "hassle penalty" costs from display but uses them for ranking.
    - Configurable via `plan_overrides.json` and CLI constants.
    - Outputs top 10 solutions with inline warnings (e.g., "Need 2 accounts", "Promo already used").

## File Structure
- `scrape_europe_plans.py`: Main plan scraper (API -> CSV).
- `scrape_promo_recurrence.py`: Supplemental scraper for promo rules (Web -> JSON).
- `optimize_esim_plans.py`: Core logic. Reads CSV + JSONs -> Optimized Combinations.
- `plan_overrides.json`: Manual rules for specific plans (e.g., FairPlay New User Only) and providers.
- `promo_recurrence_cache.json`: Output of promo scraper. Map of Provider ID -> Promo Type.
- `provider_cache.json`: Map of Provider ID -> Name.

## Setup & Usage
1.  **Install Dependencies**: `pip install -r requirements.txt` (needs `requests`, `pandas`, `beautifulsoup4`, `lxml`, `tqdm`).
2.  **Scrape Plans**: `python scrape_europe_plans.py`
3.  **Scrape Promo Rules**: `python scrape_promo_recurrence.py` (updates cache).
4.  **Verify Logic (Optional)**: `python verify_promo_logic.py` (confirms one-time promo pricing).
5.  **Run Optimizer**: `python optimize_esim_plans.py`

## Prompt for Next AI Agent
*Copy and paste this into your next AI tool to resume work:*

> I am working on an eSIM plan optimizer project in Python.
> 
> **Goal**: Find the cheapest combination of eSIM plans for a trip (e.g., 15 days, 10GB).
> 
> **Current State**:
> 1. We have a working scraper (`scrape_europe_plans.py`) that gets data from esimdb.com API.
> 2. We have a `scrape_promo_recurrence.py` script that checks if a provider's promo code is "One-time" or "Unlimited" by scraping their webpage (looking for specific badges). It caches this to `promo_recurrence_cache.json`.
> 3. We have an optimizer (`optimize_esim_plans.py`) that uses `itertools.combinations` to find the best mix of plans. It respects the cached promo rules (e.g. if RedteaGO is "one-time", buying 2 Redtea plans means the second one is full price).
> 
> **Key Logic**:
> - **Hassle Penalty**: We add a virtual cost ($0.50) for every extra account/setup required, which affects ranking but isn't shown in the final price.
> - **Overrides**: `plan_overrides.json` handles special cases like "New User Only" plans.
> 
> **Immediate Next Steps**:
> - Verify that the optimizer correctly warns the user when a "one-time" promo is exhausted in a multi-plan solution.
> - Consider adding a "Force Refresh" flag to the scrapers.
> - You can run `python optimize_esim_plans.py` to see the current output.
