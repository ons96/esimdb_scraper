# eSIM Plan Optimizer - Project Handoff

## Project Overview
This project is an **eSIM Plan Optimizer** for European and USA travel. It scrapes data from `esimdb.com`, handles complex provider-specific rules (promo recurrence, new user limits), and uses a combinatorial optimizer to find the cheapest set of eSIM plans to cover a trip's duration and data requirements.

## Current Status (Jan 10, 2025)

### Multi-Region Support
- **Unified Scraper (`scrape_all_regions_plans.py`)**: NEW! Scrapes plans for Europe, USA, North America, and Global regions from esimdb.com API.
- **Interactive Optimizer (`optimize_with_input.py`)**: NEW! User-friendly interface with prompts for region selection, trip days (default: 6), and data needs (default: 5GB).
- **Multi-Region Optimizer (`optimize_esim_plans_multi_region.py`)**: Unified optimizer supporting both Europe and USA regions via `--region` flag.
- **Unified Runner (`run_full_optimizer_multi_region.py`)**: One-click pipeline for either region.

### Europe Region
- **Scraper (`scrape_europe_plans.py`)**: Functional. Fetches plans from API.
- **Promo Scraper (`scrape_promo_recurrence.py`)**: Functional & Optimized. Uses BeautifulSoup to detect "One-time" vs "Unlimited" badges on provider pages. Multithreaded. Caches results to `promo_recurrence_cache.json`.
- **Optimizer (`optimize_esim_plans.py`)**: Functional.
    - Reads cached promo data.
    - Handles "one-time" promos (only applies promo price to first plan from that provider).
    - Hides "hassle penalty" costs from display but uses them for ranking.
    - Configurable via `plan_overrides.json` and CLI constants.
    - Outputs top 10 solutions with inline warnings (e.g., "Need 2 accounts", "Promo already used").

### USA Region
- **Scraper (`scrape_usa_plans.py`)**: Functional. Fetches USA plans from North America API and filters for USA-only coverage.
- **Promo Scraper (`scrape_usa_promo_recurrence.py`)**: Functional. Scrapes USA provider pages for promo recurrence info. Caches to `promo_recurrence_cache_usa.json`.

## File Structure
### Europe-Specific Files
- `scrape_europe_plans.py`: Main Europe plan scraper (API -> CSV).
- `scrape_promo_recurrence.py`: Promo rules scraper for Europe providers (Web -> JSON).
- `esim_plans_europe.csv`: All Europe plans (output of scraper).
- `esim_plans_europe_filtered.csv`: Filtered Europe plans (covers target countries).
- `promo_recurrence_cache.json`: Europe provider promo type cache.

### USA-Specific Files
- `scrape_usa_plans.py`: USA plan scraper (North America API -> CSV, filtered for USA).
- `scrape_usa_promo_recurrence.py`: Promo rules scraper for USA providers (Web -> JSON).
- `esim_plans_usa.csv`: USA plans (output of scraper).
- `esim_api_usa_raw.json`: Raw API response for debugging.
- `provider_cache_usa.json`: USA provider ID to name mapping.
- `promo_recurrence_cache_usa.json`: USA provider promo type cache.

### Shared Files
- `optimize_esim_plans_multi_region.py`: Multi-region optimizer supporting both Europe and USA.
- `run_full_optimizer_multi_region.py`: Unified runner script for full pipeline.
- `optimize_esim_plans.py`: Original Europe-only optimizer (legacy, still functional).
- `plan_overrides.json`: Manual rules for specific plans and providers. Now supports `usa_provider_promo_overrides` section.
- `provider_cache.json`: Provider ID -> Name mapping (Europe).

## Setup & Usage

### Quick Start - Interactive Mode (NEW!)

For the easiest experience, use the **interactive optimizer** that prompts you for region, trip duration, and data needs:

```bash
python optimize_with_input.py
```

Example session:
```
Select region:
1. Europe
2. USA
3. North America
4. Global
Enter choice (1-4, default: 1): 2

Enter trip duration in days (default: 6): 10
Enter data requirement in GB (default: 5): 8

✓ Region:      USA
✓ Trip:        10 days
✓ Data:        8.0 GB
```

Just press **Enter** to use defaults (6 days, 5GB).

### Quick Start - Multi-Region

