"""
ESIM OPTIMIZER - Interactive Mode

Enhanced version of optimize_esim_plans.py with user input prompts.

Features:
- Interactive region selection (Europe, USA, North America, Global)
- Prompts for trip duration (days) with default: 6
- Prompts for data requirement (GB) with default: 5
- All other optimizer features preserved (promo tracking, hassle penalties, warnings, etc.)
"""

import heapq
import json
import logging
import os
import sys
import time
from collections import defaultdict
from itertools import combinations

import pandas as pd

try:
    from tqdm import tqdm
except ImportError:

    def tqdm(iterable, **kwargs):
        return iterable


# --- CONFIGURATION ---
TOP_N_SOLUTIONS = 10

MAX_ESIM_ACTIVATIONS = 3
MAX_TOPUPS = 15
MAX_COMBO_SIZE = 5
SEARCH_SPACE_SIZE = 50

DEFAULT_HASSLE_PENALTY = 0.50
DEFAULT_PROMO_TYPE = "unlimited"
LOW_SPEED_THRESHOLD = 1000

LOG_FILE = "optimizer_run.log"
# ---------------------

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(message)s")


# Region definitions with their input files
REGIONS = {
    1: {
        "name": "Europe",
        "input_file": "esim_plans_europe_filtered.csv",
        "promo_cache": "promo_recurrence_cache.json",
        "overrides": "plan_overrides.json",
        "provider_key": "provider_promo_overrides",
    },
    2: {
        "name": "USA",
        "input_file": "esim_plans_usa.csv",
        "promo_cache": "promo_recurrence_cache_usa.json",
        "overrides": "plan_overrides.json",
        "provider_key": "usa_provider_promo_overrides",
    },
    3: {
        "name": "North America",
        "input_file": "esim_plans_north_america.csv",
        "promo_cache": "promo_recurrence_cache_usa.json",
        "overrides": "plan_overrides.json",
        "provider_key": "usa_provider_promo_overrides",
    },
    4: {
        "name": "Global",
        "input_file": "esim_plans_global.csv",
        "promo_cache": "promo_recurrence_cache.json",
        "overrides": "plan_overrides.json",
        "provider_key": "provider_promo_overrides",
    },
}


def get_region_selection():
    """Interactive menu to select region."""
    print("\n" + "=" * 80)
    print("SELECT REGION")
    print("=" * 80)
    for key, region_data in REGIONS.items():
        print(f"{key}. {region_data['name']}")
    print()

    while True:
        try:
            choice = input("Enter choice (1-4, default: 1): ").strip()
            if not choice:
                choice = "1"
            choice_int = int(choice)
            if choice_int in REGIONS:
                return choice_int
            print("Invalid choice. Please enter 1, 2, 3, or 4.")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except (KeyboardInterrupt, EOFError):
            print("\n\nOperation cancelled.")
            sys.exit(0)


def get_trip_params():
    """Prompt user for trip duration and data needs with defaults."""
    print("\n" + "=" * 80)
    print("TRIP PARAMETERS")
    print("=" * 80)

    while True:
        try:
            trip_days_input = input("Enter trip duration in days (default: 6): ").strip()
            if not trip_days_input:
                trip_days = 6
            else:
                trip_days = int(trip_days_input)
                if trip_days <= 0:
                    print("Trip duration must be positive. Please try again.")
                    continue
            break
        except ValueError:
            print("Invalid input. Please enter a number.")
        except (KeyboardInterrupt, EOFError):
            print("\n\nOperation cancelled.")
            sys.exit(0)

    while True:
        try:
            total_data_input = input("Enter data requirement in GB (default: 5): ").strip()
            if not total_data_input:
                total_data_gb = 5.0
            else:
                total_data_gb = float(total_data_input)
                if total_data_gb <= 0:
                    print("Data requirement must be positive. Please try again.")
                    continue
            break
        except ValueError:
            print("Invalid input. Please enter a number.")
        except (KeyboardInterrupt, EOFError):
            print("\n\nOperation cancelled.")
            sys.exit(0)

    return trip_days, total_data_gb


