
"""
MULTI-COUNTRY SCRAPER - Fetches eSIM plans for a specific itinerary list.

Fetches plans for: Germany, Austria, Czechia, Slovakia, and Europe (Regional).
Tags each plan with the countries it covers.
"""
import requests
import pandas as pd
import datetime
import os
import json
import time

# Configuration
API_URL_TEMPLATE = "https://esimdb.com/api/client/countries/{slug}/data-plans?locale=en"
REGIONAL_URL = "https://esimdb.com/api/client/regions/europe/data-plans?locale=en"
PROVIDER_CACHE_FILE = "provider_cache.json"
OUTPUT_FILE = "esim_plans_itinerary.csv"

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

def get_exchange_rates():
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        return resp.json().get("rates", {})
    except:
        return {}

from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

def create_session():
    session = requests.Session()
    retry = Retry(connect=3, backoff_factor=1)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

SESSION = create_session()

def fetch_plans(slug, is_regional=False):
    """Fetch plans for a country slug or region"""
    url = REGIONAL_URL if is_regional else API_URL_TEMPLATE.format(slug=slug)
    print(f"Fetching {slug} ({'Regional' if is_regional else 'Local'})...")
    
    try:
        resp = SESSION.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        data = resp.json()
        plans = data.get("plans", [])
        print(f"  > Got {len(plans)} plans")
        return plans
    except Exception as e:
        print(f"Error fetching {slug}: {e}")
        return []

def main():
    rates_data = get_exchange_rates()
    # Use live rates if available, else static
    if rates_data:
        # Live: 1 USD = X EUR. So 1 EUR = 1/X USD.
        usd_rates = {k: 1/v for k,v in rates_data.items() if v != 0}
        print(f"Loaded live exchange rates (EUR={rates_data.get('EUR')})")
    else:
        # Static: Defined as 1 Unit = X USD (roughly)
        # e.g. EUR: 1.05 means 1 EUR = 1.05 USD
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

    # 1. Fetch Local Plans
    for country, coverage in TARGET_COUNTRIES.items():
        plans = fetch_plans(country)
        for p in plans:
            parsed = parse_plan(p, [], "local", provider_cache, usd_rates)
            if parsed:
                pid = parsed["plan_id"]
                if pid not in all_plans_map:
                    parsed["countries"] = set()
                    all_plans_map[pid] = parsed
                
                # Explicit Coverage (if present in local plan)
                if parsed.get("raw_coverages"):
                    for iso in parsed["raw_coverages"]:
                        if iso in iso_map:
                            all_plans_map[pid]["countries"].add(iso_map[iso])
                            
                # Implicit Coverage (from Endpoint)
                all_plans_map[pid]["countries"].update(coverage)
            else:
                dropped_count += 1
        time.sleep(1)

    # 2. Fetch Regional Plans
    regional_plans = fetch_plans("europe", is_regional=True)
    for p in regional_plans:
        parsed = parse_plan(p, [], "regional", provider_cache, usd_rates)
        if parsed:
            pid = parsed["plan_id"]
            if pid not in all_plans_map:
                parsed["countries"] = set()
                all_plans_map[pid] = parsed
            
            # Explicit Coverage (CRITICAL for Europe plans)
            explicit_found = False
            if parsed.get("raw_coverages"):
                for iso in parsed["raw_coverages"]:
                    if iso in iso_map:
                        all_plans_map[pid]["countries"].add(iso_map[iso])
                        explicit_found = True
            
            # If explicit list was found, we trust it purely?
            # User said "check for presence".
            # If NO explicit list found, fallback to assuming it covers all targets
            if not explicit_found:
                 all_plans_map[pid]["countries"].update(REGIONAL_COVERAGE)
            
            all_plans_map[pid]["scope"] = "regional"
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
        # ... (debug print kept same) ...
    
    df = pd.DataFrame(final_rows)
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved {len(df)} unique plans to {OUTPUT_FILE} (Dropped {dropped_count})")

def parse_plan(plan, coverage, scope, provider_cache, usd_rates):
    """Parse raw API plan into flat dict - Coverage is handled by caller now"""
    # ... (Reuse Logic from scrape_europe_plans.py but allow variable coverage)
    
    # Extract Provider
    provider_val = plan.get("provider")
    if isinstance(provider_val, dict):
        pid = provider_val.get("_id")
        pname = provider_val.get("name")
    else:
        pid = str(provider_val)
        pname = provider_cache.get(pid, pid)
        
    # Pricing
    # API endpoints vary: some use 'usdPrice', some use 'price.USD', some 'prices.USD'
    usd_price = plan.get("usdPrice")
    
    if usd_price is None:
        # Check nested structures
        prices = plan.get("prices") or plan.get("price") or {}
        if "USD" in prices:
            usd_price = prices["USD"]
        else:
            # Try to convert from other currency
            currency = plan.get("currency")
            amount = plan.get("amount")
            
            # Sometimes info is in 'prices' dict
            if not amount and prices:
                # Take first available price to convert
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

    # Features
    tethering = plan.get("tethering") # None/True = Yes, False = No
    
    # Coverage (ISO Codes)
    if plan.get("coverages"):
        # Map ISO to slugs
        iso_map = {"DE": "germany", "AT": "austria", "CZ": "czechia", "SK": "slovakia"}
        for iso in plan["coverages"]:
            if iso in iso_map:
                # Add to set (handled by caller, but we return it in parsed dict for caller to merge)
                # Caller logic is: all_plans_map[pid]["countries"].update(coverage)
                # But coverage passed to parse_plan might be empty.
                # We need to return the strict coverage found in the object.
                pass
                
    return {
        "plan_id": plan.get("_id"),
        "provider_id": pid,
        "provider_name": pname,
        "plan_name": plan.get("enName") or plan.get("name"),
        "data_mb": plan.get("capacity"),
        "validity_days": plan.get("period"),
        "data_cap_per": plan.get("dataCapPer"), # 'day' if daily limit
        "usd_price": usd_price,
        "usd_promo_price": usd_promo_price,
        "scope": scope,
        "raw_coverages": plan.get("coverages", []), # Return raw list for caller to process
        "new_user_only": plan.get("newUserOnly", False),
        "can_top_up": plan.get("canTopUp", False),
        "tethering": tethering
    }

if __name__ == "__main__":
    main()
