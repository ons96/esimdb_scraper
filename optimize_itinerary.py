
"""
MULTI-COUNTRY OPTIMIZER

Finds cheapest plan combinations for a specific itinerary:
Germany -> Austria -> Czechia -> Slovakia

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
from math import comb

# Configuration
INPUT_FILE = "esim_plans_itinerary.csv"
OVERRIDES_FILE = "plan_overrides.json"
FULL_API_CACHE = "promo_recurrence_cache.json"

LOG_FILE = "optimizer_itinerary.log"
SEARCH_SPACE_SIZE = 40
MAX_COMBO_SIZE = 4
TOP_N_SOLUTIONS = 10

# Itinerary Requirements (Scaled to ~8.6GB Total as per user request)
# 8600 MB / 15 days = ~573 MB/day
ITINERARY = [
    {"name": "Germany", "days": 4.5, "mb": 2600, "slug": "germany"},
    {"name": "Austria", "days": 8.0, "mb": 4600, "slug": "austria"},
    {"name": "Czechia", "days": 2.0, "mb": 1200, "slug": "czechia"},
    {"name": "Slovakia", "days": 0.5, "mb": 300, "slug": "slovakia"},
]

TOTAL_DURATION = sum(step["days"] for step in ITINERARY)
DEFAULT_HASSLE_PENALTY = 0.50

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
        if "FairPlay FirstFill" in str(p.get("plan_name")):
             p["new_user_only"] = True
        
        # Tag Promo Type
        pid = p.get("provider_id")
        p["provider_promo_type"] = config["provider_promo_overrides"].get(pid, {}).get("promo_type", "unlimited")
        
        # Filter
        if p.get("usd_price") is not None and p.get("data_mb", 0) > 0 and p.get("validity_days") > 0:
            # Parse coverage countries
            try:
                # Handle CSV string conversion
                if isinstance(p["countries"], str):
                     p["coverage"] = set(json.loads(p["countries"]))
                else:
                     p["coverage"] = set()
            except:
                p["coverage"] = set()
            valid_plans.append(p)

    # Sort checks: Value (Price/GB)
    # Strategy: We need a mix of "Cheap Small Plans" and "Large Capacity Plans"
    # because user requires ~4.6GB in Austria, which 4 small plans can't cover.
    
    # 1. Cheap Plans (Value)
    regional_value = sorted([p for p in valid_plans if p["scope"]=="regional"], 
                          key=lambda x: (x.get("usd_promo_price") or x["usd_price"]) / x["data_mb"])
    local_value = sorted([p for p in valid_plans if p["scope"]=="local"], 
                       key=lambda x: (x.get("usd_promo_price") or x["usd_price"]) / x["data_mb"])
                       
    # 2. Large Plans (>= 3GB) - Essential for heavy users
    # Sort large plans by absolute price (cheapest large plan)
    regional_large = sorted([p for p in valid_plans if p["scope"]=="regional" and p["data_mb"] >= 3000],
                          key=lambda x: (x.get("usd_promo_price") or x["usd_price"]))
    local_large = sorted([p for p in valid_plans if p["scope"]=="local" and p["data_mb"] >= 3000],
                       key=lambda x: (x.get("usd_promo_price") or x["usd_price"]))
                       
    # Construct Diversified Search Space (Deduped)
    space_set = set()
    final_space = []
    
    def add_unique(candidates):
        for p in candidates:
            # Plan ID is unique? or object ref?
            # plans dicts are distinct objects but represent same row.
            # Use 'plan_id' + 'provider_id' as key? Or just object ID if list logic holds.
            # Let's use tuple of keys to check uniqueness in set
            k = (p["provider_id"], p["plan_name"], p["data_mb"]) # Good enough proxy
            if k not in space_set:
                space_set.add(k)
                final_space.append(p)
                
    add_unique(regional_value[:15])
    add_unique(local_value[:20])
    add_unique(regional_large[:10])
    add_unique(local_large[:15])
    
    search_space = final_space
    print(f"Search space: {len(search_space)} plans")

    # Calculate progress bar
    total_combos = 0
    n = len(search_space)
    for r in range(1, MAX_COMBO_SIZE + 1):
        total_combos += comb(n + r - 1, r)
        
    print(f"Evaluating {total_combos} combinations...")
    
    from tqdm import tqdm
    solutions = []
    cnt = 0
    start_time = time.time()
    
    with tqdm(total=total_combos, unit="combo") as pbar:
        for r in range(1, MAX_COMBO_SIZE + 1):
            for combo_indices in itertools.combinations_with_replacement(range(len(search_space)), r):
                 combo_plans = [search_space[i] for i in combo_indices]
                 
                 res = evaluate_itinerary(combo_plans, config["hassle_penalty"])
                 if res["valid"]:
                     cnt += 1
                     heapq.heappush(solutions, (res["ranking_cost"], cnt, res))
                 
                 pbar.update(1)
                 
    elapsed = time.time() - start_time
    # Output Header
    print("=" * 80)
    print("ESIM OPTIMIZER - MULTI-COUNTRY")
    print("=" * 80)
    print(f"Trip: {TOTAL_DURATION} days | {sum(s['mb'] for s in ITINERARY)/1000:.1f} GB needed")
    print(f"Search space: {len(search_space)} plans")
    print(f"Evaluating {total_combos:,} combinations...")
    print(f"Execution time: {elapsed:.2f} seconds")
    print("=" * 80)
    print("TOP 10 SOLUTIONS")
    print("=" * 80)
                 
    print(f"\nFound {len(solutions)} valid solutions.")
    solutions.sort(key=lambda x: x[0])
    
    for i, (cost, _, res) in enumerate(solutions[:TOP_N_SOLUTIONS], 1):
        print_solution(i, res)

def evaluate_itinerary(combo_plans, hassle_penalty):
    # Setup working copies
    plans = []
    # Identify providers for New User Check
    provider_new_user_count = defaultdict(int)
    
    # Calculate Daily Usage Rate for current Itinerary
    # User Requirement: ~587 MB/day
    total_mb_needed = sum(s["mb"] for s in ITINERARY)
    daily_usage_rate = total_mb_needed / TOTAL_DURATION
    
    for idx, p in enumerate(combo_plans):
        if p.get("new_user_only"):
             # STRICT: Max 1 new user plan per PROVIDER
             if provider_new_user_count[p["provider_id"]] > 0:
                 return {"valid": False, "ranking_cost": 0}
             provider_new_user_count[p["provider_id"]] += 1
             
        # Create a State Object for the plan
        pc = p.copy()
        pc["_id"] = idx 
        
        # Effective Data Logic:
        # A plan cannot contribute more than (validity * daily_usage)
        effective_mb = min(pc["data_mb"], pc["validity_days"] * daily_usage_rate)
        pc["effective_mb"] = effective_mb
        pc["remaining_mb"] = effective_mb
        
        # Effective Duration Logic:
        # A plan cannot last longer than (data / daily_usage)
        # 1GB plan @ 587MB/day -> ~1.7 days effective validity
        effective_days = min(pc["validity_days"], pc["data_mb"] / daily_usage_rate)
        pc["effective_days"] = effective_days
        
        if pc.get("data_cap_per") == "day":
             pc["daily_cap"] = pc["data_mb"]
        else:
             pc["daily_cap"] = None
        plans.append(pc)

    # 1. Timeline Simulation (The Core Fix)
    # We must cover the entire duration [0, TOTAL_DURATION]
    
    segments = []
    current_t = 0
    for step in ITINERARY:
        segments.append({
            "slug": step["slug"],
            "start": current_t,
            "end": current_t + step["days"],
            "mb_needed": step["mb"],
            "days": step["days"]
        })
        current_t += step["days"]
        
    if check_timeline_validity(plans, segments):
         pass
    else:
         return {"valid": False, "ranking_cost": 0}

    # Cost & Activations Calculation
    total_price = 0
    provider_seen_count = defaultdict(int)
    unique_providers = set()
    
    for p in plans:
        pid = p["provider_id"]
        unique_providers.add(pid)
        ptype = p["provider_promo_type"]
        reg_price = p.get("usd_price", 0)
        promo_price = p.get("usd_promo_price")
        
        has_promo = promo_price is not None and promo_price < reg_price
        
        # Determine if promo applies
        apply_promo = False
        if has_promo:
             if ptype == "one-time":
                 if provider_seen_count[pid] == 0:
                     apply_promo = True
             else:
                 apply_promo = True
        
        if apply_promo:
            price = promo_price
            p["_final_price"] = promo_price
            p["_price_note"] = "PROMO"
        else:
            price = reg_price
            p["_final_price"] = reg_price
            p["_price_note"] = "REG"
            
        if ptype == "one-time":
             provider_seen_count[pid] += 1
             
        total_price += price
        
    activations = len(unique_providers)
    top_ups = len(plans) - activations
    
    # Hassle Penalty: Applies to EXTRA activations (base 1 is free/needed) + top-ups?
    # Usually top-up is less hassle.
    # User config "hassle_penalty" usually means "Per Validation Event".
    # Let's keep logic simple: Penalty for every plan beyond the first.
    # The user wants ACCURATE counters, the ranking logic can stay simple or refine.
    # Current Ranking: (len(plans) - 1) * penalty. matches "Every extra plan needs action".
    
    hassle_cost = (len(plans) - 1) * hassle_penalty
    ranking_cost = total_price + hassle_cost

    return {
        "valid": True,
        "ranking_cost": ranking_cost,
        "display_cost": total_price,
        "plans": plans,
        "total_gb": sum(p["data_mb"] * (p["validity_days"] if p.get("data_cap_per")=="day" else 1) for p in plans)/1024,
        "total_days": sum(p["validity_days"] for p in plans),
        "activations": activations,
        "top_ups": top_ups
    }

def check_timeline_validity(plans, segments):
    return solve_segment(0, segments, plans)

def solve_segment(seg_idx, segments, plans):
    if seg_idx >= len(segments):
        return True
        
    seg = segments[seg_idx]
    needed = seg["mb_needed"]
    slug = seg["slug"]
    
    # Find candidates
    candidates = [p for p in plans if slug in p["coverage"]]
    
    # Sort by: (Already Started DESC, Expiry Time ASC)
    def sort_key(item):
        p = item[0]
        started = 1 if "_start_time" in p else 0
        rem_mb = item[1]
        return (-started, p["validity_days"])
        
    # Create valid candidates list with max contributions
    plan_contribs = []
    for p in candidates:
        starts_at = p.get("_start_time", seg["start"]) 
        # UPDATE: Check Expiration against EFFECTIVE Duration
        expires_at = starts_at + p["effective_days"]
        
        overlap_start = max(starts_at, seg["start"])
        overlap_end = min(expires_at, seg["end"])
        overlap_days = max(0, overlap_end - overlap_start)
        
        if overlap_days <= 0: continue
        
        if p.get("daily_cap"):
             max_mb = p["daily_cap"] * overlap_days
        else:
             max_mb = p["remaining_mb"]
             
        plan_contribs.append((p, max_mb))
        
    if sum(c[1] for c in plan_contribs) < needed: return False
    
    plan_contribs.sort(key=sort_key)
    
    left_to_fill = needed
    consumed_ops = [] 
    
    for p, possible in plan_contribs:
        if left_to_fill <= 0: break
        
        amount = min(possible, left_to_fill)
        
        if "_start_time" not in p:
             p["_start_time"] = seg["start"]
             consumed_ops.append((p, "_start_time", None))
             
        if not p.get("daily_cap"):
             p["remaining_mb"] -= amount
             consumed_ops.append((p, "remaining_mb", amount))
             
        left_to_fill -= amount
        
    if left_to_fill > 1:
        rollback(consumed_ops)
        return False
        
    if solve_segment(seg_idx + 1, segments, plans):
        return True
    else:
        rollback(consumed_ops)
        return False

def rollback(ops):
    for p, key, val in reversed(ops):
        if key == "_start_time":
            del p["_start_time"]
        elif key == "remaining_mb":
            p["remaining_mb"] += val

def print_solution(rank, res):
    print("-" * 60)
    print(f"SOLUTION #{rank}")
    print("-" * 60)
    
    # Currency
    usd = res['display_cost']
    cad = usd * 1.42
    free_cnt = sum(1 for p in res['plans'] if p['_final_price'] == 0)
    free_txt = f" [{free_cnt} FREE]" if free_cnt > 0 else ""
    
    # Format: COST: $5.23 USD / $7.43 CAD [1 FREE]
    print(f"COST: ${usd:.2f} USD / ${cad:.2f} CAD{free_txt}")
    
    # DATA: 8.8GB | DAYS: 180 | ACTIVATIONS: 3 | TOP-UPS: 0 | 3 accounts
    acc_str = f"{res['activations']} accounts"
    print(f"DATA: {res['total_gb']:.1f}GB (Effective) | DAYS: {res['total_days']} | ACTIVATIONS: {res['activations']} | TOP-UPS: {res['top_ups']} | {acc_str}")
    print("PLANS:")
    
    for p in res['plans']:
        # Format: 
        # - FairPlay (Regional): FairPlay FirstFill...
        # or
        # - MicroEsim (Local: germany): ...
        
        scope_str = "Regional"
        if p["scope"] == "local":
            # Extract country from coverage if available
            cov_list = list(p.get("coverage", []))
            c_code = cov_list[0] if cov_list else "?"
            scope_str = f"Local: {c_code}"
        else:
             # Identify target countries covered by this regional plan
             itinerary_slugs = [s["slug"] for s in ITINERARY]
             targets = [s for s in itinerary_slugs if s in p.get("coverage", [])]
             
             if len(targets) == len(itinerary_slugs):
                 scope_str = "Regional"
             elif targets:
                 t_str = ",".join(targets)
                 scope_str = f"Regional: {t_str}"
             else:
                 scope_str = "Regional"
        
        pn = p['provider_name']
        pln = p['plan_name']
        price_str = "FREE" if p['_final_price'] == 0 else f"${p['_final_price']:.2f}"
        if p['_price_note'] == "PROMO" and p['_final_price'] > 0:
             price_str += " [PROMO]"
             
        print(f"  - {pn} ({scope_str}): {pln}")
        
        # Show Effective Data if different from Raw
        eff_mb = p.get("effective_mb", p["data_mb"])
        raw_mb = p["data_mb"]
        if eff_mb < raw_mb:
            data_str = f"{eff_mb:.0f}MB (of {raw_mb}MB)"
        else:
            data_str = f"{raw_mb}MB"
            
        # Show Effective Duration if different from Raw
        eff_days = p.get("effective_days", p["validity_days"])
        if eff_days < p["validity_days"]:
            day_str = f"{eff_days:.1f} days (of {p['validity_days']} days)"
        else:
            day_str = f"{p['validity_days']} days"
            
        print(f"    {price_str} | {data_str} | {day_str}")
        if p['_price_note'] == "REG" and p.get("provider_promo_type") == "one-time":
             print("    ⚠️ Promo already used for this provider")
    print()

if __name__ == "__main__":
    main()