def load_overrides_config(overrides_file, promo_cache_file, provider_key):
    """Load plan overrides and config from JSON file."""
    config = {
        "plan_overrides": [],
        "provider_promo_overrides": {},
        "default_promo_type": DEFAULT_PROMO_TYPE,
        "hassle_penalty": DEFAULT_HASSLE_PENALTY,
    }

    if os.path.exists(overrides_file):
        try:
            with open(overrides_file, "r") as f:
                data = json.load(f)
                config["plan_overrides"] = data.get("plan_overrides", [])
                config["provider_promo_overrides"] = data.get(provider_key, {})
                config["default_promo_type"] = data.get("default_promo_type", DEFAULT_PROMO_TYPE)
                config["hassle_penalty"] = data.get("default_hassle_penalty", DEFAULT_HASSLE_PENALTY)
        except Exception:
            pass

    if os.path.exists(promo_cache_file):
        try:
            with open(promo_cache_file, "r") as f:
                scrape_cache = json.load(f)
                for pid, info in scrape_cache.items():
                    if pid not in config["provider_promo_overrides"]:
                        p_type = info.get("promo_type", "unknown")
                        if p_type in ["one-time", "unlimited"]:
                            config["provider_promo_overrides"][pid] = {
                                "promo_type": p_type,
                                "name": info.get("name", ""),
                            }
        except Exception:
            pass

    return config


def apply_overrides(plan, overrides):
    """Apply any matching overrides to a plan."""
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
    """Generate warnings for a specific plan with quantity."""
    warnings = []

    if plan.get("new_user_only") and qty > 1:
        if plan.get("requires_phone_for_account"):
            warnings.append(f"⚠️ Need {qty} accounts (phone # required, IMEI/EID may be flagged)")
        else:
            warnings.append(f"⚠️ Need {qty} accounts")

    if used_promo_from_provider and plan.get("usd_promo_price") is not None:
        warnings.append("⚠️ Promo already used for this provider - paying full price")

    if qty > 1:
        can_top_up = plan.get("can_top_up")
        if can_top_up is False and not plan.get("new_user_only"):
            warnings.append("⚠️ No top-up: new eSIM needed each time")

    speed_limit = plan.get("speed_limit")
    if speed_limit and speed_limit < LOW_SPEED_THRESHOLD:
        warnings.append(f"⚠️ Speed capped at {speed_limit}kbps")

    reduced_speed = plan.get("reduced_speed")
    if reduced_speed and reduced_speed < LOW_SPEED_THRESHOLD:
        if plan.get("data_mb") and plan.get("data_mb") > 0:
            warnings.append(f"⚠️ Throttled to {reduced_speed:.0f}kbps after data limit")

    if plan.get("possible_throttling"):
        warnings.append("⚠️ Possible throttling")

    if plan.get("tethering") is False:
        warnings.append("⚠️ No hotspot/tethering")

    if plan.get("ekyc") is True:
        warnings.append("⚠️ Requires ID verification (eKYC)")

    if plan.get("subscription") is True:
        warnings.append("⚠️ Subscription: cancel after trip")

    if plan.get("pay_as_you_go") is True:
        warnings.append("ℹ️ Pay-as-you-go pricing")

    if plan.get("has_ads") is True:
        warnings.append("⚠️ Has ads")

    return warnings