**Europe:**
```bash
# Run full pipeline (scrape + optimize) for Europe
python run_full_optimizer_multi_region.py --region europe

# With custom trip parameters
python run_full_optimizer_multi_region.py --region europe --trip-days 10 --data-gb 5
```

**USA:**
```bash
# Run full pipeline (scrape + optimize) for USA
python run_full_optimizer_multi_region.py --region usa

# With custom trip parameters
python run_full_optimizer_multi_region.py --region usa --trip-days 7 --data-gb 3
```

### Unified Scraper - All Regions

To scrape plans from all supported regions (Europe, USA, North America, Global):

```bash
# Scrape a specific region
python scrape_all_regions_plans.py --region europe
python scrape_all_regions_plans.py --region usa
python scrape_all_regions_plans.py --region north-america
python scrape_all_regions_plans.py --region global

# Scrape all regions at once
python scrape_all_regions_plans.py --all
```

**Note on USA Plans**: The USA scraper filters North America API results for USA-specific plans (≤5 countries). This gives ~1,805 focused plans. The website (esimdb.com/usa) shows ~6,755 plans because it aggregates from all regions including global/multi-continent offerings. For comprehensive coverage, you could aggregate from all regional APIs manually.

### Manual Steps - Europe
1.  **Install Dependencies**: `pip install -r requirements.txt` (needs `requests`, `pandas`, `beautifulsoup4`, `lxml`, `tqdm`, `playwright`).
2.  **Scrape Plans**: `python scrape_europe_plans.py`
3.  **Scrape Promo Rules**: `python scrape_promo_recurrence.py` (updates cache).
4.  **Run Optimizer**: `python optimize_esim_plans.py` (legacy) or `python optimize_esim_plans_multi_region.py --region europe`

### Manual Steps - USA
1.  **Install Dependencies**: Same as above.
2.  **Scrape Plans**: `python scrape_usa_plans.py`
3.  **Scrape Promo Rules**: `python scrape_usa_promo_recurrence.py` (updates cache).
4.  **Run Optimizer**: `python optimize_esim_plans_multi_region.py --region usa --trip-days 10 --data-gb 5`

### Advanced Options
- Skip scraping if data already exists: `python run_full_optimizer_multi_region.py --region usa --skip-scrape --skip-promo`
- Customize trip duration: `--trip-days N` (default: 15)
- Customize data needed: `--data-gb N` (default: 8.6)

## USA-Specific Notes
- USA plans are sourced from the North America API and filtered for USA-only coverage (excludes global/regional plans covering >5 countries).
- No currency conversion needed (all prices in USD).
- Data units normalized to MB for consistency with Europe plans.
- Promo detection works the same way as Europe (scrapes provider pages for "One-time" vs "Unlimited" badges).

## Prompt for Next AI Agent
*Copy and paste this into your next AI tool to resume work:*

> I am working on an eSIM plan optimizer project in Python that supports both Europe and USA regions.
> 
> **Goal**: Find the cheapest combination of eSIM plans for a trip (e.g., 15 days, 10GB).
> 
> **Current State**:
> 1. We have working scrapers for both Europe (`scrape_europe_plans.py`) and USA (`scrape_usa_plans.py`) that get data from esimdb.com API.
> 2. We have promo recurrence scrapers (`scrape_promo_recurrence.py` and `scrape_usa_promo_recurrence.py`) that check if a provider's promo code is "One-time" or "Unlimited" by scraping their webpage.
> 3. We have a multi-region optimizer (`optimize_esim_plans_multi_region.py`) that supports both regions via `--region` flag.
> 4. We have a unified runner (`run_full_optimizer_multi_region.py`) that orchestrates the full pipeline for either region.
> 
> **Key Logic**:
> - **Hassle Penalty**: We add a virtual cost ($0.50) for every extra account/setup required, which affects ranking but isn't shown in the final price.
> - **Promo Recurrence**: "One-time" promos only apply to the first plan from a provider; "unlimited" promos apply to all plans.
> - **Overrides**: `plan_overrides.json` handles special cases like "New User Only" plans, with separate sections for Europe and USA providers.
> 
> **File Structure**:
> - Europe: `scrape_europe_plans.py` → `esim_plans_europe.csv` → `optimize_esim_plans_multi_region.py --region europe`
> - USA: `scrape_usa_plans.py` → `esim_plans_usa.csv` → `optimize_esim_plans_multi_region.py --region usa`
