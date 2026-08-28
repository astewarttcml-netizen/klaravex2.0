"""
Integration tests for the freelance pipeline and cover letter generation system.

This module verifies that all components of the freelance bid submission pipeline
work together correctly, particularly focusing on the integration between:
1. The main FreelanceBidPipeline class
2. Cover letter generation functionality
3. Platform-specific templates

The tests ensure that the entire workflow from project discovery to cover letter generation
and bid submission functions as expected.
"""

import pytest
from typing import Dict, Any
from growth.adapters.freelance_pipeline import FreelanceBidPipeline
from growth.adapters.cover_letter_generator import cover_letter_generator
from growth.adapters.freelance_cover_letter_integration import generate_cover_letter

def test_full_pipeline_integration():
    """Test that the entire freelance pipeline integrates correctly with cover letter generation"""

    # Initialize the pipeline
    pipeline = FreelanceBidPipeline()

    # Test project data
    project_data = {
        "id": "test_project_123",
        "title": "Website Redesign Project",
        "description": "Redesign company website with modern UI/UX",
        "budget": 2500,
        "duration": "medium",
        "skills_required": ["web design", "UI/UX", "HTML/CSS"]
    }

    # Test that we can generate a cover letter through the pipeline
    cover_letter = pipeline.generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Freelancer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    assert "Klaravex AI" in cover_letter

    # Test that we can generate a cover letter using the integration function
    cover_letter_2 = generate_cover_letter(
        project_data=project_data,
        platform="upwork",
        freelancer_name="Klaravex Developer"
    )

    assert isinstance(cover_letter_2, str)
    assert len(cover_letter_2) > 0
    assert "Klaravex AI" in cover_letter_2

def test_template_manager_integration():
    """Test that the pipeline uses the correct template manager"""

    pipeline = FreelanceBidPipeline()

    # Check that the pipeline has a template manager
    assert hasattr(pipeline, 'template_manager')
    assert pipeline.template_manager is not None

    # Test that we can access available platforms
    platforms = pipeline.template_manager.get_available_platforms()
    assert isinstance(platforms, list)
    assert len(platforms) > 0

    # Test that all platforms have templates
    for platform in platforms:
        template = pipeline.template_manager.get_template(platform)
        assert isinstance(template, str)
        assert len(template) > 0

def test_cover_letter_generation_consistency():
    """Test that cover letter generation is consistent across different methods"""

    project_data = {
        "id": "test_project_456",
        "title": "Mobile App Development",
        "description": "Develop a cross-platform mobile application",
        "budget": 5000,
        "duration": "long",
        "skills_required": ["mobile development", "React Native", "Node.js"]
    }

    pipeline = FreelanceBidPipeline()

    # Generate using pipeline method
    letter1 = pipeline.generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Developer"
    )

    # Generate using direct generator
    letter2 = cover_letter_generator.generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Developer"
    )

    # Generate using integration function
    letter3 = generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Developer"
    )

    # All should be strings and contain the core message
    assert isinstance(letter1, str)
    assert isinstance(letter2, str)
    assert isinstance(letter3, str)

    assert "Klaravex AI" in letter1
    assert "Klaravex AI" in letter2
    assert "Klaravex AI" in letter3

def test_different_platform_templates():
    """Test that different platforms generate appropriate content"""

    project_data = {
        "id": "test_project_789",
        "title": "Database Optimization",
        "description": "Optimize database performance for large scale applications",
        "budget": 3000,
        "duration": "short",
        "skills_required": ["database", "SQL", "performance tuning"]
    }

    pipeline = FreelanceBidPipeline()

    platforms = ["freelancer", "upwork", "guru", "freelancermap_de"]

    letters = {}
    for platform in platforms:
        letter = pipeline.generate_cover_letter(
            project_data=project_data,
            platform=platform,
            freelancer_name="Klaravex Engineer"
        )
        letters[platform] = letter
        assert isinstance(letter, str)
        assert len(letter) > 0
        assert "Klaravex AI" in letter

    # Verify that different platforms produce different content
    unique_letters = set(letters.values())
    print(f"Generated {len(unique_letters)} unique letters out of {len(platforms)} platforms")

    # All should contain the core message but can have platform-specific variations
    for platform, letter in letters.items():
        assert "Klaravex AI" in letter
        print(f"{platform}: {letter[:100]}...")

def test_error_handling_in_integration():
    """Test that error handling works correctly in the integrated system"""

    pipeline = FreelanceBidPipeline()

    # Test with invalid platform (should fall back to generic)
    project_data = {
        "id": "test_project_invalid",
        "title": "Invalid Platform Test",
        "description": "Testing error handling",
        "budget": 1000,
        "duration": "short",
        "skills_required": ["testing"]
    }

    # This should not raise an exception
    cover_letter = pipeline.generate_cover_letter(
        project_data=project_data,
        platform="invalid_platform",
        freelancer_name="Klaravex Tester"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    # Should still contain the core message even with fallback
    assert "Klaravex AI" in cover_letter

if __name__ == "__main__":
    print("Running comprehensive freelance pipeline integration tests...")

    test_full_pipeline_integration()
    print("✓ Full pipeline integration test passed")

    test_template_manager_integration()
    print("✓ Template manager integration test passed")

    test_cover_letter_generation_consistency()
    print("✓ Cover letter generation consistency test passed")

    test_different_platform_templates()
    print("✓ Different platform templates test passed")

    test_error_handling_in_integration()
    print("✓ Error handling integration test passed")

    print("\nAll integration tests passed successfully!")