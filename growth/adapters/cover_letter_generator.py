"""
Cover Letter Generator

This module provides a comprehensive system for generating platform-specific cover letters
for freelance bid submissions, integrating with the template manager.
"""

from typing import Dict, Any, Optional
import structlog
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager

logger = structlog.get_logger(__name__)

class CoverLetterGenerator:
    """
    A generator for creating platform-specific cover letters.

    This class provides functionality to generate cover letters tailored for
    different freelance platforms with appropriate tone and content.
    """

    def __init__(self, template_manager: Optional[CoverLetterTemplateManager] = None):
        """
        Initialize the cover letter generator.

        Args:
            template_manager (CoverLetterTemplateManager): The template manager to use.
                If None, a new one will be created.
        """
        if template_manager is not None:
            self.template_manager = template_manager
        else:
            self.template_manager = CoverLetterTemplateManager()

    def generate_cover_letter(self, project_data: Dict[str, Any],
                            platform: str, freelancer_name: str = "Freelancer",
                            context_overrides: Optional[Dict[str, Any]] = None) -> str:
        """
        Generate a cover letter for a specific platform based on project data.

        Args:
            project_data (Dict): Project information including title, description, budget, etc.
            platform (str): The platform to generate the letter for
            freelancer_name (str): Name of the freelancer
            context_overrides (Dict): Additional context variables to override template defaults

        Returns:
            str: Generated cover letter
        """
        try:
            # Generate the cover letter using the template manager
            cover_letter = self.template_manager.generate_cover_letter(
                project_data=project_data,
                platform=platform,
                freelancer_name=freelancer_name
            )

            logger.info("Cover letter generated successfully", platform=platform,
                       project_title=project_data.get("title", ""))

            return cover_letter

        except Exception as e:
            logger.error("Error generating cover letter", error=str(e), platform=platform)
            # Return a basic fallback if template generation fails
            return f"Cover letter could not be generated: {str(e)}"

    def validate_template(self, platform: str) -> bool:
        """
        Validate if a template exists for the given platform.

        Args:
            platform (str): The platform name to validate

        Returns:
            bool: True if template exists, False otherwise
        """
        try:
            template = self.template_manager.get_template(platform)
            return template is not None and template != ""
        except Exception:
            return False

    def get_supported_platforms(self) -> list:
        """
        Get a list of all supported platforms.

        Returns:
            List of platform names that have templates available.
        """
        return self.template_manager.get_available_platforms()

    def add_custom_template(self, platform: str, template: str):
        """
        Add or update a custom template for a specific platform.

        Args:
            platform (str): The platform name
            template (str): The Jinja2 template string
        """
        self.template_manager.add_template(platform, template)
        logger.info("Added/updated custom template", platform=platform)

    def get_template_preview(self, platform: str, project_data: Dict[str, Any],
                           freelancer_name: str = "Freelancer") -> str:
        """
        Get a preview of a cover letter without fully generating it.

        Args:
            platform (str): The platform to generate the preview for
            project_data (Dict): Project information
            freelancer_name (str): Name of the freelancer

        Returns:
            str: Preview of the cover letter
        """
        try:
            # Use the template manager to get a preview
            return self.template_manager.generate_cover_letter(
                project_data=project_data,
                platform=platform,
                freelancer_name=freelancer_name
            )
        except Exception as e:
            logger.error("Error generating template preview", error=str(e), platform=platform)
            return f"Preview could not be generated: {str(e)}"


# Global instance for backward compatibility
cover_letter_generator = CoverLetterGenerator()


def generate_cover_letter(project_data: Dict[str, Any], platform: str,
                         freelancer_name: str = "Freelancer",
                         context_overrides: Optional[Dict[str, Any]] = None) -> str:
    """
    Backward compatible function for generating cover letters.

    Args:
        project_data (Dict): Project information including title, description, budget, etc.
        platform (str): The platform to generate the letter for
        freelancer_name (str): Name of the freelancer
        context_overrides (Dict): Additional context variables to override template defaults

    Returns:
        str: Generated cover letter
    """
    return cover_letter_generator.generate_cover_letter(
        project_data=project_data,
        platform=platform,
        freelancer_name=freelancer_name,
        context_overrides=context_overrides
    )