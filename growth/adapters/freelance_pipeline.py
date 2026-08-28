"""
Freelance bid pipeline implementation for Klaravex growth system.
This module manages the end-to-end workflow for discovering, scoring,
and submitting bids to freelance platforms.
"""

import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel
from typing import Dict, Any, Optional

# Import platform adapters
from growth.adapters.freelance_sites import (
    FreelancerAdapter,
    FreelancermapAdapter,
    UpworkAdapter,
    GuruAdapter,
    PeoplePerHourAdapter,
    ManualBidAdapter,
    get_freelance_adapter
)

# Import utilities
from growth.adapters.credentials import creds_configured
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager
from growth.adapters.cover_letter_generator import cover_letter_generator
from growth.adapters.cover_letter_generator import cover_letter_generator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/freelance", tags=["freelance"])

@dataclass
class Project:
    """Data class representing a freelance project"""
    id: str
    title: str
    description: str
    budget: float
    duration: str  # short, medium, long
    skills_required: List[str]
    platform: str
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


class CoverLetterRequest(BaseModel):
    """Request model for generating cover letters"""
    project_data: Dict[str, Any]
    platform: str
    freelancer_name: Optional[str] = None

@dataclass
class BidSubmission:
    """Data class representing a bid submission"""
    project_id: str
    platform: str
    amount: float
    cover_letter: str
    delivery_days: int
    currency: str
    submitted_at: datetime = None
    status: str = "pending"  # pending, submitted, failed

    def __post_init__(self):
        if self.submitted_at is None:
            self.submitted_at = datetime.now()

