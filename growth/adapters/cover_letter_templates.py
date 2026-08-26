"""
Cover Letter Template Manager

This module provides a flexible system for generating platform-specific cover letters
for freelance bid submissions.
"""

import jinja2
from typing import Dict, List, Any
import structlog

logger = structlog.get_logger(__name__)

class CoverLetterTemplateManager:
    """
    A manager for handling platform-specific cover letter templates.

    This class provides functionality to generate cover letters tailored for
    different freelance platforms with appropriate tone and content.
    """

    def __init__(self):
        """Initialize the template manager with predefined templates."""
        self.templates = {}
        self._load_default_templates()

    def _load_default_templates(self):
        """Load default templates for supported platforms."""
        # Enhanced Freelancer.com template based on recent improvements
        freelancer_template = """
Klaravex AI resolves most IT issues instantly, any hour. The cases that need judgment go to a named senior engineer with full context — 2-hour human SLA, no junior queue, no vendor commissions.

I'm particularly drawn to your {{ project_title }} opportunity because:
- {{ project_title }} aligns with my expertise in {{ required_skills|join(', ') }}
- I have experience working with clients on similar projects

My experience includes:
- Developing solutions with {{ required_skills|join(', ') }}
- Managing projects with budgets up to {{ project_budget }}
- Delivering quality work within {{ project_duration }} timeframes

What I offer:
- Technical expertise in {{ required_skills|join(', ') }}
- Strong problem-solving abilities
- Reliable communication and collaboration

{{ project_title }} aligns with our Foundation/Directive tier offerings. For healthcare practices like yours, Klaravex keeps network topology observable, MFA hardened, backups tested, and compliance evidence ready — Foundation through Directive, published pricing on klaravex.com.

I'd be happy to discuss how I can contribute to your team. Please feel free to contact me with any questions.

Best regards,
{{ freelancer_name }}
        """

        # Enhanced Freelancermap.de template (German platform) based on recent improvements
        freelancermap_de_template = """
Klaravex AI löst die meisten IT-Probleme sofort, jederzeit. Die Fälle, die Beurteilung benötigen, werden einem benannten Senior-Engineer mit vollständigem Kontext übergeben — 2-Stunden-SLA für Menschen, keine Junior-Warteschlange, keine Vendor-Provisionen.

Ich bin besonders an Ihrer {{ project_title }} Gelegenheit interessiert, weil:
- {{ project_title }} mit meinem Fachwissen in {{ required_skills|join(', ') }} übereinstimmt
- Ich Erfahrung mit Kunden auf ähnlichen Projekten habe

Meine Erfahrung umfasst:
- Lösungen mit {{ required_skills|join(', ') }} entwickeln
- Projekte mit Budgets bis zu {{ project_budget }} managen
- Qualität innerhalb von {{ project_duration }} Zeitrahmen liefern

Was ich anbiete:
- Technische Expertise in {{ required_skills|join(', ') }}
- Starke Problemlösungsfähigkeiten
- Zuverlässige Kommunikation und Zusammenarbeit

{{ project_title }} passt zu unseren Foundation/Directive-Tarifmodellen. Für kleine Rechtsfirmen, Buchhaltungspraxen und medizinische Büros hält Klaravex M365 gehärtet, Backups getestet und das Netzwerk beobachtbar — Foundation bis Directive, veröffentlichte Preise auf klaravex.com.

Ich würde gerne besprechen, wie ich zu Ihrem Team beitragen kann. Bitte kontaktieren Sie mich mit Fragen.

Mit freundlichen Grüßen,
{{ freelancer_name }}
        """

        # Enhanced Upwork template based on recent improvements
        upwork_template = """
Klaravex AI resolves most IT issues instantly, any hour. The cases that need judgment go to a named senior engineer with full context — 2-hour human SLA, no junior queue, no vendor commissions.

I'm excited to apply for your {{ project_title }} position. Based on my experience with {{ required_skills|join(', ') }}, I'm confident I can deliver exceptional results that align with your project needs.

My expertise includes:
- {{ project_description }}
- Successfully managing {{ project_budget }} budget projects
- Delivering quality work within {{ project_duration }} timelines

What I bring to the table:
- Strong technical skills in {{ required_skills|join(', ') }}
- Excellent communication and collaboration abilities
- Proven track record of meeting deadlines and exceeding expectations

I'm particularly drawn to this opportunity because:
- {{ project_title }} aligns with my expertise in {{ required_skills|join(', ') }}
- I have experience working with clients on similar projects

{{ project_title }} aligns with our Foundation/Directive tier offerings. For small law firms, accounting practices, and medical offices, Klaravex keeps M365 hardened, backups tested, and the network observable — Foundation through Directive, published pricing on klaravex.com.

I would love the chance to discuss how I can contribute to your success. Please let me know if you'd like to see any additional information.

Best regards,
{{ freelancer_name }}
        """

        # Enhanced Guru template based on recent improvements
        guru_template = """
Klaravex AI resolves most IT issues instantly, any hour. The cases that need judgment go to a named senior engineer with full context — 2-hour human SLA, no junior queue, no vendor commissions.

I am interested in your {{ project_title }} opportunity and believe my background in {{ required_skills|join(', ') }} makes me an excellent fit for this role.

My experience includes:
- Developing solutions with {{ required_skills|join(', ') }}
- Managing projects with budgets up to {{ project_budget }}
- Delivering quality work within {{ project_duration }} timeframes

What I offer:
- Technical expertise in {{ required_skills|join(', ') }}
- Strong problem-solving abilities
- Reliable communication and collaboration

I am particularly excited about this opportunity because:
- {{ project_title }} matches my area of expertise
- I have successfully completed similar projects

{{ project_title }} aligns with our Foundation/Directive tier offerings. For small law firms, accounting practices, and medical offices, Klaravex keeps M365 hardened, backups tested, and the network observable — Foundation through Directive, published pricing on klaravex.com.

I'd be happy to discuss how I can contribute to your team. Please feel free to contact me with any questions.

Best regards,
{{ freelancer_name }}
        """

        # Enhanced PeoplePerHour template based on recent improvements
        peopleperhour_template = """
Klaravex AI resolves most IT issues instantly, any hour. The cases that need judgment go to a named senior engineer with full context — 2-hour human SLA, no junior queue, no vendor commissions.

I am writing to express my interest in your {{ project_title }} project. With my background in {{ required_skills|join(', ') }}, I believe I can provide the quality and expertise you're looking for.

My experience includes:
- Working on projects like {{ project_description }}
- Managing {{ project_budget }} budget projects
- Delivering results within {{ project_duration }} timeframes

Key strengths:
- Technical proficiency in {{ required_skills|join(', ') }}
- Strong attention to detail
- Ability to work independently and collaboratively

I have successfully completed similar projects where:
- {{ project_title }} was a key requirement
- {{ required_skills|join(', ') }} were essential skills

{{ project_title }} aligns with our Foundation/Directive tier offerings. For small law firms, accounting practices, and medical offices, Klaravex keeps M365 hardened, backups tested, and the network observable — Foundation through Directive, published pricing on klaravex.com.

I would appreciate the opportunity to discuss how I can contribute to your project. Please let me know if you need any additional information.

Warm regards,
{{ freelancer_name }}
        """

        # Enhanced generic fallback template based on recent improvements
        generic_template = """
Klaravex AI resolves most IT issues instantly, any hour. The cases that need judgment go to a named senior engineer with full context — 2-hour human SLA, no junior queue, no vendor commissions.

I am writing to express my interest in your {{ project_title }} project. With experience in {{ required_skills|join(', ') }}, I believe I can deliver results that meet your requirements.

My background includes:
- {{ project_description }}
- Working on {{ project_budget }} budget projects
- Delivering within {{ project_duration }} timeframes

What I bring:
- Expertise in {{ required_skills|join(', ') }}
- Strong communication skills
- Reliable delivery of quality work

I am excited about this opportunity because:
- {{ project_title }} aligns with my experience
- {{ required_skills|join(', ') }} are key strengths for me

{{ project_title }} aligns with our Foundation/Directive tier offerings. For small law firms, accounting practices, and medical offices, Klaravex keeps M365 hardened, backups tested, and the network observable — Foundation through Directive, published pricing on klaravex.com.

I would welcome the chance to discuss how I can contribute to your success. Please let me know if you need any additional information.

Best regards,
{{ freelancer_name }}
        """

        # Enhanced manual platform template (specific for email notifications)
        manual_template = """
Klaravex AI resolves most IT issues instantly, any hour. The cases that need judgment go to a named senior engineer with full context — 2-hour human SLA, no junior queue, no vendor commissions.

This is an automated notification about your {{ project_title }} opportunity.

Based on our analysis:
- {{ project_title }} aligns with my expertise in {{ required_skills|join(', ') }}
- I am available to discuss this opportunity and can deliver within {{ project_duration }} timeframe

Key points:
- {{ project_description }}
- Budget: {{ project_budget }}
- Skills match: {{ required_skills|join(', ') }}

{{ project_title }} aligns with our Foundation/Directive tier offerings. For small law firms, accounting practices, and medical offices, Klaravex keeps M365 hardened, backups tested, and the network observable — Foundation through Directive, published pricing on klaravex.com.

For email notifications, I recommend setting up a follow-up system to track these opportunities. This ensures we don't miss valuable work while maintaining our quality standards.

Best regards,
{{ freelancer_name }}
        """

        self.templates = {
            "freelancer": freelancer_template,
            "freelancermap_de": freelancermap_de_template,
            "upwork": upwork_template,
            "guru": guru_template,
            "peopleperhour": peopleperhour_template,
            "generic": generic_template,
            "manual": manual_template
        }

    def get_available_platforms(self) -> List[str]:
        """
        Get a list of all available platforms with templates.

        Returns:
            List of platform names that have templates available.
        """
        return list(self.templates.keys())

    def add_template(self, platform: str, template: str):
        """
        Add or update a template for a specific platform.

        Args:
            platform (str): The platform name
            template (str): The Jinja2 template string
        """
        self.templates[platform] = template
        logger.info("Added/updated template", platform=platform)

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
            if platform in self.templates:
                template_str = self.templates[platform]
            else:
                # Fallback to generic template for unsupported platforms
                logger.warning("Unsupported platform, using generic template", platform=platform)
                template_str = self.templates["generic"]

            # Create Jinja2 environment and template
            env = jinja2.Environment()
            template = env.from_string(template_str)

            # Prepare context data
            context = {
                "project_title": project_data.get("title", ""),
                "project_description": project_data.get("description", ""),
                "project_budget": f"€{project_data.get('budget', 0):,}",
                "project_duration": project_data.get("duration", ""),
                "required_skills": project_data.get("skills_required", []),
                "freelancer_name": freelancer_name
            }

            # Generate the cover letter
            cover_letter = template.render(context)

            logger.info("Cover letter generated successfully", platform=platform,
                       project_title=project_data.get("title", ""))

            return cover_letter.strip()

        except Exception as e:
            logger.error("Error generating cover letter", error=str(e), platform=platform)
            # Return a basic fallback if template generation fails
            return f"Cover letter could not be generated: {str(e)}"

    def get_template(self, platform: str) -> str:
        """
        Get the raw template for a specific platform.

        Args:
            platform (str): The platform name

        Returns:
            str: The template string or empty string if not found
        """
        return self.templates.get(platform, "")