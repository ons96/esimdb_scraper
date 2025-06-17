import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import os

async def scrape_data():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto("https://esimdb.com/usa")
        # Add before the evaluate call
        await page.wait_for_selector('.offers-list-item.cell', timeout=10000)  # 10 second timeout

        
        # Add debug print
        print("Page loaded, attempting to scrape...")
        
        # Print the inner HTML of the entire page
        page_html = await page.content()
        print("Page HTML:")
        print(page_html)
        
        # Extract data using evaluate
        offers = await page.evaluate("""
            () => {
                const offers = [];
                const items = document.querySelectorAll('.offer-item');  // Changed selector
                console.log('Found ' + items.length + ' items');
                items.forEach(row => {
                    const offer = {
                        Provider: row.querySelector('.provider-logo img')?.getAttribute('alt') || '',
                        'Plan Name': row.querySelector('.offer-title')?.textContent.trim() || '',
                        Size: row.querySelector('.data-amount')?.textContent.trim() || '',
                        Validity: row.querySelector('.validity-period')?.textContent.trim() || '',
                        Price: row.querySelector('.price-amount')?.textContent.trim() || ''
                    };
                    offers.push(offer);
                });
                return offers;
            }
        """)

        
        # Add debug print
        print(f"Number of offers scraped: {len(offers)}")
        if len(offers) > 0:
            print("Sample first offer:", offers[0])
        else:
            print("No offers found!")
            
        await browser.close()
        return offers

# Run the async scraping
all_data = asyncio.run(scrape_data())

# Process the data
df = pd.DataFrame(all_data)

# Calculate price per GB
for idx, row in df.iterrows():
    try:
        size_num = float(row['Size'].replace('GB', '').strip())
        price_num = float(row['Price'].replace('$', '').replace('CA$', '').strip())
        df.at[idx, 'Price/GB'] = f"${price_num/size_num:.2f}/GB"
    except:
        df.at[idx, 'Price/GB'] = ""

# Save to CSV
downloads_path = os.path.expanduser("~\\Downloads")
csv_filename = os.path.join(downloads_path, "esimdb_data.csv")
df.to_csv(csv_filename, index=False)
print("Data saved to:", csv_filename)
