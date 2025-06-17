import pandas as pd
import numpy as np
import re
import math

def parse_data(data_str):
    """Converts data string (e.g., '1GB', '500MB', 'Unlimited') to MB."""
    data_str = str(data_str).strip().upper()
    if 'UNLIMITED' in data_str:
        return np.inf  # Represent unlimited data as infinity
    gb_match = re.match(r'([\d.]+)\s*GB', data_str)
    mb_match = re.match(r'([\d.]+)\s*MB', data_str)
    if gb_match:
        return float(gb_match.group(1)) * 1024
    elif mb_match:
        return float(mb_match.group(1))
    else:
        # Try to convert directly if it's just a number (assuming MB)
        try:
            return float(data_str)
        except ValueError:
            return 0 # Or np.nan, depending on how you want to handle invalid formats

def parse_validity(validity_str):
    """Converts validity string (e.g., '7 Days', 'No Expiry') to days or np.inf."""
    validity_str = str(validity_str).strip().lower() # Convert to lower for case-insensitive matching

    # Check for unlimited/no expiry terms
    if 'no expiry' in validity_str or 'unlimited' in validity_str or 'never' in validity_str:
        return np.inf

    # Check for explicit days
    days_match = re.match(r'([\d]+)\s*days?', validity_str)
    if days_match:
        return int(days_match.group(1))
    else:
        # Try to convert directly if it's just a number (assuming days)
        try:
            return int(validity_str)
        except ValueError:
            return 0 # Treat unparseable formats as 0 validity

def calculate_total_cost(row, trip_duration_days, total_required_data_mb):
    """Calculates the total cost for a plan based on trip requirements."""
    price = row['price']
    validity = row['validity_days']
    data = row['data_mb']

    # Handle invalid numeric data before calculations
    # Allow price == 0 for free/trial plans
    if pd.isna(price) or pd.isna(validity) or pd.isna(data):
        return np.nan # Cannot calculate cost if essential info is missing

    # Purchases needed for duration
    if validity == np.inf: # No expiry / Unlimited validity
        purchases_needed_duration = 1
    elif validity <= 0:
        purchases_needed_duration = np.inf # Cannot fulfill duration if validity is 0 or less (and not infinite)
    else:
        purchases_needed_duration = math.ceil(trip_duration_days / validity)

    # Purchases needed for data
    if data == 0:
         purchases_needed_data = np.inf # Cannot fulfill data if data amount is 0
    elif data == np.inf: # Unlimited data
        purchases_needed_data = 1 # Only need 1 purchase for data if it's unlimited
    else:
        purchases_needed_data = math.ceil(total_required_data_mb / data)

    # Total purchases is the max needed for either duration or data
    total_purchases = max(purchases_needed_duration, purchases_needed_data)

    # If infinite purchases needed, cost is infinite
    if total_purchases == np.inf:
        return np.inf
    else:
        return total_purchases * price


def analyze_plans(input_csv_path, output_csv_path, trip_duration_days, daily_data_mb):
    """
    Analyzes eSIM plans, calculates total trip cost considering multiple purchases,
    and saves the results to a CSV file.

    Args:
        input_csv_path (str): Path to the input CSV file containing plan data.
        output_csv_path (str): Path to save the analyzed CSV file.
        trip_duration_days (int): The duration of the trip in days.
        daily_data_mb (int): The minimum required data per day in MB.
    """
    try:
        df = pd.read_csv(input_csv_path)
        print(f"Successfully read {len(df)} plans from {input_csv_path}")
    except FileNotFoundError:
        print(f"Error: Input CSV file not found at {input_csv_path}")
        return
    except Exception as e:
        print(f"Error reading input CSV file: {e}")
        return

    # --- Data Cleaning ---
    df['price'] = df['price'].astype(str).str.replace(r'[$,]', '', regex=True).replace('', np.nan)
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df['data_mb'] = df['data'].apply(parse_data)
    df['validity_days'] = df['validity'].apply(parse_validity)

    # Drop rows where essential numeric conversions failed (price is crucial)
    # Keep rows even if data/validity parsing failed initially, cost calculation handles NaN
    df.dropna(subset=['price'], inplace=True)
    print(f"{len(df)} plans remaining after initial price cleaning.")

    # --- Calculation ---
    total_required_data_mb = trip_duration_days * daily_data_mb

    print(f"\nTrip Requirements:")
    print(f"- Duration: {trip_duration_days} days")
    print(f"- Minimum Daily Data: {daily_data_mb} MB")
    print(f"- Minimum Total Data: {total_required_data_mb} MB\n")

    # Calculate total trip cost for each plan
    df['total_trip_cost'] = df.apply(
        calculate_total_cost,
        axis=1,
        trip_duration_days=trip_duration_days,
        total_required_data_mb=total_required_data_mb
    )

    # Drop plans where cost calculation resulted in NaN or Inf (cannot meet requirements)
    df.replace([np.inf, -np.inf], np.nan, inplace=True) # Replace Inf with NaN for dropping
    df.dropna(subset=['total_trip_cost'], inplace=True)
    print(f"{len(df)} plans remaining after calculating and filtering by total trip cost.")


    # --- Sorting ---
    if df.empty:
        print("No plans found that could meet the specified requirements even with multiple purchases.")
        return

    df.sort_values(by='total_trip_cost', ascending=True, inplace=True)

    # --- Output ---
    # Save to CSV
    try:
        df.to_csv(output_csv_path, index=False, encoding='utf-8')
        print(f"\nAnalysis complete. Results saved to: {output_csv_path}")
    except Exception as e:
        print(f"Error saving results to CSV: {e}")

    # Print top 5 to console
    print("\n--- Top 5 Cheapest Plans (Based on Total Trip Cost) ---")
    print(df.head(5)[['provider', 'plan_title', 'price', 'data', 'validity', 'total_trip_cost']].to_string(index=False))
    print("--------------------------------------------------------")


if __name__ == "__main__":
    # Configuration
    INPUT_CSV = 'esim_plans_usa.csv'       # Path relative to the execution directory
    OUTPUT_CSV = 'analyzed_esim_plans_usa.csv' # Path relative to the execution directory
    TRIP_DURATION = 6                      # days
    DAILY_DATA_NEED = 100                  # MB

    analyze_plans(INPUT_CSV, OUTPUT_CSV, TRIP_DURATION, DAILY_DATA_NEED)