"""
Unified ESIMDB Scraper - Fetches eSIM plan data from the ESIMDB API for multiple regions.

Regions supported:
- europe
- global
- north-america
- usa (filtered from north-america; the /regions/usa endpoint exists but currently returns 0 plans)

API endpoint findings (tested 2026-01-10):
- https://esimdb.com/api/client/regions/global/data-plans?locale=en -> 200 with plans
- https://esimdb.com/api/client/regions/north-america/data-plans?locale=en -> 200 with plans
- https://esimdb.com/api/client/regions/usa/data-plans?locale=en -> 200 but 0 plans
- https://esimdb.com/api/client/regions/europe/data-plans?locale=en -> 200 with plans

Usage:
  python scrape_all_regions_plans.py --region usa
  python scrape_all_regions_plans.py --region north-america
  python scrape_all_regions_plans.py --region global
  python scrape_all_regions_plans.py --region europe
  python scrape_all_regions_plans.py --all
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass

import pandas as pd
import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

EUROPE_TARGET_COUNTRIES = ["DE", "AT", "CZ", "SK"]
USA_COUNTRY_CODE = "US"


@dataclass(frozen=True)
class RegionSpec:
    slug: str
    api_slug: str
    output_csv: str
    provider_cache_file: str
    raw_json_file: str


REGION_SPECS: dict[str, RegionSpec] = {
    "europe": RegionSpec(
        slug="europe",
        api_slug="europe",
        output_csv="esim_plans_europe.csv",
        provider_cache_file="provider_cache.json",
        raw_json_file="esim_api_europe_raw.json",
    ),
    "global": RegionSpec(
        slug="global",
        api_slug="global",
        output_csv="esim_plans_global.csv",
        provider_cache_file="provider_cache_global.json",
        raw_json_file="esim_api_global_raw.json",
    ),
    "north-america": RegionSpec(
        slug="north-america",
        api_slug="north-america",
        output_csv="esim_plans_north_america.csv",
        provider_cache_file="provider_cache_north_america.json",
        raw_json_file="esim_api_north_america_raw.json",
    ),
    # NOTE: /regions/usa/data-plans exists but returns 0 plans.
    # We therefore fetch north-america and filter to USA coverage.
    "usa": RegionSpec(
        slug="usa",
        api_slug="north-america",
        output_csv="esim_plans_usa.csv",
        provider_cache_file="provider_cache_usa.json",
        raw_json_file="esim_api_usa_raw.json",
    ),
}


def get_live_rates() -> dict:
    """Fetch live exchange rates with fallback (USD base)."""
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        data = resp.json()
        if data.get("result") == "success":
            print("✓ Got live exchange rates")
            return data["rates"]
    except Exception:
        pass

    print("⚠ Using fallback exchange rates")
    return {"USD": 1.0, "CAD": 1.37, "EUR": 0.92, "GBP": 0.79}


def load_provider_cache(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cache = json.load(f)
                if cache:
                    return cache
        except Exception:
            pass
    return {}


def save_provider_cache(path: str, cache: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def fetch_providers() -> dict:
    """Fetch provider names from the API."""
    print("Fetching provider names from API...")
    try:
        resp = requests.get(
            "https://esimdb.com/api/client/providers",
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()
        providers = resp.json()

        cache: dict[str, str] = {}
        for p in providers:
            if "_id" in p and "name" in p:
                cache[p["_id"]] = p["name"]

        print(f"✓ Got {len(cache)} provider names")
        return cache
    except Exception as e:
        print(f"⚠ Could not fetch providers: {e}")
        return {}


def extract_provider_info(provider_val, provider_cache: dict) -> tuple[str, str]:
    if isinstance(provider_val, dict):
        provider_id = provider_val.get("_id", "")
        provider_name = provider_val.get("name", "")
        if provider_name and provider_id:
            provider_cache[provider_id] = provider_name
        return provider_id, provider_name if provider_name else provider_id

    provider_id = str(provider_val) if provider_val else ""
    provider_name = provider_cache.get(provider_id, provider_id)
    return provider_id, provider_name


def build_api_url(region_api_slug: str) -> str:
    return f"https://esimdb.com/api/client/regions/{region_api_slug}/data-plans?locale=en"


def should_include_plan(region: str, plan: dict) -> bool:
    if region != "usa":
        return True

    # USA filtering: we intentionally focus on USA-specific / small-coverage plans.
    # The public API endpoint /api/client/regions/usa/data-plans currently returns 0 plans,
    # so USA scraping is derived from the north-america endpoint and filtered.
    #
    # Note: the website https://esimdb.com/usa may display a much larger plan count
    # (it appears to aggregate global/multi-region offerings). This scraper keeps the
    # dataset smaller/more USA-focused for the optimizer.
    coverages = plan.get("coverages", [])
    if USA_COUNTRY_CODE not in coverages:
        return False

    # Exclude very wide coverage (often "global" plans) to keep the USA dataset focused.
    return len(coverages) <= 5


def scrape_region(region: str) -> tuple[pd.DataFrame, list]:
    spec = REGION_SPECS[region]

    print(f"Fetching {region} plans from API...")
    url = build_api_url(spec.api_slug)

    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    all_plans = data.get("plans", [])
    print(f"Got {len(all_plans)} plans ({spec.api_slug})")

    # Save raw for debugging
    with open(spec.raw_json_file, "w", encoding="utf-8") as f:
        json.dump(all_plans, f, indent=2)
    print(f"Saved raw API response to {spec.raw_json_file}")

    provider_cache = load_provider_cache(spec.provider_cache_file)
    if not provider_cache:
        provider_cache = fetch_providers()
        if provider_cache:
            save_provider_cache(spec.provider_cache_file, provider_cache)

    exchange_rates = get_live_rates()

    cleaned = []
    kept = 0

    for plan in all_plans:
        if not should_include_plan(region, plan):
            continue

        kept += 1

        provider_id, provider_name = extract_provider_info(plan.get("provider", ""), provider_cache)

        usd_price = plan.get("usdPrice")
        usd_promo_price = plan.get("usdPromoPrice")

        if usd_promo_price is not None and usd_promo_price < (usd_price or float("inf")):
            effective_price = usd_promo_price
            is_promo = True
        else:
            effective_price = usd_price
            is_promo = False

        coverages = plan.get("coverages", [])

        cleaned.append(
            {
                "plan_id": plan.get("_id", ""),
                "provider_id": provider_id,
                "provider_name": provider_name,
                "plan_name": plan.get("enName") or plan.get("name", ""),
                "data_mb": plan.get("capacity", 0),
                "validity_days": plan.get("period", 0),
                "data_cap_per": plan.get("dataCapPer"),
                "usd_price": usd_price,
                "usd_promo_price": usd_promo_price,
                "effective_price": effective_price,
                "is_promo": is_promo,
                "price_cad": effective_price * exchange_rates.get("CAD", 1.37) if effective_price else None,
                "new_user_only": plan.get("newUserOnly", False),
                "promo_enabled": plan.get("promoEnabled", False),
                "can_top_up": plan.get("canTopUp"),
                "subscription": plan.get("subscription", False),
                "pay_as_you_go": plan.get("payAsYouGo", False),
                "ekyc": plan.get("eKYC", False),
                "speed_limit": plan.get("speedLimit"),
                "reduced_speed": plan.get("reducedSpeed"),
                "possible_throttling": plan.get("possibleThrottling", False),
                "has_5g": plan.get("has5G", False),
                "tethering": plan.get("tethering"),
                "has_ads": plan.get("hasAds", False),
                "num_countries": len(coverages),
            }
        )

    save_provider_cache(spec.provider_cache_file, provider_cache)
    print(f"Provider cache: {len(provider_cache)} providers -> {spec.provider_cache_file}")

    df = pd.DataFrame(cleaned)
    if len(df) == 0:
        print(f"No plans kept after filtering for region '{region}'.")
        return df, all_plans

    df["data_display"] = df.apply(
        lambda x: f"{x['data_mb']/1024:.1f}GB" if x["data_mb"] >= 1024 else f"{x['data_mb']}MB",
        axis=1,
    )
    df["validity_display"] = df["validity_days"].apply(lambda x: f"{x} days" if x > 0 else "No expiry")

    print(f"Kept {kept} plans after filtering")
    return df, all_plans


def save_region_outputs(region: str, df: pd.DataFrame) -> None:
    spec = REGION_SPECS[region]

    if len(df) == 0:
        return

    df.to_csv(spec.output_csv, index=False)
    print(f"Saved {len(df)} plans to {spec.output_csv}")

    if region == "europe":
        # Mirror scrape_europe_plans.py filtering (DE/AT/CZ/SK)
        target_countries = EUROPE_TARGET_COUNTRIES

        # We need coverages in order to compute this; the API provides it but we didn't store it.
        # For compatibility, we re-fetch raw plans file and compute coverage filter there.
        try:
            with open(spec.raw_json_file, "r", encoding="utf-8") as f:
                raw_plans = json.load(f)
        except Exception:
            raw_plans = []

        id_to_covers = {}
        for p in raw_plans:
            pid = p.get("_id", "")
            cov = p.get("coverages", [])
            id_to_covers[pid] = all(c in cov for c in target_countries)

        df_filtered = df.copy()
        df_filtered["covers_all_target"] = df_filtered["plan_id"].map(id_to_covers).fillna(False)
        df_filtered = df_filtered[df_filtered["covers_all_target"] == True].copy()

        filtered_path = "esim_plans_europe_filtered.csv"
        df_filtered.to_csv(filtered_path, index=False)
        print(f"Saved filtered plans to {filtered_path} (covers {', '.join(target_countries)})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified ESIMDB region scraper")
    parser.add_argument("--region", choices=list(REGION_SPECS.keys()))
    parser.add_argument("--all", action="store_true", help="Scrape all regions")
    args = parser.parse_args()

    regions: list[str]
    if args.all:
        regions = ["europe", "usa", "north-america", "global"]
    else:
        if not args.region:
            parser.error("Must supply --region or --all")
        regions = [args.region]

    print("=" * 80)
    print("ESIMDB UNIFIED SCRAPER")
    print("=" * 80)

    for region in regions:
        spec = REGION_SPECS[region]
        print("\n" + "-" * 80)
        print(f"Region: {region}")
        print(f"API: {build_api_url(spec.api_slug)}")
        print(f"Output: {spec.output_csv}")
        print(f"Provider cache: {spec.provider_cache_file}")
        print("-" * 80)

        try:
            df, _ = scrape_region(region)
            save_region_outputs(region, df)
        except Exception as e:
            print(f"ERROR scraping region '{region}': {e}")


if __name__ == "__main__":
    main()
