"""
Freelance Bid Pipeline Router
Handles bid submission across multiple freelance platforms with enhanced scoring and management.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
import httpx

# Import the actual classes from freelance_sites module
from growth.adapters.freelance_sites import (
    FreelancerAdapter,
    FreelancermapAdapter,
    ManualBidAdapter
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize routers
router = APIRouter(prefix="/freelance", tags=["freelance"])

# Platform configuration
PLATFORMS = {
    "freelancer": FreelancerAdapter,
    "freelancermap_de": FreelancermapAdapter,
    "manual": ManualBidAdapter
}

class BidSubmission(BaseModel):
    project_id: str
    platform: str
    bid_amount: float
    cover_letter: str

class ProjectScore(BaseModel):
    project_id: str
    score: float
    reason: str

class BidResult(BaseModel):
    project_id: str
    platform: str
    success: bool
    message: str
    bid_amount: Optional[float] = None

# Global variables for tracking
BID_COUNTS = {}
KILL_SWITCH_ACTIVE = False

def get_platform(platform_name: str) -> FreelancerSite:
    """Get platform instance by name"""
    if platform_name not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform_name}")
    return PLATFORMS[platform_name]()

def calculate_project_score(project_data: dict) -> Tuple[float, str]:
    """
    Calculate project score using Claude LLM
    Returns (score, reason)
    """
    try:
        # This is a simplified version - in reality this would call Claude API
        # For now, we'll use a basic scoring logic

        # Extract key features from project data
        title = project_data.get('title', '').lower()
        description = project_data.get('description', '').lower()
        budget = project_data.get('budget', 0)
        duration = project_data.get('duration', 'medium')

        # Basic scoring logic (this would be replaced with Claude LLM in production)
        score = 0.5  # Base score

        # Adjust based on features
        if 'python' in title or 'python' in description:
            score += 0.1
        if 'react' in title or 'react' in description:
            score += 0.1
        if budget > 1000:
            score += 0.2
        if duration == 'short':
            score -= 0.1

        # Ensure score is between 0 and 1
        score = max(0, min(1, score))

        reason = f"Score based on: title keywords (python/react), budget (${budget}), duration ({duration})"

        return score, reason

    except Exception as e:
        logger.error(f"Error calculating project score: {e}")
        return 0.0, "Error calculating score"

def validate_bid_amount(amount: float, platform: str) -> bool:
    """Validate bid amount against platform requirements"""
    # Platform-specific validation
    platform_min_bids = {
        "freelancer": 5,
        "freelancermap_de": 10,
        "upwork": 10,
        "guru": 5,
        "peopleperhour": 5
    }

    min_bid = platform_min_bids.get(platform, 5)
    return amount >= min_bid

async def get_project_data(project_id: str) -> dict:
    """Fetch project data from database or API"""
    # This would typically fetch from a database or external API
    # For now returning mock data
    return {
        "id": project_id,
        "title": "Web development project",
        "description": "Need a Python developer to build a web application",
        "budget": 1500,
        "duration": "medium",
        "skills": ["python", "django", "postgresql"],
        "posted_date": datetime.now().isoformat()
    }

async def submit_bid_to_platform(
    project_id: str,
    platform_name: str,
    bid_amount: float,
    cover_letter: str
) -> BidResult:
    """Submit bid to a specific platform"""
    try:
        # Get platform instance
        platform = get_platform(platform_name)

        # Validate bid amount
        if not validate_bid_amount(bid_amount, platform_name):
            return BidResult(
                project_id=project_id,
                platform=platform_name,
                success=False,
                message=f"Bid amount must be at least {platform_name} minimum"
            )

        # Check kill switch
        if KILL_SWITCH_ACTIVE:
            return BidResult(
                project_id=project_id,
                platform=platform_name,
                success=False,
                message="Kill switch is active - bids not submitted"
            )

        # Get project data
        project_data = await get_project_data(project_id)

        # Submit bid to platform
        result = await platform.submit_bid(
            project_data=project_data,
            bid_amount=bid_amount,
            cover_letter=cover_letter
        )

        return BidResult(
            project_id=project_id,
            platform=platform_name,
            success=result.get('success', False),
            message=result.get('message', ''),
            bid_amount=bid_amount
        )

    except Exception as e:
        logger.error(f"Error submitting bid to {platform_name}: {e}")
        return BidResult(
            project_id=project_id,
            platform=platform_name,
            success=False,
            message=f"Error submitting bid: {str(e)}"
        )

async def execute_bid_pipeline(
    project_id: str,
    bid_amount: float,
    cover_letter: str,
    platforms: List[str] = None
) -> List[BidResult]:
    """Execute full bid pipeline across multiple platforms"""
    if platforms is None:
        platforms = list(PLATFORMS.keys())

    # Check daily bid cap
    today = datetime.now().date()
    if today not in BID_COUNTS:
        BID_COUNTS[today] = 0

    if BID_COUNTS[today] >= 100:  # Daily cap of 100 bids
        logger.warning("Daily bid cap reached")
        return []

    results = []

    for platform_name in platforms:
        try:
            result = await submit_bid_to_platform(
                project_id=project_id,
                platform_name=platform_name,
                bid_amount=bid_amount,
                cover_letter=cover_letter
            )

            # Update bid count if successful
            if result.success:
                BID_COUNTS[today] += 1

            results.append(result)

        except Exception as e:
            logger.error(f"Error processing platform {platform_name}: {e}")
            results.append(BidResult(
                project_id=project_id,
                platform=platform_name,
                success=False,
                message=f"Platform error: {str(e)}"
            ))

    return results

@router.post("/score_project")
async def score_project(project_data: dict) -> ProjectScore:
    """Score a project based on various factors"""
    try:
        score, reason = calculate_project_score(project_data)
        return ProjectScore(
            project_id=project_data.get('id', 'unknown'),
            score=score,
            reason=reason
        )
    except Exception as e:
        logger.error(f"Error scoring project: {e}")
        raise HTTPException(status_code=500, detail="Failed to score project")

@router.post("/submit_bid")
async def submit_bid(
    bid_data: BidSubmission,
    background_tasks: BackgroundTasks
) -> List[BidResult]:
    """Submit a bid to one or more platforms"""
    try:
        # Validate bid amount
        if bid_data.bid_amount <= 0:
            raise HTTPException(status_code=400, detail="Bid amount must be positive")

        # Execute bid pipeline
        results = await execute_bid_pipeline(
            project_id=bid_data.project_id,
            bid_amount=bid_data.bid_amount,
            cover_letter=bid_data.cover_letter,
            platforms=[bid_data.platform] if bid_data.platform else None
        )

        return results

    except Exception as e:
        logger.error(f"Error submitting bid: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit bid")

@router.post("/submit_multiple_bids")
async def submit_multiple_bids(
    bids: List[BidSubmission],
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """Submit multiple bids in parallel"""
    try:
        tasks = []
        for bid in bids:
            task = execute_bid_pipeline(
                project_id=bid.project_id,
                bid_amount=bid.bid_amount,
                cover_letter=bid.cover_letter,
                platforms=[bid.platform] if bid.platform else None
            )
            tasks.append(task)

        # Run all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results and handle exceptions
        flattened_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error in bid submission: {result}")
                flattened_results.append(BidResult(
                    project_id="unknown",
                    platform="unknown",
                    success=False,
                    message=str(result)
                ))
            else:
                flattened_results.extend(result)

        return {
            "total_submitted": len(flattened_results),
            "results": flattened_results
        }

    except Exception as e:
        logger.error(f"Error submitting multiple bids: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit multiple bids")

@router.get("/bid_status/{project_id}")
async def get_bid_status(project_id: str) -> Dict[str, Any]:
    """Get status of bids for a specific project"""
    try:
        # This would typically query the database for bid status
        return {
            "project_id": project_id,
            "status": "completed",
            "bids_submitted": len(PLATFORMS),
            "successful_bids": 0,
            "failed_bids": 0
        }
    except Exception as e:
        logger.error(f"Error getting bid status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get bid status")

@router.post("/renew_cookies")
async def renew_cookies() -> Dict[str, Any]:
    """Renew cookies for all platforms"""
    try:
        results = {}
        for platform_name, platform_class in PLATFORMS.items():
            try:
                platform = platform_class()
                success = await platform.renew_cookies()
                results[platform_name] = success
            except Exception as e:
                logger.error(f"Error renewing cookies for {platform_name}: {e}")
                results[platform_name] = False

        return {
            "renewed": results,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error renewing cookies: {e}")
        raise HTTPException(status_code=500, detail="Failed to renew cookies")

@router.post("/kill_switch")
async def toggle_kill_switch(active: bool) -> Dict[str, Any]:
    """Toggle kill switch for bid submissions"""
    global KILL_SWITCH_ACTIVE
    KILL_SWITCH_ACTIVE = active
    return {
        "kill_switch_active": KILL_SWITCH_ACTIVE,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/bid_statistics")
async def get_bid_statistics() -> Dict[str, Any]:
    """Get bid submission statistics"""
    today = datetime.now().date()
    total_today = BID_COUNTS.get(today, 0)

    return {
        "daily_bids": total_today,
        "total_platforms": len(PLATFORMS),
        "platforms": list(PLATFORMS.keys()),
        "kill_switch_active": KILL_SWITCH_ACTIVE
    }

@router.post("/validate_skills")
async def validate_skills(skills: List[str]) -> Dict[str, Any]:
    """Validate that skills match platform requirements"""
    try:
        # This would typically check against platform skill requirements
        valid_skills = []
        invalid_skills = []

        for skill in skills:
            # In a real implementation, this would check against platform skill databases
            if len(skill) > 2:  # Basic validation - skills should be at least 3 chars
                valid_skills.append(skill)
            else:
                invalid_skills.append(skill)

        return {
            "valid_skills": valid_skills,
            "invalid_skills": invalid_skills,
            "total_valid": len(valid_skills),
            "total_invalid": len(invalid_skills)
        }
    except Exception as e:
        logger.error(f"Error validating skills: {e}")
        raise HTTPException(status_code=500, detail="Failed to validate skills")

@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "platforms": list(PLATFORMS.keys())
    }

# Additional utility functions for internal use
def get_platform_skills(platform_name: str) -> List[str]:
    """Get required skills for a platform"""
    # This would be implemented based on platform requirements
    return ["python", "javascript", "html", "css"] if platform_name in PLATFORMS else []

async def process_project_queue() -> None:
    """Process projects from a queue (background task)"""
    try:
        # This would typically pull projects from a queue/database
        logger.info("Processing project queue")
        # Implementation would go here
    except Exception as e:
        logger.error(f"Error processing project queue: {e}")