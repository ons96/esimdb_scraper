
"""
MULTI-COUNTRY SCRAPER - Fetches eSIM plans for a specific itinerary list.

Fetches plans for: Germany, Austria, Czechia, Slovakia, and Europe (Regional).
Tags each plan with the countries it covers.

Optimizations:
- Parallel Fetching (ThreadPoolExecutor)
- File-based Caching (scraped_data/*.json)
"""
import requests
import pandas as pd
import datetime
import os
import json
import time
import concurrent.futures
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Configuration
API_URL_TEMPLATE = "https://esimdb.com/api/client/countries/{slug}/data-plans?locale=en"
REGIONAL_URL = "https://esimdb.com/api/client/regions/europe/data-plans?locale=en"
PROVIDER_CACHE_FILE = "provider_cache.json"
OUTPUT_FILE = "esim_plans_itinerary.csv"
CACHE_DIR = "scraped_data"
CACHE_DURATION_HOURS = 24

# Target regions
TARGET_COUNTRIES = {
    "germany": ["germany"],
    "austria": ["austria"],
    "czechia": ["czechia"],
    "slovakia": ["slovakia"],
}
# "europe" covers all of them (simplification for this specific trip)
REGIONAL_COVERAGE = ["germany", "austria", "czechia", "slovakia"]

# Exchange rates (static fallback)
EXCHANGE_RATES = {"EUR": 1.05, "GBP": 1.25, "CAD": 0.73, "AUD": 0.65}

def create_session():
    session = requests.Session()
    retry = Retry(connect=3, backoff_factor=1)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

SESSION = create_session()

def get_exchange_rates():
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        return resp.json().get("rates", {})
    except:
        return {}

def get_cached_response(slug):
    """Load response from cache if valid"""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
        
    cache_path = os.path.join(CACHE_DIR, f"cache_{slug}.json")
    if os.path.exists(cache_path):
        # Check age
        mtime = os.path.getmtime(cache_path)
        if (time.time() - mtime) < (CACHE_DURATION_HOURS * 3600):
            try:
                with open(cache_path, "r") as f:
                    return json.load(f)
            except:
                pass
    return None

