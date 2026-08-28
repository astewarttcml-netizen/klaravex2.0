"""
End-to-end integration test for freelance pipeline with cover letter generation.
"""

import pytest
from fastapi.testclient import TestClient
from growth.api.main import app


# Create test client using the main app
client = TestClient(app)


def test_end_to_end_freelance_pipeline_with_cover_letters():
    """Test complete end-to-end flow from project scoring to cover letter generation."""

    # Test data - a sample project
    project_data = {
        "id": "e2e_test_project_123",
        "title": "Full Stack Developer Needed",
        "description": "Looking for a full stack developer with experience in Python, React and PostgreSQL",
        "budget": 3000,
        "duration": "long",
        "skills_required": ["python", "react", "postgresql", "django", "javascript"]
    }

    # Step 1: Score the project
    response = client.post("/freelance/score", json=project_data)
    assert response.status_code == 200

    score_data = response.json()
    assert "project_id" in score_data
    assert "score" in score_data
    assert "reason" in score_data
    assert score_data["score"] >= 0
    assert len(score_data["reason"]) > 0

    project_id = score_data["project_id"]

    # Step 2: Generate cover letter for the project
    response = client.post("/freelance/generate_cover_letter", json={
        "project_data": project_data,
        "platform": "freelancer.com",
        "freelancer_name": "Test Freelancer"
    })

    assert response.status_code == 200

    cover_letter_data = response.json()
    assert "cover_letter" in cover_letter_data
    assert "platform" in cover_letter_data
    assert "generated_at" in cover_letter_data

    assert cover_letter_data["platform"] == "freelancer.com"
    assert isinstance(cover_letter_data["cover_letter"], str)
    assert len(cover_letter_data["cover_letter"]) > 0

    # Step 3: Verify that we can list platforms
    response = client.get("/freelance/platforms")
    assert response.status_code == 200

    platform_data = response.json()
    assert "platforms" in platform_data
    assert len(platform_data["platforms"]) > 0
    assert "freelancer.com" in platform_data["platforms"]

    # Step 4: Verify that we can list projects
    response = client.get("/freelance/projects")
    assert response.status_code == 200

    projects_data = response.json()
    assert "projects" in projects_data
    assert projects_data["total"] >= 0

    print("✓ End-to-end test passed successfully!")
    print(f"  - Project scored: {score_data['score']}/100")
    print(f"  - Cover letter generated: {len(cover_letter_data['cover_letter'])} characters")
    print(f"  - Platforms available: {platform_data['total']}")


if __name__ == "__main__":
    test_end_to_end_freelance_pipeline_with_cover_letters()
    print("All end-to-end tests passed!")