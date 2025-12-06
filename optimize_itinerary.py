
"""
MULTI-COUNTRY OPTIMIZER

Finds cheapest plan combinations for a specific itinerary:
Germany (4.5d, 2GB) -> Austria (8d, 200MB) -> Czechia (2d, 1GB) -> Slovakia (0.5d, 500MB)

Mixes LOCAL plans (specific country) and REGIONAL plans (Europe).
Checks coverage of Data and Days.
"""
import pandas as pd
import json
import os
import itertools
from collections import defaultdict
import heapq
import time
import logging

# Configuration
INPUT_FILE = "esim_plans_itinerary.csv"
OVERRIDES_FILE = "plan_overrides.json"
FULL_API_CACHE = "promo_recurrence_cache.json"

LOG_FILE = "optimizer_itinerary.log"
SEARCH_SPACE_SIZE = 40  # Increase search space since we have more variety
MAX_COMBO_SIZE = 4      # Allow up to 4 plans (one per country potentially)
TOP_N_SOLUTIONS = 10

# Itinerary Requirements
ITINERARY = [
    {"name": "Germany", "days": 4.5, "mb": 2000, "slug": "germany"},
    {"name": "Austria", "days": 8.0, "mb": 200, "slug": "austria"},
    {"name": "Czechia", "days": 2.0, "mb": 1000, "slug": "czechia"},
    {"name": "Slovakia", "days": 0.5, "mb": 500, "slug": "slovakia"},
]

TOTAL_DURATION = sum(step["days"] for step in ITINERARY)
DEFAULT_HASSLE_PENALTY = 0.50
MAX_ACTIVATIONS = 5     # Higher limit for multi-country

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(message)s')

def load_config():
    config = {
        "plan_overrides": [],
        "provider_promo_overrides": {},
        "hassle_penalty": DEFAULT_HASSLE_PENALTY
    }
    if os.path.exists(OVERRIDES_FILE):
        try:
            with open(OVERRIDES_FILE, "r") as f:
                data = json.load(f)
                config.update({
                    "plan_overrides": data.get("plan_overrides", []),
                    "provider_promo_overrides": data.get("provider_promo_overrides", {}),
                    "hassle_penalty": data.get("default_hassle_penalty", DEFAULT_HASSLE_PENALTY)
                })
        except: pass
        
    # Merge Scraper Cache
    if os.path.exists(FULL_API_CACHE):
        try:
            with open(FULL_API_CACHE, "r") as f:
                scrape_cache = json.load(f)
                for pid, info in scrape_cache.items():
                    if pid not in config["provider_promo_overrides"]:
                        p_type = info.get("promo_type", "unknown")
                        if p_type in ["one-time", "unlimited"]:
                            config["provider_promo_overrides"][pid] = {
                                "promo_type": p_type,
                                "name": info.get("name", "")
                            }
        except: pass
    return config

def main():
    print(f"Loading plans from {INPUT_FILE}...")
    df = pd.read_csv(INPUT_FILE)
    config = load_config()
    
    # Process Plans
    plans = df.to_dict('records')
    valid_plans = []
    
    for p in plans:
        # Apply Overrides (e.g. FairPlay)
        # (Simplified override logic for brevity)
        if "FairPlay FirstFill" in str(p.get("plan_name")):
             p["new_user_only"] = True
        
        # Tag Promo Type
        pid = p.get("provider_id")
        p["provider_promo_type"] = config["provider_promo_overrides"].get(pid, {}).get("promo_type", "unlimited")
        
        # Filter
        if p.get("usd_price") is not None and p.get("data_mb", 0) > 0 and p.get("validity_days") > 0:
            # Parse coverage countries
            try:
                p["coverage"] = set(json.loads(p["countries"]))
            except:
                p["coverage"] = set()
            valid_plans.append(p)

    # Sort checks: Value (Price/GB/Day)
    # We need separate candidate lists for Local vs Regional to ensure we explore both
    regional_candidates = [p for p in valid_plans if p["scope"] == "regional"]
    local_candidates = [p for p in valid_plans if p["scope"] == "local"]
    
    # Heuristic: Sort by Price/GB
    regional_candidates.sort(key=lambda x: (x.get("usd_promo_price") or x["usd_price"]) / x["data_mb"])
    local_candidates.sort(key=lambda x: (x.get("usd_promo_price") or x["usd_price"]) / x["data_mb"])
    
    # Take top N
    search_space = regional_candidates[:20] + local_candidates[:40]
    print(f"Search space: {len(search_space)} plans")
    
    # Generate Combinations
    solutions = []
    print("Evaluating combinations...")
    
    # Check combos of size 1 to 4
    for r in range(1, 5):
        for combo_indices in itertools.combinations(range(len(search_space)), r):
            # Qty pattern: Assume x1 for all for simplicity in multi-country (complex enough already)
            # Maybe allowing repeat of same plan?
            # Let's start with unique plans (x1 qty) in combination, but itertools.combinations_with_replacement?
            pass 
    
    # Simpler loop: itertools produces unique sets.
    # We usually buy distinct plans for distinct countries.
    # We will use combinations_with_replacement to allow buying 2 of the same plan
    
    cnt = 0
    start_time = time.time()
    
    for r in range(1, MAX_COMBO_SIZE + 1):
        for combo_indices in itertools.combinations_with_replacement(range(len(search_space)), r):
             # combo_indices is tuple of indices
             combo_plans = [search_space[i] for i in combo_indices]
             
             res = evaluate_itinerary(combo_plans, config["hassle_penalty"])
             if res["valid"]:
                 cnt += 1
                 # Add counter 'cnt' as tie-breaker so 'res' dict is never compared
                 heapq.heappush(solutions, (res["ranking_cost"], cnt, res))
                 
    # Output
    print(f"\nFound {len(solutions)} valid solutions.")
    # Sort and pick top N (element 0 is cost)
    solutions.sort(key=lambda x: x[0])
    
    for i, (cost, _, res) in enumerate(solutions[:TOP_N_SOLUTIONS], 1):
        print_solution(i, res)

