"""
ESIM OPTIMIZER - Find the best eSIM plan combinations for your trip.

Multi-region version supporting both Europe and USA.

Features:
- Progress bar with tqdm
- Hassle penalties for new account creation (hidden from display cost)
- Per-provider promo tracking (promo assumed one-time per provider)
- Max eSIM activations and max top-ups limits
- Per-plan inline warnings
"""
import pandas as pd
import json
import os
import time
import heapq
import logging
import argparse
from datetime import datetime
from itertools import combinations
from collections import defaultdict

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

# --- CONFIGURATION ---
TRIP_DAYS = 15
TOTAL_DATA_GB = 8.6
TOP_N_SOLUTIONS = 10  # Number of solutions to display

# Limits for plan complexity
MAX_ESIM_ACTIVATIONS = 3   # Max different providers/plans requiring new eSIM activation
MAX_TOPUPS = 15            # Max top-ups/repurchases of same plan

MAX_COMBO_SIZE = 5         # Max number of different plans in a combination
SEARCH_SPACE_SIZE = 50     # Top N plans to consider

DEFAULT_PROMO_TYPE = "unlimited"
DEFAULT_HASSLE_PENALTY = 0.50  # Per additional account needed

# Threshold for "low speed" warnings (kbps)
LOW_SPEED_THRESHOLD = 1000  # 1 Mbps - below this, streaming may buffer
# ---------------------

TOTAL_DATA_MB = TOTAL_DATA_GB * 1024
DAILY_DATA_NEED = TOTAL_DATA_MB / TRIP_DAYS

LOG_FILE = "optimizer_run.log"

# Region-specific file paths
REGION_CONFIG = {
    "europe": {
        "input_file": "esim_plans_europe_filtered.csv",
        "promo_cache": "promo_recurrence_cache.json",
        "overrides": "plan_overrides.json",
    },
    "usa": {
        "input_file": "esim_plans_usa.csv",
        "promo_cache": "promo_recurrence_cache_usa.json",
        "overrides": "plan_overrides.json",  # Same file for now
    }
}

def load_overrides_config(overrides_file, promo_cache_file):
    """Load plan overrides and config from JSON file"""
    config = {
        "plan_overrides": [],
        "provider_promo_overrides": {},
        "default_promo_type": DEFAULT_PROMO_TYPE,
        "hassle_penalty": DEFAULT_HASSLE_PENALTY,
    }

    # Load manual overrides
    if os.path.exists(overrides_file):
        try:
            with open(overrides_file, "r") as f:
                data = json.load(f)
                config["plan_overrides"] = data.get("plan_overrides", [])
                
                # Check for region-specific overrides
                region_name = "usa" if "usa" in overrides_file.lower() else "europe"
                usa_overrides = data.get("usa_provider_promo_overrides", {})
                
                # Merge overrides
                config["provider_promo_overrides"] = data.get("provider_promo_overrides", {})
                config["provider_promo_overrides"].update(usa_overrides)
                
                config["default_promo_type"] = data.get("default_promo_type", DEFAULT_PROMO_TYPE)
                config["hassle_penalty"] = data.get("default_hassle_penalty", DEFAULT_HASSLE_PENALTY)
        except:
            pass
            
    # Load scraped cache and merge (manual overrides take precedence)
    if os.path.exists(promo_cache_file):
        try:
            with open(promo_cache_file, "r") as f:
                scrape_cache = json.load(f)
                for pid, info in scrape_cache.items():
                    # Only add if not manually overridden and we found a specific type
                    if pid not in config["provider_promo_overrides"]:
                        p_type = info.get("promo_type", "unknown")
                        if p_type in ["one-time", "unlimited"]:
                            config["provider_promo_overrides"][pid] = {
                                "promo_type": p_type,
                                "name": info.get("name", "")
                            }
        except:
            pass
            
    return config

def apply_overrides(plan, overrides):
    """Apply any matching overrides to a plan"""
    plan_name = str(plan.get("plan_name", "")).lower()
    
    for override_entry in overrides:
        match = override_entry.get("match", {})
        if "name_contains" in match:
            if match["name_contains"].lower() in plan_name:
                for key, value in override_entry.get("override", {}).items():
                    plan[key] = value
                if "note" in override_entry:
                    plan["override_note"] = override_entry["note"]
    return plan