def save_to_cache(slug, data):
    """Save response to cache"""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    
    cache_path = os.path.join(CACHE_DIR, f"cache_{slug}.json")
    try:
        with open(cache_path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Warning: Failed to cache data for {slug}: {e}")

def fetch_plans_worker(args):
    """Worker for threaded fetching"""
    slug, is_regional = args
    
    # Try cache first
    cached = get_cached_response(slug)
    if cached:
        print(f"[{slug}] Loaded from cache")
        plans = cached.get("plans", [])
        return slug, plans, is_regional
        
    # Fetch from API
    url = REGIONAL_URL if is_regional else API_URL_TEMPLATE.format(slug=slug)
    print(f"[{slug}] Fetching from API...")
    
    try:
        resp = SESSION.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        plans = data.get("plans", [])
        print(f"[{slug}] Got {len(plans)} plans")
        
        # Save to cache
        save_to_cache(slug, data)
        
        return slug, plans, is_regional
    except Exception as e:
        print(f"[{slug}] Error: {e}")
        return slug, [], is_regional

def parse_plan(plan, coverage, scope, provider_cache, usd_rates):
    """Parse raw API plan into flat dict"""
    
    # Extract Provider
    provider_val = plan.get("provider")
    if isinstance(provider_val, dict):
        pid = provider_val.get("_id")
        pname = provider_val.get("name")
    else:
        pid = str(provider_val)
        pname = provider_cache.get(pid, pid)
        
    # Pricing
    usd_price = plan.get("usdPrice")
    
    if usd_price is None:
        prices = plan.get("prices") or plan.get("price") or {}
        if "USD" in prices:
            usd_price = prices["USD"]
        else:
            currency = plan.get("currency")
            amount = plan.get("amount")
            if not amount and prices:
                for cur, amt in prices.items():
                    currency = cur
                    amount = amt
                    break
            
            if currency == "USD":
                usd_price = amount
            elif currency and amount is not None and currency in usd_rates:
                usd_price = amount * usd_rates[currency]
    
    # Promo logic
    usd_promo_price = plan.get("usdPromoPrice")
    if usd_promo_price is None and plan.get("promoPrices"):
        promos = plan.get("promoPrices")
        if "USD" in promos:
            usd_promo_price = promos["USD"]
            
    if usd_price is None:
        return None

    tethering = plan.get("tethering")
    
    return {
        "plan_id": plan.get("_id"),
        "provider_id": pid,
        "provider_name": pname,
        "plan_name": plan.get("enName") or plan.get("name"),
        "data_mb": plan.get("capacity"),
        "validity_days": plan.get("period"),
        "data_cap_per": plan.get("dataCapPer"), 
        "usd_price": usd_price,
        "usd_promo_price": usd_promo_price,
        "scope": scope,
        "raw_coverages": plan.get("coverages", []),
        "new_user_only": plan.get("newUserOnly", False),
        "can_top_up": plan.get("canTopUp", False),
        "tethering": tethering
    }

def main():
    rates_data = get_exchange_rates()
    if rates_data:
        usd_rates = {k: 1/v for k,v in rates_data.items() if v != 0}
        print(f"Loaded live exchange rates (EUR={rates_data.get('EUR')})")
    else:
        usd_rates = EXCHANGE_RATES.copy()
        print("Using static exchange rates fallback")

    # Load provider cache
    provider_cache = {}
    if os.path.exists(PROVIDER_CACHE_FILE):
        with open(PROVIDER_CACHE_FILE, "r") as f:
            provider_cache = json.load(f)

    all_plans_map = {}
    dropped_count = 0
    iso_map = {"DE": "germany", "AT": "austria", "CZ": "czechia", "SK": "slovakia"}

    # Prepare jobs
    jobs = []
    # Local Jobs
    for country in TARGET_COUNTRIES.keys():
        jobs.append((country, False))
    # Regional Job
    jobs.append(("europe", True))
    
    print(f"Starting parallel fetch for {len(jobs)} regions with ThreadPoolExecutor...")
    start_time = time.time()
    
    # Parallel Execution
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_plans_worker, jobs))
        
    elapsed = time.time() - start_time
    print(f"All fetches completed in {elapsed:.2f}s")

    # Process Results
    for slug, plans, is_regional in results:
        if is_regional:
            scope = "regional"
            base_coverage = [] # Rely on explicit first, fallback to REGIONAL_COVERAGE
        else:
            scope = "local"
            base_coverage = TARGET_COUNTRIES.get(slug, [])

        for p in plans:
            parsed = parse_plan(p, [], scope, provider_cache, usd_rates)
            if parsed:
                pid = parsed["plan_id"]
                if pid not in all_plans_map:
                    parsed["countries"] = set()
                    all_plans_map[pid] = parsed
                
                # Logic for coverage tagging
                explicit_found = False
                if parsed.get("raw_coverages"):
                    for iso in parsed["raw_coverages"]:
                        if iso in iso_map:
                            all_plans_map[pid]["countries"].add(iso_map[iso])
                            explicit_found = True
                            
                # Fallback logic
                if is_regional:
                    if not explicit_found:
                        all_plans_map[pid]["countries"].update(REGIONAL_COVERAGE)
                else:
                    # For local, implicit coverage is adding the country itself
                    all_plans_map[pid]["countries"].update(base_coverage)
                    
            else:
                dropped_count += 1

    # Convert to list and serialize coverage
    final_rows = []
    for p in all_plans_map.values():
        p["countries"] = json.dumps(list(p["countries"])) # Serialize for CSV
        final_rows.append(p)
        
    # Save
    if not final_rows:
        print(f"ERROR: No plans parsed successfully. Dropped {dropped_count} plans.")
        return
    
    df = pd.DataFrame(final_rows)
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved {len(df)} unique plans to {OUTPUT_FILE} (Dropped {dropped_count})")

if __name__ == "__main__":
    main()
