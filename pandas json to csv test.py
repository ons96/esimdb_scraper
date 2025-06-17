import json
import pandas as pd
import re
import os

def convert_to_mb(data_str):
    """Convert data amounts to MB."""
    if pd.isna(data_str) or data_str == '':
        return float('inf')  # Using float('inf') to indicate unlimited data
    match = re.search(r'(\d+\.?\d*)\s*(MB|GB)', data_str, re.IGNORECASE)
    if match:
        amount, unit = match.groups()
        amount = float(amount)
        if unit.upper() == 'GB':
            amount *= 1000
        return amount
    return float('inf')  # Changed -1 to float('inf') for clarity

def convert_to_days(validity_str):
    """Convert plan validity to days."""
    if pd.isna(validity_str) or validity_str == '':
        return -1  # Using -1 to indicate unlimited or unspecified validity
    if "monthly" in validity_str.lower():
        return 30
    elif "daily" in validity_str.lower():
        return 1
    match = re.search(r'(\d+)\s*(day|month|monthly)', validity_str, re.IGNORECASE)
    if match:
        amount, unit = match.groups()
        amount = int(amount)
        if unit.lower() == 'month':
            amount *= 30
        return amount
    elif "no expiry" in validity_str.lower():
        return 36500  # Set to 100 years for no expiry
    return -1

def extract_cost(cost_str):
    """Extract numeric cost from string."""
    if pd.isna(cost_str) or cost_str == '':
        return 0
    match = re.search(r'(\d+\.\d+)', cost_str)
    if match:
        return float(match.group(1))
    return 0

def consolidate_plans(json_file_path, trip_length=None, data_usage_per_day=None, data_usage_per_month=None):
    """
    Consolidate extracted plans, convert data and validity, and calculate cost per day.
    """
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Load data directly into DataFrame from scraped JSON
    df = pd.DataFrame(data)

    # Convert data and validity
    df['data_mb'] = df['capacity'].apply(convert_to_mb)
    df['validity_days'] = df['period'].apply(convert_to_days)

    # Extract plan cost
    df['plan_cost'] = df['price'].apply(extract_cost)

    # Calculate cost per day and data per day
    df['cost_per_day'] = df.apply(
        lambda row: row['plan_cost'] / row['validity_days'] if row['validity_days'] != -1 else (row['plan_cost'] / 36500), 
        axis=1
    ).replace([float('inf'), float('-inf')], 0)

    df['data_per_day'] = df.apply(
        lambda row: 'Unlimited' if row['data_mb'] == float('inf') 
        else (row['data_mb'] / row['validity_days'] if row['validity_days'] > 0 else 0),
        axis=1
    ).replace([float('inf'), float('-inf')], 0)

    # Handle monthly data usage
    if data_usage_per_month is not None and data_usage_per_day is None:
        data_usage_per_day = data_usage_per_month / 30.0

    # Add new columns for trip length and data usage
    df['trip_length'] = trip_length
    df['data_usage_per_day'] = data_usage_per_day
    df['data_usage_per_month'] = data_usage_per_month

    # Calculate total plan cost for trip based on the new logic
    total_trip_data = (trip_length * data_usage_per_day) if trip_length and data_usage_per_day is not None else float('inf')
    df['total_plan_cost_for_trip'] = df.apply(
        lambda row: max(
            (trip_length * data_usage_per_day / row['data_mb']) * row['plan_cost'] if row['validity_days'] >= trip_length and row['data_mb'] >= total_trip_data else float('inf'),
            (trip_length / row['validity_days']) * row['plan_cost'] if row['data_mb'] >= total_trip_data else float('inf')
        ),
        axis=1
    )

    df['overall_cost_per_day'] = df.apply(
        lambda row: row['total_plan_cost_for_trip'] / trip_length if trip_length is not None and trip_length > 0 else row['cost_per_day'],
        axis=1
    )

    # Filter plans based on trip length
    if trip_length:
        df = df[((df['validity_days'] <= trip_length) | (df['total_plan_cost_for_trip'] < df['plan_cost'] * trip_length)) | (df['validity_days'] == -1)]

    # Find the best plan based on total plan cost for trip
    if not trip_length:
        best_plan = df.sort_values(by='overall_cost_per_day').head(1)
        print("\nBest plan based on lowest overall cost per day:")
        print(best_plan)
    else:
        print("\nPlans after filtering:")
        print(df)

    return df

# File paths
json_file_path = "scraped_data/esimdb_plans.json"  # Updated path relative to workspace root
output_file_path = "scraped_data/esim_plans_consolidated_6days.csv" # Save CSV alongside JSON

# Consolidate plans
consolidated_df = consolidate_plans(json_file_path, trip_length=6, data_usage_per_day=100.0, data_usage_per_month=None)

# Save to CSV
os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
consolidated_df.to_csv(output_file_path, index=False)

print(f"Total plans consolidated: {len(consolidated_df)}")
print(f"CSV saved to: {output_file_path}")
