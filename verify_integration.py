"""
Verification that freelance pipeline properly integrates cover letter generation.
This demonstrates the complete integration of pipeline components with cover letters.
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, '/home/anthony/Klaravex2.0')

from growth.adapters.freelance_pipeline import FreelanceBidPipeline
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager

def verify_integration():
    """Verify that the pipeline properly integrates with cover letter generation"""

    print("=== Verifying Pipeline and Cover Letter Integration ===")

    # Create a pipeline instance
    pipeline = FreelanceBidPipeline()

    # Verify template manager is available
    assert hasattr(pipeline, 'template_manager')
    assert isinstance(pipeline.template_manager, CoverLetterTemplateManager)
    print("✓ Template manager properly initialized")

    # Test project data
    project_data = {
        "id": "test_integration_123",
        "title": "Python Web Application Development",
        "description": "Need a Python developer to build a web application using Django framework",
        "budget": 2000,
        "duration": "medium",
        "skills_required": ["python", "django", "postgresql"]
    }

    # Test cover letter generation for different platforms
    platforms = ["freelancer", "upwork", "guru"]

    for platform in platforms:
        try:
            cover_letter = pipeline.generate_cover_letter(
                project_data=project_data,
                platform=platform,
                freelancer_name="Klaravex Freelancer"
            )

            assert isinstance(cover_letter, str)
            assert len(cover_letter) > 0
            assert "Klaravex Freelancer" in cover_letter
            assert project_data["title"] in cover_letter

            print(f"✓ Cover letter generated successfully for {platform}")

        except Exception as e:
            print(f"✗ Failed to generate cover letter for {platform}: {e}")
            return False

    # Verify that the pipeline has proper methods
    assert hasattr(pipeline, 'generate_cover_letter')
    assert hasattr(pipeline, 'submit_bid')
    assert hasattr(pipeline, 'get_adapter')
    assert hasattr(pipeline, 'score_project')

    print("✓ All pipeline methods are available")
    print("✓ Integration complete - pipeline properly connects to cover letter generation")

    return True

if __name__ == "__main__":
    success = verify_integration()
    if success:
        print("\n🎉 Integration verification PASSED!")
        print("The freelance bid pipeline successfully integrates with cover letter generation.")
    else:
        print("\n❌ Integration verification FAILED!")
        sys.exit(1)