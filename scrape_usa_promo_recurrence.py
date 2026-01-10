"""
USA PROMO RECURRENCE SCRAPER - Fetches promo usage limits from esimdb USA provider pages.

This script visits each provider's USA page on esimdb to extract whether their promo code
is "One-time" or "Unlimited" use, since this info is NOT in the API.

Uses BeautifulSoup with the specific badge class that contains the promo type.
Optimized with ThreadPoolExecutor for concurrent scraping.
"""
import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os
import concurrent.futures
from tqdm import tqdm

# Cache file path
PROMO_CACHE_FILE = "promo_recurrence_cache_usa.json"
PROVIDERS_URL = "https://esimdb.com/api/client/providers"
BASE_PROVIDER_URL = "https://esimdb.com/usa/{slug}"

def get_all_providers():
    """Get list of all providers from API"""
    try:
        resp = requests.get(PROVIDERS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        return resp.json()
    except Exception as e:
        print(f"Error fetching providers list: {e}")
        return []

def scrape_promo_info(provider_data):
    """
    Scrape a provider's USA page to get promo recurrence info.
    Returns dict with promo_code, promo_type (one-time/unlimited/unknown), promo_discount
    """
    slug = provider_data.get("slug")
    if not slug:
        return None

    url = BASE_PROVIDER_URL.format(slug=slug)
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        soup = BeautifulSoup(resp.text, 'lxml')
        html = resp.text
        
        promo_code = None
        promo_type = "unknown"
        promo_discount = None
        
        # Method 1: Find badge with specific class (most reliable)
        # The promo type is in a div with classes: badge rounded-full text-caption
        badges = soup.find_all(class_=lambda c: c and 'badge' in c and 'rounded-full' in c and 'text-caption' in c)
        
        for badge in badges:
            text = badge.get_text(strip=True).lower()
            if 'one-time' in text or 'one time' in text:
                promo_type = "one-time"
                break
            elif 'unlimited' in text:
                promo_type = "unlimited"
                break
        
        # Find promo code (ESIMDB pattern)
        code_match = re.search(r'([A-Z0-9]+ESIMDB[A-Z0-9]*|ESIMDB[A-Z0-9]+)', html)
        if code_match:
            promo_code = code_match.group(1)
        
        # Find discount percentage
        discount_match = re.search(r'GET\s+(\d+)\s*%\s*OFF', html, re.IGNORECASE)
        if discount_match:
            promo_discount = int(discount_match.group(1))
        
        # Look for dollar discount
        if not promo_discount:
            dollar_match = re.search(r'\$(\d+(?:\.\d+)?)\s*(?:off|discount)', html, re.IGNORECASE)
            if dollar_match:
                promo_discount = f"${dollar_match.group(1)}"
        
        return {
            "provider_id": provider_data.get("_id"),
            "name": provider_data.get("name"),
            "slug": slug,
            "promo_type": promo_type,
            "promo_code": promo_code,
            "promo_discount": promo_discount,
        }
    except Exception as e:
        # print(f"  Error scraping {slug}: {e}") # Reduce noise
        return {
            "provider_id": provider_data.get("_id"),
            "name": provider_data.get("name"),
            "slug": slug,
            "promo_type": "error", 
            "promo_code": None, 
            "promo_discount": None
        }

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
    print("USA PROMO RECURRENCE SCRAPER (Optimized)")
    print("="*60)
    
    # Get all providers
    print("Fetching providers from API...")
    providers = get_all_providers()
    print(f"Found {len(providers)} providers")
    
    # Load existing cache (to skip already-scraped)
    cache = load_existing_cache()
    print(f"Existing cache: {len(cache)} providers")
    
    # Identify providers that need scraping
    providers_to_scrape = []
    for p in providers:
        pid = p.get("_id")
        if pid not in cache:
            providers_to_scrape.append(p)
            
    print(f"Providers to scrape: {len(providers_to_scrape)}")
    
    if not providers_to_scrape:
        print("All providers cached. Exiting.")
        return

    # Scrape concurrently
    results_buffer = []
    MAX_WORKERS = 10
    
    print(f"Starting scrape with {MAX_WORKERS} threads...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Map each provider to a future
        future_to_provider = {executor.submit(scrape_promo_info, p): p for p in providers_to_scrape}
        
        # Use tqdm for progress bar
        for future in tqdm(concurrent.futures.as_completed(future_to_provider), total=len(providers_to_scrape), unit="provider"):
            provider = future_to_provider[future]
            try:
                data = future.result()
                if data:
                    pid = data["provider_id"]
                    # Store simpler dict in cache
                    cache[pid] = {k: v for k, v in data.items() if k != "provider_id"}
                    
                    if len(cache) % 10 == 0:
                        save_cache(cache)
            except Exception as exc:
                print(f'{provider.get("name")} generated an exception: {exc}')
                
    # Final save
    save_cache(cache)
    
    # Statistics
    one_time = sum(1 for v in cache.values() if v.get("promo_type") == "one-time")
    unlimited = sum(1 for v in cache.values() if v.get("promo_type") == "unlimited")
    
    print()
    print("="*60)
    print(f"COMPLETE: {len(cache)} providers cached")
    print(f"  One-time promos: {one_time}")
    print(f"  Unlimited promos: {unlimited}")
    print(f"  Unknown/Other: {len(cache) - one_time - unlimited}")
    print(f"Saved to: {PROMO_CACHE_FILE}")
    print("="*60)

if __name__ == "__main__":
    main()
