"""
Tests for cover letter template manager.

These tests verify that cover letters are generated correctly for different platforms.
"""

import pytest
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager

def test_template_manager_initialization():
    """Test that the template manager initializes correctly"""
    manager = CoverLetterTemplateManager()
    assert manager is not None
    assert len(manager.get_available_platforms()) > 0

def test_get_available_platforms():
    """Test that available platforms are returned correctly"""
    manager = CoverLetterTemplateManager()
    platforms = manager.get_available_platforms()
    assert isinstance(platforms, list)
    assert len(platforms) > 0
    # Check that all expected platforms are present
    expected_platforms = ['freelancer', 'freelancermap_de', 'upwork', 'guru', 'peopleperhour', 'generic']
    for platform in expected_platforms:
        assert platform in platforms

def test_generate_cover_letter_freelancer():
    """Test cover letter generation for Freelancer.com"""
    manager = CoverLetterTemplateManager()

    project_data = {
        "id": "test123",
        "title": "Python Web Application",
        "description": "Need a Python developer to build a web application using Django",
        "budget": 1500,
        "duration": "medium",
        "skills_required": ["python", "django", "postgresql"]
    }

    cover_letter = manager.generate_cover_letter(project_data, "freelancer", "John Doe")

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    # Check that the letter contains key elements
    assert "Klaravex AI resolves most IT issues instantly" in cover_letter
    assert "Python Web Application" in cover_letter
    assert "John Doe" in cover_letter

def test_generate_cover_letter_manual():
    """Test cover letter generation for manual platform"""
    manager = CoverLetterTemplateManager()

    project_data = {
        "id": "test456",
        "title": "Web Development Project",
        "description": "Need a web developer to build a React application",
        "budget": 1000,
        "duration": "short",
        "skills_required": ["javascript", "react"]
    }

    cover_letter = manager.generate_cover_letter(project_data, "manual", "Jane Smith")

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    # Check that the letter contains key elements - should use generic template for manual
    assert "Klaravex AI resolves most IT issues instantly" in cover_letter
    assert "Web Development Project" in cover_letter
    assert "Jane Smith" in cover_letter

def test_generate_cover_letter_generic():
    """Test cover letter generation with generic platform"""
    manager = CoverLetterTemplateManager()

    project_data = {
        "id": "test789",
        "title": "Mobile App Development",
        "description": "Need a mobile developer to build an iOS app",
        "budget": 2000,
        "duration": "long",
        "skills_required": ["swift", "ios"]
    }

    cover_letter = manager.generate_cover_letter(project_data, "generic", "Bob Johnson")

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    # Check that the letter contains key elements
    assert "Klaravex AI resolves most IT issues instantly" in cover_letter
    assert "Mobile App Development" in cover_letter
    assert "Bob Johnson" in cover_letter

def test_generate_cover_letter_unsupported_platform():
    """Test cover letter generation with unsupported platform (should fallback to generic)"""
    manager = CoverLetterTemplateManager()

    project_data = {
        "id": "test101",
        "title": "Data Science Project",
        "description": "Need a data scientist to analyze large datasets",
        "budget": 3000,
        "duration": "medium",
        "skills_required": ["python", "pandas"]
    }

    cover_letter = manager.generate_cover_letter(project_data, "unsupported_platform", "Alice Brown")

    assert isinstance(cover_letter, str)
    assert len(cover_letter) > 0
    # Should fallback to generic template
    assert "Klaravex AI resolves most IT issues instantly" in cover_letter
    assert "Data Science Project" in cover_letter
    assert "Alice Brown" in cover_letter

def test_template_addition():
    """Test adding a new custom template"""
    manager = CoverLetterTemplateManager()

    # Add a custom template
    custom_template = "Custom template for {{ project_title }} by {{ freelancer_name }}"
    manager.add_template("custom", custom_template)

    project_data = {
        "title": "Custom Project",
        "description": "A custom project",
        "budget": 500,
        "duration": "short",
        "skills_required": ["custom"]
    }

    cover_letter = manager.generate_cover_letter(project_data, "custom", "Custom Freelancer")

    assert isinstance(cover_letter, str)
    assert "Custom template for Custom Project by Custom Freelancer" in cover_letter

def test_template_retrieval():
    """Test retrieving raw templates"""
    manager = CoverLetterTemplateManager()

    # Get a specific template
    template = manager.get_template("freelancer")
    assert isinstance(template, str)
    assert len(template) > 0
    assert "Klaravex AI resolves most IT issues instantly" in template

    # Get non-existent template
    empty_template = manager.get_template("nonexistent")
    assert empty_template == ""

if __name__ == "__main__":
    pytest.main([__file__, "-v"])