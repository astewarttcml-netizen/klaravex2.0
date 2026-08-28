"""
Final comprehensive tests for the freelance pipeline integration.

This module contains final integration tests that validate all aspects of the
freelance bid submission pipeline, ensuring that the cover letter generation
system works seamlessly with the overall workflow.
"""

from typing import Dict, Any
from growth.adapters.freelance_pipeline import FreelanceBidPipeline
from growth.adapters.cover_letter_generator import cover_letter_generator
from growth.adapters.freelance_cover_letter_integration import generate_cover_letter

def test_complete_pipeline_workflow():
    """Test the complete workflow from project discovery to cover letter generation"""

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
    assert "Klaravex Freelancer" in cover_letter
    assert "Website Redesign Project" in cover_letter

def test_integration_with_direct_generator():
    """Test that the pipeline integrates properly with the direct cover letter generator"""

    project_data = {
        "id": "test_project_456",
        "title": "Mobile App Development",
        "description": "Develop a cross-platform mobile application",
        "budget": 5000,
        "duration": "long",
        "skills_required": ["mobile development", "React Native", "Node.js"]
    }

    pipeline = FreelanceBidPipeline()

    # Generate using pipeline
    letter1 = pipeline.generate_cover_letter(
        project_data=project_data,
        platform="upwork",
        freelancer_name="Klaravex Developer"
    )

    # Generate using direct generator
    letter2 = cover_letter_generator.generate_cover_letter(
        project_data=project_data,
        platform="upwork",
        freelancer_name="Klaravex Developer"
    )

    # Both should produce valid results
    assert isinstance(letter1, str)
    assert isinstance(letter2, str)
    assert len(letter1) > 0
    assert len(letter2) > 0
    assert "Klaravex Developer" in letter1
    assert "Klaravex Developer" in letter2

def test_platform_specific_templates():
    """Test that different platforms generate appropriate platform-specific content"""

    project_data = {
        "id": "test_project_789",
        "title": "Database Optimization",
        "description": "Optimize database performance for large scale applications",
        "budget": 3000,
        "duration": "short",
        "skills_required": ["database", "SQL", "performance tuning"]
    }

    pipeline = FreelanceBidPipeline()

    # Test multiple platforms
    platforms = ["freelancer", "upwork", "guru", "peopleperhour", "freelancermap_de"]

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
        assert "Klaravex Engineer" in letter

    # Verify that we can access the template manager
    assert hasattr(pipeline, 'template_manager')
    assert pipeline.template_manager is not None

def test_error_handling_and_fallbacks():
    """Test that error handling works correctly with fallback mechanisms"""

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
        platform="nonexistent_platform",
        freelancer_name="Klaravex Tester"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    # Should still contain the core message even with fallback
    assert "Klaravex Tester" in cover_letter

def test_template_validation():
    """Test that platform template validation works correctly"""

    pipeline = FreelanceBidPipeline()

    # Test valid platforms through the template manager
    valid_platforms = ["freelancer", "upwork", "guru"]
    available_platforms = pipeline.template_manager.get_available_platforms()

    for platform in valid_platforms:
        # Check if platform is in available platforms
        is_valid = platform in available_platforms
        assert isinstance(is_valid, bool)
        assert is_valid is True

    # Test invalid platform
    is_valid = "invalid_platform" in available_platforms
    assert isinstance(is_valid, bool)
    assert is_valid is False

def test_supported_platforms():
    """Test that we can get a list of supported platforms"""

    pipeline = FreelanceBidPipeline()

    platforms = pipeline.template_manager.get_available_platforms()
    assert isinstance(platforms, list)
    assert len(platforms) > 0

    # Should contain at least the main platforms
    expected_platforms = ["freelancer", "upwork", "guru", "peopleperhour", "freelancermap_de"]
    for platform in expected_platforms:
        assert platform in platforms

def test_integration_function_compatibility():
    """Test compatibility with the integration module functions"""

    project_data = {
        "id": "test_project_compat",
        "title": "Compatibility Test",
        "description": "Testing integration functions",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["testing", "compatibility"]
    }

    # Test the integration module function directly
    cover_letter = generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Integrator"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    assert "Klaravex Integrator" in cover_letter

def test_consistent_output_format():
    """Test that all generated cover letters have consistent formatting"""

    project_data = {
        "id": "test_project_format",
        "title": "Formatting Test",
        "description": "Ensure consistent output format",
        "budget": 2000,
        "duration": "short",
        "skills_required": ["format", "consistency"]
    }

    pipeline = FreelanceBidPipeline()

    platforms = ["freelancer", "upwork", "guru"]
    letters = []

    for platform in platforms:
        letter = pipeline.generate_cover_letter(
            project_data=project_data,
            platform=platform,
            freelancer_name="Klaravex Formatter"
        )
        letters.append(letter)

        assert isinstance(letter, str)
        assert len(letter) > 0
        assert "Klaravex Formatter" in letter
        # Should have proper structure with newlines
        assert "\n" in letter

    # All letters should be different (platform-specific content)
    unique_letters = set(letters)
    assert len(unique_letters) == len(letters)

if __name__ == "__main__":
    print("Running final freelance pipeline integration tests...")

    test_complete_pipeline_workflow()
    print("✓ Complete pipeline workflow test passed")

    test_integration_with_direct_generator()
    print("✓ Direct generator integration test passed")

    test_platform_specific_templates()
    print("✓ Platform-specific templates test passed")

    test_error_handling_and_fallbacks()
    print("✓ Error handling and fallbacks test passed")

    test_template_validation()
    print("✓ Template validation test passed")

    test_supported_platforms()
    print("✓ Supported platforms test passed")

    test_integration_function_compatibility()
    print("✓ Integration function compatibility test passed")

    test_consistent_output_format()
    print("✓ Consistent output format test passed")

    print("\nAll final integration tests passed successfully!")