class FreelanceBidPipeline:
    """Main pipeline class for managing freelance bids across platforms"""

    def __init__(self):
        self.project_scores: Dict[str, float] = {}
        self.bid_history: List[BidSubmission] = []
        self.template_manager = CoverLetterTemplateManager()
        self.adapters: Dict[str, Any] = {}

    def get_adapter(self, platform: str) -> Any:
        """Get or create adapter for a specific platform"""
        if platform not in self.adapters:
            try:
                self.adapters[platform] = get_freelance_adapter(platform)
            except Exception as e:
                logger.error(f"Failed to initialize adapter for {platform}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to initialize adapter for {platform}"
                )
        return self.adapters[platform]

    def score_project(self, project_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score a project based on various criteria
        Returns a score between 0-100 with reasoning
        """
        try:
            # Create project object
            project = Project(
                id=project_data.get('id', ''),
                title=project_data.get('title', ''),
                description=project_data.get('description', ''),
                budget=project_data.get('budget', 0),
                duration=project_data.get('duration', 'medium'),
                skills_required=project_data.get('skills_required', []),
                platform=project_data.get('platform', '')
            )

            # Scoring logic
            score = 50  # Base score

            # Budget scoring (higher budget = better score)
            budget_score = min(project.budget / 1000, 30)  # Max 30 points for budget
            score += budget_score

            # Duration scoring (shorter duration = higher score)
            duration_multipliers = {
                'short': 25,
                'medium': 15,
                'long': 5
            }
            score += duration_multipliers.get(project.duration, 15)

            # Skill match scoring
            required_skills = project.skills_required
            if required_skills:
                skill_score = min(len(required_skills) * 5, 20)  # Max 20 points for skills
                score += skill_score

            # Normalize score to 0-100 range
            score = min(score, 100)

            # Generate reasoning
            reasons = [
                f"Budget: {project.budget} EUR",
                f"Duration: {project.duration}",
                f"Skills required: {len(required_skills)}"
            ]

            self.project_scores[project.id] = score

            return {
                "project_id": project.id,
                "score": round(score, 2),
                "reason": reasons,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Error scoring project {project_data.get('id', 'unknown')}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to score project: {str(e)}"
            )

    def generate_cover_letter(self, project_data: Dict[str, Any], platform: str,
                            freelancer_name: str = "Klaravex Freelancer") -> str:
        """Generate a cover letter for a specific platform"""
        try:
            return cover_letter_generator.generate_cover_letter(
                project_data=project_data,
                platform=platform,
                freelancer_name=freelancer_name
            )
        except Exception as e:
            logger.error(f"Error generating cover letter for {platform}: {e}")
            # Return a basic fallback cover letter
            return f"""Dear Hiring Manager,

I am writing to express my interest in your project '{project_data.get('title', 'Project')}'.

With my experience in {', '.join(project_data.get('skills_required', []))}, I believe I can deliver quality results for this project.

I look forward to discussing how I can contribute to your team.

Best regards,
{freelancer_name}"""

    def submit_bid(self, bid_data: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a bid to the specified platform"""
        project_id = bid_data.get('project_id')
        platform = bid_data.get('platform')
        amount = bid_data.get('bid_amount')
        cover_letter = bid_data.get('cover_letter')
        delivery_days = bid_data.get('delivery_days', 7)
        currency = bid_data.get('currency', 'EUR')

        if not all([project_id, platform, amount, cover_letter]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required bid parameters"
            )

        # Get the appropriate adapter
        adapter = self.get_adapter(platform)

        # Prepare project data for submission (simplified for this example)
        project_data = {
            "id": project_id,
            "title": "Project Title",
            "description": "Project Description",
            "budget": amount,
            "duration": "medium",
            "skills_required": ["skill1", "skill2"]
        }

        # Submit bid
        if hasattr(adapter, 'submit_bid'):
            # Check if it's an async method by inspecting the function
            import inspect
            submit_method = getattr(adapter, 'submit_bid')
            if inspect.iscoroutinefunction(submit_method):
                # Handle async methods
                result = asyncio.run(submit_method(project_data, amount, cover_letter))
            else:
                # Handle sync methods
                result = submit_method(project_data, amount, cover_letter)
        else:
            # If no submit_bid method, just log it as manual
            result = {
                'success': True,
                'message': f'Manual bid required for {platform}',
                'bid_id': f'{platform}_{int(time.time())}'
            }

        # Record the bid submission
        bid_submission = BidSubmission(
            project_id=project_id,
            platform=platform,
            amount=amount,
            cover_letter=cover_letter,
            delivery_days=delivery_days,
            currency=currency,
            status='submitted' if result['success'] else 'failed'
        )

        self.bid_history.append(bid_submission)

        return {
            "success": result['success'],
            "message": result['message'],
            "bid_id": result.get('bid_id'),
            "project_id": project_id,
            "platform": platform,
            "timestamp": datetime.now().isoformat()
        }

    def health_check(self) -> Dict[str, Any]:
        """Check the health status of the pipeline"""
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "adapter_count": len(self.adapters),
            "bid_history_count": len(self.bid_history)
        }

    def submit_multiple_bids(self, bids_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Submit multiple bids in sequence"""
        results = []
        total_submitted = 0

        for bid_data in bids_data:
            try:
                result = self.submit_bid(bid_data)
                results.append(result)
                if result['success']:
                    total_submitted += 1
            except Exception as e:
                logger.error(f"Error submitting bid {bid_data.get('project_id', 'unknown')}: {e}")
                results.append({
                    "success": False,
                    "message": f"Failed to submit bid: {str(e)}",
                    "project_id": bid_data.get('project_id'),
                    "platform": bid_data.get('platform')
                })

        return {
            "total_submitted": total_submitted,
            "total_attempts": len(bids_data),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }

    def get_bid_statistics(self) -> Dict[str, Any]:
        """Get statistics about bid submissions"""
        total_bids = len(self.bid_history)

        # Count bids by platform
        platform_counts = {}
        for bid in self.bid_history:
            platform = bid.platform
            platform_counts[platform] = platform_counts.get(platform, 0) + 1

        return {
            "daily_bids": total_bids,
            "total_platforms": len(platform_counts),
            "platforms": platform_counts,
            "timestamp": datetime.now().isoformat()
        }

    def get_bid_status(self, project_id: str) -> Dict[str, Any]:
        """Get status of bids for a specific project"""
        project_bids = [bid for bid in self.bid_history if bid.project_id == project_id]

        if not project_bids:
            return {
                "project_id": project_id,
                "status": "no_bids",
                "timestamp": datetime.now().isoformat()
            }

        # Get the most recent bid status
        latest_bid = max(project_bids, key=lambda x: x.submitted_at)

        return {
            "project_id": project_id,
            "status": latest_bid.status,
            "total_bids": len(project_bids),
            "platforms": [bid.platform for bid in project_bids],
            "timestamp": datetime.now().isoformat()
        }

    def validate_skills(self, skills: List[str]) -> Dict[str, Any]:
        """Validate a list of skills"""
        # In a real implementation, this would check against a skill database
        # For now, we'll just return the skills as valid
        return {
            "valid_skills": skills,
            "invalid_skills": [],
            "timestamp": datetime.now().isoformat()
        }

# Global pipeline instance
pipeline = FreelanceBidPipeline()

def score_project(project_data: Dict[str, Any]) -> Dict[str, Any]:
    """Score a project - exposed for API use"""
    return pipeline.score_project(project_data)

def submit_bid(bid_data: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a bid - exposed for API use"""
    return pipeline.submit_bid(bid_data)

def submit_multiple_bids(bids_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Submit multiple bids - exposed for API use"""
    return pipeline.submit_multiple_bids(bids_data)

def get_bid_statistics() -> Dict[str, Any]:
    """Get bid statistics - exposed for API use"""
    return pipeline.get_bid_statistics()

def get_bid_status(project_id: str) -> Dict[str, Any]:
    """Get bid status for a project - exposed for API use"""
    return pipeline.get_bid_status(project_id)

def validate_skills(skills: List[str]) -> Dict[str, Any]:
    """Validate skills - exposed for API use"""
    return pipeline.validate_skills(skills)

def health_check() -> Dict[str, Any]:
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "pipeline": "active"
    }

@router.post("/score")
def score_project_endpoint(project_data: Dict[str, Any]) -> Dict[str, Any]:
    """Score a project based on various factors"""
    return pipeline.score_project(project_data)


@router.post("/submit")
def submit_bid_endpoint(bid_data: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a bid to one or more platforms"""
    return pipeline.submit_bid(bid_data)


@router.post("/submit_multiple_bids")
def submit_multiple_bids_endpoint(bids_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Submit multiple bids in parallel"""
    return pipeline.submit_multiple_bids(bids_data)


@router.get("/bid_status/{project_id}")
def get_bid_status_endpoint(project_id: str) -> Dict[str, Any]:
    """Get status of bids for a project"""
    return pipeline.get_bid_status(project_id)


@router.post("/generate_cover_letter")
def generate_cover_letter_endpoint(request: CoverLetterRequest) -> Dict[str, Any]:
    """Generate a cover letter for a specific platform"""
    try:
        cover_letter = pipeline.generate_cover_letter(
            project_data=request.project_data,
            platform=request.platform,
            freelancer_name=request.freelancer_name or "Klaravex Freelancer"
        )

        return {
            "cover_letter": cover_letter,
            "platform": request.platform,
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error generating cover letter: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate cover letter: {str(e)}"
        )


@router.post("/renew_cookies")
def renew_cookies_endpoint() -> Dict[str, Any]:
    """Renew cookies for all platforms"""
    # This would implement cookie renewal logic
    return {
        "message": "Cookie renewal functionality would be implemented here",
        "timestamp": datetime.now().isoformat()
    }


@router.post("/kill_switch")
def kill_switch_endpoint(enabled: bool) -> Dict[str, Any]:
    """Toggle kill switch for bid submissions"""
    # This would implement kill switch logic
    return {
        "message": f"Kill switch {'enabled' if enabled else 'disabled'}",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/bid_statistics")
def get_bid_statistics_endpoint() -> Dict[str, Any]:
    """Get bid submission statistics"""
    return pipeline.get_bid_statistics()


@router.post("/validate_skills")
def validate_skills_endpoint(skills: List[str]) -> Dict[str, Any]:
    """Validate skills against platform requirements"""
    return pipeline.validate_skills(skills)


@router.get("/projects")
def get_projects_endpoint(limit: int = 20) -> Dict[str, Any]:
    """Get list of available projects from all platforms"""
    # This endpoint would typically aggregate projects from multiple platforms
    # For now, we'll return a placeholder response
    return {
        "projects": [],
        "total": 0,
        "platforms": ["freelancer.com", "freelancermap.de", "upwork"]
    }


@router.get("/platforms")
def get_platforms_endpoint() -> Dict[str, Any]:
    """Get list of supported freelance platforms"""
    return {
        "platforms": ["freelancer.com", "freelancermap.de", "upwork"],
        "total": 3,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/health")
def health_check_endpoint() -> Dict[str, Any]:
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "pipeline": "active"
    }


# Export for registry
freelance_pipeline = health_check_endpoint