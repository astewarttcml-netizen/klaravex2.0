"""
Integration module for cover letter generation within the freelance pipeline.

This module provides functions that integrate with the existing cover letter
generation system to support the freelance bid submission pipeline.
"""

from typing import Dict, Any, Optional
from growth.adapters.cover_letter_generator import CoverLetterGenerator, cover_letter_generator

# Global instance for easy access
generator = cover_letter_generator


def generate_cover_letter(project_data: Dict[str, Any],
                         platform: str,
                         freelancer_name: str = "Klaravex Freelancer") -> str:
    """
    Generate a cover letter for a specific platform based on project data.

    This function integrates with the existing CoverLetterGenerator class to
    provide seamless cover letter generation within the freelance pipeline.

    Args:
        project_data (Dict): Project information including title, description, budget, etc.
        platform (str): The platform to generate the letter for
        freelancer_name (str): Name of the freelancer

    Returns:
        str: Generated cover letter
    """
    return generator.generate_cover_letter(
        project_data=project_data,
        platform=platform,
        freelancer_name=freelancer_name
    )


def generate_cover_letter_preview(project_data: Dict[str, Any],
                                 platform: str,
                                 freelancer_name: str = "Klaravex Freelancer") -> str:
    """
    Generate a preview of the cover letter without actually generating it.

    Args:
        project_data (Dict): Project information
        platform (str): Platform name
        freelancer_name (str): Freelancer name

    Returns:
        str: Preview of the cover letter
    """
    return generator.get_template_preview(
        platform=platform,
        project_data=project_data,
        freelancer_name=freelancer_name
    )


def validate_platform(platform: str) -> bool:
    """
    Validate that a template exists for the specified platform.

    Args:
        platform (str): Platform name

    Returns:
        bool: True if template exists, False otherwise
    """
    return generator.validate_template(platform)


def get_supported_platforms() -> list:
    """
    Get a list of all supported platforms.

    Returns:
        list: List of supported platform names
    """
    return generator.get_supported_platforms()


def add_custom_template(platform: str, template: str):
    """
    Add or update a custom template for a specific platform.

    Args:
        platform (str): Platform name
        template (str): Jinja2 template string
    """
    generator.add_custom_template(platform, template)