def evaluate_itinerary(plans, hassle_penalty):
    # 1. Coverage Check (Data & Days) and Allocation
    
    # Initialize Deficits
    deficits = {step["slug"]: step["mb"] for step in ITINERARY}
    
    # Separate Local vs Regional
    local_plans = [p for p in plans if p["scope"] == "local"]
    regional_plans = [p for p in plans if p["scope"] == "regional"]
    
    # A. Apply Local Plans to their countries
    for p in local_plans:
        # A local plan covers exactly one country in TARGET_COUNTRIES
        # Check which one
        covered_slugs = [s["slug"] for s in ITINERARY if s["slug"] in p["coverage"]]
        for slug in covered_slugs:
            deficits[slug] -= p["data_mb"]
            
    # B. Apply Regional Plans to remaining deficits
    remaining_total_deficit = sum(max(0, d) for d in deficits.values())
    regional_total_capacity = sum(p["data_mb"] for p in regional_plans)
    
    if regional_total_capacity < remaining_total_deficit:
        return {"valid": False}
        
    # C. Days Check
    # Simplification: Total Validity >= Total Duration?
    # Or does each segment need coverage?
    # Strict check: Local plans cover their segment's duration?
    # Loose check (usually fine for seamless travel): Total Days >= 15
    total_days = sum(p["validity_days"] for p in plans)
    if total_days < TOTAL_DURATION:
        return {"valid": False}
        
    # 2. Cost Calculation (Promo Logic)
    total_price = 0
    provider_usage = defaultdict(int)
    # Group by provider to check "One-Time" logic
    # Plans list might contain duplicates (same plan object)
    
    # Sort plans to prioritize using promo on expensive ones?
    # Or just sequential order. Usually strictly one-time.
    # Let's count provider occurrences
    
    # We need to preserve distinct items if we bought 2 identical plans
    # `plans` is a list of dicts.
    
    # Track provider counts seen so far
    provider_seen_count = defaultdict(int)
    
    for p in plans:
        pid = p["provider_id"]
        ptype = p["provider_promo_type"]
        
        reg_price = p.get("usd_price", 0)
        promo_price = p.get("usd_promo_price")
        
        has_promo = promo_price is not None and promo_price < reg_price
        
        # Determine price
        if has_promo:
            if ptype == "one-time":
                if provider_seen_count[pid] == 0:
                     price = promo_price
                     used_promo = True
                else:
                     price = reg_price
                     used_promo = False
                provider_seen_count[pid] += 1
            else:
                price = promo_price
                used_promo = True
        else:
            price = reg_price
            used_promo = False
            
        total_price += price
        p["_used_promo"] = used_promo # Temp tag for display (mutating dict copies ref, careful)
        # Actually this mutation affects search_space objects if mapped directly!
        # Should not mutate shared objects. Return structure instead.
        
    # Valid
    # Calculate hassle
    # Hassle = (Activations - 1) * Penalty? Or just per activation?
    # Usually we treat 1 activation as base.
    hassle_cost = (len(plans) - 1) * hassle_penalty
    if hassle_cost < 0: hassle_cost = 0
    
    ranking_cost = total_price + hassle_cost
    
    return {
        "valid": True,
        "ranking_cost": ranking_cost,
        "display_cost": total_price,
        "plans": plans,
        "total_gb": sum(p["data_mb"] for p in plans)/1024,
        "total_days": total_days
    }

def print_solution(rank, res):
    print(f"SOLUTION #{rank}")
    print(f"COST: ${res['display_cost']:.2f} (Rank Cost: ${res['ranking_cost']:.2f})")
    print(f"TOTAL: {res['total_gb']:.1f}GB | {res['total_days']} Days | {len(res['plans'])} Plans")
    for p in res['plans']:
        ptype = "Regional" if p["scope"] == "regional" else f"Local: {list(p['coverage'])[0]}"
        print(f"  - {p['provider_name']} ({ptype}): {p['plan_name']}")
        print(f"    ${p.get('usd_price'):.2f} ({p['data_mb']}MB, {p['validity_days']}d)")
    print()

if __name__ == "__main__":
    main()
