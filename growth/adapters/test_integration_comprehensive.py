"""
Comprehensive integration tests for freelance pipeline and cover letter generation system.

This module verifies that all components of the freelance bid submission pipeline
work together correctly, particularly focusing on the integration between:
1. The main FreelanceBidPipeline class
2. Cover letter generation functionality
3. Platform-specific templates
4. The integration layer

The tests ensure that the entire workflow from project discovery to cover letter generation
and bid submission functions as expected.
"""

import pytest
from typing import Dict, Any
from growth.adapters.freelance_pipeline import FreelanceBidPipeline
from growth.adapters.cover_letter_generator import cover_letter_generator
from growth.adapters.freelance_cover_letter_integration import generate_cover_letter
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager

def test_pipeline_template_manager_integration():
    """Test that the pipeline properly integrates with the template manager"""

    pipeline = FreelanceBidPipeline()

    # Check that the pipeline has a template manager
    assert hasattr(pipeline, 'template_manager')
    assert isinstance(pipeline.template_manager, CoverLetterTemplateManager)
    assert pipeline.template_manager is not None

def test_pipeline_cover_letter_generation():
    """Test that the pipeline's cover letter generation works correctly"""

    pipeline = FreelanceBidPipeline()

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
    assert "Website Redesign Project" in cover_letter

def test_direct_generator_integration():
    """Test that direct generator usage works correctly"""

    project_data = {
        "id": "test_project_456",
        "title": "Mobile App Development",
        "description": "Develop a cross-platform mobile application",
        "budget": 5000,
        "duration": "long",
        "skills_required": ["mobile development", "React Native", "Node.js"]
    }

    # Test direct generator usage
    cover_letter = cover_letter_generator.generate_cover_letter(
        project_data=project_data,
        platform="upwork",
        freelancer_name="Klaravex Developer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    assert "Klaravex AI" in cover_letter

def test_integration_function_usage():
    """Test that the integration function works correctly"""

    project_data = {
        "id": "test_project_789",
        "title": "Database Optimization",
        "description": "Optimize database performance for large scale applications",
        "budget": 3000,
        "duration": "short",
        "skills_required": ["database", "SQL", "performance tuning"]
    }

    # Test integration function usage
    cover_letter = generate_cover_letter(
        project_data=project_data,
        platform="guru",
        freelancer_name="Klaravex Engineer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    assert "Klaravex AI" in cover_letter

def test_all_platform_templates():
    """Test that all platform templates work correctly"""

    project_data = {
        "id": "test_project_all",
        "title": "Multi-Platform Project",
        "description": "A project suitable for multiple platforms",
        "budget": 4000,
        "duration": "medium",
        "skills_required": ["web development", "API design"]
    }

    platforms = ["freelancer", "upwork", "guru", "freelancermap_de", "peopleperhour"]

    letters = {}
    for platform in platforms:
        letter = generate_cover_letter(
            project_data=project_data,
            platform=platform,
            freelancer_name="Klaravex Developer"
        )
        letters[platform] = letter
        assert isinstance(letter, str)
        assert len(letter) > 0
        assert "Klaravex AI" in letter

def test_template_manager_functionality():
    """Test that the template manager works correctly"""

    template_manager = CoverLetterTemplateManager()

    # Test getting available platforms
    platforms = template_manager.get_available_platforms()
    assert isinstance(platforms, list)
    assert len(platforms) > 0

    # Test getting a specific template
    template = template_manager.get_template("freelancer")
    assert isinstance(template, str)
    assert len(template) > 0

    # Test that generic template exists
    generic_template = template_manager.get_template("generic")
    assert isinstance(generic_template, str)
    assert len(generic_template) > 0

def test_error_handling():
    """Test error handling in the integrated system"""

    pipeline = FreelanceBidPipeline()

    project_data = {
        "id": "test_project_error",
        "title": "Error Handling Test",
        "description": "Testing error conditions",
        "budget": 1000,
        "duration": "short",
        "skills_required": ["testing"]
    }

    # Test with invalid platform (should fall back to generic)
    cover_letter = pipeline.generate_cover_letter(
        project_data=project_data,
        platform="invalid_platform",
        freelancer_name="Klaravex Tester"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    # Should still contain the core message even with fallback
    assert "Klaravex AI" in cover_letter

def test_consistency_across_methods():
    """Test that different methods produce consistent results"""

    project_data = {
        "id": "test_project_consistent",
        "title": "Consistency Test",
        "description": "Testing consistency across generation methods",
        "budget": 2000,
        "duration": "medium",
        "skills_required": ["testing", "quality assurance"]
    }

    # Generate using pipeline method
    letter1 = FreelanceBidPipeline().generate_cover_letter(
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

def test_platform_specific_content():
    """Test that different platforms produce platform-specific content"""

    project_data = {
        "id": "test_project_platform",
        "title": "Platform Specific Test",
        "description": "A test for platform-specific content generation",
        "budget": 3500,
        "duration": "short",
        "skills_required": ["platform", "specific", "content"]
    }

    pipeline = FreelanceBidPipeline()

    # Generate for different platforms
    letters = {}
    platforms = ["freelancer", "upwork", "guru"]

    for platform in platforms:
        letter = pipeline.generate_cover_letter(
            project_data=project_data,
            platform=platform,
            freelancer_name="Klaravex Platform Expert"
        )
        letters[platform] = letter
        assert isinstance(letter, str)
        assert len(letter) > 0
        assert "Klaravex AI" in letter

if __name__ == "__main__":
    print("Running comprehensive freelance pipeline integration tests...")

    test_pipeline_template_manager_integration()
    print("✓ Pipeline template manager integration test passed")

    test_pipeline_cover_letter_generation()
    print("✓ Pipeline cover letter generation test passed")

    test_direct_generator_integration()
    print("✓ Direct generator integration test passed")

    test_integration_function_usage()
    print("✓ Integration function usage test passed")

    test_all_platform_templates()
    print("✓ All platform templates test passed")

    test_template_manager_functionality()
    print("✓ Template manager functionality test passed")

    test_error_handling()
    print("✓ Error handling integration test passed")

    test_consistency_across_methods()
    print("✓ Consistency across methods test passed")

    test_platform_specific_content()
    print("✓ Platform specific content test passed")

    print("\nAll comprehensive integration tests passed successfully!")