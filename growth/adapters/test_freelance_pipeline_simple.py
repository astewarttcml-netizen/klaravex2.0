"""
Simple tests for the Freelance Pipeline - testing imports and basic functionality
"""

import pytest
from growth.adapters.freelance_pipeline import (
    router,
    BID_COUNTS,
    KILL_SWITCH_ACTIVE,
    calculate_project_score,
    validate_bid_amount,
    PLATFORMS
)

def test_imports():
    """Test that all modules can be imported"""
    assert router is not None
    assert BID_COUNTS is not None
    assert KILL_SWITCH_ACTIVE is not None

def test_platforms():
    """Test platform configuration"""
    assert len(PLATFORMS) > 0
    assert "freelancer" in PLATFORMS
    assert "freelancermap_de" in PLATFORMS
    assert "manual" in PLATFORMS

def test_score_calculation():
    """Test project score calculation"""
    project_data = {
        "id": "test123",
        "title": "Python web development",
        "description": "Need a Python developer",
        "budget": 1500,
        "duration": "medium"
    }

    score, reason = calculate_project_score(project_data)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0
    assert isinstance(reason, str)

def test_bid_validation():
    """Test bid amount validation"""
    # Test valid amounts for freelancer (min is 5)
    assert validate_bid_amount(10, "freelancer") == True
    assert validate_bid_amount(5, "freelancer") == True
    assert validate_bid_amount(3, "freelancer") == False  # Below minimum

    # Test that we can at least import the function
    assert callable(validate_bid_amount)

def test_global_variables():
    """Test global variable initialization"""
    assert isinstance(BID_COUNTS, dict)
    assert isinstance(KILL_SWITCH_ACTIVE, bool)