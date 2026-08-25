"""
Freelance Bid Pipeline API Handler

This module provides the API endpoints for managing the freelance bid pipeline,
including project management, bid creation, and submission workflows.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional
from pydantic import BaseModel
import structlog

from klara.agents.models.freelance_project import FreelanceProject
from klara.agents.models.platform_bid import PlatformBid
from klara.rarv.runtime import get_settings
from klara.rarv.runtime import AgentContext
from klara.rarv.runtime import db_context
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

# Initialize the router
router = APIRouter(prefix="/freelance", tags=["freelance"])

class ProjectResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    skills_required: List[str]
    category: Optional[str]
    budget_min: Optional[float]
    budget_max: Optional[float]
    budget_type: Optional[str]
    budget_currency: str
    platform: str
    client_name: Optional[str]
    client_location: Optional[str]
    posted_at: Optional[str]
    deadline_at: Optional[str]
    status: str
    fit_score: Optional[int]
    fit_rationale: Optional[str]

class BidResponse(BaseModel):
    id: str
    project_id: str
    platform: str
    cover_letter: Optional[str]
    bid_amount: Optional[float]
    bid_currency: str
    delivery_days: Optional[int]
    status: str
    created_at: str
    updated_at: str

class BidSubmissionRequest(BaseModel):
    project_id: str
    platform: str
    cover_letter: str
    bid_amount: float
    bid_currency: str = "EUR"
    delivery_days: Optional[int]

class BidSubmissionResponse(BaseModel):
    success: bool
    message: str
    bid_id: Optional[str] = None

class ProjectListRequest(BaseModel):
    status: Optional[str] = None
    platform: Optional[str] = None
    page: int = 1
    limit: int = 20

@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    request: ProjectListRequest = Depends(),
    settings = Depends(get_settings)
):
    """
    List freelance projects with optional filtering and pagination.

    Returns projects sorted by posted_at descending (newest first).
    """
    try:
        async with db_context() as db:
            # Build query
            query = db.query(FreelanceProject)

            if request.status:
                query = query.filter(FreelanceProject.status == request.status)
            if request.platform:
                query = query.filter(FreelanceProject.platform == request.platform)

            # Apply pagination
            projects = query.order_by(FreelanceProject.posted_at.desc()) \
                           .offset((request.page - 1) * request.limit) \
                           .limit(request.limit).all()

            return [
                ProjectResponse(
                    id=project.id,
                    title=project.title,
                    description=project.description,
                    skills_required=project.skills_required.split(",") if project.skills_required else [],
                    category=project.category,
                    budget_min=project.budget_min,
                    budget_max=project.budget_max,
                    budget_type=project.budget_type,
                    budget_currency=project.budget_currency,
                    platform=project.platform,
                    client_name=project.client_name,
                    client_location=project.client_location,
                    posted_at=project.posted_at.isoformat() if project.posted_at else None,
                    deadline_at=project.deadline_at.isoformat() if project.deadline_at else None,
                    status=project.status,
                    fit_score=project.fit_score,
                    fit_rationale=project.fit_rationale
                ) for project in projects
            ]
    except Exception as e:
        logger.error("Error listing projects", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve projects")

@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, settings = Depends(get_settings)):
    """
    Get a specific freelance project by ID.
    """
    try:
        async with db_context() as db:
            project = db.query(FreelanceProject).filter(FreelanceProject.id == project_id).first()
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")

            return ProjectResponse(
                id=project.id,
                title=project.title,
                description=project.description,
                skills_required=project.skills_required.split(",") if project.skills_required else [],
                category=project.category,
                budget_min=project.budget_min,
                budget_max=project.budget_max,
                budget_type=project.budget_type,
                budget_currency=project.budget_currency,
                platform=project.platform,
                client_name=project.client_name,
                client_location=project.client_location,
                posted_at=project.posted_at.isoformat() if project.posted_at else None,
                deadline_at=project.deadline_at.isoformat() if project.deadline_at else None,
                status=project.status,
                fit_score=project.fit_score,
                fit_rationale=project.fit_rationale
            )
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error("Error retrieving project", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve project")

@router.get("/bids", response_model=List[BidResponse])
async def list_bids(
    status: Optional[str] = None,
    platform: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    settings = Depends(get_settings)
):
    """
    List platform bids with optional filtering and pagination.

    Returns bids sorted by created_at descending (newest first).
    """
    try:
        async with db_context() as db:
            # Build query
            query = db.query(PlatformBid)

            if status:
                query = query.filter(PlatformBid.status == status)
            if platform:
                query = query.filter(PlatformBid.platform == platform)

            # Apply pagination
            bids = query.order_by(PlatformBid.created_at.desc()) \
                       .offset((page - 1) * limit) \
                       .limit(limit).all()

            return [
                BidResponse(
                    id=bid.id,
                    project_id=bid.project_id,
                    platform=bid.platform,
                    cover_letter=bid.cover_letter,
                    bid_amount=bid.bid_amount,
                    bid_currency=bid.bid_currency,
                    delivery_days=bid.delivery_days,
                    status=bid.status,
                    created_at=bid.created_at.isoformat() if bid.created_at else None,
                    updated_at=bid.updated_at.isoformat() if bid.updated_at else None
                ) for bid in bids
            ]
    except Exception as e:
        logger.error("Error listing bids", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve bids")

@router.post("/bids/submit", response_model=BidSubmissionResponse)
async def submit_bid(
    request: BidSubmissionRequest,
    settings = Depends(get_settings)
):
    """
    Submit a bid for a specific project on a platform.

    This endpoint creates a new PlatformBid record in queued status.
    The actual submission is handled by the bid submission task runner.
    """
    try:
        async with db_context() as db:
            # Check if the project exists
            project = db.query(FreelanceProject).filter(FreelanceProject.id == request.project_id).first()
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")

            # Create the bid record
            bid = PlatformBid(
                project_id=request.project_id,
                platform=request.platform,
                cover_letter=request.cover_letter,
                bid_amount=request.bid_amount,
                bid_currency=request.bid_currency,
                delivery_days=request.delivery_days,
                status="queued"
            )

            db.add(bid)
            await db.commit()
            await db.refresh(bid)

            # Update project status
            project.status = "bid_queued"
            project.bid_queued_at = db.func.now()
            await db.commit()

            logger.info(
                "Bid submitted successfully",
                project_id=request.project_id,
                platform=request.platform,
                bid_id=bid.id
            )

            return BidSubmissionResponse(
                success=True,
                message="Bid submitted successfully",
                bid_id=bid.id
            )
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error("Error submitting bid", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to submit bid")

@router.post("/projects/{project_id}/analyze", response_model=dict)
async def analyze_project(
    project_id: str,
    settings = Depends(get_settings)
):
    """
    Trigger analysis of a specific project.

    This endpoint calls the BidStrategyAgent to score and generate a bid for
    the specified project. The agent will create a PlatformBid if the fit score
    meets the minimum threshold.
    """
    try:
        from app.agents.bid_strategist import BidStrategyAgent

        async with db_context() as db:
            # Get the project
            project = db.query(FreelanceProject).filter(FreelanceProject.id == project_id).first()
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")

            # Run the bid strategy agent
            ctx = AgentContext(db=db, settings=settings)
            agent = BidStrategyAgent()

            result = await agent.run(ctx, {
                "project_id": project_id,
                "min_fit_score": getattr(settings, "freelance_min_fit_score", 55)
            })

            if result.success:
                return {
                    "success": True,
                    "message": "Project analyzed successfully",
                    "scored": result.output.get("scored"),
                    "bids_queued": result.output.get("bids_queued"),
                    "ignored": result.output.get("ignored"),
                    "errors": result.output.get("errors")
                }
            else:
                logger.error("Bid strategy analysis failed", error=result.error)
                raise HTTPException(status_code=500, detail=f"Analysis failed: {result.error}")

    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error("Error analyzing project", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to analyze project")

@router.get("/stats", response_model=dict)
async def get_pipeline_stats(settings = Depends(get_settings)):
    """
    Get statistics about the freelance pipeline.
    """
    try:
        async with db_context() as db:
            # Count projects by status
            project_counts = {}
            for status in ["new", "analyzed", "bid_queued", "bid_submitted", "won", "lost", "withdrawn", "ignored"]:
                count = db.query(FreelanceProject).filter(FreelanceProject.status == status).count()
                project_counts[status] = count

            # Count bids by status
            bid_counts = {}
            for status in ["draft", "queued", "submitted", "shortlisted", "won", "lost", "withdrawn", "submit_failed"]:
                count = db.query(PlatformBid).filter(PlatformBid.status == status).count()
                bid_counts[status] = count

            return {
                "projects": project_counts,
                "bids": bid_counts
            }
    except Exception as e:
        logger.error("Error getting pipeline stats", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve pipeline stats")

# Health check endpoint
@router.get("/health")
async def health_check():
    """
    Health check endpoint for the freelance bid pipeline.
    """
    return {"status": "healthy", "service": "freelance_bid_pipeline"}
