
"""
ONE-CLICK RUNNER

Executes the full eSIM optimization pipeline:
1. Scrapes/Loads latest plan data (with caching).
2. Optimizes and prints the best itinerary solutions.
"""
import scrape_itinerary_plans
import optimize_itinerary
import time
import sys

def main():
    print("="*60)
    print(" 🚀 STARTING ESIM OPTIMIZATION PIPELINE")
    print("="*60)
    
    # Step 1: Scrape Data
    print("\n[STEP 1/2] Fetching Plan Data...")
    try:
        scrape_itinerary_plans.main()
    except Exception as e:
        print(f"❌ Error during scraping: {e}")
        sys.exit(1)
        
    print("\n✅ Data ready.")
    
    # Step 2: Optimize
    print("\n[STEP 2/2] Running Optimizer...")
    print("-" * 60)
    try:
        optimize_itinerary.main()
    except Exception as e:
        print(f"❌ Error during optimization: {e}")
        sys.exit(1)
        
    print("\n" + "="*60)
    print(" ✨ DONE")
    print("="*60)

if __name__ == "__main__":
    main()
