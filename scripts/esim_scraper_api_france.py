import requests
import csv
import json

def fetch_esim_data(url):
    """Fetches data from the esimdb API."""
    try:
        response = requests.get(url)
        # Raise an exception for bad status codes (4xx or 5xx)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from {url}: {e}")
        return None

def write_to_csv(data, filename="esim_data.csv"):
    """Writes the plan data to a CSV file."""
    if not data:
        print("No data to write to CSV.")
        return

    # Combine featured plans and regular data plans
    all_plans = data.get('featured', []) + data.get('data', [])

    if not all_plans:
        print("No plans found in the 'featured' or 'data' keys.")
        return

    # Define the headers for the CSV file.
    # We'll get them from the keys of the first plan, but also add some common ones
    # to ensure all columns are present even if the first plan doesn't have them.
    headers = list(all_plans[0].keys())

    # The 'prices' and 'promoPrices' are dictionaries. We will flatten them.
    # We will remove the original dictionary keys and add the flattened ones.
    if 'prices' in headers:
        headers.remove('prices')
    if 'promoPrices' in headers:
        headers.remove('promoPrices')

    # Add specific price columns if they exist in the first plan
    if 'prices' in all_plans[0] and isinstance(all_plans[0]['prices'], dict):
        price_headers = [f"price_{currency.lower()}" for currency in all_plans[0]['prices'].keys()]
        headers.extend(price_headers)

    if 'promoPrices' in all_plans[0] and isinstance(all_plans[0]['promoPrices'], dict):
        promo_price_headers = [f"promo_price_{currency.lower()}" for currency in all_plans[0]['promoPrices'].keys()]
        headers.extend(promo_price_headers)


    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers, extrasaction='ignore')
            writer.writeheader()

            for plan in all_plans:
                # Create a copy to modify
                plan_data = plan.copy()

                # Flatten nested price dictionaries
                if 'prices' in plan_data and isinstance(plan_data['prices'], dict):
                    for currency, value in plan_data['prices'].items():
                        plan_data[f"price_{currency.lower()}"] = value
                    del plan_data['prices']

                if 'promoPrices' in plan_data and isinstance(plan_data['promoPrices'], dict):
                    for currency, value in plan_data['promoPrices'].items():
                        plan_data[f"promo_price_{currency.lower()}"] = value
                    del plan_data['promoPrices']

                # Convert list of dictionaries to a string for CSV
                if 'internetBreakouts' in plan_data and isinstance(plan_data['internetBreakouts'], list):
                    plan_data['internetBreakouts'] = ', '.join(
                        item.get('country', '') for item in plan_data['internetBreakouts']
                    )

                writer.writerow(plan_data)

        print(f"Successfully wrote {len(all_plans)} plans to {filename}")

    except IOError as e:
        print(f"Error writing to {filename}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    api_url = "https://esimdb.com/api/client/countries/france/data-plans?locale=en"
    json_data = fetch_esim_data(api_url)

    if json_data:
        write_to_csv(json_data)