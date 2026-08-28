"""
Test suite for freelance bid pipeline implementation.
"""

import asyncio
import pytest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from growth.api.main import app

# Create test client using the main app
client = TestClient(app)

def test_score_project():
    """Test project scoring functionality"""
    project_data = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"]
    }

    response = client.post("/freelance/score", json=project_data)
    assert response.status_code == 200
    data = response.json()
    assert "project_id" in data
    assert "score" in data
    assert "reason" in data

def test_bid_submission():
    """Test bid submission functionality"""
    # First, score a project to ensure it exists
    project_data = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"]
    }

    client.post("/freelance/score", json=project_data)

    # Now submit a bid
    bid_data = {
        "project_id": "test123",
        "platform": "freelancer.com",
        "bid_amount": 500,
        "cover_letter": "I am a qualified Python developer with experience in Django.",
        "delivery_days": 7,
        "currency": "EUR"
    }

    response = client.post("/freelance/submit", json=bid_data)
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "message" in data

def test_multiple_bids():
    """Test submitting multiple bids"""
    # First, score projects to ensure they exist
    project_data1 = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"]
    }

    project_data2 = {
        "id": "test456",
        "title": "Web Development Project",
        "description": "Need a web developer to build a React application",
        "budget": 1000,
        "duration": "short",
        "skills_required": ["javascript", "react"]
    }

    client.post("/freelance/score", json=project_data1)
    client.post("/freelance/score", json=project_data2)

    # Now submit multiple bids
    bids = [
        {
            "project_id": "test123",
            "platform": "freelancer.com",
            "bid_amount": 500,
            "cover_letter": "I am a qualified Python developer with experience in Django.",
            "delivery_days": 7,
            "currency": "EUR"
        },
        {
            "project_id": "test456",
            "platform": "freelancermap_de",
            "bid_amount": 300,
            "cover_letter": "I am a qualified web developer with experience in React.",
            "delivery_days": 10,
            "currency": "EUR"
        }
    ]

    response = client.post("/freelance/submit_multiple_bids", json=bids)
    assert response.status_code == 200
    data = response.json()
    assert "total_submitted" in data
    assert "results" in data

def test_bid_statistics():
    """Test bid statistics endpoint"""
    response = client.get("/freelance/bid_statistics")
    assert response.status_code == 200
    data = response.json()
    assert "daily_bids" in data
    assert "total_platforms" in data
    assert "platforms" in data

def test_health_check():
    """Test health check endpoint"""
    response = client.get("/freelance/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "timestamp" in data

def test_skill_validation():
    """Test skill validation functionality"""
    skills = ["python", "django", "postgresql"]

    response = client.post("/freelance/validate_skills", json=skills)
    assert response.status_code == 200
    data = response.json()
    assert "valid_skills" in data
    assert "invalid_skills" in data

def test_bid_status():
    """Test bid status endpoint"""
    # First, score a project and submit a bid
    project_data = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"]
    }

    client.post("/freelance/score", json=project_data)

    bid_data = {
        "project_id": "test123",
        "platform": "freelancer.com",
        "bid_amount": 500,
        "cover_letter": "I am a qualified Python developer with experience in Django.",
        "delivery_days": 7,
        "currency": "EUR"
    }

    client.post("/freelance/submit", json=bid_data)

    # Now check bid status
    response = client.get("/freelance/bid_status/test123")
    assert response.status_code == 200
    data = response.json()
    assert "project_id" in data
    assert "status" in data

if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])