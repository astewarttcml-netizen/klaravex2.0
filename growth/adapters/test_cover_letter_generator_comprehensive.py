"""
Comprehensive tests for the Cover Letter Generator

These tests verify that the cover letter generator works correctly
with all its features including integration with the template manager.
"""

import unittest
from unittest.mock import patch, MagicMock
from growth.adapters.cover_letter_generator import CoverLetterGenerator, cover_letter_generator
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager


class TestCoverLetterGenerator(unittest.TestCase):
    """Test cases for the Cover Letter Generator."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.template_manager = CoverLetterTemplateManager()
        self.generator = CoverLetterGenerator(template_manager=self.template_manager)

    def test_generator_initialization(self):
        """Test that the generator initializes correctly."""
        self.assertIsInstance(self.generator, CoverLetterGenerator)
        self.assertEqual(self.generator.template_manager, self.template_manager)

    def test_generator_with_default_template_manager(self):
        """Test that the generator works with default template manager."""
        # This should work without explicitly passing a template manager
        generator = CoverLetterGenerator()
        self.assertIsInstance(generator, CoverLetterGenerator)
        self.assertIsNotNone(generator.template_manager)

    def test_generate_cover_letter_basic(self):
        """Test basic cover letter generation."""
        project_data = {
            "title": "Website Redesign Project",
            "description": "Redesign an existing website with modern UI/UX",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["React", "Node.js", "UI/UX Design"]
        }

        cover_letter = self.generator.generate_cover_letter(
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

    def test_generate_cover_letter_with_overrides(self):
        """Test cover letter generation with context overrides."""
        project_data = {
            "title": "Website Redesign Project",
            "description": "Redesign an existing website with modern UI/UX",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["React", "Node.js", "UI/UX Design"]
        }

        context_overrides = {
            "custom_message": "This is a custom message for testing"
        }

        cover_letter = self.generator.generate_cover_letter(
            project_data=project_data,
            platform="freelancer",
            freelancer_name="Klaravex Freelancer",
            context_overrides=context_overrides
        )

        # Verify the letter was generated
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")

    def test_validate_template(self):
        """Test template validation."""
        # Test valid platforms
        self.assertTrue(self.generator.validate_template("freelancer"))
        self.assertTrue(self.generator.validate_template("upwork"))
        self.assertTrue(self.generator.validate_template("guru"))
        self.assertTrue(self.generator.validate_template("generic"))

        # Test invalid platform
        self.assertFalse(self.generator.validate_template("invalid_platform"))

    def test_get_supported_platforms(self):
        """Test getting list of supported platforms."""
        platforms = self.generator.get_supported_platforms()
        expected_platforms = ["freelancer", "freelancermap_de", "upwork", "guru",
                            "peopleperhour", "generic", "manual"]

        self.assertEqual(len(platforms), 7)
        for platform in expected_platforms:
            self.assertIn(platform, platforms)

    def test_add_custom_template(self):
        """Test adding a custom template."""
        new_template = "This is a {{ platform }} template for {{ project_title }}."

        self.generator.add_custom_template("custom_platform", new_template)

        # Verify we can generate from the new template
        project_data = {
            "title": "Custom Project",
            "description": "A custom project",
            "budget": 1000,
            "duration": "1 week",
            "skills_required": ["Python"]
        }

        cover_letter = self.generator.generate_cover_letter(
            project_data=project_data,
            platform="custom_platform",
            freelancer_name="Klaravex Freelancer"
        )

        # Verify the letter was generated
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")

    def test_get_template_preview(self):
        """Test getting template preview."""
        project_data = {
            "title": "Website Redesign Project",
            "description": "Redesign an existing website with modern UI/UX",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["React", "Node.js", "UI/UX Design"]
        }

        preview = self.generator.get_template_preview(
            platform="freelancer",
            project_data=project_data,
            freelancer_name="Klaravex Freelancer"
        )

        # Verify the preview was generated
        self.assertIsInstance(preview, str)
        self.assertNotEqual(preview, "")

    def test_generate_cover_letter_fallback(self):
        """Test fallback behavior when template generation fails."""
        project_data = {
            "title": "Website Redesign Project",
            "description": "Redesign an existing website with modern UI/UX",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["React", "Node.js", "UI/UX Design"]
        }

        # Mock a failure in template rendering to test fallback
        with patch.object(self.template_manager, 'get_template') as mock_get_template:
            mock_get_template.side_effect = Exception("Template rendering failed")

            cover_letter = self.generator.generate_cover_letter(
                project_data=project_data,
                platform="freelancer",
                freelancer_name="Klaravex Freelancer"
            )

            # Should still return a fallback letter
            self.assertIsInstance(cover_letter, str)
            self.assertNotEqual(cover_letter, "")

    def test_backward_compatibility_function(self):
        """Test the backward compatible generate_cover_letter function."""
        project_data = {
            "title": "Website Redesign Project",
            "description": "Redesign an existing website with modern UI/UX",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["React", "Node.js", "UI/UX Design"]
        }

        # Test the global function
        cover_letter = cover_letter_generator.generate_cover_letter(
            project_data=project_data,
            platform="freelancer",
            freelancer_name="Klaravex Freelancer"
        )

        # Verify the letter was generated
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")

    def test_generate_cover_letter_empty_project_data(self):
        """Test cover letter generation with empty project data."""
        project_data = {}

        cover_letter = self.generator.generate_cover_letter(
            project_data=project_data,
            platform="freelancer",
            freelancer_name="Klaravex Freelancer"
        )

        # Should still generate a letter, even with empty data
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")

    def test_generate_cover_letter_special_characters(self):
        """Test cover letter generation with special characters."""
        project_data = {
            "title": "Website Redesign Project & More",
            "description": "Redesign an existing website with modern UI/UX (updated)",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["React", "Node.js", "UI/UX Design"]
        }

        cover_letter = self.generator.generate_cover_letter(
            project_data=project_data,
            platform="freelancer",
            freelancer_name="Klaravex Freelancer"
        )

        # Verify the letter was generated
        self.assertIsInstance(cover_letter, str)
        self.assertNotEqual(cover_letter, "")

    def test_generate_cover_letter_different_platforms(self):
        """Test cover letter generation for different platforms."""
        project_data = {
            "title": "Website Redesign Project",
            "description": "Redesign an existing website with modern UI/UX",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["React", "Node.js", "UI/UX Design"]
        }

        platforms = ["freelancer", "upwork", "guru", "peopleperhour", "generic"]

        for platform in platforms:
            with self.subTest(platform=platform):
                cover_letter = self.generator.generate_cover_letter(
                    project_data=project_data,
                    platform=platform,
                    freelancer_name="Klaravex Freelancer"
                )

                # Verify the letter was generated
                self.assertIsInstance(cover_letter, str)
                self.assertNotEqual(cover_letter, "")
                self.assertIn("Website Redesign Project", cover_letter)


if __name__ == '__main__':
    unittest.main()