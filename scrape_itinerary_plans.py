
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

    all_rows = []
    dropped_count = 0
    
    # 1. Fetch Local Plans
    for country, coverage in TARGET_COUNTRIES.items():
        plans = fetch_plans(country)
        for p in plans:
            row = parse_plan(p, coverage, "local", provider_cache, usd_rates)
            if row:
                all_rows.append(row)
            else:
                dropped_count += 1
        time.sleep(1)

    # 2. Fetch Regional Plans
    regional_plans = fetch_plans("europe", is_regional=True)
    for p in regional_plans:
        row = parse_plan(p, REGIONAL_COVERAGE, "regional", provider_cache, usd_rates)
        if row:
            all_rows.append(row)
        else:
            dropped_count += 1

    # Save
    if not all_rows:
        print(f"ERROR: No plans parsed successfully. Dropped {dropped_count} plans.")
        # Print one failure reason
        if regional_plans:
            print("Debug check on first regional plan:")
            p0 = regional_plans[0]
            print(f"Currency: {p0.get('currency', 'MISSING')}, Amount: {p0.get('amount')}, USD Rates keys: {list(usd_rates.keys())}")
    
    df = pd.DataFrame(all_rows)
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved {len(df)} plans to {OUTPUT_FILE} (Dropped {dropped_count})")

def parse_plan(plan, coverage, scope, provider_cache, usd_rates):
    """Parse raw API plan into flat dict"""
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
    
    return {
        "plan_id": plan.get("_id"),
        "provider_id": pid,
        "provider_name": pname,
        "plan_name": plan.get("enName") or plan.get("name"),
        "data_mb": plan.get("capacity"),
        "validity_days": plan.get("period"),
        "usd_price": usd_price,
        "usd_promo_price": usd_promo_price,
        "scope": scope,  # local or regional
        "countries": json.dumps(coverage), # Store as JSON string for CSV
        "new_user_only": plan.get("newUserOnly", False),
        "can_top_up": plan.get("canTopUp", False),
        "tethering": tethering
    }

if __name__ == "__main__":
    main()
