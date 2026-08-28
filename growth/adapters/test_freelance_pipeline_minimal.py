"""
Test file for freelance pipeline components - Core Logic Tests Only
"""

import pytest
from growth.adapters.freelance_pipeline import calculate_project_score, validate_bid_amount

def test_calculate_project_score():
    """Test project scoring logic with various inputs"""
    # Test data
    project_data = {
        "id": "test_project_123",
        "title": "Python web development project",
        "description": "Need a Python developer to build a web application using Django",
        "budget": 1500,
        "duration": "medium",
        "skills": ["python", "django", "postgresql"]
    }

    score, reason = calculate_project_score(project_data)

    assert isinstance(score, float)
    assert 0 <= score <= 1
    assert isinstance(reason, str)
    assert len(reason) > 0

def test_validate_bid_amount():
    """Test bid amount validation for different platforms"""
    # Test valid amounts
    assert validate_bid_amount(10, "freelancer") == True
    assert validate_bid_amount(5, "guru") == True
    assert validate_bid_amount(15, "upwork") == True

    # Test invalid amounts
    assert validate_bid_amount(1, "freelancer") == False
    assert validate_bid_amount(2, "guru") == False

def test_score_calculation_logic():
    """Test that scoring logic works correctly with different inputs"""
    # Test with high budget
    project_data = {
        "title": "High budget project",
        "description": "Need a Python developer",
        "budget": 5000,
        "duration": "long"
    }

    score, reason = calculate_project_score(project_data)
    assert isinstance(score, float)
    assert 0 <= score <= 1

    # Test with low budget
    project_data = {
        "title": "Low budget project",
        "description": "Simple web page",
        "budget": 200,
        "duration": "short"
    }

    score, reason = calculate_project_score(project_data)
    assert isinstance(score, float)
    assert 0 <= score <= 1

def test_bid_validation_edge_cases():
    """Test bid validation with edge cases"""
    # Test exact minimum amounts
    assert validate_bid_amount(5, "freelancer") == True
    assert validate_bid_amount(5, "guru") == True

    # Test zero and negative values
    assert validate_bid_amount(0, "freelancer") == False
    assert validate_bid_amount(-1, "freelancer") == False

if __name__ == "__main__":
    pytest.main([__file__, "-v"])