from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import asyncio
import json
import os
import requests

async def scrape_esimdb_playwright(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        # Capture JSON responses
        json_responses = []
        async def on_response(response):
            try:
                ctype = response.headers.get('content-type', '')
                if 'application/json' in ctype:
                    body = await response.json()
                    json_responses.append(body)
            except:
                pass
        page.on('response', on_response)
        print(f"Navigating to {url}...")
        await page.goto(url, timeout=90000)
        await page.wait_for_load_state('networkidle', timeout=90000)
        # Simulate scrolling to trigger all loads
        for _ in range(5):
            await page.evaluate('window.scrollBy(0, document.body.scrollHeight)')
            await asyncio.sleep(2)
        await browser.close()
        # Extract plans from captured JSON
        all_plans = []
        for data in json_responses:
            if isinstance(data, list) and data and isinstance(data[0], dict):
                all_plans.extend(data)
            elif isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        all_plans.extend(val)
        # Normalize and dedupe
        normalized = []
        seen = set()
        for plan in all_plans:
            provider = plan.get('providerName') or plan.get('provider', '')
            name = plan.get('title') or plan.get('planName') or plan.get('name', '')
            capacity = plan.get('data') or plan.get('dataAmount', '')
            period = plan.get('validity') or plan.get('period', '')
            price_gb = plan.get('pricePerGb') or plan.get('price_per_gb', '')
            price = plan.get('price') or plan.get('cost', '')
            key = (provider, name, capacity, period, price)
            if key not in seen:
                seen.add(key)
                normalized.append({
                    'provider': provider,
                    'plan_name': name,
                    'capacity': capacity,
                    'period': period,
                    'price_per_gb': price_gb,
                    'price': price
                })
        return normalized

async def main():
    # Fetch provider URLs from country page and intercept JSON responses per provider
    country_url = 'https://esimdb.com/usa'
    print(f"Fetching provider list from {country_url}...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(country_url, headers=headers, timeout=60)
    soup = BeautifulSoup(resp.text, 'html.parser')
    provider_urls = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('/usa/') and href.count('/') == 2:
            provider_urls.add('https://esimdb.com' + href)
    print(f"Found {len(provider_urls)} providers, scraping JSON from each...")
    all_plans = []
    for url in sorted(provider_urls):
        print(f"Scraping JSON data from {url}...")
        plans = await scrape_esimdb_playwright(url)
        all_plans.extend(plans)
    os.makedirs('scraped_data', exist_ok=True)
    with open('scraped_data/esimdb_plans.json', 'w', encoding='utf-8') as f:
        json.dump(all_plans, f, ensure_ascii=False, indent=4)
    print(f"Aggregated and saved {len(all_plans)} plans to scraped_data/esimdb_plans.json")

if __name__ == '__main__':
    asyncio.run(main())