def evaluate_combination(combo_data):
    """
    Evaluate a single combination of plans.

    Key logic:
    - Promos are assumed ONE-TIME PER PROVIDER (not per plan)
    - First plan from each provider gets promo price, subsequent use regular
    - Hassle penalty affects RANKING only, not displayed cost
    """
    (
        combo_indices,
        qty_pattern,
        plans_data,
        trip_days,
        total_data_mb,
        hassle_penalty,
        max_activations,
        max_topups,
    ) = combo_data

    display_cost = 0
    ranking_cost = 0
    data = 0
    dur = 0
    info = []
    provider_plan_count = defaultdict(int)
    provider_promo_used = set()
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

        has_promo = promo_price is not None and promo_price < regular_price
        provider_promo_type = p.get("provider_promo_type", "unlimited")

        if provider_promo_type == "one-time":
            promo_already_used = provider_id in provider_promo_used
            can_use_promo = has_promo and not promo_already_used
        else:
            promo_already_used = False
            can_use_promo = has_promo

        if regular_price == 0 and (promo_price is None or promo_price == 0):
            if new_user_only:
                accounts_needed = qty
            else:
                accounts_needed = 1
            plan_display_cost = 0
            used_promo = False
        elif can_use_promo:
            if provider_promo_type == "one-time":
                plan_display_cost = promo_price + regular_price * (qty - 1)
                provider_promo_used.add(provider_id)
            else:
                plan_display_cost = promo_price * qty
            used_promo = True
            if new_user_only:
                accounts_needed = qty
            elif can_top_up:
                accounts_needed = 1
            else:
                accounts_needed = qty
        else:
            plan_display_cost = regular_price * qty
            used_promo = False
            if new_user_only:
                accounts_needed = qty
            elif can_top_up:
                accounts_needed = 1
            else:
                accounts_needed = qty

        hassle_cost = plan_hassle * max(0, accounts_needed - 1)

        display_cost += plan_display_cost
        ranking_cost += plan_display_cost + hassle_cost

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

        warnings = generate_plan_warnings(p, qty, promo_already_used and has_promo)

        data += p["data_mb"] * qty
        dur += p["validity_days"] * qty

        if regular_price == 0:
            display_price = 0
        elif can_use_promo:
            display_price = promo_price
        else:
            display_price = regular_price

        info.append(
            {
                "plan": p["plan_name"],
                "provider": provider_name,
                "price": display_price,
                "total_price": plan_display_cost,
                "data": f"{p['data_mb']/1024:.1f}GB" if p["data_mb"] >= 1024 else f"{p['data_mb']}MB",
                "val": f"{p['validity_days']} days" if p["validity_days"] > 0 else "No expiry",
                "qty": qty,
                "free": regular_price == 0,
                "can_top_up": can_top_up and not new_user_only,
                "warnings": warnings,
                "accounts": accounts_needed,
                "used_promo": used_promo,
            }
        )

    if total_activations > max_activations:
        return None
    if total_topups > max_topups:
        return None

    if data >= total_data_mb and dur >= trip_days:
        return {
            "display_cost": display_cost,
            "ranking_cost": ranking_cost,
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
    start_time = time.perf_counter()

    print("=" * 80)
    print("eSIM OPTIMIZER - INTERACTIVE MODE")
    print("=" * 80)

    region_choice = get_region_selection()
    trip_days, total_data_gb = get_trip_params()

    region_data = REGIONS[region_choice]
    region_name = region_data["name"]
    input_file = region_data["input_file"]
    promo_cache = region_data["promo_cache"]
    overrides_file = region_data["overrides"]
    provider_key = region_data["provider_key"]

    total_data_mb = total_data_gb * 1024
    daily_data_need = total_data_mb / trip_days

    print()
    print("=" * 80)
    print("SELECTED PARAMETERS")
    print("=" * 80)
    print(f"✓ Region:      {region_name}")
    print(f"✓ Trip:        {trip_days} days")
    print(f"✓ Data:        {total_data_gb} GB")
    print("=" * 80)
    print()

    if not os.path.exists(input_file):
        print(f"ERROR: Input file not found: {input_file}")
        print(f"\nPlease run the appropriate scraper first:")
        print(f"  python scrape_all_regions_plans.py --region {region_name.lower().replace(' ', '-')}")
        return

    config = load_overrides_config(overrides_file, promo_cache, provider_key)
    overrides = config["plan_overrides"]
    provider_promo_overrides = config["provider_promo_overrides"]
    default_promo_type = config["default_promo_type"]
    hassle_penalty = config["hassle_penalty"]

    print(f"Hassle penalty: ${hassle_penalty:.2f}/extra account (affects ranking only)")
    one_time_providers = [
        v.get("name", k) for k, v in provider_promo_overrides.items() if v.get("promo_type") == "one-time"
    ]
    if one_time_providers:
        display_list = ", ".join(one_time_providers[:10])
        if len(one_time_providers) > 10:
            display_list += f"... and {len(one_time_providers) - 10} more"
        print(f"One-time promo providers: {display_list}")
    print(f"Default promo type: {default_promo_type}")

    df = pd.read_csv(input_file)
    print(f"Loaded plans: {len(df)}")

    if overrides:
        print(f"Loaded {len(overrides)} plan overrides")

    plans_list = df.to_dict("records")
    plans_list = [apply_overrides(p, overrides) for p in plans_list]

    for p in plans_list:
        provider_id = p.get("provider_id", "")
        if provider_id in provider_promo_overrides:
            p["provider_promo_type"] = provider_promo_overrides[provider_id].get(
                "promo_type", default_promo_type
            )
        else:
            p["provider_promo_type"] = default_promo_type

    valid_plans = [
        p
        for p in plans_list
        if p.get("usd_price") is not None and p.get("data_mb", 0) > 0 and p.get("validity_days", 0) > 0
    ]

    for p in valid_plans:
        effective = p.get("effective_price") or p.get("usd_price") or 0
        days_covered = min(p["data_mb"] / daily_data_need, p["validity_days"])
        p["cpd"] = effective / max(days_covered, 0.1)

    valid_plans.sort(key=lambda x: x["cpd"])

    free_plans = [p for p in valid_plans if (p.get("usd_price") or 0) == 0]
    paid_plans = [p for p in valid_plans if (p.get("usd_price") or 0) > 0][:SEARCH_SPACE_SIZE]
    search_plans = free_plans + paid_plans

    print(f"Search space: {len(search_plans)} plans ({len(free_plans)} free)")
    print()

    all_combos = []

    for n in range(1, min(MAX_COMBO_SIZE, MAX_ESIM_ACTIVATIONS) + 1):
        if n == 1:
            qty_patterns = [[1], [2], [3], [5], [10]]
        elif n == 2:
            qty_patterns = [[1, 1], [2, 1], [1, 2], [3, 1], [2, 2]]
        elif n == 3:
            qty_patterns = [[1, 1, 1], [2, 1, 1], [1, 2, 1], [1, 1, 2]]
        else:
            qty_patterns = [[1] * n]

        for combo in combinations(range(len(search_plans)), n):
            for qty_pattern in qty_patterns:
                all_combos.append((combo, qty_pattern))

    print(f"Evaluating {len(all_combos):,} combinations...")

    plans_data = search_plans
    combo_data_list = [
        (combo, qty, plans_data, trip_days, total_data_mb, hassle_penalty, MAX_ESIM_ACTIVATIONS, MAX_TOPUPS)
        for combo, qty in all_combos
    ]

    solutions = []
    counter = 0

    for combo_data in tqdm(combo_data_list, desc="Checking combinations", unit="combo"):
        result = evaluate_combination(combo_data)
        if result:
            counter += 1
            if len(solutions) < TOP_N_SOLUTIONS:
                heapq.heappush(solutions, (-result["ranking_cost"], counter, result))
            elif result["ranking_cost"] < -solutions[0][0]:
                heapq.heapreplace(solutions, (-result["ranking_cost"], counter, result))

    solutions = [s[2] for s in sorted(solutions, key=lambda x: -x[0])]

    elapsed = time.perf_counter() - start_time

    if not solutions:
        print("\nNo valid solutions found meeting requirements.")
        print("Try increasing MAX_ESIM_ACTIVATIONS or MAX_TOPUPS.")
        logging.info(f"Run completed: No solutions found. Elapsed: {elapsed:.2f}s")
        return

    print()
    print("=" * 80)
    print(f"TOP {min(len(solutions), TOP_N_SOLUTIONS)} SOLUTIONS")
    print("=" * 80)

    for i, s in enumerate(solutions[:TOP_N_SOLUTIONS], 1):
        free_tag = f" [{s['free_count']} FREE]" if s["free_count"] > 0 else ""
        accounts_note = f" | {s['total_accounts']} accounts" if s["total_accounts"] > 1 else ""

        print(f"SOLUTION #{i}")
        print("-" * 40)
        print(f"COST: ${s['display_cost']:.2f} USD / ${s['cad']:.2f} CAD{free_tag}")
        print(
            f"DATA: {s['gb']:.1f}GB | DAYS: {int(s['days'])} | ACTIVATIONS: {s['total_activations']} | TOP-UPS: {s['total_topups']}{accounts_note}"
        )

        print("PLANS:")
        for p in s["info"]:
            qty_text = f" (x{p['qty']})" if p["qty"] > 1 else ""
            if p["free"]:
                price_text = "FREE"
            elif p["qty"] > 1:
                price_text = f"${p['price']:.2f} each = ${p['total_price']:.2f} USD"
            else:
                price_text = f"${p['price']:.2f} USD"

            top_up_note = " [top-up OK]" if p.get("can_top_up") and p["qty"] > 1 else ""
            promo_note = " [PROMO]" if p.get("used_promo") else ""

            print(f"  - {p['provider']}: {p['plan']}")
            print(f"    {price_text}{qty_text}{top_up_note}{promo_note} | {p['data']} | {p['val']}")

            if p.get("warnings"):
                for w in p["warnings"]:
                    print(f"    {w}")
        print()

    print("=" * 80)
    print(f"⏱️  Execution time: {elapsed:.2f} seconds")
    print("=" * 80)

    logging.info(f"Run completed: {len(solutions)} solutions. Best: ${solutions[0]['display_cost']:.2f}. Elapsed: {elapsed:.2f}s")


if __name__ == "__main__":
    main()
