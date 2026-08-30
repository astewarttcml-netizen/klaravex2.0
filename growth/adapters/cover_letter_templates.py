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

        # Create improved templates for different platforms based on the review notes
        improved_templates = {
            "freelancer": """
Klaravex AI resolves most IT issues instantly, any hour. The cases that need judgment go to a named senior engineer with full context — 2-hour human SLA, no junior queue, no vendor commissions.

I came across your project "{{ project_title }}" and I'm confident I can deliver. Based on the requirements for {{ skills_required|join(', ') }}, I believe my experience aligns well with what you're seeking.

What sets me apart is my ability to consistently deliver reliable IT solutions that combine technical execution with strategic thinking. In my recent work with {{ client_type }}, I've achieved {{ specific_benefit }} within {{ timeframe }}.

For small law firms, accounting practices, and medical offices, Klaravex keeps M365 hardened, backups tested, and the network observable — Foundation through Directive, published pricing on klaravex.com.

We'll conduct a comprehensive assessment of your IT environment to identify gaps and implement solutions that align with your business needs. Our approach includes:
- Network segmentation analysis
- Multi-factor authentication implementation
- Backup RPO/RTO checklist review with recommendations
- Readiness evaluation for regulatory requirements
- Integration of our Foundation/Directive tier offerings tailored to SMB environments

The budget of {{ project_budget }} USD and timeline of {{ project_duration }} align well with my services. I'm confident that my expertise aligns well with your requirements and would be a valuable addition to your team. Please find my portfolio and previous work attached for your review.

To discuss how Klaravex can help bring your project to success, please visit klaravex.com or reply to this message.

Best regards,
{{ freelancer_name }}
            """,

            "freelancermap_de": """
Sehr geehrte Damen und Herren,

Ich schreibe Ihnen in Bezug auf Ihr Projekt "{{ project_title }}". Mit unserer Erfahrung in {{ skills_required|join(', ') }} können wir qualitativ hochwertige Ergebnisse für dieses Projekt liefern.

Basierend auf der Projektbeschreibung: "{{ project_description }}",
verstehe ich, dass Sie jemanden suchen, der folgende Fähigkeiten besitzt:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

Was uns auszeichnet ist unsere Sorgfalt bei der Arbeit und unser Engagement für Ergebnisse, die über Erwartungen hinausgehen. Unsere bisherige Arbeit mit Kunden ähnlicher Projekte zeigt, dass wir effektiv zu Ihrem Team beitragen können. Der Budget von {{ project_budget }} EUR und die Dauer von {{ project_duration }} passen gut zu unserem Profil.

Was uns auszeichnet ist unsere Fähigkeit, {{ specific_benefit }} zu liefern. In unseren kürzlichen Projekten mit {{ client_type }} erreichten wir {{ quantifiable_result }} innerhalb von {{ timeframe }}.

Unsere Herangehensweise kombiniert technische Ausführung mit strategischem Denken, was dazu beiträgt, dass Kunden wie {{ similar_client }} {{ measurable_outcome }} erreichen konnten. Diese Erfahrung übersetzt sich direkt auf Ihr Projekt.

Wir sind überzeugt, dass unsere Expertise gut zu Ihren Anforderungen passt und ein wertvoller Bestandteil Ihres Teams sein würde. Bitte finden Sie unser Portfolio und frühere Arbeiten im Anhang.

Mit freundlichen Grüßen,
{{ freelancer_name }}
            """,

            "upwork": """
Hello,

I'm excited to apply for your {{ project_title }} project. Based on my experience with similar projects, I can help you achieve {{ specific_result }} within {{ timeframe }}.

What sets us apart is our track record of delivering {{ measurable_outcome }} for clients in {{ industry_sector }}. Our approach combines technical expertise with strategic thinking to ensure {{ desired_outcome }}.

From your project details:
- {{ skills_required|join(', ') }}
- Budget: {{ project_budget }} USD
- Timeline: {{ project_duration }}

I've successfully completed projects like this for companies such as {{ client_reference }} where we achieved {{ quantifiable_result }}. I'm confident that my expertise aligns with your needs and would be a valuable addition to your team.

Please review my portfolio and past work attached, and let's discuss how I can help bring your project to success.

Best regards,
{{ freelancer_name }}
            """,

            "guru": """
Hi there,

I'm excited about the opportunity to work on your "{{ project_title }}" project. My expertise in {{ skills_required|join(', ') }} enables me to deliver results that directly impact business outcomes.

From your project details: "{{ project_description }}",
I see you need someone who can:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

What makes us a strong candidate is our proven track record of achieving {{ specific_result }} for clients in {{ industry_sector }}. In projects similar to yours, we've consistently delivered {{ measurable_outcome }} within {{ timeframe }}.

Our experience includes working with companies such as {{ client_reference }}, where we successfully accomplished {{ quantifiable_result }}. This background positions us well to help you achieve your project goals efficiently and effectively.

Looking forward to collaborating with you.

Best regards,
{{ freelancer_name }}
            """,

            "peopleperhour": """
Hello,

I am interested in your "{{ project_title }}" project. My experience in {{ skills_required|join(', ') }} makes me a strong candidate for this opportunity.

Based on the project description: "{{ project_description }}",
I understand you require someone who can:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

With our track record of successful project completions, I'm confident I can deliver results that exceed your expectations. The budget of {{ project_budget }} EUR and timeframe of {{ project_duration }} align well with our services.

What sets us apart is our commitment to quality work and clear communication throughout the project. We have a proven history of delivering projects on time and within budget while maintaining high standards of excellence.

I would appreciate the chance to discuss how we can contribute to your success.

Thank you,
{{ freelancer_name }}
            """,

            "generic": """
Dear Hiring Manager,

I am writing to express my interest in your "{{ project_title }}" project. Based on our background and skills, we believe we can make a valuable contribution to your team.

From the project description: "{{ project_description }}",
I understand that you are seeking someone who can:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

Our experience working with clients similar to your needs has prepared us well for this opportunity. The budget of {{ project_budget }} EUR and timeline of {{ project_duration }} match our capabilities.

What we bring to the table is a commitment to quality work, clear communication, and delivering results that exceed expectations. We're confident that our expertise aligns well with your project requirements and would be a valuable addition to your team.

I would welcome the chance to discuss how we can help achieve your project goals.

Thank you for considering our application.

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
            """,

            # Healthcare-specific template based on the review notes
            "healthcare_security": """
Klaravex AI resolves most IT issues instantly, any hour. The cases that need judgment go to a named senior engineer with full context — 2-hour human SLA, no junior queue, no vendor commissions.

Dear Hiring Manager,

I'm writing to express my interest in your "{{ project_title }}" project. With my experience in {{ skills_required|join(', ') }}, I believe I can deliver quality results that directly address your needs.

Based on the project description: "{{ project_description }}",
I understand that you're looking for someone who can:
{% for skill in skills_required %}
- {{ skill }}
{% endfor %}

What sets me apart is my ability to consistently deliver {{ specific_benefit }}. In my recent work with {{ client_type }}, I achieved {{ quantifiable_result }} within {{ timeframe }}.

My approach combines technical execution with strategic thinking, which has helped clients like {{ similar_client }} achieve {{ measurable_outcome }}. This experience directly translates to what you're seeking for this project.

For healthcare organizations, Klaravex keeps M365 hardened, backups tested, and the network observable — Foundation through Directive, published pricing on klaravex.com.

We'll conduct a comprehensive assessment of your healthcare IT environment to identify gaps and implement solutions that align with your business needs. Our approach includes:
- HIPAA-compliant network segmentation analysis
- Multi-factor authentication implementation with healthcare-specific requirements
- Backup RPO/RTO checklist review with recommendations tailored for healthcare
- Compliance readiness evaluation aligned with healthcare regulations
- Integration of our Foundation/Directive tier offerings tailored to healthcare environments

The budget of {{ project_budget }} USD and timeline of {{ project_duration }} align well with my services. I'm confident that my expertise aligns well with your requirements and would be a valuable addition to your team. Please find my portfolio and previous work attached for your review.

To discuss how Klaravex can help secure your healthcare organization's network, please visit klaravex.com or reply to this message.

Best regards,
{{ freelancer_name }}
            """
        }

        # Write each template to a file
        for platform, template_content in improved_templates.items():
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
                "freelancer_name": freelancer_name,
                # Additional context variables for improved templates
                "specific_result": project_data.get("specific_result", "measurable outcomes"),
                "timeframe": project_data.get("timeframe", "the project timeline"),
                "industry_sector": project_data.get("industry_sector", "your industry"),
                "measurable_outcome": project_data.get("measurable_outcome", "significant improvements"),
                "desired_outcome": project_data.get("desired_outcome", "your business goals"),
                "client_reference": project_data.get("client_reference", "leading companies"),
                "quantifiable_result": project_data.get("quantifiable_result", "tangible results"),
                "specific_benefit": project_data.get("specific_benefit", "exceptional value"),
                "client_type": project_data.get("client_type", "similar clients"),
                "similar_client": project_data.get("similar_client", "industry leaders")
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