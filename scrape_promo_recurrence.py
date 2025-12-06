"""
PROMO RECURRENCE SCRAPER - Fetches promo usage limits from esimdb provider pages.

This script visits each provider page on esimdb to extract whether their promo code
is "One-time" or "Unlimited" use, since this info is NOT in the API.
"""
import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os

# Cache file path
PROMO_CACHE_FILE = "promo_recurrence_cache.json"
PROVIDERS_URL = "https://esimdb.com/api/client/providers"
BASE_PROVIDER_URL = "https://esimdb.com/region/europe/{slug}"

def get_all_providers():
    """Get list of all providers from API"""
    resp = requests.get(PROVIDERS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    return resp.json()

def scrape_promo_info(provider_slug):
    """
    Scrape a provider page to get promo recurrence info.
    Returns dict with promo_code, promo_type (one-time/unlimited/none), promo_discount
    """
    url = BASE_PROVIDER_URL.format(slug=provider_slug)
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        html = resp.text
        
        # Look for promo patterns in the HTML
        # The page typically shows: "GET X% OFF", "One-time" or "Unlimited", promo code
        
        # Try to find promo code and type using regex patterns
        promo_code = None
        promo_type = "unknown"
        promo_discount = None
        
        # Find the promo code first
        code_match = re.search(r'([A-Z0-9]+ESIMDB[A-Z0-9]*|ESIMDB[A-Z0-9]+)', html)
        if code_match:
            promo_code = code_match.group(1)
            code_pos = code_match.start()
            
            # Look for promo type within 500 chars BEFORE the promo code
            # This is where "One-time" or "Unlimited" label appears in the HTML
            before_code = html[max(0, code_pos-500):code_pos]
            
            # Find the LAST occurrence of these words before the code (closest to it)
            one_time_pos = max(before_code.rfind("One-time"), before_code.rfind("one-time"))
            unlimited_pos = before_code.rfind("Unlimited")  # Case sensitive for label
            
            # Whichever is closer to the code (higher position) wins
            if one_time_pos > unlimited_pos:
                promo_type = "one-time"
            elif unlimited_pos > one_time_pos:
                promo_type = "unlimited"
        
        # Look for discount percentage
        discount_match = re.search(r'GET\s+(\d+)\s*%\s*OFF', html, re.IGNORECASE)
        if discount_match:
            promo_discount = int(discount_match.group(1))
        
        # Look for dollar discount
        if not promo_discount:
            dollar_match = re.search(r'\$(\d+(?:\.\d+)?)\s*(?:off|discount)', html, re.IGNORECASE)
            if dollar_match:
                promo_discount = f"${dollar_match.group(1)}"
        
        return {
            "promo_type": promo_type,
            "promo_code": promo_code,
            "promo_discount": promo_discount,
        }
    except Exception as e:
        print(f"  Error scraping {provider_slug}: {e}")
        return {"promo_type": "error", "promo_code": None, "promo_discount": None}

def load_existing_cache():
    """Load existing cache to avoid re-scraping"""
    if os.path.exists(PROMO_CACHE_FILE):
        with open(PROMO_CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    """Save cache to file"""
    with open(PROMO_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

def main():
    print("="*60)
    print("PROMO RECURRENCE SCRAPER")
    print("="*60)
    
    # Get all providers
    print("Fetching providers from API...")
    providers = get_all_providers()
    print(f"Found {len(providers)} providers")
    
    # Load existing cache (to skip already-scraped)
    cache = load_existing_cache()
    print(f"Existing cache: {len(cache)} providers")
    
    # Scrape each provider
    scraped_count = 0
    one_time_count = 0
    unlimited_count = 0
    
    for p in providers:
        slug = p.get("slug", "")
        provider_id = p.get("_id", "")
        name = p.get("name", "")
        
        if not slug:
            continue
        
        # Skip if already in cache
        if provider_id in cache:
            if cache[provider_id].get("promo_type") == "one-time":
                one_time_count += 1
            elif cache[provider_id].get("promo_type") == "unlimited":
                unlimited_count += 1
            continue
        
        print(f"Scraping {name} ({slug})...", end=" ")
        promo_info = scrape_promo_info(slug)
        
        cache[provider_id] = {
            "name": name,
            "slug": slug,
            **promo_info
        }
        
        status = promo_info["promo_type"]
        if status == "one-time":
            one_time_count += 1
        elif status == "unlimited":
            unlimited_count += 1
        
        print(status)
        scraped_count += 1
        
        # Rate limit to be nice to the server
        time.sleep(0.5)
        
        # Save periodically
        if scraped_count % 20 == 0:
            save_cache(cache)
            print(f"  (saved {len(cache)} providers)")
    
    # Final save
    save_cache(cache)
    
    print()
    print("="*60)
    print(f"COMPLETE: {len(cache)} providers cached")
    print(f"  One-time promos: {one_time_count}")
    print(f"  Unlimited promos: {unlimited_count}")
    print(f"  Unknown/Other: {len(cache) - one_time_count - unlimited_count}")
    print(f"Saved to: {PROMO_CACHE_FILE}")
    print("="*60)

if __name__ == "__main__":
    main()
