import requests
import json
import os
from bs4 import BeautifulSoup

# Realistic User-Agent header
def get_user_agent():
    return {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Extract provider slugs from main page links
def get_provider_slugs(country_url='https://esimdb.com/usa'):
    resp = requests.get(country_url, headers=get_user_agent(), timeout=60)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    slugs = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('/usa/') and href.count('/') == 2:
            slugs.add(href.rstrip('/').split('/')[-1])
    return sorted(slugs)

# Recursive search for plan arrays in JSON
def find_plan_list(obj):
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

# Extract Next.js buildId via parsing __NEXT_DATA__ script
def get_build_id(country_url='https://esimdb.com/usa'):
    """Parse __NEXT_DATA__ JSON from main page to retrieve buildId."""
    resp = requests.get(country_url, headers=get_user_agent(), timeout=60)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    script = soup.find('script', id='__NEXT_DATA__')
    if not script or not script.string:
        raise RuntimeError('Could not find __NEXT_DATA__ script on main page')
    data = json.loads(script.string)
    build_id = data.get('buildId')
    if not build_id:
        raise RuntimeError('Could not extract buildId from __NEXT_DATA__')
    return build_id

# Fetch plan data via Next.js JSON API endpoint
def fetch_provider_plans(build_id, slug):
    data_url = f'https://esimdb.com/_next/data/{build_id}/usa/{slug}.json'
    resp = requests.get(data_url, headers=get_user_agent(), timeout=60)
    resp.raise_for_status()
    data = resp.json()
    # pageProps may live under data['pageProps'] or data['props']['pageProps']
    page_props = data.get('props', {}).get('pageProps') or data.get('pageProps', {})
    plans_raw = find_plan_list(page_props)
    plans = []
    for p in plans_raw:
        plans.append({
            'provider': slug,
            'plan_name': p.get('title') or p.get('name') or '',
            'capacity': p.get('data') or p.get('dataAmount') or '',
            'period': p.get('validity') or p.get('period') or '',
            'price_per_gb': p.get('pricePerGb') or '',
            'price': p.get('price') or p.get('cost') or ''
        })
    return plans

# Main script
def main():
    country_url = 'https://esimdb.com/usa'
    slugs = get_provider_slugs(country_url)
    print(f'Found {len(slugs)} providers')
    build_id = get_build_id(country_url)
    print(f'Using buildId={build_id}')
    all_plans = []
    for slug in slugs:
        print(f'Fetching {slug}...')
        try:
            plans = fetch_provider_plans(build_id, slug)
            print(f'  -> {len(plans)} plans')
            all_plans.extend(plans)
        except Exception as e:
            print(f'Error fetching {slug}: {e}')
    os.makedirs('scraped_data', exist_ok=True)
    out_path = os.path.join('scraped_data', 'esimdb_plans.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(all_plans, f, ensure_ascii=False, indent=4)
    print(f'Saved {len(all_plans)} plans to {out_path}')

if __name__ == '__main__':
    main()
