# --- Imports ---
import asyncio
import json
import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import argparse
import traceback
import os
import csv # Needed for fallback CSV save
import time

# --- Configuration ---
URL = "https://esimdb.com/usa"
MAX_STALL_COUNT = 10      # Adjusted stall count slightly for faster pace
SCROLL_DELAY_S = 0.6      # << REDUCED scroll delay (seconds). Tune this! Start ~0.5-0.7s
INITIAL_WAIT_S = 1.0    # << Reduced initial wait after first card found

# --- Data Storage ---
scraped_plans_data = []
scraped_plan_signatures = set()

# --- Signature Function (using BS elements) ---
# (Keep the get_plan_signature_bs function as it was)
def get_plan_signature_bs(card_soup):
    try:
        provider_img = card_soup.select_one('img.provider-image')
        provider = provider_img['alt'].strip() if provider_img and provider_img.get('alt') else 'N/A'
        if provider == 'N/A':
             provider_span = card_soup.select_one('span.provider-name')
             if provider_span:
                  full_name = provider_span.text.strip()
                  provider = full_name.split('/')[0].strip() if '/' in full_name else full_name

        plan_name_el = card_soup.select_one('div.plan-name')
        plan_title = plan_name_el.text.strip() if plan_name_el else 'N/A'

        data_el = card_soup.select_one('div.capacity-value')
        data = data_el.text.replace('<!---->','').strip() if data_el else 'N/A'

        price_el = card_soup.select_one('div.price-value')
        price = price_el.text.replace('<!---->','').strip() if price_el else 'N/A'

        signature = f"{provider}|{plan_title}|{data}|{price}".strip()
        return signature if signature and signature != 'N/A|N/A|N/A|N/A' else None # Ensure non-empty signature
    except Exception as e:
        # print(f"DEBUG: Error generating signature from soup: {e}") # Less verbose
        return None

# --- Detail Extraction Function (using BS elements) ---
# (Keep the extract_plan_details_bs function as it was)
def extract_plan_details_bs(card_soup):
    details = {
        'provider': 'N/A', 'plan_title': 'N/A', 'price': 'N/A',
        'data': 'N/A', 'validity': 'N/A', 'details_link': 'N/A'
    }
    try:
        # Reuse signature logic parts for consistency
        provider_img = card_soup.select_one('img.provider-image')
        details['provider'] = provider_img['alt'].strip() if provider_img and provider_img.get('alt') else 'N/A'
        if details['provider'] == 'N/A':
             provider_span = card_soup.select_one('span.provider-name')
             if provider_span:
                  full_name = provider_span.text.strip()
                  details['provider'] = full_name.split('/')[0].strip() if '/' in full_name else full_name

        plan_name_el = card_soup.select_one('div.plan-name')
        details['plan_title'] = plan_name_el.text.strip() if plan_name_el else 'N/A'

        data_el = card_soup.select_one('div.capacity-value')
        details['data'] = data_el.text.replace('<!---->','').strip() if data_el else 'N/A'

        validity_val_el = card_soup.select_one('div.period-value')
        validity_unit_el = card_soup.select_one('div.period-label')
        validity_val = validity_val_el.text.strip() if validity_val_el else ''
        validity_unit = validity_unit_el.text.strip() if validity_unit_el else ''
        validity_combined = f"{validity_val} {validity_unit}".strip()
        details['validity'] = validity_combined if validity_combined else 'N/A'

        price_el = card_soup.select_one('div.price-value')
        details['price'] = price_el.text.replace('<!---->','').strip() if price_el else 'N/A'

        parent_link_tag = card_soup.find_parent('a') # BeautifulSoup's parent find
        if parent_link_tag and parent_link_tag.get('href'):
            href = parent_link_tag['href']
            details['details_link'] = "https://esimdb.com" + href if href.startswith('/') else href

        return details
    except Exception as e:
        # print(f"DEBUG: Error extracting details from soup: {e}") # Less verbose
        return details # Return partially filled dict

