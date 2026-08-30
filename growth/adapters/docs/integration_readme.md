# Freelance Pipeline Cover Letter Integration

## Overview

This module provides integration between the freelance pipeline and the cover letter generation system. It allows for seamless generation of platform-specific cover letters based on project data, which is a key component of the Klaravex growth system.

## Key Features

- Integration with `CoverLetterGenerator` class
- Support for multiple platforms (freelancer, upwork, guru, etc.)
- Template preview functionality
- Platform validation
- Custom template support
- Platform-specific templates optimized for each freelance marketplace

## Usage Examples

### Basic Cover Letter Generation

```python
from growth.adapters.freelance_cover_letter_integration import generate_cover_letter

project_data = {
    "id": "test_project_123",
    "title": "Website Redesign Project",
    "description": "Redesign company website with modern UI/UX",
    "budget": 2500,
    "duration": "medium",
    "skills_required": ["web design", "UI/UX", "HTML/CSS"]
}

cover_letter = generate_cover_letter(
    project_data=project_data,
    platform="freelancer",
    freelancer_name="Klaravex Freelancer"
)
```

### Template Preview

```python
from growth.adapters.freelance_cover_letter_integration import generate_cover_letter_preview

preview = generate_cover_letter_preview(
    project_data=project_data,
    platform="upwork",
    freelancer_name="Klaravex Developer"
)
```

### Platform Validation

```python
from growth.adapters.freelance_cover_letter_integration import validate_platform, get_supported_platforms

# Check if platform is supported
is_valid = validate_platform("freelancer")  # Returns True

# Get all supported platforms
platforms = get_supported_platforms()  # Returns list of platform names
```

## Integration with Freelance Pipeline

The integration seamlessly works with the `FreelanceBidPipeline` class:

```python
from growth.adapters.freelance_pipeline import FreelanceBidPipeline

pipeline = FreelanceBidPipeline()
cover_letter = pipeline.generate_cover_letter(
    project_data=project_data,
    platform="freelancer",
    freelancer_name="Klaravex Freelancer"
)
```

## System Architecture

The integration works through the following components:

1. **FreelanceBidPipeline** - Main class managing the end-to-end workflow
2. **CoverLetterGenerator** - Core generator that uses templates for each platform
3. **TemplateManager** - Manages platform-specific Jinja2 templates
4. **Platform Adapters** - Individual adapters for different freelance platforms

## Template Structure

The system uses Jinja2 templates with the following variables:
- `project_title`: The title of the project
- `project_description`: Description of the project
- `skills_required`: List of required skills for the project
- `project_budget`: Budget allocated for the project
- `project_duration`: Duration of the project (short, medium, long)
- `freelancer_name`: Name of the freelancer

## Test Coverage

All integration functionality is tested in `test_freelance_pipeline_cover_letter_integration.py` which includes:

- Full pipeline integration testing
- Template manager integration
- Generation consistency across methods
- Different platform templates
- Error handling verification
- Fallback behavior for unknown platforms
- Template preview functionality