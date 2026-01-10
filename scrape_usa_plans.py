"""
ESIMDB USA Scraper - Fetches eSIM plan data from the ESIMDB API.
Saves both raw JSON (for debugging) and cleaned CSV with essential columns.
"""
import requests
import pandas as pd
import json
import os
from datetime import datetime

# --- CONFIGURATION ---
TARGET_COUNTRY = "US"  # United States country code
API_URL = "https://esimdb.com/api/client/regions/north-america/data-plans?locale=en"
PROVIDER_CACHE_FILE = "provider_cache_usa.json"
# ---------------------

def get_live_rates():
    """Fetch live exchange rates with fallback (USD is base)"""
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        data = resp.json()
        if data.get("result") == "success":
            print("✓ Got live exchange rates")
            return data["rates"]
    except:
        pass
    
    print("⚠ Using fallback exchange rates")
    return {"USD": 1.0, "CAD": 1.37, "EUR": 0.92, "GBP": 0.79}

def load_provider_cache():
    """Load cached provider ID -> name mapping"""
    if os.path.exists(PROVIDER_CACHE_FILE):
        try:
            with open(PROVIDER_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                if cache:  # Only return if not empty
                    return cache
        except:
            pass
    return {}

def fetch_providers():
    """Fetch provider names from the API"""
    print("Fetching provider names from API...")
    try:
        resp = requests.get(
            "https://esimdb.com/api/client/providers",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=30
        )
        resp.raise_for_status()
        providers = resp.json()
        
        # Build ID -> name mapping
        cache = {}
        for p in providers:
            if "_id" in p and "name" in p:
                cache[p["_id"]] = p["name"]
        
        print(f"✓ Got {len(cache)} provider names")
        return cache
    except Exception as e:
        print(f"⚠ Could not fetch providers: {e}")
        return {}

def save_provider_cache(cache):
    """Save provider cache to disk"""
    with open(PROVIDER_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

def extract_provider_info(provider_val, provider_cache):
    """Extract provider ID and name from API response"""
    if isinstance(provider_val, dict):
        provider_id = provider_val.get("_id", "")
        provider_name = provider_val.get("name", "")
        if provider_name and provider_id:
            provider_cache[provider_id] = provider_name
        return provider_id, provider_name if provider_name else provider_id
    else:
        provider_id = str(provider_val) if provider_val else ""
        # Check cache for name
        provider_name = provider_cache.get(provider_id, provider_id)
        return provider_id, provider_name

def scrape_usa_plans():
    """Fetch and parse eSIM plans from the ESIMDB API"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    print("Fetching North America plans from API (will filter for USA)...")
    try:
        resp = requests.get(API_URL, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error fetching API: {e}")
        return [], []

    all_plans = data.get("plans", [])
    print(f"Got {len(all_plans)} plans (North America)")
    
    # Save raw JSON for debugging
    with open("esim_api_usa_raw.json", "w", encoding="utf-8") as f:
        json.dump(all_plans, f, indent=2)
    print("Saved raw API response to esim_api_usa_raw.json")

    # Load or fetch provider cache
    provider_cache = load_provider_cache()
    if not provider_cache:
        provider_cache = fetch_providers()
        if provider_cache:
            save_provider_cache(provider_cache)
    
    exchange_rates = get_live_rates()
    
    clean_plans = []

    for plan in all_plans:
        # Filter for USA-only plans or plans that include USA
        coverages = plan.get("coverages", [])
        if TARGET_COUNTRY not in coverages:
            continue
        
        # Also filter out plans that cover too many countries (e.g., global plans)
        # Focus on USA-specific or North America-specific plans
        if len(coverages) > 5:  # Exclude global plans
            continue
        
        # Provider info
        provider_id, provider_name = extract_provider_info(
            plan.get("provider", ""), provider_cache
        )

        # Pricing - keep BOTH regular and promo prices
        usd_price = plan.get("usdPrice")  # Regular price (always populated)
        usd_promo_price = plan.get("usdPromoPrice")  # Promo price (may be None)
        
        # Determine the effective "best" price for first purchase
        if usd_promo_price is not None and usd_promo_price < (usd_price or float('inf')):
            effective_price = usd_promo_price
            is_promo = True
        else:
            effective_price = usd_price
            is_promo = False
        
        # Speed/throttling info
        speed_limit = plan.get("speedLimit")  # Speed cap in kbps
        reduced_speed = plan.get("reducedSpeed")  # Speed after data cap
        possible_throttling = plan.get("possibleThrottling", False)
        
        # Plan features
        can_top_up = plan.get("canTopUp")
        new_user_only = plan.get("newUserOnly", False)
        promo_enabled = plan.get("promoEnabled", False)
        has_5g = plan.get("has5G", False)
        ekyc = plan.get("eKYC", False)
        tethering = plan.get("tethering")
        subscription = plan.get("subscription", False)
        pay_as_you_go = plan.get("payAsYouGo", False)
        has_ads = plan.get("hasAds", False)
        
        # Data capacity (MB)
        capacity = plan.get("capacity", 0)
        period = plan.get("period", 0)
        
        # Additional info for display
        data_cap_per = plan.get("dataCapPer")  # "day" if daily limit
        
        clean_plans.append({
            # IDs
            "plan_id": plan.get("_id", ""),
            "provider_id": provider_id,
            "provider_name": provider_name,
            
            # Plan details
            "plan_name": plan.get("enName") or plan.get("name", ""),
            "data_mb": capacity,
            "validity_days": period,
            "data_cap_per": data_cap_per,  # "day" if daily reset
            
            # Pricing (BOTH columns!)
            "usd_price": usd_price,
            "usd_promo_price": usd_promo_price,
            "effective_price": effective_price,
            "is_promo": is_promo,
            "price_cad": effective_price * exchange_rates.get("CAD", 1.37) if effective_price else None,
            
            # Restrictions
            "new_user_only": new_user_only,
            "promo_enabled": promo_enabled,
            "can_top_up": can_top_up,
            "subscription": subscription,
            "pay_as_you_go": pay_as_you_go,
            "ekyc": ekyc,
            
            # Speed/throttling
            "speed_limit": speed_limit,
            "reduced_speed": reduced_speed,
            "possible_throttling": possible_throttling,
            
            # Features
            "has_5g": has_5g,
            "tethering": tethering,
            "has_ads": has_ads,
            
            # Coverage
            "num_countries": len(coverages),
            "covers_usa": True,
        })

    # Save provider cache
    save_provider_cache(provider_cache)
    print(f"Provider cache: {len(provider_cache)} providers")

    return clean_plans, all_plans

def main():
    print("="*80)
    print("ESIMDB USA SCRAPER")
    print(f"Target country: {TARGET_COUNTRY} (filtering from North America API)")
    print("="*80)
    
    plans, raw_plans = scrape_usa_plans()
    
    if not plans:
        print("No plans scraped.")
        return

    df = pd.DataFrame(plans)

    # Add display columns
    df["data_display"] = df.apply(
        lambda x: f"{x['data_mb']/1024:.1f}GB" if x['data_mb'] >= 1024 else f"{x['data_mb']}MB",
        axis=1
    )
    df["validity_display"] = df["validity_days"].apply(lambda x: f"{x} days" if x > 0 else "No expiry")
    
    # Stats
    print(f"\nTotal USA plans: {len(df)}")
    
    # Calculate attribute frequencies for smart warnings
    if len(df) > 0:
        can_top_up_pct = df["can_top_up"].fillna(False).mean()
        tethering_pct = df["tethering"].fillna(True).mean()
        has_ads_pct = df["has_ads"].fillna(False).mean()
        ekyc_pct = df["ekyc"].fillna(False).mean()
        
        print(f"\nAttribute frequencies:")
        print(f"  Can top up: {can_top_up_pct*100:.1f}%")
        print(f"  Tethering allowed: {tethering_pct*100:.1f}%")
        print(f"  Has ads: {has_ads_pct*100:.1f}%")
        print(f"  Requires eKYC: {ekyc_pct*100:.1f}%")
    
    # Save files
    output_file = "esim_plans_usa.csv"
    df.to_csv(output_file, index=False)
    print(f"\nSaved plans to {output_file}")
    
    print("\nRun optimize_esim_plans.py next to find the best combinations.")

if __name__ == "__main__":
    main()
