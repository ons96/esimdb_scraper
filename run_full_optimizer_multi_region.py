"""
ONE-CLICK MULTI-REGION RUNNER

Executes the full eSIM optimization pipeline for Europe or USA:
1. Scrapes/Loads latest plan data (with caching).
2. Scrapes promo recurrence info.
3. Optimizes and prints the best solutions.
"""
import subprocess
import sys
import argparse
import time
from datetime import datetime

def run_command(script_name, description):
    """Run a Python script and handle errors"""
    print("="*80)
    print(f"[{description}]")
    print("="*80)
    start = time.time()
    
    try:
        result = subprocess.run(
            [sys.executable, script_name],
            check=True,
            capture_output=False,
            text=True
        )
        elapsed = time.time() - start
        print(f"\n✅ {description} completed successfully ({elapsed:.1f}s)")
        return True
    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start
        print(f"\n❌ Error during {description} (after {elapsed:.1f}s)")
        print(f"Return code: {e.returncode}")
        return False
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n❌ Unexpected error during {description} (after {elapsed:.1f}s): {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Full eSIM optimization pipeline for Europe or USA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_full_optimizer_multi_region.py --region europe
  python run_full_optimizer_multi_region.py --region usa
  python run_full_optimizer_multi_region.py --region usa --trip-days 10 --data-gb 5
        """
    )
    parser.add_argument("--region", choices=["europe", "usa"], required=True,
                        help="Region to optimize (europe or usa)")
    parser.add_argument("--trip-days", type=int, default=15,
                        help="Trip duration in days (default: 15)")
    parser.add_argument("--data-gb", type=float, default=8.6,
                        help="Total data needed in GB (default: 8.6)")
    parser.add_argument("--skip-scrape", action="store_true",
                        help="Skip scraping step if data already exists")
    parser.add_argument("--skip-promo", action="store_true",
                        help="Skip promo scraping step if cache already exists")
    
    args = parser.parse_args()
    
    print("="*80)
    print(" 🚀 STARTING ESIM OPTIMIZATION PIPELINE")
    print("="*80)
    print(f"Region: {args.region.upper()}")
    print(f"Trip parameters: {args.trip_days} days, {args.data_gb} GB")
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Define scripts based on region
    if args.region == "europe":
        scraper_script = "scrape_europe_plans.py"
        promo_script = "scrape_promo_recurrence.py"
    else:  # usa
        scraper_script = "scrape_usa_plans.py"
        promo_script = "scrape_usa_promo_recurrence.py"
    
    # Step 1: Scrape Plan Data
    if not args.skip_scrape:
        print("\n[STEP 1/3] Scraping Plan Data...")
        if not run_command(scraper_script, "Plan Scraping"):
            print("\n❌ Plan scraping failed. Cannot continue.")
            sys.exit(1)
    else:
        print("\n[STEP 1/3] Skipping plan scraping (--skip-scrape flag)")
        
    print("\n✅ Data ready.")
    
    # Step 2: Scrape Promo Recurrence
    if not args.skip_promo:
        print("\n[STEP 2/3] Scraping Promo Recurrence Info...")
        if not run_command(promo_script, "Promo Scraping"):
            print("\n⚠️  Promo scraping failed. Continuing with default promo settings...")
    else:
        print("\n[STEP 2/3] Skipping promo scraping (--skip-promo flag)")
        
    # Step 3: Optimize
    print("\n[STEP 3/3] Running Optimizer...")
    print("-" * 80)
    
    try:
        # Build optimizer command with trip parameters
        optimizer_cmd = [
            sys.executable,
            "optimize_esim_plans_multi_region.py",
            "--region", args.region,
            "--trip-days", str(args.trip_days),
            "--data-gb", str(args.data_gb)
        ]
        
        result = subprocess.run(optimizer_cmd, check=True)
        
        print("\n" + "="*80)
        print(" ✨ PIPELINE COMPLETED SUCCESSFULLY")
        print("="*80)
        print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error during optimization: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error during optimization: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
