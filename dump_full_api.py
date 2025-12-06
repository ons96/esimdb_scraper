"""
Dump full API response to CSV for review.
This extracts ALL fields from the ESIMDB API without filtering.
"""
import requests
import pandas as pd
import json

def main():
    url = "https://esimdb.com/api/client/regions/europe/data-plans?locale=en"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    print("Fetching Europe plans from API...")
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    all_plans = data.get("plans", [])
    print(f"Got {len(all_plans)} plans")

    # Flatten the JSON - expand nested dicts into separate columns
    flattened_plans = []
    for plan in all_plans:
        flat = {}
        for key, value in plan.items():
            if isinstance(value, dict):
                # Expand dict fields like "prices", "promoPrices"
                for sub_key, sub_val in value.items():
                    flat[f"{key}_{sub_key}"] = sub_val
            elif isinstance(value, list):
                # Convert lists to comma-separated strings or count
                if len(value) > 10:
                    flat[key] = f"{len(value)} items"
                else:
                    flat[key] = ",".join(str(v) for v in value) if value else ""
            else:
                flat[key] = value
        flattened_plans.append(flat)

    df = pd.DataFrame(flattened_plans)
    
    # Save full dump
    output_file = "esim_api_full_dump.csv"
    df.to_csv(output_file, index=False)
    print(f"Saved FULL API dump to {output_file}")
    print(f"Columns ({len(df.columns)}): {list(df.columns)}")
    print(f"File size: {len(df.to_csv()):,} bytes (approx)")
    
    # Also save raw JSON for reference
    with open("esim_api_full_dump.json", "w", encoding="utf-8") as f:
        json.dump(all_plans[:5], f, indent=2)  # First 5 plans for review
    print("Saved first 5 plans to esim_api_full_dump.json for review")

if __name__ == "__main__":
    main()