# --- Main Async Function ---
async def scrape_esimdb(url, headless_mode=False):
    global scraped_plans_data, scraped_plan_signatures
    scraped_plans_data = []
    scraped_plan_signatures = set()

    async with async_playwright() as p:
        print(f"Launching browser (Headless: {headless_mode})...")
        browser = await p.chromium.launch(headless=headless_mode)
        page = await browser.new_page()

        await page.set_viewport_size({"width": 1920, "height": 1080})
        await page.set_extra_http_headers({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        })

        try:
            print(f"Navigating to {url}...")
            await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            print("DOM content loaded.")

            # --- Wait for Initial Cards ---
            plan_card_selector_bs = 'div.plan-card-mobile'
            print(f"Waiting for first plan card selector ('{plan_card_selector_bs}') to appear...")
            try:
                await page.wait_for_selector(plan_card_selector_bs, state='attached', timeout=30000)
                print("First plan card selector found.")
                print(f"Waiting {INITIAL_WAIT_S}s for initial render...") # Use configured wait
                await asyncio.sleep(INITIAL_WAIT_S)
            except PlaywrightTimeoutError:
                print(f"Warning: Did not find selector '{plan_card_selector_bs}' initially.")
                await browser.close()
                return

            # --- Looping Scroll and Scrape (with pageYOffset check) ---
            no_new_plans_count = 0
            attempt = 0
            MAX_ATTEMPTS = 500 # Keep safety break reasonable
            last_scroll_position = await page.evaluate("window.pageYOffset") # Get initial position

            print("\nStarting scroll loop...")
            while attempt < MAX_ATTEMPTS:
                attempt += 1
                print(f"\n--- Loop Attempt {attempt}/{MAX_ATTEMPTS} ---")
                # print(f"Current unique plans collected: {len(scraped_plans_data)}") # Less verbose

                # 1. Get Content and Parse
                # print("Getting page content...") # Less verbose
                try:
                    html = await page.content()
                    soup = BeautifulSoup(html, 'html.parser')
                except Exception as parse_err:
                    print(f"Error getting/parsing content: {parse_err}. Skipping attempt.")
                    await asyncio.sleep(SCROLL_DELAY_S)
                    continue

                # 2. Find Cards in Current View
                current_view_cards = soup.select(plan_card_selector_bs)
                # print(f"Found {len(current_view_cards)} card elements in current HTML.") # Less verbose

                # 3. Process Cards and Check for New Ones
                new_plans_found_this_loop = False
                initial_plan_count = len(scraped_plans_data)
                process_start_time = time.time() # Time processing
                for card_soup in current_view_cards:
                    signature = get_plan_signature_bs(card_soup)
                    if signature and signature not in scraped_plan_signatures:
                        scraped_plan_signatures.add(signature)
                        plan_details = extract_plan_details_bs(card_soup)
                        scraped_plans_data.append(plan_details)
                        new_plans_found_this_loop = True
                process_end_time = time.time()
                # print(f"Processing {len(current_view_cards)} cards took {process_end_time - process_start_time:.2f}s") # Optional performance metric

                added_count = len(scraped_plans_data) - initial_plan_count
                if added_count > 0:
                    print(f"Added {added_count} NEW unique plans in this loop (Total: {len(scraped_plans_data)}).")
                    no_new_plans_count = 0 # Reset stall counter because new data was found

                # 4. Scroll and Check Stall Condition
                # print("Attempting to scroll down...") # Less verbose
                # Get scroll position BEFORE scroll
                # current_scroll_position = await page.evaluate("window.pageYOffset") # Already have last_scroll_position
                await page.keyboard.press("PageDown")
                # print(f"Waiting {SCROLL_DELAY_S}s after scroll...") # Less verbose
                await asyncio.sleep(SCROLL_DELAY_S)
                # Get scroll position AFTER scroll and wait
                new_scroll_position = await page.evaluate("window.pageYOffset")
                # print(f"Scroll positions: Before={last_scroll_position}, After={new_scroll_position}") # Less verbose

                scrolled_down = new_scroll_position > last_scroll_position + 5 # Check if it moved meaningfully

                # Update last known position for the *next* loop iteration's check
                last_scroll_position = new_scroll_position

                # Increment stall counter ONLY if no new plans AND scroll didn't advance
                if not new_plans_found_this_loop and not scrolled_down:
                    print("No new plans found AND scroll position did not advance.")
                    no_new_plans_count += 1
                    print(f"Stall count incremented to {no_new_plans_count}/{MAX_STALL_COUNT}")
                elif not new_plans_found_this_loop and scrolled_down:
                     print("No new plans found, BUT scroll position advanced. Continuing...")
                     no_new_plans_count = 0 # Reset stall because we made scroll progress
                # If new_plans_found_this_loop was True, stall counter was already reset


                # 5. Exit conditions
                if no_new_plans_count >= MAX_STALL_COUNT:
                    print(f"\nStalled {MAX_STALL_COUNT} times (No new plans AND no scroll progress). Assuming end.")
                    break

                if attempt >= MAX_ATTEMPTS:
                    print("\nMax loop attempts reached.")
                    break

        except PlaywrightTimeoutError as pte:
            print(f"A Playwright Timeout Error occurred: {pte}")
        except Exception as e:
            print(f"An unexpected error occurred during Playwright execution: {e}")
            print(traceback.format_exc())
        finally:
            print("Closing browser.")
            if 'browser' in locals() and browser.is_connected():
                await browser.close()


