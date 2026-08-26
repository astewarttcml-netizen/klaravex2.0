"""
Simple integration tests for freelance bid pipeline implementation.
"""

import pytest
from fastapi.testclient import TestClient
from growth.adapters.freelance_pipeline import router

# Create test client
client = TestClient(router)

def test_health_endpoint():
    """Test the health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "healthy"

def test_score_project_endpoint():
    """Test project scoring endpoint"""
    project_data = {
        "id": "test123",
        "title": "Web Development Project",
        "description": "Need a web developer with Python experience",
        "budget": 1500,
        "duration": "medium"
    }

    response = client.post("/score_project", json=project_data)
    assert response.status_code == 200
    data = response.json()
    assert "project_id" in data
    assert "score" in data
    assert "reason" in data

def test_bid_statistics_endpoint():
    """Test bid statistics endpoint"""
    response = client.get("/bid_statistics")
    assert response.status_code == 200
    data = response.json()
    assert "daily_bids" in data
    assert "total_platforms" in data
    assert "kill_switch_active" in data

def test_basic_bid_submission():
    """Test basic bid submission endpoint"""
    bid_data = {
        "project_id": "test123",
        "platform": "freelancer",
        "bid_amount": 500,
        "cover_letter": "Testing bid submission"
    }

    response = client.post("/submit_bid", json=bid_data)
    assert response.status_code == 200
    # Should return a list of results (even if empty or with errors)
    results = response.json()
    assert isinstance(results, list)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])