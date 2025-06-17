from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import asyncio
import json
import os

async def scrape_esimdb_playwright(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await page.set_extra_http_headers({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'
        })

        await page.goto(url)
        await page.wait_for_selector('div#__nuxt', timeout=60000)

        plans = []
        extracted_data = set()
        no_new_plans_count = 0
        
        # Initial wait for first batch of content
        await asyncio.sleep(2)

        while True:
            # Get current page content
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            # Find all plans in the current viewport
            all_plan_rows = soup.find_all('a', class_='offers-list-row')
            current_plans_count = len(plans)
            
            # Print current status
            print(f"Current total plans extracted: {current_plans_count}")
            print(f"Current viewport plans found: {len(all_plan_rows)}")
            
            # Process plans
            new_plans_found = False
            initial_plan_count = len(plans)
            
            for row in all_plan_rows:
                plan_data = {
                    'provider': row.select_one('.provider-logo + div .ts-small').text.strip() if row.select_one('.provider-logo + div .ts-small') else '',
                    'plan_name': row.select_one('.offers-list-item-thin .text-overflow-ellipsis').text.strip() if row.select_one('.offers-list-item-thin .text-overflow-ellipsis') else '',
                    'capacity': row.select_one('.offers-list-item:nth-child(3) strong').text.strip() if row.select_one('.offers-list-item:nth-child(3) strong') else '',
                    'period': row.select_one('.offers-list-item:nth-child(4) strong').text.strip() if row.select_one('.offers-list-item:nth-child(4) strong') else '',
                    'price_per_gb': row.select_one('.offers-list-item:nth-child(5)').text.strip() if row.select_one('.offers-list-item:nth-child(5)') else '',
                    'price': row.select_one('.offers-list-item:nth-child(6) .price strong').text.strip() if row.select_one('.offers-list-item:nth-child(6) .price strong') else ''
                }
                
                plan_id = (plan_data['provider'], plan_data['plan_name'], plan_data['capacity'], plan_data['period'])
                if plan_id not in extracted_data:
                    extracted_data.add(plan_id)
                    plans.append(plan_data)
                    new_plans_found = True
            
            if new_plans_found:
                print(f"Found {len(plans) - initial_plan_count} new plans. Total plans now: {len(plans)}")
                no_new_plans_count = 0
                
                # Trigger scroll events that might be used by the site
                await page.evaluate("""
                    window.dispatchEvent(new Event('scroll'));
                    window.dispatchEvent(new Event('resize'));
                    if (typeof IntersectionObserver !== 'undefined') {
                        document.querySelectorAll('.offers-list-row').forEach(el => {
                            const rect = el.getBoundingClientRect();
                            const ratio = Math.min(1, Math.max(0, 
                                rect.bottom / window.innerHeight
                            ));
                            if (ratio > 0) {
                                el.dispatchEvent(new Event('intersect', { bubbles: true }));
                            }
                        });
                    }
                """)
                
                # Use multiple scroll methods
                current_position = await page.evaluate('window.pageYOffset')
                await page.evaluate(f'window.scrollTo(0, {current_position + 1000})')
                await page.keyboard.press("PageDown")
                await asyncio.sleep(1)
            else:
                no_new_plans_count += 1
                print(f"No new plans found. Attempt {no_new_plans_count}")
                
                if no_new_plans_count % 3 == 0:
                    # Try to trigger more aggressive loading
                    await page.evaluate("""
                        for (let i = 0; i < 1000; i += 100) {
                            setTimeout(() => {
                                window.scrollTo(0, window.pageYOffset + i);
                                window.dispatchEvent(new Event('scroll'));
                            }, i);
                        }
                    """)
                    await asyncio.sleep(2)
            
            # Exit conditions
            if len(plans) >= 2950:
                print("Found all expected plans. Finishing scraping.")
                break
            
            if no_new_plans_count >= 10:
                if len(plans) < 2900:
                    print(f"Only found {len(plans)} plans, attempting recovery...")
                    # Try to force reload all content
                    await page.evaluate("""
                        window.scrollTo(0, 0);
                        setTimeout(() => {
                            for (let i = 0; i < document.body.scrollHeight; i += 500) {
                                setTimeout(() => {
                                    window.scrollTo(0, i);
                                    window.dispatchEvent(new Event('scroll'));
                                }, i);
                            }
                        }, 1000);
                    """)
                    await asyncio.sleep(3)
                    no_new_plans_count = 0
                    continue
                else:
                    print("Finishing scraping.")
                    break

        await browser.close()

        # Save the data
        if plans:
            os.makedirs('scraped_data', exist_ok=True)
            with open('scraped_data/esimdb_plans.json', 'w', encoding='utf-8') as f:
                json.dump(plans, f, ensure_ascii=False, indent=4)
            print(f"Successfully saved {len(plans)} plans to scraped_data/esimdb_plans.json")
        else:
            print("No plans were found.")

async def main():
    url = 'https://esimdb.com/usa'
    await scrape_esimdb_playwright(url)

if __name__ == '__main__':
    asyncio.run(main())