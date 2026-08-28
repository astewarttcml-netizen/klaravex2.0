"""
Tests for the Cover Letter Template Manager

These tests verify that the cover letter template system works correctly
and that templates are properly loaded and rendered.
"""

import unittest
from unittest.mock import patch, MagicMock
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager


class TestCoverLetterTemplateManager(unittest.TestCase):
    """Test cases for the Cover Letter Template Manager."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.template_manager = CoverLetterTemplateManager()

    def test_template_manager_initialization(self):
        """Test that the template manager initializes correctly."""
        self.assertIsInstance(self.template_manager, CoverLetterTemplateManager)
        self.assertIsNotNone(self.template_manager.templates)

    def test_get_available_platforms(self):
        """Test that all platforms are returned correctly."""
        platforms = self.template_manager.get_available_platforms()
        # The actual number may be 8 because of the additional manual template
        expected_platforms = ["freelancer", "freelancermap_de", "upwork", "guru",
                            "peopleperhour", "generic", "manual"]

        # Check that all expected platforms are present (allowing for extra)
        for platform in expected_platforms:
            self.assertIn(platform, platforms)

    def test_template_exists_for_all_platforms(self):
        """Test that templates exist for all supported platforms."""
        platforms = self.template_manager.get_available_platforms()

        for platform in platforms:
            template = self.template_manager.get_template(platform)
            self.assertIsNotNone(template)
            self.assertNotEqual(template, "")

    def test_generate_cover_letter_freelancer(self):
        """Test generating a cover letter for Freelancer.com."""
        project_data = {
            "title": "Website Redesign Project",
            "description": "Redesign an existing website with modern UI/UX",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["React", "Node.js", "UI/UX Design"]
        }

        cover_letter = self.template_manager.generate_cover_letter(
            project_data=project_data,
            platform="freelancer",
            freelancer_name="Klaravex Freelancer"
        )

        # Verify the letter was generated
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")

        # Check that key elements are present
        self.assertIn("Website Redesign Project", cover_letter)
        self.assertIn("React", cover_letter)
        self.assertIn("Node.js", cover_letter)
        self.assertIn("UI/UX Design", cover_letter)
        self.assertIn("Klaravex Freelancer", cover_letter)

    def test_generate_cover_letter_generic(self):
        """Test generating a generic cover letter."""
        project_data = {
            "title": "Mobile App Development",
            "description": "Develop a cross-platform mobile application",
            "budget": 5000,
            "duration": "1 month",
            "skills_required": ["React Native", "Firebase", "UI/UX Design"]
        }

        cover_letter = self.template_manager.generate_cover_letter(
            project_data=project_data,
            platform="generic",
            freelancer_name="Klaravex Freelancer"
        )

        # Verify the letter was generated
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")

        # Check that key elements are present
        self.assertIn("Mobile App Development", cover_letter)
        self.assertIn("React Native", cover_letter)
        self.assertIn("Firebase", cover_letter)
        self.assertIn("UI/UX Design", cover_letter)
        self.assertIn("Klaravex Freelancer", cover_letter)

    def test_generate_cover_letter_manual(self):
        """Test generating a manual cover letter."""
        project_data = {
            "title": "IT Security Audit",
            "description": "Conduct comprehensive security audit for enterprise systems",
            "budget": 10000,
            "duration": "3 weeks",
            "skills_required": ["Cybersecurity", "Penetration Testing", "Compliance"]
        }

        cover_letter = self.template_manager.generate_cover_letter(
            project_data=project_data,
            platform="manual",
            freelancer_name="Klaravex Freelancer"
        )

        # Verify the letter was generated
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")

        # Check that key elements are present
        self.assertIn("IT Security Audit", cover_letter)
        self.assertIn("Cybersecurity", cover_letter)
        self.assertIn("Penetration Testing", cover_letter)
        self.assertIn("Compliance", cover_letter)
        self.assertIn("Klaravex Freelancer", cover_letter)

    def test_generate_cover_letter_unknown_platform(self):
        """Test generating a cover letter for an unknown platform."""
        project_data = {
            "title": "Custom Software Development",
            "description": "Develop custom software solution",
            "budget": 3000,
            "duration": "4 weeks",
            "skills_required": ["Python", "Django", "PostgreSQL"]
        }

        # This should fall back to the generic template
        cover_letter = self.template_manager.generate_cover_letter(
            project_data=project_data,
            platform="unknown_platform",
            freelancer_name="Klaravex Freelancer"
        )

        # Verify the letter was generated (should not fail)
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")

    def test_add_template(self):
        """Test adding a new template."""
        new_template = "This is a {{ platform }} template with {{ project_title }}."

        self.template_manager.add_template("test_platform", new_template)

        # Verify the template was added
        platforms = self.template_manager.get_available_platforms()
        self.assertIn("test_platform", platforms)

        # Verify we can get the template back (should return Template object, not string)
        retrieved_template = self.template_manager.get_template("test_platform")
        self.assertIsNotNone(retrieved_template)
        # Test that it's a Jinja2 Template object
        self.assertTrue(hasattr(retrieved_template, 'render'))

    def test_template_rendering_with_jinja2(self):
        """Test that templates are properly rendered with Jinja2."""
        project_data = {
            "title": "Website Redesign Project",
            "description": "Redesign an existing website with modern UI/UX",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["React", "Node.js", "UI/UX Design"]
        }

        # Test with freelancer template
        cover_letter = self.template_manager.generate_cover_letter(
            project_data=project_data,
            platform="freelancer",
            freelancer_name="Klaravex Freelancer"
        )

        # Verify that Jinja2 variables were properly replaced
        self.assertIn("Website Redesign Project", cover_letter)
        self.assertIn("React", cover_letter)
        self.assertIn("Node.js", cover_letter)
        self.assertIn("UI/UX Design", cover_letter)
        self.assertIn("Klaravex Freelancer", cover_letter)

    def test_empty_project_data(self):
        """Test cover letter generation with empty project data."""
        project_data = {}

        cover_letter = self.template_manager.generate_cover_letter(
            project_data=project_data,
            platform="freelancer",
            freelancer_name="Klaravex Freelancer"
        )

        # Should still generate a letter, even with empty data
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")

    def test_special_characters_in_project_data(self):
        """Test cover letter generation with special characters."""
        project_data = {
            "title": "Website Redesign Project & More",
            "description": "Redesign an existing website with modern UI/UX (updated)",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["React", "Node.js", "UI/UX Design"]
        }

        cover_letter = self.template_manager.generate_cover_letter(
            project_data=project_data,
            platform="freelancer",
            freelancer_name="Klaravex Freelancer"
        )

        # Verify the letter was generated
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")


if __name__ == '__main__':
    unittest.main()