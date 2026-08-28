"""
Comprehensive Tests for the Cover Letter Template Manager

These tests verify that the cover letter template system works correctly
and that templates are properly loaded and rendered.
"""

import unittest
import os
import tempfile
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager


class TestCoverLetterTemplateManager(unittest.TestCase):
    """Test cases for the Cover Letter Template Manager."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a temporary directory for testing
        self.temp_dir = tempfile.mkdtemp()
        self.template_manager = CoverLetterTemplateManager(template_dir=self.temp_dir)

    def tearDown(self):
        """Clean up after each test method."""
        # Clean up the temporary directory
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_template_manager_initialization(self):
        """Test that the template manager initializes correctly."""
        self.assertIsInstance(self.template_manager, CoverLetterTemplateManager)
        self.assertIsNotNone(self.template_manager.templates)
        # Should have loaded default templates
        self.assertGreater(len(self.template_manager.get_available_platforms()), 0)

    def test_get_available_platforms(self):
        """Test that all platforms are returned correctly."""
        platforms = self.template_manager.get_available_platforms()

        # Should include at least the basic platforms
        expected_platforms = ["freelancer", "freelancermap_de", "upwork", "guru",
                            "peopleperhour", "generic", "manual"]

        for platform in expected_platforms:
            self.assertIn(platform, platforms)

    def test_template_exists_for_all_platforms(self):
        """Test that templates exist for all supported platforms."""
        platforms = self.template_manager.get_available_platforms()

        for platform in platforms:
            template = self.template_manager.get_template(platform)
            self.assertIsNotNone(template)
            # Template should be a Jinja2 Template object
            self.assertTrue(hasattr(template, 'render'))

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

        # Verify we can get the template back
        retrieved_template = self.template_manager.get_template("test_platform")
        self.assertIsNotNone(retrieved_template)

    def test_add_template_with_jinja2_variables(self):
        """Test adding a template with Jinja2 variables."""
        new_template = """
Project: {{ project_title }}
Skills: {{ skills_required|join(', ') }}
Freelancer: {{ freelancer_name }}
        """

        self.template_manager.add_template("jinja_test", new_template)

        # Test generating from the new template
        project_data = {
            "title": "Test Project",
            "description": "A test project",
            "budget": 1000,
            "duration": "1 week",
            "skills_required": ["Python", "Django"]
        }

        cover_letter = self.template_manager.generate_cover_letter(
            project_data=project_data,
            platform="jinja_test",
            freelancer_name="Test Freelancer"
        )

        # Verify the letter was generated and variables were replaced
        self.assertIsInstance(cover_letter, str)
        self.assertIn("Test Project", cover_letter)
        self.assertIn("Python", cover_letter)
        self.assertIn("Django", cover_letter)
        self.assertIn("Test Freelancer", cover_letter)

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

    def test_update_template(self):
        """Test updating an existing template."""
        # First add a template
        initial_template = "Initial template content."
        self.template_manager.add_template("update_test", initial_template)

        # Verify initial content
        retrieved_template = self.template_manager.get_template("update_test")
        self.assertIsNotNone(retrieved_template)

        # Update the template
        updated_template = "Updated template content with {{ project_title }}."
        self.template_manager.update_template("update_test", updated_template)

        # Generate using updated template
        project_data = {
            "title": "Updated Project",
            "description": "A test project",
            "budget": 1000,
            "duration": "1 week",
            "skills_required": ["Test"]
        }

        cover_letter = self.template_manager.generate_cover_letter(
            project_data=project_data,
            platform="update_test",
            freelancer_name="Test Freelancer"
        )

        # Verify that the updated template was used
        self.assertIn("Updated Project", cover_letter)

    def test_remove_template(self):
        """Test removing a template."""
        # Add a template first
        self.template_manager.add_template("remove_test", "Test template content.")

        # Verify it exists
        platforms = self.template_manager.get_available_platforms()
        self.assertIn("remove_test", platforms)

        # Remove the template
        self.template_manager.remove_template("remove_test")

        # Verify it's gone
        platforms = self.template_manager.get_available_platforms()
        self.assertNotIn("remove_test", platforms)

        # Verify the template is no longer retrievable
        template = self.template_manager.get_template("remove_test")
        self.assertIsNone(template)


if __name__ == '__main__':
    unittest.main()