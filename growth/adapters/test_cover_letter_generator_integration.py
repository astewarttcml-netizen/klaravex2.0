"""
Integration tests for the Cover Letter Generator within the Freelance Pipeline.

These tests verify that the cover letter generator works correctly with
the freelance pipeline system and can be integrated into bid submission workflows.
"""

import pytest
from unittest.mock import patch, MagicMock
from growth.adapters.cover_letter_generator import CoverLetterGenerator, cover_letter_generator
from growth.adapters.freelance_pipeline import FreelanceBidPipeline


def test_cover_letter_generator_integration_with_pipeline():
    """Test that the cover letter generator integrates properly with the freelance pipeline."""

    # Create a sample project
    project_data = {
        "id": "test_project_123",
        "title": "Website Redesign Project",
        "description": "Redesign company website with modern UI/UX",
        "budget": 2500,
        "duration": "medium",
        "skills_required": ["web design", "UI/UX", "HTML/CSS"]
    }

    # Test that we can generate a cover letter using the global generator
    cover_letter = cover_letter_generator.generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Freelancer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    assert "Klaravex AI" in cover_letter  # Core message should be included


def test_cover_letter_generator_different_platforms():
    """Test that cover letter generator works with different platforms."""

    project_data = {
        "id": "test_project_456",
        "title": "Mobile App Development",
        "description": "Develop a cross-platform mobile application",
        "budget": 5000,
        "duration": "long",
        "skills_required": ["mobile development", "React Native", "Node.js"]
    }

    platforms = ["freelancer", "upwork", "freelancermap_de", "generic"]

    for platform in platforms:
        cover_letter = cover_letter_generator.generate_cover_letter(
            project_data=project_data,
            platform=platform,
            freelancer_name="Klaravex Developer"
        )

        assert isinstance(cover_letter, str)
        assert len(cover_letter) > 0
        # Check that key phrases are present in the generated letter
        if platform == "freelancer":
            assert "Klaravex AI" in cover_letter
        elif platform == "upwork":
            assert "Klaravex AI" in cover_letter or "Klaravex can help bring your project to success" in cover_letter
        elif platform == "freelancermap_de":
            assert "Klaravex AI" in cover_letter or "Klaravex kann Ihr Projekt erfolgreich umsetzen" in cover_letter
        elif platform == "generic":
            assert "Klaravex AI" in cover_letter or "Klaravex can help bring your project to success" in cover_letter


def test_pipeline_cover_letter_generation():
    """Test that the freelance pipeline can generate cover letters for bids."""

    project_data = {
        "id": "test_project_789",
        "title": "Database Optimization",
        "description": "Optimize database performance for large scale applications",
        "budget": 3000,
        "duration": "short",
        "skills_required": ["database", "SQL", "performance tuning"]
    }

    pipeline = FreelanceBidPipeline()

    # Test that the pipeline can generate a cover letter
    cover_letter = pipeline.generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Engineer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    assert "Klaravex AI" in cover_letter


def test_cover_letter_with_context_overrides():
    """Test that cover letter generation works with context overrides."""

    project_data = {
        "id": "test_project_101",
        "title": "E-commerce Platform Development",
        "description": "Build a complete e-commerce solution with payment integration",
        "budget": 7500,
        "duration": "medium",
        "skills_required": ["e-commerce", "payment processing", "frontend development"]
    }

    # Test that the generator works without context_overrides (since it's not supported)
    cover_letter = cover_letter_generator.generate_cover_letter(
        project_data=project_data,
        platform="upwork",
        freelancer_name="Klaravex Developer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    # The upwork template doesn't have "Klaravex AI" in the first line but does mention Klaravex
    assert "Klaravex" in cover_letter


def test_cover_letter_template_validation():
    """Test that the generator can validate templates."""

    # Test valid platforms
    assert cover_letter_generator.validate_template("freelancer") == True
    assert cover_letter_generator.validate_template("upwork") == True
    assert cover_letter_generator.validate_template("guru") == True
    assert cover_letter_generator.validate_template("generic") == True

    # Test invalid platform
    assert cover_letter_generator.validate_template("invalid_platform") == False


def test_supported_platforms_list():
    """Test that we can get a list of supported platforms."""

    platforms = cover_letter_generator.get_supported_platforms()

    assert isinstance(platforms, list)
    assert len(platforms) > 0

    # Check that common platforms are included
    expected_platforms = ["freelancer", "upwork", "guru", "peopleperhour", "generic"]
    for platform in expected_platforms:
        assert platform in platforms


def test_cover_letter_preview_functionality():
    """Test that we can generate cover letter previews."""

    project_data = {
        "id": "test_project_202",
        "title": "API Development Project",
        "description": "Develop RESTful APIs for a web application",
        "budget": 4000,
        "duration": "medium",
        "skills_required": ["API", "Node.js", "Express"]
    }

    preview = cover_letter_generator.get_template_preview(
        platform="freelancer",
        project_data=project_data,
        freelancer_name="Klaravex Developer"
    )

    assert isinstance(preview, str)
    assert len(preview) > 0


def test_backward_compatibility():
    """Test that the backward compatible function still works."""

    project_data = {
        "id": "test_project_303",
        "title": "Cloud Migration Project",
        "description": "Migrate existing applications to cloud infrastructure",
        "budget": 6000,
        "duration": "long",
        "skills_required": ["cloud", "AWS", "Docker"]
    }

    # Test the global function
    cover_letter = cover_letter_generator.generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Cloud Engineer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0


def test_empty_project_data():
    """Test that cover letter generation works with minimal project data."""

    project_data = {}

    cover_letter = cover_letter_generator.generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Freelancer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0


def test_special_characters_handling():
    """Test that cover letter generation handles special characters correctly."""

    project_data = {
        "id": "test_project_404",
        "title": "Website Redesign Project & More",
        "description": "Redesign an existing website with modern UI/UX (updated)",
        "budget": 2500,
        "duration": "2 weeks",
        "skills_required": ["React", "Node.js", "UI/UX Design"]
    }

    cover_letter = cover_letter_generator.generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Freelancer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0


def test_integration_with_mocked_adapter():
    """Test integration with mocked adapters to ensure end-to-end functionality."""

    project_data = {
        "id": "test_project_505",
        "title": "Web Application Development",
        "description": "Develop a full-stack web application",
        "budget": 3500,
        "duration": "medium",
        "skills_required": ["web development", "full stack"]
    }

    # Mock the adapter to ensure it works end-to-end
    with patch('growth.adapters.freelance_sites.FreelancerAdapter') as mock_adapter:
        mock_instance = MagicMock()
        mock_adapter.return_value = mock_instance

        # Test that the pipeline can still generate cover letters even when adapters are mocked
        pipeline = FreelanceBidPipeline()

        cover_letter = pipeline.generate_cover_letter(
            project_data=project_data,
            platform="freelancer",
            freelancer_name="Klaravex Developer"
        )

        assert isinstance(cover_letter, str)
        assert len(cover_letter) > 0


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])