import os
import re
import json
import math
import time
import argparse
from typing import List, Dict, Any, Optional

import requests
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup

# -------- Scraper utilities (France) -------- #

def get_user_agent() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def get_provider_slugs(country_url: str) -> List[str]:
    """Discover provider slugs from the country page (e.g., '/france/<slug>')."""
    resp = requests.get(country_url, headers=get_user_agent(), timeout=60)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    slugs = set()
    # Provider detail links look like '/france/<slug>'
    country_path = "/" + country_url.rstrip("/").split("/")[-1] + "/"
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(country_path) and href.count("/") == 2:
            slugs.add(href.rstrip("/").split("/")[-1])
    return sorted(slugs)


def find_plan_list(obj: Any) -> List[Dict[str, Any]]:
    """Recursively search a JSON object for the first list of dicts (plan-like)."""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            return obj
        for item in obj:
            res = find_plan_list(item)
            if res:
                return res
    elif isinstance(obj, dict):
        for val in obj.values():
            res = find_plan_list(val)
            if res:
                return res
    return []


# -------- Country API (preferred for France) -------- #

def _extract_price_from_plan_dict(plan: Dict[str, Any]) -> str:
    """Deprecated: kept for fallback. Prefer _extract_usd_prices."""
    if plan.get("usdPromoPrice") is not None:
        return str(plan.get("usdPromoPrice"))
    if plan.get("usdPrice") is not None:
        return str(plan.get("usdPrice"))
    if isinstance(plan.get("promoPrices"), dict):
        d = plan["promoPrices"]
        for key in ["USD","usd","EUR","eur","GBP","gbp"]:
            if key in d and d[key] is not None:
                return str(d[key])
    if isinstance(plan.get("prices"), dict):
        d = plan["prices"]
        for key in ["USD","usd","EUR","eur","GBP","gbp"]:
            if key in d and d[key] is not None:
                return str(d[key])
    if plan.get("price") is not None:
        return str(plan.get("price"))
    return ""


