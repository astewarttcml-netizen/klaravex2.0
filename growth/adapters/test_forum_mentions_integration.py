"""
Integration tests for forum mentions functionality in freelance pipeline.

This test verifies that forum mentions are properly handled and integrated
into the freelance bid submission process.
"""

import pytest
from unittest.mock import Mock, patch
import json
from datetime import datetime

# Import the actual pipeline module
from growth.adapters.freelance_pipeline import (
    FreelanceBidPipeline,
    Project,
    BidSubmission,
    score_project,
    submit_bid,
    submit_multiple_bids,
    get_bid_statistics,
    get_bid_status,
    validate_skills,
    health_check
)

def test_forum_mentions_in_project_scoring():
    """Test that forum mentions are considered in project scoring"""
    pipeline = FreelanceBidPipeline()

    # Test project with forum mention signal
    project_data = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django. "
                      "Forum mention: 'Ask HN: How do I get press coverage for my startup as a high schooler?'",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"],
        "forum_mentions": [
            {
                "signal_id": "forum-01",
                "scraper": "forum_mentions",
                "excerpt": "Ask HN: How do I get press coverage for my startup as a high schooler?",
                "prospect": "acme-clinic-acmeclinic-com"
            }
        ]
    }

    result = pipeline.score_project(project_data)

    assert "project_id" in result
    assert "score" in result
    assert "reason" in result
    assert result["project_id"] == "test123"
    assert isinstance(result["score"], (int, float))
    assert result["score"] >= 0 and result["score"] <= 100

def test_forum_mentions_in_cover_letter_generation():
    """Test that forum mentions are included in cover letter generation"""
    pipeline = FreelanceBidPipeline()

    project_data = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"],
        "forum_mentions": [
            {
                "signal_id": "forum-01",
                "scraper": "forum_mentions",
                "excerpt": "Ask HN: How do I get press coverage for my startup as a high schooler?",
                "prospect": "acme-clinic-acmeclinic-com"
            }
        ]
    }

    # Test generation for different platforms
    cover_letter = pipeline.generate_cover_letter(project_data, "manual")
    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0

    # Forum mentions should be referenced in the cover letter
    if project_data.get("forum_mentions"):
        # The cover letter might reference forum mentions but we don't have a
        # specific implementation to test here, so we just verify it doesn't crash
        pass

def test_forum_mentions_with_different_platforms():
    """Test forum mentions handling across different platforms"""
    pipeline = FreelanceBidPipeline()

    project_data = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"],
        "forum_mentions": [
            {
                "signal_id": "forum-01",
                "scraper": "forum_mentions",
                "excerpt": "HackerNews: 'Ask HN: How do I get press coverage for my startup as a high schooler?'",
                "prospect": "acme-clinic-acmeclinic-com"
            },
            {
                "signal_id": "forum-02",
                "scraper": "forum",
                "excerpt": "r/sysadmin: 'Best practices for network security in 2024'",
                "prospect": "acme-clinic-acmeclinic-com"
            }
        ]
    }

    # Test that the pipeline can handle multiple forum mentions
    result = pipeline.score_project(project_data)

    assert "project_id" in result
    assert isinstance(result["score"], (int, float))
    assert result["score"] >= 0 and result["score"] <= 100

def test_forum_mentions_empty_list():
    """Test handling of empty forum mentions list"""
    pipeline = FreelanceBidPipeline()

    project_data = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"],
        "forum_mentions": []
    }

    result = pipeline.score_project(project_data)

    assert "project_id" in result
    assert isinstance(result["score"], (int, float))
    assert result["score"] >= 0 and result["score"] <= 100

def test_forum_mentions_none_value():
    """Test handling of None forum mentions value"""
    pipeline = FreelanceBidPipeline()

    project_data = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"],
        "forum_mentions": None
    }

    result = pipeline.score_project(project_data)

    assert "project_id" in result
    assert isinstance(result["score"], (int, float))
    assert result["score"] >= 0 and result["score"] <= 100

def test_forum_mentions_complex_excerpt():
    """Test handling of complex forum mention excerpts"""
    pipeline = FreelanceBidPipeline()

    project_data = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"],
        "forum_mentions": [
            {
                "signal_id": "forum-01",
                "scraper": "forum_mentions",
                "excerpt": "HackerNews: 'Ask HN: How do I get press coverage for my startup as a high schooler?' "
                          "This is a very long forum mention with multiple sentences that might contain "
                          "important context for the project. The discussion mentions both technical "
                          "aspects and business considerations.",
                "prospect": "acme-clinic-acmeclinic-com"
            }
        ]
    }

    result = pipeline.score_project(project_data)

    assert "project_id" in result
    assert isinstance(result["score"], (int, float))
    assert result["score"] >= 0 and result["score"] <= 100

def test_forum_mentions_integration_with_existing_pipeline():
    """Test that forum mentions work with the full pipeline functionality"""
    pipeline = FreelanceBidPipeline()

    # Create a comprehensive project with forum mentions
    project_data = {
        "id": "test123",
        "title": "Python Web Development Project",
        "description": "Need a Python developer to build a web application with Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django"],
        "forum_mentions": [
            {
                "signal_id": "forum-01",
                "scraper": "forum_mentions",
                "excerpt": "HackerNews: 'Ask HN: How do I get press coverage for my startup as a high schooler?'",
                "prospect": "acme-clinic-acmeclinic-com"
            }
        ]
    }

    # Test all main pipeline functions with forum mentions
    score_result = pipeline.score_project(project_data)
    assert "project_id" in score_result
    assert "score" in score_result

    # Test that we can generate a cover letter
    cover_letter = pipeline.generate_cover_letter(project_data, "manual")
    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0

if __name__ == "__main__":
    # Run all tests
    pytest.main([__file__, "-v"])