# --- Main Execution ---
async def main():
    parser = argparse.ArgumentParser(description='Scrape esimdb.com USA plans.')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    args = parser.parse_args()

    await scrape_esimdb(URL, headless_mode=args.headless)

    # --- Final Output ---
    # (Keep final output section as it was)
    print(f"\nScraping complete. Total unique plans found: {len(scraped_plans_data)}")
    print(f"Total unique signatures found: {len(scraped_plan_signatures)}")
    output_dir = 'scraped_data'
    os.makedirs(output_dir, exist_ok=True)
    output_json_file = os.path.join(output_dir, 'esim_plans_usa.json')
    output_csv_file = os.path.join(output_dir, 'esim_plans_usa.csv')
    print(f"\nSaving data to {output_json_file}...")
    final_data = [plan for plan in scraped_plans_data if plan is not None]
    with open(output_json_file, 'w', encoding='utf-8') as f: json.dump(final_data, f, ensure_ascii=False, indent=4)
    print("JSON Data saved successfully.")
    print(f"\nSaving data to {output_csv_file}...")
    if final_data:
        try:
            df = pd.DataFrame(final_data)
            df['signature_check'] = df.apply(lambda row: f"{row.get('provider', 'N/A')}|{row.get('plan_title', 'N/A')}|{row.get('data', 'N/A')}|{row.get('price', 'N/A')}".strip(), axis=1)
            df = df.drop_duplicates(subset=['signature_check'])
            df = df.drop(columns=['signature_check'])
            print(f"Saving {len(df)} unique plans to CSV after deduplication.")
            df.to_csv(output_csv_file, index=False, encoding='utf-8')
            print("CSV Data saved successfully.")
        except Exception as pd_err:
             print(f"Error processing/saving CSV with pandas: {pd_err}")
             try:
                  if final_data:
                     keys = final_data[0].keys()
                     with open(output_csv_file, 'w', newline='', encoding='utf-8') as output_file:
                          dict_writer = csv.DictWriter(output_file, keys)
                          dict_writer.writeheader()
                          dict_writer.writerows(final_data)
                     print("Fallback CSV save successful (raw dicts).")
                  else: print("No data for fallback CSV save.")
             except Exception as csv_err: print(f"Fallback CSV save also failed: {csv_err}")
    else: print("No data to save to CSV.")
    print("\nScript finished.")


if __name__ == '__main__':
    asyncio.run(main())