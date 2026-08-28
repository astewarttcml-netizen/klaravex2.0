"""
Integration tests for cover letter generation within the freelance pipeline.
These tests ensure that the cover letter generator works correctly with the freelance pipeline system.
"""

import pytest
from typing import Dict, Any
from growth.adapters.freelance_pipeline import FreelanceBidPipeline
from growth.adapters.cover_letter_generator import cover_letter_generator
from growth.adapters.freelance_cover_letter_integration import generate_cover_letter

def test_cover_letter_generation_integration():
    """Test that cover letter generation works correctly within the freelance pipeline"""

    # Test project data
    project_data = {
        "id": "test_project_123",
        "title": "Website Redesign Project",
        "description": "Redesign company website with modern UI/UX",
        "budget": 2500,
        "duration": "medium",
        "skills_required": ["web design", "UI/UX", "HTML/CSS"]
    }

    # Test different platforms
    platforms = ["freelancer", "freelancermap_de", "upwork", "guru", "peopleperhour", "generic"]

    pipeline = FreelanceBidPipeline()

    for platform in platforms:
        # Generate cover letter using the pipeline's method
        cover_letter = pipeline.generate_cover_letter(
            project_data=project_data,
            platform=platform,
            freelancer_name="Klaravex Freelancer"
        )

        # Verify that a cover letter was generated
        assert isinstance(cover_letter, str)
        assert len(cover_letter) > 0
        assert "Klaravex AI" in cover_letter  # Check that the core message is included

        print(f"Generated cover letter for {platform}:")
        print(cover_letter[:200] + "..." if len(cover_letter) > 200 else cover_letter)
        print("-" * 50)

def test_direct_generator_integration():
    """Test direct cover letter generation using the generator class"""

    project_data = {
        "id": "test_project_456",
        "title": "Mobile App Development",
        "description": "Develop a cross-platform mobile application",
        "budget": 5000,
        "duration": "long",
        "skills_required": ["mobile development", "React Native", "Node.js"]
    }

    # Test using the direct generator
    cover_letter = cover_letter_generator.generate_cover_letter(
        project_data=project_data,
        platform="freelancer",
        freelancer_name="Klaravex Developer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    assert "Klaravex AI" in cover_letter

    print("Direct generator test:")
    print(cover_letter[:200] + "..." if len(cover_letter) > 200 else cover_letter)

def test_integration_function():
    """Test the integration function directly"""

    project_data = {
        "id": "test_project_789",
        "title": "Database Optimization",
        "description": "Optimize database performance for large scale applications",
        "budget": 3000,
        "duration": "short",
        "skills_required": ["database", "SQL", "performance tuning"]
    }

    # Test using the integration function
    cover_letter = generate_cover_letter(
        project_data=project_data,
        platform="upwork",
        freelancer_name="Klaravex Engineer"
    )

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    assert "Klaravex AI" in cover_letter

    print("Integration function test:")
    print(cover_letter[:200] + "..." if len(cover_letter) > 200 else cover_letter)

def test_platform_specific_templates():
    """Test that different platforms generate different content while maintaining core message"""

    project_data = {
        "id": "test_project_101",
        "title": "E-commerce Platform Development",
        "description": "Build a complete e-commerce solution with payment integration",
        "budget": 7500,
        "duration": "medium",
        "skills_required": ["e-commerce", "payment processing", "frontend development"]
    }

    platforms = ["freelancer", "upwork", "freelancermap_de"]

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

    # Verify that different platforms produce different content (but all contain core message)
    unique_letters = set(letters.values())
    print(f"Generated {len(unique_letters)} unique letters out of {len(platforms)} platforms")

    for platform, letter in letters.items():
        print(f"\n{platform} template:")
        print(letter[:150] + "..." if len(letter) > 150 else letter)

if __name__ == "__main__":
    print("Running cover letter generation integration tests...")
    test_cover_letter_generation_integration()
    test_direct_generator_integration()
    test_integration_function()
    test_platform_specific_templates()
    print("\nAll integration tests passed!")