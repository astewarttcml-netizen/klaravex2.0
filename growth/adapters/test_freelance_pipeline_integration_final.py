"""
Final integration tests for freelance bid pipeline with enhanced cover letter templates.
Tests the complete integration between pipeline components and improved cover letter functionality.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

# Import the actual pipeline module
from growth.adapters.freelance_pipeline import (
    FreelanceBidPipeline,
    Project,
    BidSubmission
)

def test_pipeline_enhanced_cover_letter_generation():
    """Test that the pipeline properly generates enhanced cover letters with Klaravex service tiers"""

    # Create a pipeline instance
    pipeline = FreelanceBidPipeline()

    # Test data for different types of projects
    project_data = {
        "id": "test_project_123",
        "title": "Python Web Application",
        "description": "Need a Python developer to build a web application using Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django", "postgresql"]
    }

    # Test that we can generate cover letters for different platforms with enhanced content
    platforms = ["freelancer", "upwork", "guru", "freelancermap_de", "peopleperhour"]

    for platform in platforms:
        # Generate a cover letter through the pipeline
        cover_letter = pipeline.generate_cover_letter(
            project_data=project_data,
            platform=platform,
            freelancer_name="Klaravex Freelancer"
        )

        assert isinstance(cover_letter, str)
        assert len(cover_letter) > 0
        assert "Klaravex Freelancer" in cover_letter
        assert project_data["title"] in cover_letter

        # Verify enhanced content is present for all platforms
        # Note: German template uses different intro text but same service tier references
        if platform == "freelancermap_de":
            assert "Klaravex AI löst die meisten IT-Probleme sofort" in cover_letter
        else:
            assert "Klaravex AI resolves most IT issues instantly" in cover_letter
        # Check that service tier information is present (different phrasing in German)
        assert ("Foundation/Directive tier offerings" in cover_letter or
                "Foundation/Directive-Tarifmodellen" in cover_letter)
        # Check that pricing information is present (English or German version)
        assert ("published pricing on klaravex.com" in cover_letter or
                "veröffentlichte Preise auf klaravex.com" in cover_letter)

def test_pipeline_submit_bid_with_enhanced_cover_letters():
    """Test that bid submission works with enhanced cover letters through the pipeline"""

    pipeline = FreelanceBidPipeline()

    # Mock the adapter to avoid actual API calls
    mock_adapter = Mock()
    mock_adapter.submit_bid.return_value = {
        'success': True,
        'message': 'Bid submitted successfully',
        'bid_id': 'test_bid_123'
    }

    with patch.object(pipeline, 'get_adapter', return_value=mock_adapter):
        # Create bid data that includes project info and enhanced cover letter
        bid_data = {
            "project_id": "test_project_123",
            "platform": "freelancer.com",
            "bid_amount": 500,
            "cover_letter": "Test enhanced cover letter for the project with Foundation/Directive tiers",
            "delivery_days": 7,
            "currency": "EUR"
        }

        # Submit the bid
        result = pipeline.submit_bid(bid_data)

        assert result["success"] is True
        assert result["message"] == "Bid submitted successfully"
        assert result["project_id"] == "test_project_123"
        assert result["platform"] == "freelancer.com"

def test_pipeline_integration_with_enhanced_template_manager():
    """Test that the pipeline properly uses the enhanced template manager for cover letters"""

    pipeline = FreelanceBidPipeline()

    # Check that template manager is initialized
    assert hasattr(pipeline, 'template_manager')
    assert hasattr(pipeline.template_manager, 'generate_cover_letter')

    # Test with minimal project data
    project_data = {
        "id": "minimal_project",
        "title": "Simple Project",
        "description": "A simple project",
        "budget": 500,
        "duration": "short",
        "skills_required": ["test"]
    }

    # Generate cover letter using the pipeline's enhanced template manager
    cover_letter = pipeline.generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Enhanced Template Test"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    assert "Enhanced Template Test" in cover_letter

    # Verify enhanced content is present
    assert "Klaravex AI resolves most IT issues instantly" in cover_letter
    assert "Foundation/Directive tier offerings" in cover_letter

def test_pipeline_score_and_enhanced_generation_integration():
    """Test that scoring and enhanced cover letter generation work together properly"""

    pipeline = FreelanceBidPipeline()

    # Test data with various skill requirements
    project_data = {
        "id": "scoring_test_123",
        "title": "Complex Web Application",
        "description": "Need a full-stack developer to build a complex web application with microservices",
        "budget": 3000,
        "duration": "long",
        "skills_required": ["python", "django", "react", "postgresql", "redis", "docker", "kubernetes"]
    }

    # Score the project
    score_result = pipeline.score_project(project_data)

    assert "project_id" in score_result
    assert "score" in score_result
    assert "reason" in score_result

    # Generate enhanced cover letter based on the scored project
    cover_letter = pipeline.generate_cover_letter(
        project_data=project_data,
        platform="upwork",
        freelancer_name="Senior Developer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    assert "Senior Developer" in cover_letter

    # Verify that the generated cover letter contains relevant information from the project
    assert project_data["title"] in cover_letter
    assert "Senior Developer" in cover_letter

    # Verify enhanced content is present
    assert "Klaravex AI resolves most IT issues instantly" in cover_letter
    assert "Foundation/Directive tier offerings" in cover_letter

def test_pipeline_enhanced_template_content():
    """Test that all platform templates contain the enhanced Klaravex content"""

    pipeline = FreelanceBidPipeline()

    # Test data
    project_data = {
        "id": "template_test",
        "title": "Template Testing Project",
        "description": "Project for testing templates",
        "budget": 1000,
        "duration": "medium",
        "skills_required": ["test"]
    }

    # Test all supported platforms
    platforms = ["freelancer", "freelancermap_de", "upwork", "guru", "peopleperhour", "manual"]

    for platform in platforms:
        cover_letter = pipeline.generate_cover_letter(
            project_data=project_data,
            platform=platform,
            freelancer_name="Template Tester"
        )

        assert isinstance(cover_letter, str)
        assert len(cover_letter) > 0

        # All templates should contain enhanced Klaravex content
        if platform == "freelancermap_de":
            assert "Klaravex AI löst die meisten IT-Probleme sofort" in cover_letter
        else:
            assert "Klaravex AI resolves most IT issues instantly" in cover_letter
        # Check that service tier information is present (different phrasing in German)
        assert ("Foundation/Directive tier offerings" in cover_letter or
                "Foundation/Directive-Tarifmodellen" in cover_letter)
        # Check that pricing information is present (English or German version)
        assert ("published pricing on klaravex.com" in cover_letter or
                "veröffentlichte Preise auf klaravex.com" in cover_letter)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])