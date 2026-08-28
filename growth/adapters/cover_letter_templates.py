"""
Cover Letter Template Manager

This module provides a system for managing platform-specific cover letter templates
for the freelance bid submission pipeline.
"""

import os
import logging
from typing import Dict, Any, Optional
from jinja2 import Template, Environment, FileSystemLoader
import json

logger = logging.getLogger(__name__)

class CoverLetterTemplateManager:
    """
    A manager for handling cover letter templates for different platforms.

    This class provides functionality to load, manage, and render cover letter
    templates tailored for different freelance platforms.
    """

    def __init__(self, template_dir: Optional[str] = None):
        """
        Initialize the cover letter template manager.

        Args:
            template_dir (str): Directory containing template files.
                               If None, uses default templates.
        """
        self.templates: Dict[str, Template] = {}
        self.template_dir = template_dir or os.path.join(
            os.path.dirname(__file__), 'cover_letters'
        )

        # Initialize with default templates if directory doesn't exist
        if not os.path.exists(self.template_dir):
            self._create_default_templates()
        else:
            # Ensure that we have templates in case directory exists but is empty
            try:
                files = os.listdir(self.template_dir)
                if len(files) == 0:
                    self._create_default_templates()
            except Exception as e:
                logger.warning(f"Could not check template directory: {e}")
                self._create_default_templates()

        self._load_templates()

    def _create_default_templates(self):
        """Create default template directory and files."""
        os.makedirs(self.template_dir, exist_ok=True)

        # Create default templates for different platforms
        default_templates = {
            "freelancer": """
Dear Hiring Manager,

I am writing to express my interest in your project "{{ project_title }}".
With my experience in {{ skills_required|join(', ') }}, I believe I can deliver quality results for this project.

Based on the project description: "{{ project_description }}",
I understand that you're looking for someone who can:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

My background includes working with clients on similar projects, and I'm confident I can contribute effectively to your team.
The budget of {{ project_budget }} EUR and duration of {{ project_duration }} align well with my experience.

I would welcome the opportunity to discuss how I can help bring your vision to life.
Please find my portfolio and previous work attached for your review.

Best regards,
{{ freelancer_name }}
            """,

            "freelancermap_de": """
Sehr geehrte Damen und Herren,

Ich schreibe Ihnen in Bezug auf Ihr Projekt "{{ project_title }}".
Mit meiner Erfahrung in {{ skills_required|join(', ') }} kann ich qualitativ hochwertige Ergebnisse für dieses Projekt liefern.

Basierend auf der Projektbeschreibung: "{{ project_description }}",
verstehe ich, dass Sie jemanden suchen, der folgende Fähigkeiten besitzt:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

Meine bisherige Arbeit mit Kunden ähnlicher Projekte zeigt, dass ich effektiv zu Ihrem Team beitragen kann.
Der Budget von {{ project_budget }} EUR und die Dauer von {{ project_duration }} passen gut zu meiner Erfahrung.

Ich würde gerne die Gelegenheit haben, wie ich Ihr Vorhaben verwirklichen kann.
Bitte finden Sie meine Portfolio- und frühere Arbeiten im Anhang.

Mit freundlichen Grüßen,
{{ freelancer_name }}
            """,

            "upwork": """
Hello,

I am interested in your project "{{ project_title }}".
Based on my skills in {{ skills_required|join(', ') }}, I believe I can provide valuable contributions to your team.

From the project description: "{{ project_description }}",
I understand you are looking for someone who can:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

My experience working with clients on similar projects has prepared me well for this opportunity.
The budget of {{ project_budget }} USD and duration of {{ project_duration }} fit my capabilities perfectly.

I would love to discuss how I can help bring your project to success.
Please review my portfolio and past work attached.

Thank you,
{{ freelancer_name }}
            """,

            "guru": """
Hi there,

I'm excited about the opportunity to work on your "{{ project_title }}" project.
With expertise in {{ skills_required|join(', ') }}, I can deliver high-quality results that meet your requirements.

From your project details: "{{ project_description }}",
I see you need someone who can:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

Having successfully completed similar projects, I'm confident I can help achieve your goals.
The budget of {{ project_budget }} EUR and timeline of {{ project_duration }} are well within my experience.

Looking forward to collaborating with you.
Best regards,
{{ freelancer_name }}
            """,

            "peopleperhour": """
Hello,

I am interested in your "{{ project_title }}" project.
My experience in {{ skills_required|join(', ') }} makes me a strong candidate for this opportunity.

Based on the project description: "{{ project_description }}",
I understand you require someone who can:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

With my track record of successful project completions, I'm confident I can deliver results that exceed your expectations.
The budget of {{ project_budget }} EUR and timeframe of {{ project_duration }} align well with my services.

I would appreciate the chance to discuss how I can contribute.
Thank you,
{{ freelancer_name }}
            """,

            "generic": """
Dear Hiring Manager,

I am writing to express my interest in your "{{ project_title }}" project.
Based on my background and skills, I believe I can make a valuable contribution to your team.

From the project description: "{{ project_description }}",
I understand that you are seeking someone who can:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

My experience working with clients similar to your needs has prepared me well for this opportunity.
The budget of {{ project_budget }} EUR and timeline of {{ project_duration }} match my capabilities.

I would welcome the chance to discuss how I can help achieve your project goals.
Thank you for considering my application.

Best regards,
{{ freelancer_name }}
            """,

            "manual": """
Dear Hiring Manager,

I am writing in response to your "{{ project_title }}" project posting.
I have reviewed the requirements and believe I can provide the expertise needed for this work.

Project details:
- Description: {{ project_description }}
- Budget: {{ project_budget }} EUR
- Duration: {{ project_duration }}
- Required skills: {{ skills_required|join(', ') }}

Based on my experience, I am confident that I can deliver quality results within your timeframe and budget constraints.

I would be happy to discuss this opportunity further and provide additional information about my qualifications.
Please feel free to contact me if you have any questions.

Best regards,
{{ freelancer_name }}
            """
        }

        # Write each template to a file
        for platform, template_content in default_templates.items():
            with open(os.path.join(self.template_dir, f"{platform}.j2"), "w") as f:
                f.write(template_content.strip())

    def _load_templates(self):
        """Load all templates from the template directory."""
        try:
            # Clear existing templates
            self.templates.clear()

            # Load each template file
            for filename in os.listdir(self.template_dir):
                if filename.endswith('.j2'):
                    platform = filename[:-3]  # Remove .j2 extension

                    with open(os.path.join(self.template_dir, filename), 'r') as f:
                        template_content = f.read()

                    # Create Jinja2 template
                    self.templates[platform] = Template(template_content)

            logger.info(f"Loaded {len(self.templates)} cover letter templates")

        except Exception as e:
            logger.error(f"Error loading templates: {e}")
            # Initialize with basic templates if file loading fails
            self._initialize_basic_templates()

    def _initialize_basic_templates(self):
        """Initialize with basic fallback templates if file loading fails."""
        # This is a simple fallback implementation
        pass

    def get_template(self, platform: str) -> Optional[Template]:
        """
        Get the template for a specific platform.

        Args:
            platform (str): The platform name

        Returns:
            Template: The Jinja2 template for the platform, or None if not found
        """
        return self.templates.get(platform)

    def get_available_platforms(self) -> list:
        """
        Get a list of all available platforms with templates.

        Returns:
            List of platform names
        """
        return list(self.templates.keys())

    def generate_cover_letter(self, project_data: Dict[str, Any],
                            platform: str, freelancer_name: str = "Freelancer") -> str:
        """
        Generate a cover letter for a specific platform based on project data.

        Args:
            project_data (Dict): Project information including title, description, budget, etc.
            platform (str): The platform to generate the letter for
            freelancer_name (str): Name of the freelancer

        Returns:
            str: Generated cover letter
        """
        try:
            # Get the appropriate template
            template = self.get_template(platform)

            # If no specific template found, fall back to generic
            if not template:
                logger.warning(f"No template found for platform '{platform}', using generic")
                template = self.get_template("generic")

            # If still no template, return error message
            if not template:
                return f"Could not generate cover letter: No template available for {platform}"

            # Prepare context data for the template
            context = {
                "project_title": project_data.get("title", ""),
                "project_description": project_data.get("description", ""),
                "project_budget": project_data.get("budget", 0),
                "project_duration": project_data.get("duration", ""),
                "skills_required": project_data.get("skills_required", []),
                "freelancer_name": freelancer_name
            }

            # Render the template with context
            cover_letter = template.render(context)

            logger.info(f"Cover letter generated for platform '{platform}'")
            return cover_letter

        except Exception as e:
            logger.error(f"Error generating cover letter for {platform}: {e}")
            return f"Could not generate cover letter: {str(e)}"

    def add_template(self, platform: str, template_content: str):
        """
        Add or update a template for a specific platform.

        Args:
            platform (str): The platform name
            template_content (str): The Jinja2 template string
        """
        try:
            # Create the Jinja2 template
            template = Template(template_content)

            # Store in memory
            self.templates[platform] = template

            # Save to file
            with open(os.path.join(self.template_dir, f"{platform}.j2"), "w") as f:
                f.write(template_content.strip())

            logger.info(f"Added/updated template for platform '{platform}'")

        except Exception as e:
            logger.error(f"Error adding template for {platform}: {e}")
            raise

    def remove_template(self, platform: str):
        """
        Remove a template for a specific platform.

        Args:
            platform (str): The platform name
        """
        if platform in self.templates:
            del self.templates[platform]

            # Remove from file system too
            try:
                os.remove(os.path.join(self.template_dir, f"{platform}.j2"))
            except Exception as e:
                logger.error(f"Error removing template file for {platform}: {e}")

            logger.info(f"Removed template for platform '{platform}'")

    def update_template(self, platform: str, template_content: str):
        """
        Update an existing template for a specific platform.

        Args:
            platform (str): The platform name
            template_content (str): The new Jinja2 template string
        """
        self.add_template(platform, template_content)