"""
Integration tests for cover letter generation within the freelance pipeline.
"""

import pytest
from fastapi.testclient import TestClient
from growth.api.main import app
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager


# Create test client using the main app
client = TestClient(app)


def test_cover_letter_generation_integration():
    """Test that cover letter generation works properly within the freelance pipeline context."""

    # Initialize template manager to verify templates exist
    template_manager = CoverLetterTemplateManager()

    # Verify all expected platforms are available
    platforms = template_manager.get_available_platforms()
    expected_platforms = ["freelancer", "freelancermap_de", "upwork", "guru", "peopleperhour"]

    for platform in expected_platforms:
        assert platform in platforms, f"Platform {platform} should be available"

    # Test data
    project_data = {
        "id": "test_project_123",
        "title": "Python Web Application",
        "description": "Need a Python developer to build a web application using Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django", "postgresql"]
    }

    # Test generation for each platform
    for platform in expected_platforms:
        response = client.post("/freelance/generate_cover_letter", json={
            "project_data": project_data,
            "platform": platform,
            "freelancer_name": "John Doe"
        })

        assert response.status_code == 200, f"Failed to generate cover letter for {platform}"

        data = response.json()
        assert "cover_letter" in data
        assert "platform" in data
        assert "generated_at" in data

        assert data["platform"] == platform
        assert isinstance(data["cover_letter"], str)
        assert len(data["cover_letter"]) > 0
        assert "John Doe" in data["cover_letter"]


def test_cover_letter_generation_with_different_freelancer_names():
    """Test cover letter generation with different freelancer names."""

    project_data = {
        "id": "test_project_456",
        "title": "React Developer Needed",
        "description": "Looking for React developer to build a modern web app",
        "budget": 2000,
        "duration": "short",
        "skills_required": ["javascript", "react", "typescript"]
    }

    freelancer_names = ["Alice Smith", "Bob Johnson", "Charlie Brown"]

    for name in freelancer_names:
        response = client.post("/freelance/generate_cover_letter", json={
            "project_data": project_data,
            "platform": "freelancer",
            "freelancer_name": name
        })

        assert response.status_code == 200

        data = response.json()
        assert name in data["cover_letter"], f"Freelancer name {name} should appear in cover letter"


def test_cover_letter_generation_with_minimal_project():
    """Test cover letter generation with minimal project data."""

    project_data = {
        "id": "minimal_test",
        "title": "Simple Project",
        "description": "A simple project",
        "budget": 500,
        "duration": "short",
        "skills_required": ["test"]
    }

    response = client.post("/freelance/generate_cover_letter", json={
        "project_data": project_data,
        "platform": "upwork",
        "freelancer_name": "Test Freelancer"
    })

    assert response.status_code == 200

    data = response.json()
    assert isinstance(data["cover_letter"], str)
    assert len(data["cover_letter"]) > 0


def test_platform_list_endpoint():
    """Test that the platform list endpoint works correctly."""

    response = client.get("/freelance/platforms")
    assert response.status_code == 200

    data = response.json()
    assert "platforms" in data
    assert "total" in data

    # Should have at least the core platforms
    assert len(data["platforms"]) >= 3
    assert isinstance(data["total"], int)
    assert data["total"] == len(data["platforms"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])