"""
Test cases for the improved cover letter templates.
"""

import unittest
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager
from growth.adapters.cover_letter_generator import CoverLetterGenerator

class TestImprovedCoverLetterTemplates(unittest.TestCase):
    """Test cases for the improved cover letter templates."""

    def setUp(self):
        """Set up test fixtures."""
        self.template_manager = CoverLetterTemplateManager()
        self.generator = CoverLetterGenerator()

    def test_template_loading(self):
        """Test that all templates load correctly."""
        platforms = self.template_manager.get_available_platforms()
        self.assertGreater(len(platforms), 0)
        self.assertIn("upwork", platforms)
        self.assertIn("freelancer", platforms)
        self.assertIn("guru", platforms)
        self.assertIn("healthcare_security", platforms)

    def test_upwork_template_improvements(self):
        """Test that the Upwork template has improved structure."""
        project_data = {
            "title": "Website Redesign Project",
            "description": "Need a modern website redesign for our e-commerce business",
            "budget": 2500,
            "duration": "2 weeks",
            "skills_required": ["HTML", "CSS", "JavaScript"],
            "specific_result": "a responsive and user-friendly website",
            "timeframe": "2 weeks",
            "industry_sector": "e-commerce",
            "measurable_outcome": "improved user engagement by 40%",
            "desired_outcome": "enhanced customer experience",
            "client_reference": "leading online retailers",
            "quantifiable_result": "increased conversion rates by 25%"
        }

        cover_letter = self.generator.generate_cover_letter(
            project_data=project_data,
            platform="upwork"
        )

        # Check that the improved elements are present
        self.assertIn("I'm excited to apply for your", cover_letter)
        # The variables should be replaced with actual values, not remain as placeholders
        self.assertNotIn("specific_result", cover_letter)  # Should be replaced by actual value
        self.assertNotIn("industry_sector", cover_letter)  # Should be replaced by actual value
        self.assertNotIn("measurable_outcome", cover_letter)  # Should be replaced by actual value
        self.assertNotIn("client_reference", cover_letter)  # Should be replaced by actual value
        # Check that actual values are present
        self.assertIn("a responsive and user-friendly website", cover_letter)
        self.assertIn("e-commerce", cover_letter)
        self.assertIn("improved user engagement by 40%", cover_letter)
        self.assertIn("leading online retailers", cover_letter)

    def test_freelancer_template_improvements(self):
        """Test that the Freelancer template has improved structure."""
        project_data = {
            "title": "Mobile App Development",
            "description": "Develop a cross-platform mobile application for fitness tracking",
            "budget": 5000,
            "duration": "4 weeks",
            "skills_required": ["React Native", "Node.js", "MongoDB"],
            "specific_benefit": "seamless user experience and efficient performance",
            "client_type": "healthcare technology companies",
            "quantifiable_result": "reduced app load time by 60%",
            "timeframe": "4 weeks",
            "similar_client": "leading health tech startups",
            "measurable_outcome": "significant performance improvements"
        }

        cover_letter = self.generator.generate_cover_letter(
            project_data=project_data,
            platform="freelancer"
        )

        # Check that the improved elements are present
        self.assertIn("I came across your project", cover_letter)
        # The variables should be replaced with actual values, not remain as placeholders
        self.assertNotIn("specific_benefit", cover_letter)  # Should be replaced by actual value
        self.assertNotIn("client_type", cover_letter)  # Should be replaced by actual value
        self.assertNotIn("measurable_outcome", cover_letter)  # Should be replaced by actual value
        # Check that the key content elements are present (some values may be different)
        self.assertIn("Klaravex AI resolves most IT issues instantly", cover_letter)
        self.assertIn("2-hour human SLA", cover_letter)

    def test_healthcare_template(self):
        """Test that the healthcare template has specialized improvements."""
        project_data = {
            "title": "HIPAA Compliance Audit",
            "description": "Conduct a comprehensive audit of our healthcare network security",
            "budget": 3500,
            "duration": "3 weeks",
            "skills_required": ["Network Security", "HIPAA Compliance", "Risk Assessment"],
            "specific_result": "enhanced network security posture",
            "timeframe": "3 weeks",
            "industry_sector": "healthcare",
            "measurable_outcome": "reduced security vulnerabilities by 85%",
            "desired_outcome": "compliance readiness",
            "client_reference": "leading healthcare providers",
            "quantifiable_result": "achieved 99% compliance score"
        }

        cover_letter = self.generator.generate_cover_letter(
            project_data=project_data,
            platform="healthcare_security"
        )

        # Check that the healthcare-specific elements are present
        self.assertIn("Klaravex AI resolves most IT issues instantly", cover_letter)
        self.assertIn("2-hour human SLA", cover_letter)
        # The variables should be replaced with actual values, not remain as placeholders
        self.assertNotIn("specific_result", cover_letter)  # Should be replaced by actual value
        # Check that key content elements are present (some values may be different)
        self.assertIn("healthcare sector", cover_letter)
        self.assertIn("regulatory requirements (HIPAA, GDPR)", cover_letter)

    def test_template_structure_consistency(self):
        """Test that all templates follow consistent structure."""
        project_data = {
            "title": "Test Project",
            "description": "A test project for template validation",
            "budget": 1000,
            "duration": "1 week",
            "skills_required": ["Testing"],
            "specific_result": "test results",
            "timeframe": "1 week"
        }

        platforms = self.template_manager.get_available_platforms()

        # Test that all templates can be generated without errors
        for platform in platforms:
            if platform != "manual":  # Skip manual since it's a basic template
                cover_letter = self.generator.generate_cover_letter(
                    project_data=project_data,
                    platform=platform
                )
                self.assertIsInstance(cover_letter, str)
                self.assertGreater(len(cover_letter), 0)

    def test_template_content_improvements(self):
        """Test that templates have the key improvements from review notes."""
        project_data = {
            "title": "Website Optimization",
            "description": "Optimize website performance and user experience",
            "budget": 2000,
            "duration": "2 weeks",
            "skills_required": ["SEO", "Performance Optimization"],
            "specific_result": "improved page load speed",
            "timeframe": "2 weeks",
            "industry_sector": "digital marketing",
            "measurable_outcome": "reduced bounce rate by 30%",
            "desired_outcome": "enhanced user engagement"
        }

        cover_letter = self.generator.generate_cover_letter(
            project_data=project_data,
            platform="upwork"
        )

        # Test that key improvements are present:
        # 1. Enhanced Openers - Should start with impactful value statement
        self.assertIn("I'm excited to apply for your", cover_letter)

        # 2. Added Vertical Hooks - Should mention industry sector
        self.assertNotIn("industry_sector", cover_letter)  # Should be replaced by actual value
        self.assertIn("digital marketing", cover_letter)  # Check that actual value is present

        # 3. Concrete Metrics - Should include measurable outcomes
        self.assertNotIn("measurable_outcome", cover_letter)  # Should be replaced by actual value
        self.assertIn("reduced bounce rate by 30%", cover_letter)  # Check that actual value is present

        # 4. Stronger Differentiation - Should highlight unique value propositions
        self.assertNotIn("specific_result", cover_letter)  # Should be replaced by actual value
        self.assertIn("improved page load speed", cover_letter)  # Check that actual value is present

    def test_template_fallback_mechanism(self):
        """Test that the template manager falls back to generic when needed."""
        project_data = {
            "title": "Test Project",
            "description": "A test project",
            "budget": 1000,
            "duration": "1 week",
            "skills_required": ["Testing"]
        }

        # Test with a non-existent platform (should fall back to generic)
        cover_letter = self.generator.generate_cover_letter(
            project_data=project_data,
            platform="nonexistent_platform"
        )

        # Should still return a string (fallback to generic template)
        self.assertIsInstance(cover_letter, str)
        self.assertGreater(len(cover_letter), 0)

if __name__ == '__main__':
    unittest.main()