def generate_plan_warnings(plan, qty, used_promo_from_provider):
    """Generate warnings for a specific plan with quantity. Returns list of warning strings."""
    warnings = []
    
    # New user only warning with phone/IMEI note
    if plan.get("new_user_only") and qty > 1:
        if plan.get("requires_phone_for_account"):
            warnings.append(f"⚠️ Need {qty} accounts (phone # required, IMEI/EID may be flagged)")
        else:
            warnings.append(f"⚠️ Need {qty} accounts")
    
    # Promo already used from this provider warning
    if used_promo_from_provider and plan.get("usd_promo_price") is not None:
        warnings.append(f"⚠️ Promo already used for this provider - paying full price")
    
    # Top-up warning (only if qty > 1 and can't top up)
    if qty > 1:
        can_top_up = plan.get("can_top_up")
        if can_top_up == False and not plan.get("new_user_only"):
            warnings.append(f"⚠️ No top-up: new eSIM needed each time")
    
    # Speed limit warning
    speed_limit = plan.get("speed_limit")
    if speed_limit and speed_limit < LOW_SPEED_THRESHOLD:
        warnings.append(f"⚠️ Speed capped at {speed_limit}kbps")
    
    # Reduced speed after data cap
    reduced_speed = plan.get("reduced_speed")
    if reduced_speed and reduced_speed < LOW_SPEED_THRESHOLD:
        if plan.get("data_mb") and plan.get("data_mb") > 0:
            warnings.append(f"⚠️ Throttled to {reduced_speed:.0f}kbps after data limit")
    
    # Possible throttling
    if plan.get("possible_throttling"):
        warnings.append(f"⚠️ Possible throttling")
    
    # Tethering warning
    if plan.get("tethering") == False:
        warnings.append(f"⚠️ No hotspot/tethering")
    
    # eKYC warning
    if plan.get("ekyc") == True:
        warnings.append(f"⚠️ Requires ID verification (eKYC)")
    
    # Subscription warning
    if plan.get("subscription") == True:
        warnings.append(f"⚠️ Subscription: cancel after trip")
    
    # Pay as you go info
    if plan.get("pay_as_you_go") == True:
        warnings.append(f"ℹ️ Pay-as-you-go pricing")
    
    # Ads warning
    if plan.get("has_ads") == True:
        warnings.append(f"⚠️ Has ads")
    
    return warnings