def _extract_usd_prices(plan: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Extract promo and base USD prices and detect zero in any currency.
    Returns {"promo_usd": float|None, "base_usd": float|None, "promo_zero_any": bool, "base_zero_any": bool}.
    """
    promo = None
    base = None
    promo_zero_any = False
    base_zero_any = False
    try:
        if isinstance(plan.get("promoPrices"), dict):
            d = plan["promoPrices"]
            # USD preferred
            if "USD" in d and d["USD"] is not None:
                promo = float(d["USD"])
            elif "usd" in d and d["usd"] is not None:
                promo = float(d["usd"])
            # Any currency zero?
            for v in d.values():
                try:
                    if float(v) == 0.0:
                        promo_zero_any = True
                        break
                except Exception:
                    continue
        if promo is None and plan.get("usdPromoPrice") is not None:
            promo = float(plan.get("usdPromoPrice"))
            if promo == 0.0:
                promo_zero_any = True
    except Exception:
        pass
    try:
        if isinstance(plan.get("prices"), dict):
            d = plan["prices"]
            if "USD" in d and d["USD"] is not None:
                base = float(d["USD"])
            elif "usd" in d and d["usd"] is not None:
                base = float(d["usd"])
            for v in d.values():
                try:
                    if float(v) == 0.0:
                        base_zero_any = True
                        break
                except Exception:
                    continue
        if base is None and plan.get("usdPrice") is not None:
            base = float(plan.get("usdPrice"))
            if base == 0.0:
                base_zero_any = True
    except Exception:
        pass
    return {"promo_usd": promo, "base_usd": base, "promo_zero_any": promo_zero_any, "base_zero_any": base_zero_any}


def _is_plan_dict(d: Dict[str, Any]) -> bool:
    if not isinstance(d, dict):
        return False
    has_price = any(k in d for k in ["prices", "promoPrices", "price", "usdPrice", "usdPromoPrice"]) 
    has_capacity = any(k in d for k in ["capacity", "capacity_info", "data", "dataAmount", "amount", "dailyData"]) 
    has_period = any(k in d for k in ["period", "periodType", "validity", "validityInDays", "days"]) 
    return has_price and (has_capacity or has_period)


def _collect_plan_dicts(obj: Any) -> List[Dict[str, Any]]:
    """Recursively collect likely plan dictionaries from any JSON structure."""
    results: List[Dict[str, Any]] = []
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and _is_plan_dict(item):
                results.append(item)
            results.extend(_collect_plan_dicts(item))
    elif isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, dict) and _is_plan_dict(v):
                results.append(v)
            results.extend(_collect_plan_dicts(v))
    return results


def _provider_name_lookup(payload: Any) -> Dict[str, str]:
    """Build a map from provider _id to name if present in the payload.
    Prefers payload['providers'] if available.
    """
    mapping: Dict[str, str] = {}
    # Prefer explicit providers index if present
    if isinstance(payload, dict) and isinstance(payload.get("providers"), dict):
        for pid, info in payload["providers"].items():
            if not isinstance(info, dict):
                continue
            nm = info.get("name") or info.get("enName") or info.get("displayName") or info.get("title") or info.get("providerName")
            if pid and nm:
                mapping[str(pid)] = str(nm)
    # Heuristic collection as fallback
    def maybe_collect(d: Dict[str, Any]):
        pid = d.get("_id")
        nm = d.get("name") or d.get("enName") or d.get("title")
        nm = nm or d.get("displayName") or d.get("providerName")
        if pid and isinstance(pid, str) and nm:
            mapping[pid] = str(nm)
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k == "providers":
                continue
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        maybe_collect(item)
            elif isinstance(v, dict):
                maybe_collect(v)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                maybe_collect(item)
    return mapping


def _providers_index(payload: Any) -> Dict[str, Dict[str, Any]]:
    """Return providers index from payload if available: id -> provider dict."""
    idx: Dict[str, Dict[str, Any]] = {}
    if isinstance(payload, dict) and isinstance(payload.get("providers"), dict):
        for pid, info in payload["providers"].items():
            if isinstance(info, dict):
                idx[str(pid)] = info
    return idx


def _extract_capacity(plan: Dict[str, Any]) -> str:
    # Prefer precise numeric fields first, then textual
    for k in ["capacity", "data", "capacity_info"]:
        if plan.get(k) not in (None, ""):
            val = plan.get(k)
            # If numeric capacity, treat as MB; check if it's per-day via dataCapPer
            cap_per = (plan.get("dataCapPer") or "").lower()
            if isinstance(val, (int, float)):
                if cap_per in ("day", "daily"):
                    return f"{val} MB/day"
                return f"{val} MB"
            sval = str(val)
            # If string already contains unit or /day, return as-is
            if re.search(r"mb|gb|/\s*day|daily", sval, re.IGNORECASE):
                return sval
            # Fallback: assume MB
            return f"{sval} MB"
    amount = plan.get("dataAmount") or plan.get("amount")
    unit = plan.get("dataUnit") or plan.get("unit")
    if amount is not None:
        if unit:
            u = str(unit).upper()
            if u in ("MB", "GB"):
                return f"{amount}{u}"
        # Unknown or missing unit; assume MB
        return f"{amount} MB"
    # Daily style fields
    daily = plan.get("dailyData") or plan.get("perDayData")
    if daily not in (None, ""):
        # If numeric, assume MB/day
        if isinstance(daily, (int, float)):
            return f"{daily} MB/day"
        sval = str(daily)
        if re.search(r"mb|gb", sval, re.IGNORECASE):
            return sval if "/" in sval.lower() else f"{sval}/day"
        return f"{sval} MB/day"
    return ""


def _extract_period(plan: Dict[str, Any]) -> str:
    # Prefer a textual field if present
    for k in ["validity", "period_info", "duration"]:
        if plan.get(k):
            return str(plan[k])
    # Combine numeric + type (e.g., 7 + Days)
    period_val = plan.get("period") or plan.get("validityInDays") or plan.get("days")
    period_type = plan.get("periodType")
    if period_val is not None:
        if period_type:
            return f"{period_val} {period_type}"
        return f"{period_val} Days"
    if plan.get("noExpiry"):
        return "No expiry"
    return ""


def _extract_provider(plan: Dict[str, Any]) -> str:
    for k in ["providerName", "provider", "brand", "vendor", "seller"]:
        if plan.get(k):
            return str(plan[k])
    # Some APIs nest provider
    prov = plan.get("providerInfo") or plan.get("providerDetails")
    if isinstance(prov, dict):
        return str(prov.get("name") or prov.get("title") or "")
    return ""


def _extract_title(plan: Dict[str, Any]) -> str:
    for k in ["enName", "title", "planName", "name"]:
        if plan.get(k):
            return str(plan[k])
    return ""


def scrape_country_via_api(country_slug: str = "france") -> List[Dict[str, Any]]:
    os.makedirs("scraped_data", exist_ok=True)
    cache_raw = os.path.join("scraped_data", f"esimdb_{country_slug}_raw.json")

    # If a cached raw JSON exists, use it to allow offline runs
    if os.path.exists(cache_raw):
        print(f"Loading cached raw JSON: {cache_raw}")
        with open(cache_raw, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        base_urls = [
            f"https://esimdb.com/api/client/countries/{country_slug}/data-plans?locale=en",
            f"https://www.esimdb.com/api/client/countries/{country_slug}/data-plans?locale=en",
        ]
        payload = None
        last_err = None
        for base in base_urls:
            print(f"Fetching full JSON from country API: {base}")
            # Conditional fetch using ETag/Last-Modified if available
            meta_path = os.path.join("scraped_data", f"esimdb_{country_slug}_meta.json")
            etag = None
            last_mod = None
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as mf:
                        meta = json.load(mf)
                        etag = meta.get("etag")
                        last_mod = meta.get("last_modified")
                except Exception:
                    pass
            headers = get_user_agent().copy()
            if etag:
                headers["If-None-Match"] = etag
            if last_mod:
                headers["If-Modified-Since"] = last_mod

            for attempt in range(1, 6):
                try:
                    r = requests.get(base, headers=headers, timeout=180)
                    if r.status_code == 304 and os.path.exists(cache_raw):
                        print("Server reports Not Modified (304); using cached raw JSON.")
                        with open(cache_raw, "r", encoding="utf-8") as f:
                            payload = json.load(f)
                        break
                    r.raise_for_status()
                    payload = r.json()
                    # Cache raw payload for reuse/offline
                    with open(cache_raw, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False)
                    # Update meta
                    try:
                        new_meta = {
                            "etag": r.headers.get("ETag"),
                            "last_modified": r.headers.get("Last-Modified"),
                            "fetched_at": time.time(),
                            "totalPlans": payload.get("totalPlans") if isinstance(payload, dict) else None,
                        }
                        with open(meta_path, "w", encoding="utf-8") as mf:
                            json.dump(new_meta, mf, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    break
                except Exception as e:
                    last_err = e
                    wait = min(2 ** attempt, 30)
                    print(f"Attempt {attempt} failed: {e}. Retrying in {wait}s ...")
                    time.sleep(wait)
            if payload is not None:
                break
        if payload is None:
            print("Country API scrape failed: {}".format(last_err))
            print(f"If the error persists, download the JSON manually from one of the URLs above and save it to: {cache_raw}")
            return []

    # Build providers data
    provider_map = _provider_name_lookup(payload)
    providers_idx = _providers_index(payload)

    # Recursively collect all plan-like dicts anywhere in the payload
    all_candidates = _collect_plan_dicts(payload)

    normalized: List[Dict[str, Any]] = []
    seen = set()
    for p in all_candidates:
        provider_id = p.get("provider") if isinstance(p.get("provider"), str) else None
        provider_name = None
        if provider_id and provider_id in provider_map:
            provider_name = provider_map[provider_id]
        else:
            provider_name = _extract_provider(p)
        # Try slug
        provider_slug = None
        if provider_id and provider_id in providers_idx:
            provider_slug = providers_idx[provider_id].get("slug") or providers_idx[provider_id].get("providerSlug")
        title = _extract_title(p)
        capacity = _extract_capacity(p)
        period = _extract_period(p)
        usd_prices = _extract_usd_prices(p)
        promo_usd = usd_prices.get("promo_usd")
        base_usd = usd_prices.get("base_usd")
        promo_zero_any = usd_prices.get("promo_zero_any")
        base_zero_any = usd_prices.get("base_zero_any")
        price = None
        if promo_usd is not None:
            price = promo_usd
        elif base_usd is not None:
            price = base_usd
        else:
            # Fallback to any currency
            fallback = _extract_price_from_plan_dict(p)
            try:
                price = float(fallback) if fallback != "" else None
            except Exception:
                price = None
        # Coverage hints
        ib = p.get("internetBreakouts") if isinstance(p.get("internetBreakouts"), list) else []
        coverage_count = len(ib) if isinstance(ib, list) else 0
        ttl = (title or "").lower()
        scope_pref = 2 if ("global" in ttl or "world" in ttl) else (1 if "europe" in ttl else 0)

        # Basic sanity check: need a price (0 is allowed) and some capacity/period info
        if price is None:
            continue
        if not capacity and not period:
            continue

        key = (provider_id or provider_name, title, capacity, period, price)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "provider": provider_name or "",
            "provider_id": provider_id or "",
            "provider_slug": provider_slug or "",
            "plan_title": title,
            "capacity": capacity,
            "period": period,
            "price": price,
            "price_usd_promo": promo_usd,
            "price_usd_base": base_usd,
            "promo_zero_any": bool(promo_zero_any),
            "base_zero_any": bool(base_zero_any),
            "coverage_count": coverage_count,
            "scope_pref": scope_pref,
            "plan_id": p.get("_id"),
        })

    total_plans_reported = 0
    if isinstance(payload, dict):
        total_plans_reported = payload.get("totalPlans") or 0

    print(f"Country API normalized {len(normalized)} plans (reported total: {total_plans_reported}).")

    # Write normalized plans CSV for auditing
    try:
        norm_df = pd.DataFrame(normalized)
        norm_csv = os.path.join("scraped_data", f"normalized_plans_{country_slug}.csv")
        norm_df.to_csv(norm_csv, index=False, encoding="utf-8")
        print(f"Wrote normalized plans CSV to: {norm_csv}")
    except Exception as e:
        print(f"Warning: failed to write normalized plans CSV: {e}")

    return normalized


def scrape_country(country_slug: str = "france") -> List[Dict[str, Any]]:
    # Prefer country API for France. If it fails or yields nothing, we can extend with fallbacks later.
    try:
        plans = scrape_country_via_api(country_slug)
        if plans:
            os.makedirs("scraped_data", exist_ok=True)
            out_json = os.path.join("scraped_data", f"esimdb_plans_{country_slug}.json")
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(plans, f, ensure_ascii=False, indent=2)
            print(f"Saved {len(plans)} plans to {out_json}")
            return plans
        else:
            print("Country API returned no plans.")
    except Exception as e:
        print(f"Country API scrape failed: {e}")

    # Fallback stub (provider pages) could be added here if needed.
    return []


# -------- Analysis utilities -------- #

def convert_to_mb(data_str: Any) -> float:
    if pd.isna(data_str) or data_str == "":
        return np.nan
    s = str(data_str).strip()
    # If it's a plain number, assume MB
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    m = re.search(r"(\d+\.?\d*)\s*(MB|GB)", s, re.IGNORECASE)
    if m:
        amount = float(m.group(1))
        unit = m.group(2).upper()
        if unit == "GB":
            amount *= 1000.0
        return amount
    if "unlimited" in s.lower():
        return float("inf")
    # Unknown format -> treat as missing
    return np.nan


def convert_to_days(validity_str: Any) -> float:
    if pd.isna(validity_str) or validity_str == "":
        return -1
    s = str(validity_str).lower().strip()
    if "no expiry" in s or "unlimited" in s or "never" in s:
        return float("inf")
    if "monthly" in s:
        return 30
    if "daily" in s:
        return 1
    # Hours support: convert to days (ceil)
    m = re.search(r"(\d+)\s*(hour|hours)", s, re.IGNORECASE)
    if m:
        hrs = int(m.group(1))
        return math.ceil(hrs / 24.0)
    m = re.search(r"(\d+)\s*(day|days|month|months)", s, re.IGNORECASE)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("month"):
            return amount * 30
        return amount
    # As a last resort, try plain integer
    try:
        return int(s)
    except Exception:
        return -1


def extract_cost(cost_str: Any) -> float:
    if pd.isna(cost_str) or cost_str == "":
        return 0.0
    s = str(cost_str)
    m = re.search(r"(\d+\.?\d*)", s)
    if m:
        return float(m.group(1))
    return 0.0


def analyze_plans(plans: List[Dict[str, Any]], trip_days: int, daily_mb: Optional[float]) -> pd.DataFrame:
    df = pd.DataFrame(plans)
    if df.empty:
        return df

    # Normalize fields
    df["data_mb"] = df.get("capacity", "").apply(convert_to_mb)
    df["validity_days"] = df.get("period", "").apply(convert_to_days)
    df["plan_cost"] = df.get("price", "").apply(extract_cost)

    # Detect daily quota capacities (e.g., "1 GB/day", "Daily 1GB")
    cap_str = df.get("capacity", "").astype(str).str.lower()
    df["is_daily_quota"] = cap_str.str.contains(r"/\s*day|per\s*day|daily", regex=True)

    # Compute effective total data across the validity window
    def effective_total_data(row) -> float:
        data = row.get("data_mb", np.nan)
        validity = row.get("validity_days", np.nan)
        if pd.isna(data) or pd.isna(validity):
            return np.nan
        if data == float("inf") or validity == float("inf"):
            return float("inf")
        if row.get("is_daily_quota", False):
            try:
                if validity > 0:
                    return data * validity
            except Exception:
                return np.nan
        return data

    df["plan_total_data_mb"] = df.apply(effective_total_data, axis=1)

    total_required_data_mb = (trip_days * daily_mb) if (daily_mb is not None) else float("inf")

    def calculate_total_cost_row(row) -> float:
        price = row.get("plan_cost", np.nan)
        validity = row.get("validity_days", np.nan)
        total_data = row.get("plan_total_data_mb", np.nan)

        if pd.isna(price) or pd.isna(validity) or pd.isna(total_data):
            return np.nan

        # purchases for duration
        if validity == float("inf"):
            purchases_duration = 1
        elif validity <= 0:
            purchases_duration = float("inf")
        else:
            purchases_duration = math.ceil(trip_days / validity)

        # purchases for data
        if total_data == 0:
            purchases_data = float("inf")
        elif total_data == float("inf"):
            purchases_data = 1
        else:
            purchases_data = math.ceil(total_required_data_mb / total_data)

        total_purchases = max(purchases_duration, purchases_data)
        if total_purchases == float("inf"):
            return float("inf")
        return total_purchases * price

    df["total_plan_cost_for_trip"] = df.apply(calculate_total_cost_row, axis=1)

    # Derived convenience metric
    df["overall_cost_per_day"] = df.apply(
        lambda r: (r["total_plan_cost_for_trip"] / trip_days)
        if (trip_days and trip_days > 0 and not pd.isna(r["total_plan_cost_for_trip"]) and r["total_plan_cost_for_trip"] not in (float("inf"),))
        else np.nan,
        axis=1,
    )

    # Remove rows that cannot satisfy requirements (inf or nan) only for the total_plan_cost_for_trip metric
    df.loc[df["total_plan_cost_for_trip"].isin([np.inf, -np.inf]), "total_plan_cost_for_trip"] = np.nan
    df.dropna(subset=["total_plan_cost_for_trip"], inplace=True)

    # Sort by total trip cost
    df.sort_values(by=["total_plan_cost_for_trip", "overall_cost_per_day"], inplace=True, ascending=[True, True])
    return df


# -------- Trip solution builder -------- #

def _merge_or_add_selection(selections: List[Dict[str, Any]], new_sel: Dict[str, Any]):
    """Merge purchases of the same plan to reduce the number of distinct plan entries.
    Two entries are considered the same plan if plan_id matches (preferred), else provider+plan_title.
    """
    pid = str(new_sel.get("plan_id") or "")
    for s in selections:
        same = False
        if pid and pid == str(s.get("plan_id") or ""):
            same = True
        elif (not pid) and (s.get("plan_id") in (None, "")):
            if str(new_sel.get("provider","")) == str(s.get("provider","")) and str(new_sel.get("plan_title","")) == str(s.get("plan_title","")):
                same = True
        if same:
            s["purchase_count"] = s.get("purchase_count", 0) + new_sel.get("purchase_count", 0)
            s["days_covered"] = s.get("days_covered", 0) + new_sel.get("days_covered", 0)
            s["data_delivered_mb"] = s.get("data_delivered_mb", 0.0) + new_sel.get("data_delivered_mb", 0.0)
            s["used_mb_for_feasibility"] = s.get("used_mb_for_feasibility", 0.0) + new_sel.get("used_mb_for_feasibility", 0.0)
            s["cost_total"] = s.get("cost_total", 0.0) + new_sel.get("cost_total", 0.0)
            # keep the max effective days for info
            eff = new_sel.get("plan_effective_days_at_R")
            if eff is not None:
                s["plan_effective_days_at_R"] = max(s.get("plan_effective_days_at_R", 0), eff)
            # prefer lower effective cost/day if present
            ecpd_new = new_sel.get("effective_cost_per_day_at_R_trip")
            ecpd_old = s.get("effective_cost_per_day_at_R_trip")
            if ecpd_new is not None:
                s["effective_cost_per_day_at_R_trip"] = min(ecpd_old, ecpd_new) if ecpd_old is not None else ecpd_new
            return
    selections.append(new_sel)

def _compute_deliverable_for_days(row: pd.Series, daily_need_mb: float, days_to_use: int) -> float:
    if days_to_use <= 0:
        return 0.0
    validity = row.get("validity_days", np.nan)
    if pd.isna(validity) or validity <= 0:
        return 0.0
    days = min(days_to_use, int(validity) if validity != float("inf") else days_to_use)
    data_mb = row.get("data_mb", np.nan)
    if pd.isna(data_mb):
        return 0.0
    # If unlimited data
    if data_mb == float("inf"):
        return daily_need_mb * days
    # Daily quota?
    is_daily = bool(row.get("is_daily_quota", False)) or (isinstance(row.get("capacity", ""), str) and "/day" in str(row.get("capacity", "")).lower())
    if is_daily:
        daily_quota = data_mb  # data_mb stores MB per day in this case
        usable_per_day = min(daily_quota, daily_need_mb)
        return usable_per_day * days
    # Non-daily total cap: can only use up to R MB per day for 'days'
    return min(data_mb, daily_need_mb * days)


def _days_covered_at_R(row: pd.Series, daily_need_mb: float) -> int:
    validity = row.get("validity_days", np.nan)
    if pd.isna(validity) or validity <= 0:
        return 0
    if validity == float("inf"):
        validity = 36500  # practically infinite for our purpose
    total_data = row.get("plan_total_data_mb", np.nan)
    if pd.isna(total_data) or total_data == float("inf"):
        return int(validity)
    max_days_by_data = math.floor(total_data / max(daily_need_mb, 1e-9))
    if max_days_by_data < 0:
        max_days_by_data = 0
    return int(min(validity, max_days_by_data))


def build_trip_solution(plans: List[Dict[str, Any]], trip_days: int, daily_need_mb: Optional[float], exclude_providers: Optional[List[str]] = None, exclude_title_keywords: Optional[List[str]] = None):
    # Normalize first (similar to analyze_plans but without filtering rows out)
    df = pd.DataFrame(plans)
    if df.empty:
        return [], {"ok": False, "reason": "No plans scraped"}

    # Exclude providers if requested
    if exclude_providers:
        ex = [e.strip().lower() for e in exclude_providers if e.strip()]
        if ex:
            prov_norm = df.get("provider", "").astype(str).str.lower()
            mask = ~prov_norm.apply(lambda p: any(e in p for e in ex))
            df = df[mask]
            if df.empty:
                return [], {"ok": False, "reason": "All plans excluded by provider filter"}

    # Exclude plan title keywords (e.g., when ineligible for specific promos)
    if exclude_title_keywords:
        exk = [e.strip().lower() for e in exclude_title_keywords if e.strip()]
        if exk:
            title_norm = df.get("plan_title", "").astype(str).str.lower()
            mask = ~title_norm.apply(lambda t: any(k in t for k in exk))
            df = df[mask]
            if df.empty:
                return [], {"ok": False, "reason": "All plans excluded by title filter"}

    df["data_mb"] = df.get("capacity", "").apply(convert_to_mb)
    df["validity_days"] = df.get("period", "").apply(convert_to_days)
    # Use numeric USD-derived price directly when available; fall back to price
    df["plan_cost"] = pd.to_numeric(df.get("price"), errors='coerce')

    cap_str = df.get("capacity", "").astype(str).str.lower()
    df["is_daily_quota"] = cap_str.str.contains(r"/\s*day|per\s*day|daily", regex=True)

    # Effective total data across own validity
    def effective_total(row):
        data = row.get("data_mb", np.nan)
        validity = row.get("validity_days", np.nan)
        if pd.isna(data) or pd.isna(validity):
            return np.nan
        if data == float("inf") or validity == float("inf"):
            return float("inf")
        if row.get("is_daily_quota", False):
            return data * validity if validity > 0 else 0.0
        return data

    df["plan_total_data_mb"] = df.apply(effective_total, axis=1)

    # Max data usable within the trip window (independent of R)
    def plan_max_data_trip(row):
        validity = row.get("validity_days", np.nan)
        if pd.isna(validity) or validity <= 0:
            return 0.0
        if np.isinf(validity):
            effective_days = trip_days
        else:
            effective_days = min(int(validity), int(trip_days))
        data = row.get("data_mb", np.nan)
        if pd.isna(data):
            return 0.0
        if row.get("is_daily_quota", False):
            # Daily quota plans: at most daily_quota * min(validity, trip_days)
            if np.isinf(data):
                return float("inf")
            return float(data) * float(effective_days)
        # Non-daily plans: full bucket available during validity within trip
        total = row.get("plan_total_data_mb", np.nan)
        if pd.isna(total):
            return 0.0
        return float(total)

    df["plan_max_data_trip_mb"] = df.apply(plan_max_data_trip, axis=1)

    # Daily requirement used in effective validity and data_possible metrics
    R = daily_need_mb if (daily_need_mb is not None) else 1.0

    # Effective validity in days at R (not bounded by trip)
    def eff_valid_days(row):
        v = row.get("validity_days", np.nan)
        if pd.isna(v) or v <= 0:
            return 0.0
        vdays = float('inf') if np.isinf(v) else float(v)
        total = row.get("plan_total_data_mb", np.nan)
        if pd.isna(total):
            return 0.0
        if R <= 0:
            return vdays
        # days until data exhaust at R
        days_by_data = float('inf') if np.isinf(total) else (total / R)
        return float(min(vdays, days_by_data))

    df["effective_validity_days_at_R"] = df.apply(eff_valid_days, axis=1)
    df["effective_validity_days_at_R_trip"] = df["effective_validity_days_at_R"].apply(lambda x: min(x, float(trip_days)))

    # Data possible at R (not bounded by trip) and within trip
    def data_possible_at_R(row):
        v = row.get("validity_days", np.nan)
        total = row.get("plan_total_data_mb", np.nan)
        if pd.isna(v) or pd.isna(total):
            return 0.0
        vdays = float('inf') if np.isinf(v) else float(v)
        if np.isinf(total):
            return float('inf') if np.isinf(vdays) else R * vdays
        return min(total, R * vdays)

    def data_possible_at_R_trip(row):
        v = row.get("validity_days", np.nan)
        total = row.get("plan_total_data_mb", np.nan)
        if pd.isna(v) or pd.isna(total):
            return 0.0
        vdays = float('inf') if np.isinf(v) else float(v)
        vdays_trip = min(vdays, float(trip_days))
        if np.isinf(total):
            return float('inf') if np.isinf(vdays_trip) else R * vdays_trip
        return min(total, R * vdays_trip)

    df["data_possible_mb_at_R"] = df.apply(data_possible_at_R, axis=1)
    df["data_possible_mb_at_R_trip"] = df.apply(data_possible_at_R_trip, axis=1)

    # Determine free and Firsty
    # Coerce promo/base to numeric then detect free
    df["price_usd_promo"] = pd.to_numeric(df.get("price_usd_promo"), errors='coerce')
    df["price_usd_base"] = pd.to_numeric(df.get("price_usd_base"), errors='coerce')
    # Consider any-currency zero as free as well
    df["promo_zero_any"] = df.get("promo_zero_any", False).astype(bool)
    df["base_zero_any"] = df.get("base_zero_any", False).astype(bool)
    df["is_free_via_promo"] = (df["price_usd_promo"].fillna(np.inf) <= 1e-9) | df["promo_zero_any"]
    df["is_free_via_base"] = (df["price_usd_base"].fillna(np.inf) <= 1e-9) | df["base_zero_any"]
    df["is_free_raw"] = df["plan_cost"].fillna(np.inf) <= 1e-9
    df["is_free"] = df["is_free_raw"] | df["is_free_via_promo"] | df["is_free_via_base"]
    # Force plan_cost to 0.0 for free plans
    df.loc[df["is_free"], "plan_cost"] = 0.0

    prov = df.get("provider", "").astype(str).str.lower()
    title = df.get("plan_title", "").astype(str).str.lower()
    # Firsty Free detection: either provider exactly "firsty free" OR (provider contains "firsty" AND cost == 0)
    prov_norm = prov.str.strip()
    exact_firsty_free = prov_norm.eq("firsty free")
    firsty_and_zero_cost = prov_norm.str.contains("firsty") & (df["plan_cost"].fillna(0) <= 1e-9)
    df["is_firsty_free"] = exact_firsty_free | firsty_and_zero_cost

    # Daily requirement already defined above for metrics

    N = int(trip_days)
    remaining_need = [R] * N
    selections: List[Dict[str, Any]] = []

    def simulate_plan(row: pd.Series, rem: List[float]) -> (List[float], float, int):
        # Returns per-day contributions, total delivered, days_covered (any contribution),
        # while allowing best activation shift within trip window.
        valid = row.get("validity_days", np.nan)
        if pd.isna(valid) or valid <= 0:
            return [0.0]*N, 0.0, 0
        days_valid = N if np.isinf(valid) else min(int(valid), N)
        is_daily = bool(row.get("is_daily_quota", False))
        data = row.get("data_mb", np.nan)
        total_bucket = float('inf') if (not is_daily and (np.isinf(data))) else row.get("plan_total_data_mb", 0.0)

        best_contrib = [0.0]*N
        best_delivered = 0.0
        best_days_cov = 0
        # Try all possible activation starts
        for start in range(0, N):
            end = min(N, start + days_valid)
            contrib = [0.0]*N
            delivered_sum = 0.0
            days_cov = 0
            bucket = total_bucket if not pd.isna(total_bucket) else 0.0
            for d in range(start, end):
                need = rem[d]
                if need <= 1e-9:
                    continue
                if is_daily:
                    dq = data if not pd.isna(data) else 0.0
                    delivered = max(0.0, min(need, dq))
                else:
                    if pd.isna(bucket) or bucket <= 0.0:
                        delivered = 0.0
                    else:
                        delivered = max(0.0, min(need, R, bucket))
                if delivered > 0:
                    contrib[d] += delivered
                    delivered_sum += delivered
                    days_cov += 1
                    if not is_daily and not np.isinf(bucket):
                        bucket -= delivered
            # Keep best by delivered_sum then days_cov
            if (delivered_sum > best_delivered + 1e-9) or (abs(delivered_sum - best_delivered) <= 1e-9 and days_cov > best_days_cov):
                best_contrib = contrib
                best_delivered = delivered_sum
                best_days_cov = days_cov
        return best_contrib, best_delivered, best_days_cov

    def apply_selection(row: pd.Series, contrib: List[float], delivered: float, days_cov: int, price: float, promo_used_flag: bool):
        nonlocal remaining_need
        # subtract per-day
        for d in range(N):
            if contrib[d] > 0:
                remaining_need[d] = max(0.0, remaining_need[d] - contrib[d])
        # For reporting, data_delivered_mb should reflect plan's possible data at R within trip (even if sums exceed need)
        plan_possible = row.get("data_possible_mb_at_R_trip", delivered)
        eff_valid_trip = row.get("effective_validity_days_at_R_trip", 0.0)
        eff_cost_per_day = 0.0
        try:
            eff_cost_per_day = float(price) / eff_valid_trip if eff_valid_trip > 0 else (0.0 if float(price) == 0.0 else float('inf'))
        except Exception:
            eff_cost_per_day = 0.0
        sel = {
            "provider": row.get("provider", ""),
            "provider_id": row.get("provider_id", ""),
            "provider_slug": row.get("provider_slug", ""),
            "plan_id": row.get("plan_id", ""),
            "plan_title": row.get("plan_title", ""),
            "price": row.get("plan_cost", 0.0),
            "purchase_count": 1,
            "days_covered": days_cov,
            "data_delivered_mb": plan_possible,
            "used_mb_for_feasibility": delivered,
            "cost_total": float(price),
            "plan_effective_days_at_R": _days_covered_at_R(row, R),
            "plan_total_data_mb": row.get("plan_total_data_mb", np.nan),
            "validity_days": row.get("validity_days", np.nan),
            "effective_validity_days_at_R": row.get("effective_validity_days_at_R", 0.0),
            "effective_validity_days_at_R_trip": eff_valid_trip,
            "effective_cost_per_day_at_R_trip": eff_cost_per_day,
            "promo_used": bool(promo_used_flag),
        }
        _merge_or_add_selection(selections, sel)

    # 1) Non-Firsty free plans (one per provider)
    free_df = df[(df["is_free"] | df["is_free_via_promo"] | df["is_free_via_base"]) & (~df["is_firsty_free"])].copy()
    # Track promo consumption per plan_id (used in free and paid steps)
    promo_consumed_by_plan: Dict[str, bool] = {}
    if not free_df.empty:
        # Prepare columns
        if "scope_pref" not in free_df.columns:
            free_df["scope_pref"] = 0
        if "coverage_count" not in free_df.columns:
            free_df["coverage_count"] = 0
        if "effective_validity_days_at_R_trip" not in free_df.columns:
            free_df["effective_validity_days_at_R_trip"] = 0.0
        used_providers = set()
        # Greedy loop: keep selecting the best remaining free plan that contributes > 0
        while True:
            if all(n <= 1e-9 for n in remaining_need):
                break
            best_idx = None
            best_row = None
            best_rank = None  # tuple for sorting
            best_contrib = None
            best_delivered = 0.0
            best_days_cov = 0
            for idx, row in free_df.iterrows():
                prov_id = str(row.get("provider_id", "")).strip().lower()
                prov_name_key = str(row.get("provider", "")).strip().lower()
                prov_key = prov_id if prov_id else prov_name_key
                if prov_key in used_providers:
                    continue
                contrib, delivered, days_cov = simulate_plan(row, remaining_need)
                if delivered <= 0 and days_cov <= 0:
                    continue
                rank = (
                    float(row.get("effective_validity_days_at_R_trip", 0.0)),
                    int(row.get("scope_pref", 0)),
                    int(row.get("coverage_count", 0)),
                    float(row.get("validity_days", 0) if not pd.isna(row.get("validity_days", np.nan)) else 0),
                )
                if (best_rank is None) or (rank > best_rank):
                    best_rank = rank
                    best_idx = idx
                    best_row = row
                    best_contrib = contrib
                    best_delivered = delivered
                    best_days_cov = days_cov
            if best_row is None:
                break
            promo_used_here = bool(best_row.get("is_free_via_promo", False))
            apply_selection(best_row, best_contrib, best_delivered, best_days_cov, price=0.0, promo_used_flag=promo_used_here)
            pid = str(best_row.get("plan_id", ""))
            if promo_used_here and pid:
                promo_consumed_by_plan[pid] = True
            prov_id = str(best_row.get("provider_id", "")).strip().lower()
            prov_name_key = str(best_row.get("provider", "")).strip().lower()
            prov_key = prov_id if prov_id else prov_name_key
            used_providers.add(prov_key)

    # 2) Paid plans until all days satisfied
    paid_df = df[~(df["is_free"] | df["is_free_via_promo"] | df["is_free_via_base"])].copy()
    # Track promo consumption per plan_id (also used in free step)
    promo_consumed_by_plan: Dict[str, bool] = {}
    while not all(n <= 1e-9 for n in remaining_need) and not paid_df.empty:
        best = None
        best_cpm = None
        best_days_cov = 0
        best_delivered = 0.0
        for idx, row in paid_df.iterrows():
            contrib, delivered, days_cov = simulate_plan(row, remaining_need)
            if delivered <= 0:
                continue
            pid = str(row.get("plan_id", ""))
            promo_avail = row.get("price_usd_promo") if row.get("price_usd_promo") is not None else None
            base_price = row.get("price_usd_base") if row.get("price_usd_base") is not None else None
            if pid and promo_avail is not None and not promo_consumed_by_plan.get(pid, False):
                price_current = float(promo_avail)
                promo_used_here = True
            else:
                price_current = float(base_price) if base_price is not None else None
                promo_used_here = False
            if price_current is None:
                continue
            cpm = price_current / max(delivered, 1e-12)
            if (best_cpm is None) or (cpm < best_cpm) or (abs(cpm - best_cpm) <= 1e-12 and (days_cov > best_days_cov or (days_cov == best_days_cov and delivered > best_delivered))):
                best = (idx, row, contrib, delivered, days_cov, price_current, promo_used_here)
                best_cpm = cpm
                best_days_cov = days_cov
                best_delivered = delivered
        if best is None:
            break
        _, row, contrib, delivered, days_cov, price_current, promo_used_here = best
        apply_selection(row, contrib, delivered, days_cov, price=price_current, promo_used_flag=promo_used_here)
        pid = str(row.get("plan_id", ""))
        if promo_used_here and pid:
            promo_consumed_by_plan[pid] = True

    # No Firsty Free here, as we require per-day data >= R; firsty is not considered sufficient data

    total_cost = sum(s["cost_total"] for s in selections)
    used_total = sum(s.get("used_mb_for_feasibility", 0.0) for s in selections)
    days_met = sum(1 for n in remaining_need if n <= 1e-9)

    ok = (days_met >= trip_days and used_total + 1e-6 >= trip_days * R and all(n <= 1e-9 for n in remaining_need))
    stats = {
        "ok": ok,
        "total_cost": total_cost,
        "total_data_mb": used_total,
        "required_data_mb": trip_days * R,
        "days_covered": days_met,
        "trip_days": trip_days,
    }
    return selections, stats


# -------- File writing helpers -------- #

def _unique_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    for i in range(1, 100):
        candidate = f"{base}_{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
    # Fallback to timestamp if many collisions
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"{base}_{ts}{ext}"


def _safe_write_csv(df: pd.DataFrame, path: str):
    try:
        df.to_csv(path, index=False, encoding="utf-8")
    except PermissionError as e:
        alt = _unique_path(path)
        print(f"Permission denied writing {path}. Trying alternate filename: {alt}")
        df.to_csv(alt, index=False, encoding="utf-8")
        return alt
    return path


def _safe_write_json(obj: Any, path: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except PermissionError:
        alt = _unique_path(path)
        print(f"Permission denied writing {path}. Trying alternate filename: {alt}")
        with open(alt, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return alt
    return path


# -------- Orchestrator (interactive) -------- #

def prompt_float(prompt: str, allow_blank: bool = False) -> Optional[float]:
    while True:
        s = input(prompt).strip()
        if allow_blank and s == "":
            return None
        try:
            v = float(s)
            if v < 0:
                print("Please enter a non-negative number.")
                continue
            return v
        except ValueError:
            print("Invalid number. Try again.")


def prompt_int(prompt: str) -> int:
    while True:
        s = input(prompt).strip()
        try:
            v = int(s)
            if v <= 0:
                print("Enter an integer > 0.")
                continue
            return v
        except ValueError:
            print("Invalid integer. Try again.")


def main():
    print("=== eSIM Plan Workflow (France) ===")

    # Country is fixed to France per request, but keep here for future flexibility
    country_slug = "france"
    print("Country: France")

    # Prompt for trip parameters
    trip_days = prompt_int("How many days is the trip? ")
    print("Provide either daily usage (MB/day) OR monthly usage (MB/month). Leave one blank.")
    daily_mb = prompt_float("Estimated data usage per day (MB/day), or press Enter to skip: ", allow_blank=True)
    monthly_mb = None
    if daily_mb is None:
        monthly_mb = prompt_float("Estimated data usage per month (MB/month): ")
        # Convert monthly -> daily
        daily_mb = monthly_mb / 30.0 if monthly_mb is not None else None

    if daily_mb is None:
        print("No usage provided. Assuming unlimited data requirement (may exclude many plans).")

    # Scrape
    plans = scrape_country(country_slug)

    # Build a concrete trip solution rather than a ranked list
    # Optional exclusion list
    ex_input = input("Exclude providers (comma-separated, optional): ").strip()
    exclude_list = [s.strip() for s in ex_input.split(",")] if ex_input else None
    exk_input = input("Exclude plan title keywords (comma-separated, optional): ").strip()
    exclude_keywords = [s.strip() for s in exk_input.split(",")] if exk_input else None

    selections, stats = build_trip_solution(plans, trip_days=trip_days, daily_need_mb=daily_mb, exclude_providers=exclude_list, exclude_title_keywords=exclude_keywords)

    os.makedirs("scraped_data", exist_ok=True)
    usage_tag = f"{int(daily_mb)}mbpd" if (daily_mb is not None and not math.isinf(daily_mb)) else "unbounded"
    out_csv = os.path.join("scraped_data", f"trip_solution_{country_slug}_{trip_days}days_{usage_tag}.csv")

    if not selections:
        print("No feasible trip solution could be constructed.")
        raise SystemExit(1)

    # Write selections CSV
    sel_df = pd.DataFrame(selections)
    sel_df = sel_df[[c for c in [
        "provider","provider_id","provider_slug","plan_id","plan_title","price",
        "purchase_count","days_covered","data_delivered_mb","used_mb_for_feasibility",
        "plan_total_data_mb","validity_days",
        "effective_validity_days_at_R","effective_validity_days_at_R_trip","effective_cost_per_day_at_R_trip",
        "promo_used","price_usd_promo","price_usd_base","promo_zero_any","base_zero_any",
        "cost_total","plan_effective_days_at_R"
    ] if c in sel_df.columns]]
    out_csv_written = _safe_write_csv(sel_df, out_csv)

    # Also write a JSON with stats
    stats_path = os.path.join("scraped_data", f"trip_solution_{country_slug}_{trip_days}days_{usage_tag}.json")
    stats_written = _safe_write_json({"stats": stats, "selections": selections}, stats_path)

    print("\nTrip solution summary:")
    print(f"- Feasible: {stats['ok']}")
    print(f"- Trip days: {stats['trip_days']}")
    print(f"- Required data (MB): {int(stats['required_data_mb'])}")
    print(f"- Delivered data (MB): {int(stats['total_data_mb'])}")
    print(f"- Total cost: ${stats['total_cost']:.2f}")
    print(f"Saved CSV to: {out_csv_written}")
    print(f"Saved JSON to: {stats_written}")


if __name__ == "__main__":
    main()
