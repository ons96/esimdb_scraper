
# Phase 2: Multi-Country Itinerary Optimization

## Goal
Optimize eSIM costs for a specific multi-country itinerary, allowing the mix of **Local** (single country) and **Regional** (Europe) plans to find the global minimum cost.

## User Itinerary
1. **Germany**: 4.5 days (~2GB)
2. **Austria**: 8.0 days (~200MB - low usage)
3. **Czechia**: 2.0 days (~1GB)
4. **Slovakia**: 0.5 days (~500MB)
*Total Duration*: ~15 days.

## Proposed Architecture

### 1. Multi-Country Scraper (`scrape_itinerary_plans.py`)
- **Input**: List of countries (`germany`, `austria`, `czechia`, `slovakia`, `europe`).
- **Action**: Fetch plans for each country from API.
- **Processing**:
    - Tag plans with `coverage_type`: 'local' or 'regional'.
    - Tag plans with `countries`: `['germany']` for local, `['germany', 'austria', ...]` for regional.
- **Output**: `esim_plans_itinerary.csv` (consolidated list).

### 2. Itinerary Optimizer (`optimize_itinerary.py`)
- **Input**:
    - `esim_plans_itinerary.csv`
    - `ITINERARY` config (list of segments with days/MB).
- **Logic**:
    - Generate combinations of plans (Local & Regional).
    - **Coverage Validation**:
        - For each step in itinerary, ensure allocated plans have enough capacity.
        - *Logic*:
            1. Use **Local** plans to cover their specific country first.
            2. Use **Regional** plans to cover remaining deficits in any country.
            3. If all deficits <= 0, combination is VALID.
    - **Costing**:
        - Same detailed logic as Phase 1 (Promos, One-time rules, Hassle penalty).
- **Output**: Best combinations of Local + Regional plans.

## Verification
- Verify that a solution mixing "Germany Local" + "Europe Regional" (for the rest) is considered.
- Verify "Hassle Penalty" correctly discourages buying 4 separate local plans (too many installs).

## Timeline
1. Create `scrape_itinerary_plans.py`
2. Create `optimize_itinerary.py`
3. Run and Compare results with Phase 1.