def evaluate_combination(combo_data):
    """
    Evaluate a single combination of plans.
    
    Key logic:
    - Promos are assumed ONE-TIME PER PROVIDER (not per plan)
    - First plan from each provider gets promo price, subsequent use regular
    - Hassle penalty affects RANKING only, not displayed cost
    """
    combo_indices, qty_pattern, plans_data, trip_days, total_data_mb, hassle_penalty, max_activations, max_topups = combo_data
    
    display_cost = 0  # Actual cost to show user
    ranking_cost = 0  # Cost used for sorting (includes hassle penalties)
    data = 0
    dur = 0
    info = []
    provider_plan_count = defaultdict(int)
    provider_promo_used = set()  # Track which providers have had promo used
    total_activations = 0
    total_topups = 0
    total_accounts = 0
    
    for idx, qty in zip(combo_indices, qty_pattern):
        p = plans_data[idx]
        provider_id = p["provider_id"]
        provider_name = p["provider_name"]
        can_top_up = p.get("can_top_up", False)
        new_user_only = p.get("new_user_only", False)
        
        promo_price = p.get("usd_promo_price")
        regular_price = p.get("usd_price") or 0
        plan_hassle = p.get("hassle_penalty_per_account", hassle_penalty)
        
        # Determine if this plan can use promo
        # Only track promo usage for "one-time" providers, unlimited providers can always use promo
        has_promo = promo_price is not None and promo_price < regular_price
        provider_promo_type = p.get("provider_promo_type", "unlimited")
        
        if provider_promo_type == "one-time":
            # One-time promo: only first plan from this provider gets promo
            promo_already_used = provider_id in provider_promo_used
            can_use_promo = has_promo and not promo_already_used
        else:
            # Unlimited promo: all plans can use promo
            promo_already_used = False
            can_use_promo = has_promo
        
        # Calculate actual price for this plan
        if regular_price == 0 and (promo_price is None or promo_price == 0):
            # Free plan
            if new_user_only:
                accounts_needed = qty
            else:
                accounts_needed = 1
            plan_display_cost = 0
            used_promo = False
        elif can_use_promo:
            # Eligible for promo price
            if provider_promo_type == "one-time":
                # Promo applies to first purchase only, rest at regular
                plan_display_cost = promo_price + regular_price * (qty - 1)
                provider_promo_used.add(provider_id)
            else:
                # Unlimited promo - all purchases at promo price
                plan_display_cost = promo_price * qty
            used_promo = True
            if new_user_only:
                accounts_needed = qty
            elif can_top_up:
                accounts_needed = 1
            else:
                accounts_needed = qty
        else:
            # No promo available (either none or already used for this provider)
            plan_display_cost = regular_price * qty
            used_promo = False
            if new_user_only:
                accounts_needed = qty
            elif can_top_up:
                accounts_needed = 1
            else:
                accounts_needed = qty
        
        # Hassle cost for ranking only
        hassle_cost = plan_hassle * max(0, accounts_needed - 1)
        
        display_cost += plan_display_cost
        ranking_cost += plan_display_cost + hassle_cost
        
        # Count activations vs top-ups
        if can_top_up and qty > 1 and not new_user_only:
            activations_for_plan = 1
            topups_for_plan = qty - 1
        else:
            activations_for_plan = qty
            topups_for_plan = 0
        
        provider_plan_count[provider_id] += 1
        total_activations += 1
        if activations_for_plan > 1:
            total_activations += activations_for_plan - 1
        total_topups += topups_for_plan
        total_accounts += accounts_needed
        
        # Generate warnings (pass info about promo usage)
        warnings = generate_plan_warnings(p, qty, promo_already_used and has_promo)
        
        data += p["data_mb"] * qty
        dur = max(dur, p["validity_days"] * qty)
        
        # Store actual price paid (for display), not promo price if promo wasn't used
        if regular_price == 0:
            display_price = 0
        elif can_use_promo:
            display_price = promo_price  # Show promo price
        else:
            display_price = regular_price  # Show regular price
        
        info.append({
            "plan": p["plan_name"],
            "provider": provider_name,
            "price": display_price,
            "total_price": plan_display_cost,
            "data": f"{p['data_mb']/1024:.1f}GB" if p['data_mb'] >= 1024 else f"{p['data_mb']}MB",
            "val": f"{p['validity_days']} days" if p['validity_days'] > 0 else "No expiry",
            "qty": qty,
            "free": regular_price == 0,
            "can_top_up": can_top_up and not new_user_only,
            "warnings": warnings,
            "accounts": accounts_needed,
            "used_promo": used_promo,
        })
    
    # Check limits
    if total_activations > max_activations:
        return None
    if total_topups > max_topups:
        return None
    
    # Check data/duration constraints
    if data >= total_data_mb and dur >= trip_days:
        return {
            "display_cost": display_cost,  # Actual cost to show
            "ranking_cost": ranking_cost,  # Cost for sorting (includes hassle)
            "cad": display_cost * 1.37,
            "info": info,
            "gb": data / 1024,
            "days": dur,
            "free_count": sum(1 for x in info if x["free"]),
            "num_providers": len(provider_plan_count),
            "total_activations": total_activations,
            "total_topups": total_topups,
            "total_accounts": total_accounts,
        }
    
    return None

