"""
Test script to verify that the updated cover letter templates work correctly
with the freelance pipeline system.
"""

import sys
import os
import unittest

# Add the project root to Python path
sys.path.insert(0, '/home/anthony/Klaravex2.0')

from growth.adapters.cover_letter_generator import CoverLetterGenerator

class TestUpdatedTemplates(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.generator = CoverLetterGenerator()

    def test_updated_templates(self):
        """Test that updated templates work correctly."""

        # Sample project data
        project_data = {
            "id": "test_project_123",
            "title": "Website Redesign Project",
            "description": "Redesign company website with modern UI/UX",
            "budget": 2500,
            "duration": "medium",
            "skills_required": ["web design", "UI/UX", "HTML/CSS"]
        }

        # Test a few platforms to ensure they work
        platforms = ["freelancer", "upwork", "generic"]

        for platform in platforms:
            with self.subTest(platform=platform):
                cover_letter = self.generator.generate_cover_letter(
                    project_data=project_data,
                    platform=platform,
                    freelancer_name="Klaravex AI"
                )

                self.assertIsInstance(cover_letter, str)
                self.assertGreater(len(cover_letter), 0)
                self.assertIn("Klaravex AI", cover_letter)

    def test_healthcare_template(self):
        """Test that healthcare template works correctly."""

        project_data = {
            "id": "test_healthcare_project",
            "title": "Healthcare Network Security Audit",
            "description": "Conduct a comprehensive security audit of healthcare network infrastructure",
            "budget": 5000,
            "duration": "medium",
            "skills_required": ["network security", "healthcare compliance", "risk assessment"]
        }

        cover_letter = self.generator.generate_cover_letter(
            project_data=project_data,
            platform="healthcare_security",
            freelancer_name="Klaravex Security Specialist"
        )

        self.assertIsInstance(cover_letter, str)
        self.assertGreater(len(cover_letter), 0)
        # Healthcare template should contain Klaravex AI messaging
        self.assertIn("Klaravex AI", cover_letter)

if __name__ == "__main__":
    unittest.main()