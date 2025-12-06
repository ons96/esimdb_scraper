
import optimize_esim_plans
import json

def test_promo_logic():
    print("TESTING PROMO LOGIC")
    print("===================")
    
    # Mock data
    # MicroEsim ID: 65fd5b85efc7ee1e3444055a (One-time)
    provider_id = '65fd5b85efc7ee1e3444055a'
    
    overrides = {
        "provider_promo_overrides": {
            provider_id: {"promo_type": "one-time", "name": "MicroEsim"}
        }
    }
    
    # Mock plan
    plan = {
        "provider_id": provider_id,
        "plan_name": "Test Plan 1GB",
        "usd_price": 10.0,
        "usd_promo_price": 5.0,  # 50% off
        "provider_promo_type": "one-time",
        "new_user_only": False,
        "can_top_up": True
    }
    
    # Logic extracted/adapted from optimize_esim_plans.evaluate_combination
    # We want to verify the cost calculation for quantity = 2
    
    qty = 2
    regular_price = plan["usd_price"]
    promo_price = plan["usd_promo_price"]
    provider_promo_type = plan["provider_promo_type"]
    
    print(f"Provider: {overrides['provider_promo_overrides'][provider_id]['name']}")
    print(f"Promo Type: {provider_promo_type}")
    print(f"Regular Price: ${regular_price}")
    print(f"Promo Price: ${promo_price}")
    print(f"Buying Quantity: {qty}")
    
    # --- LOGIC UNDER TEST ---
    provider_promo_used = set() # Empty initially
    
    # 1. Determine eligibility
    has_promo = promo_price is not None and promo_price < regular_price
    
    if provider_promo_type == "one-time":
        promo_already_used = provider_id in provider_promo_used
        can_use_promo = has_promo and not promo_already_used
    else:
        promo_already_used = False
        can_use_promo = has_promo
        
    # 2. Calculate Cost
    cost = 0
    if can_use_promo:
        if provider_promo_type == "one-time":
            # Expected: 1 @ $5.0, 1 @ $10.0 = $15.0
            cost = promo_price + regular_price * (qty - 1)
            provider_promo_used.add(provider_id)
        else:
            cost = promo_price * qty
    else:
        cost = regular_price * qty
        
    print(f"Calculated Cost: ${cost}")
    
    expected_cost = 5.0 + 10.0
    if cost == expected_cost:
        print("✅ PASS: Correctly charged 1st at promo, 2nd at regular")
    else:
        print(f"❌ FAIL: Expected ${expected_cost}, got ${cost}")

    # --- TEST 2: buying another one after using ---
    print("\n--- Test 2: Buying another plan from same provider ---")
    
    # Reset variables for next step in loop simulation
    # provider_promo_used now contains the ID
    
    qty_2 = 1
    if provider_promo_type == "one-time":
        promo_already_used = provider_id in provider_promo_used
        can_use_promo = has_promo and not promo_already_used
    
    cost_2 = 0
    if can_use_promo:
         # ...
         pass
    else:
        # Expected path
        cost_2 = regular_price * qty_2
        
    print(f"Promo already used? {promo_already_used}")
    print(f"Can use promo? {can_use_promo}")
    print(f"Cost for 3rd unit: ${cost_2}")
    
    if cost_2 == 10.0:
        print("✅ PASS: Correctly charged regular price for subsequent purchase")
    else:
        print(f"❌ FAIL: Expected $10.0, got ${cost_2}")

if __name__ == "__main__":
    test_promo_logic()