def main():
    parser = argparse.ArgumentParser(description="eSIM Plan Optimizer - Multi-Region")
    parser.add_argument("--region", choices=["europe", "usa"], default="europe", 
                        help="Region to optimize (default: europe)")
    parser.add_argument("--trip-days", type=int, default=TRIP_DAYS,
                        help=f"Trip duration in days (default: {TRIP_DAYS})")
    parser.add_argument("--data-gb", type=float, default=TOTAL_DATA_GB,
                        help=f"Total data needed in GB (default: {TOTAL_DATA_GB})")
    
    args = parser.parse_args()
    
    region = args.region
    trip_days = args.trip_days
    total_data_gb = args.data_gb
    total_data_mb = total_data_gb * 1024
    daily_data_need = total_data_mb / trip_days
    
    start_time = time.perf_counter()
    
    print("="*80)
    print(f"ESIM OPTIMIZER - {region.upper()} REGION")
    print("="*80)
    print(f"Trip: {trip_days} days | {total_data_gb} GB needed")
    print(f"Limits: max {MAX_ESIM_ACTIVATIONS} activations, max {MAX_TOPUPS} top-ups")
    print(f"Showing top {TOP_N_SOLUTIONS} solutions")
    
    # Get region-specific config
    config = REGION_CONFIG.get(region)
    if not config:
        print(f"ERROR: Unknown region '{region}'")
        return
    
    input_file = config["input_file"]
    promo_cache = config["promo_cache"]
    overrides_file = config["overrides"]
    
    # Load config
    overrides_config = load_overrides_config(overrides_file, promo_cache)
    overrides = overrides_config["plan_overrides"]
    provider_promo_overrides = overrides_config["provider_promo_overrides"]
    default_promo_type = overrides_config["default_promo_type"]
    hassle_penalty = overrides_config["hassle_penalty"]
    
    print(f"Hassle penalty: ${hassle_penalty:.2f}/extra account (affects ranking only)")
    one_time_providers = [v.get("name", k) for k, v in provider_promo_overrides.items() if v.get("promo_type") == "one-time"]
    if one_time_providers:
        print(f"One-time promo providers: {', '.join(one_time_providers[:10])}")  # Show first 10
        if len(one_time_providers) > 10:
            print(f"  ... and {len(one_time_providers) - 10} more")
    print(f"Default promo type: {default_promo_type}")
    
    # Load data
    if not os.path.exists(input_file):
        print(f"ERROR: Input file not found: {input_file}")
        print(f"Run the appropriate scraper first:")
        if region == "europe":
            print(f"  python scrape_europe_plans.py")
        elif region == "usa":
            print(f"  python scrape_usa_plans.py")
        return

    df = pd.read_csv(input_file)
    print(f"Loaded plans: {len(df)}")
    
    if overrides:
        print(f"Loaded {len(overrides)} plan overrides")
    
    # Convert to dict and apply overrides
    plans_list = df.to_dict('records')
    plans_list = [apply_overrides(p, overrides) for p in plans_list]
    
    # Apply provider promo type to each plan
    for p in plans_list:
        provider_id = p.get("provider_id", "")
        if provider_id in provider_promo_overrides:
            p["provider_promo_type"] = provider_promo_overrides[provider_id].get("promo_type", default_promo_type)
        else:
            p["provider_promo_type"] = default_promo_type
    
    # Filter valid plans
    valid_plans = [
        p for p in plans_list
        if p.get("usd_price") is not None and p.get("data_mb", 0) > 0 and p.get("validity_days", 0) > 0
    ]
    
    # Sort by cost per day (value metric)
    for p in valid_plans:
        effective = p.get("effective_price") or p.get("usd_price") or 0
        days_covered = min(p["data_mb"] / daily_data_need, p["validity_days"])
        p["cpd"] = effective / max(days_covered, 0.1)
    
    valid_plans.sort(key=lambda x: x["cpd"])
    
    # Take free plans + top paid plans for search space
    free_plans = [p for p in valid_plans if (p.get("usd_price") or 0) == 0]
    paid_plans = [p for p in valid_plans if (p.get("usd_price") or 0) > 0][:SEARCH_SPACE_SIZE]
    search_plans = free_plans + paid_plans
    
    print(f"Search space: {len(search_plans)} plans ({len(free_plans)} free)")
    print()
    
    # Generate all combinations to evaluate
    all_combos = []
    
    for n in range(1, min(MAX_COMBO_SIZE, MAX_ESIM_ACTIVATIONS) + 1):
        if n == 1:
            qty_patterns = [[1], [2], [3], [5], [10]]
        elif n == 2:
            qty_patterns = [[1,1], [2,1], [1,2], [3,1], [2,2]]
        elif n == 3:
            qty_patterns = [[1,1,1], [2,1,1], [1,2,1], [1,1,2]]
        else:
            qty_patterns = [[1]*n]
        
        for combo in combinations(range(len(search_plans)), n):
            for qty_pattern in qty_patterns:
                all_combos.append((combo, qty_pattern))
    
    print(f"Evaluating {len(all_combos):,} combinations...")
    
    # Prepare data for evaluation
    plans_data = search_plans
    combo_data_list = [
        (combo, qty, plans_data, trip_days, total_data_mb, hassle_penalty, MAX_ESIM_ACTIVATIONS, MAX_TOPUPS)
        for combo, qty in all_combos
    ]
    
    # Evaluate combinations with progress bar
    # Use RANKING_COST for heap ordering, but store display_cost for showing
    solutions = []
    counter = 0
    
    for combo_data in tqdm(combo_data_list, desc="Checking combinations", unit="combo"):
        result = evaluate_combination(combo_data)
        if result:
            counter += 1
            # Sort by ranking_cost (includes hassle penalty), but display_cost is shown
            if len(solutions) < TOP_N_SOLUTIONS:
                heapq.heappush(solutions, (-result["ranking_cost"], counter, result))
            elif result["ranking_cost"] < -solutions[0][0]:
                heapq.heapreplace(solutions, (-result["ranking_cost"], counter, result))
    
    # Extract and sort solutions by ranking_cost
    solutions = [s[2] for s in sorted(solutions, key=lambda x: -x[0])]
    
    elapsed = time.perf_counter() - start_time
    
    if not solutions:
        print("\nNo valid solutions found meeting requirements.")
        print("Try increasing MAX_ESIM_ACTIVATIONS or MAX_TOPUPS.")
        logging.info(f"Run completed: No solutions found. Elapsed: {elapsed:.2f}s")
        return

    print()
    print("="*80)
    print(f"TOP {min(len(solutions), TOP_N_SOLUTIONS)} SOLUTIONS")
    print("="*80)
    
    for i, s in enumerate(solutions[:TOP_N_SOLUTIONS], 1):
        free_tag = f" [{s['free_count']} FREE]" if s['free_count'] > 0 else ""
        accounts_note = f" | {s['total_accounts']} accounts" if s['total_accounts'] > 1 else ""
        
        print(f"SOLUTION #{i}")
        print("-" * 40)
        # Show DISPLAY cost (actual price), not ranking cost
        print(f"COST: ${s['display_cost']:.2f} USD / ${s['cad']:.2f} CAD{free_tag}")
        print(f"DATA: {s['gb']:.1f}GB | DAYS: {int(s['days'])} | ACTIVATIONS: {s['total_activations']} | TOP-UPS: {s['total_topups']}{accounts_note}")
        
        print("PLANS:")
        for p in s["info"]:
            qty_text = f" (x{p['qty']})" if p['qty'] > 1 else ""
            if p['free']:
                price_text = "FREE"
            elif p['qty'] > 1:
                price_text = f"${p['price']:.2f} each = ${p['total_price']:.2f} USD"
            else:
                price_text = f"${p['price']:.2f} USD"
            
            top_up_note = " [top-up OK]" if p.get('can_top_up') and p['qty'] > 1 else ""
            promo_note = " [PROMO]" if p.get('used_promo') else ""
            
            print(f"  - {p['provider']}: {p['plan']}")
            print(f"    {price_text}{qty_text}{top_up_note}{promo_note} | {p['data']} | {p['val']}")
            
            # Per-plan warnings (inline)
            if p.get('warnings'):
                for w in p['warnings']:
                    print(f"    {w}")
        print()
    
    # Print timing
    print("="*80)
    print(f"⏱️  Execution time: {elapsed:.2f} seconds")
    print("="*80)
    
    # Log results
    logging.info(f"Run completed: {len(solutions)} solutions. Best: ${solutions[0]['display_cost']:.2f}. Elapsed: {elapsed:.2f}s")

if __name__ == "__main__":
    main()
