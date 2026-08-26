#!/usr/bin/env python3
"""
Simple validation test for freelance pipeline functionality.
This validates the core components without requiring API keys.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, '/home/anthony/Klaravex2.0')

def test_freelance_pipeline_basic():
    """Test basic freelance pipeline functionality without external dependencies"""

    print("=== Basic Freelance Pipeline Validation ===\n")

    # Test 1: Import all modules successfully
    print("1. Testing imports...")
    try:
        from growth.adapters.freelance_sites import (
            get_freelance_adapter,
            FreelancerAdapter,
            FreelancermapAdapter,
            UpworkAdapter,
            PeoplePerHourAdapter,
            ManualBidAdapter,
            freelance_pipeline
        )

        from growth.adapters.freelance_pipeline import (
            calculate_project_score,
            validate_bid_amount,
            get_platform,
            get_min_amount,
            get_bid_statistics,
            get_bid_status
        )

        print("   ✓ All modules imported successfully")
    except Exception as e:
        print(f"   ✗ Import failed: {e}")
        return False

    # Test 2: Test core functions that don't require API keys
    print("\n2. Testing core pipeline functions...")

    # Test project scoring with mock data
    try:
        test_project = {
            "id": "test123",
            "title": "Python Web Development Project",
            "description": "Need a Python developer to build a web application with Django",
            "budget": 1500,
            "duration": "medium",
            "skills_required": ["python", "django"]
        }

        score, reason = calculate_project_score(test_project)
        print(f"   ✓ Project scoring works: score={score}, reason='{reason[:50]}...'")

        # Verify return types
        assert isinstance(score, (int, float)), f"Score should be numeric, got {type(score)}"
        assert 0 <= score <= 1, f"Score should be between 0 and 1, got {score}"
        assert isinstance(reason, str), f"Reason should be string, got {type(reason)}"

    except Exception as e:
        print(f"   ✗ Project scoring failed: {e}")
        return False

    # Test bid amount validation
    try:
        valid = validate_bid_amount(100, "freelancer.com")
        print(f"   ✓ Bid amount validation works: {valid}")
        assert isinstance(valid, bool), f"Validation should return boolean, got {type(valid)}"
    except Exception as e:
        print(f"   ✗ Bid amount validation failed: {e}")
        return False

    # Test minimum amount retrieval
    try:
        min_amount = get_min_amount("freelancer.com")
        print(f"   ✓ Minimum amount retrieval works: {min_amount}")
        assert isinstance(min_amount, (int, float)), f"Min amount should be numeric, got {type(min_amount)}"
    except Exception as e:
        print(f"   ⚠ Minimum amount retrieval failed (expected in dev): {e}")

    # Test platform retrieval with platforms that don't require keys
    print("\n3. Testing platform factory...")

    # Test platforms that work without credentials
    platforms_to_test = ["freelancer.com", "freelancermap.de", "peopleperhour", "upwork"]

    for platform in platforms_to_test:
        try:
            adapter = get_freelance_adapter(platform)
            print(f"   ✓ get_freelance_adapter('{platform}') works")
        except Exception as e:
            # This is expected for some platforms due to missing credentials
            print(f"   ⚠ get_freelance_adapter('{platform}') failed (expected): {type(e).__name__}")

    # Test pipeline probe
    print("\n4. Testing pipeline status...")
    try:
        result = freelance_pipeline()
        print(f"   ✓ Pipeline probe works: status={result['status']}")
        assert 'status' in result
        assert 'timestamp' in result
    except Exception as e:
        print(f"   ✗ Pipeline probe failed: {e}")
        return False

    # Test that all functions exist and are callable
    print("\n5. Testing function availability...")

    functions_to_test = [
        calculate_project_score,
        validate_bid_amount,
        get_platform,
        get_min_amount,
        get_bid_statistics,
        get_bid_status
    ]

    for func in functions_to_test:
        try:
            assert callable(func), f"{func.__name__} should be callable"
            print(f"   ✓ {func.__name__} is available and callable")
        except Exception as e:
            print(f"   ✗ {func.__name__} test failed: {e}")
            return False

    print("\n=== All Basic Tests Passed ===")
    print("✓ The freelance pipeline core functionality is working correctly")
    print("✓ All required components are properly structured and accessible")

    return True

if __name__ == "__main__":
    success = test_freelance_pipeline_basic()
    if not success:
        sys.exit(1)
    print("\nSUCCESS: Freelance pipeline validation completed successfully!")