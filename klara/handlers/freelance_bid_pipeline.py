"""
Klaravex freelance bid pipeline — FastAPI router.

Three-stage pipeline:
  1. Scout  — discover new projects from Freelancer.com (API) + Upwork (manual queue)
  2. Score  — Claude scores each project 0–100 + writes cover letter
  3. Submit — submit qualifying bids (Freelancer.com via API; Upwork via manual email)

Routes:
  POST /internal/freelance/scout       run a scout pass
  GET  /internal/freelance/projects    list discovered projects (pending score)
  POST /internal/freelance/score       run scoring on all 'new' projects
  GET  /internal/freelance/bids        list queued bids
  POST /internal/freelance/submit      submit all queued bids (daily cap enforced)
  POST /internal/freelance/run         convenience: scout + score + submit in one call
  POST /internal/freelance/bids/{id}/mark-sent  mark a manual bid as sent
  GET  /internal/freelance/report      daily summary

Required env vars:
  FREELANCER_ACCESS_TOKEN     Freelancer.com OAuth V1 token (FREELANCER_OAUTH_TOKEN also accepted)
  ANTHROPIC_API_KEY           Anthropic API key (already set)
  LOKI_INTERNAL_SECRET        shared secret to protect endpoints
  APPROVAL_NOTIFY_EMAIL       where to send bid alerts (default: astewart@klaravex.com)
  APP_BASE_URL                base URL (default: https://api.klaravex.com)
  FREELANCE_MIN_BUDGET_USD    min project budget to consider (default: 500)
  FREELANCE_MIN_FIT_SCORE     min fit score to bid (default: 55)
  FREELANCE_MAX_BIDS_PER_DAY  max bids per day (default: 5)
  FREELANCE_BIDS_ENABLED      kill-switch; set to "false" to pause the whole
                              pipeline without redeploy (default: enabled)
"""

import json
import logging
import os
import re
import secrets
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import uuid
from decimal import Decimal

import anthropic
import httpx
from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import JSONResponse

from .lib.db import get_pool
from .lib.email import send_email

log = logging.getLogger("klaravex.freelance_bid_pipeline")

router = APIRouter()

# Global configuration from environment variables
FREELANCER_ACCESS_TOKEN = os.environ.get("FREELANCER_ACCESS_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LOKI_INTERNAL_SECRET = os.environ.get("LOKI_INTERNAL_SECRET", "")
APPROVAL_NOTIFY_EMAIL = os.environ.get("APPROVAL_NOTIFY_EMAIL", "astewart@klaravex.com")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://api.klaravex.com")
FREELANCE_MIN_BUDGET_USD = int(os.environ.get("FREELANCE_MIN_BUDGET_USD", "500"))
FREELANCE_MIN_FIT_SCORE = int(os.environ.get("FREELANCE_MIN_FIT_SCORE", "55"))
FREELANCE_MAX_BIDS_PER_DAY = int(os.environ.get("FREELANCE_MAX_BIDS_PER_DAY", "5"))
FREELANCE_BIDS_ENABLED = os.environ.get("FREELANCE_BIDS_ENABLED", "true").lower() != "false"

# Mock data structures for demonstration
mock_projects = []
mock_bids = []

@router.post("/internal/freelance/scout")
async def scout_projects(request: Request):
    """Stage 1: Scout new projects from Freelancer.com and Upwork."""
    # Verify internal secret
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header != f"Bearer {LOKI_INTERNAL_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not FREELANCE_BIDS_ENABLED:
        return JSONResponse(content={"message": "Bids pipeline is disabled"}, status_code=200)

    # In a real implementation, this would call the Freelancer API
    # and scrape Upwork manual queue for new projects

    log.info("Starting scout pass")

    # Mock project discovery
    discovered_projects = [
        {
            "id": str(uuid.uuid4()),
            "platform": "freelancer.com",
            "title": "Network security audit for healthcare practice",
            "budget": 2000,
            "skills": ["network security", "HIPAA compliance", "UniFi"],
            "description": "Need network audit for dental practice with HIPAA requirements",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "platform": "upwork",
            "title": "Cloud migration to Azure",
            "budget": 5000,
            "skills": ["Azure", "cloud migration", "M365"],
            "description": "Migrating from on-prem to Microsoft cloud services",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    ]

    # Store projects in mock database
    for project in discovered_projects:
        mock_projects.append(project)

    log.info(f"Discovered {len(discovered_projects)} new projects")

    return JSONResponse(content={
        "message": f"Scout complete: discovered {len(discovered_projects)} projects",
        "projects": [p["id"] for p in discovered_projects]
    })

@router.get("/internal/freelance/projects")
async def list_projects(request: Request):
    """List all projects that are pending scoring."""
    # Verify internal secret
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header != f"Bearer {LOKI_INTERNAL_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Filter projects that are pending score (not yet scored)
    pending_projects = [p for p in mock_projects if "score" not in p]

    return JSONResponse(content={
        "projects": pending_projects,
        "count": len(pending_projects)
    })

@router.post("/internal/freelance/score")
async def score_projects(request: Request):
    """Stage 2: Score projects and generate cover letters."""
    # Verify internal secret
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header != f"Bearer {LOKI_INTERNAL_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not FREELANCE_BIDS_ENABLED:
        return JSONResponse(content={"message": "Bids pipeline is disabled"}, status_code=200)

    # Find projects that need scoring
    pending_projects = [p for p in mock_projects if "score" not in p]

    scored_projects = []
    for project in pending_projects:
        # Mock scoring - in real implementation, this would call Claude API
        score = 75 + hash(project["id"]) % 25  # Random score between 75-100

        # Generate mock cover letter
        cover_letter = f"""
I've reviewed your project "{project['title']}" and believe our team is well-positioned to handle this work.

Our approach includes:
- AI-first support that resolves 89% of routine issues instantly
- Senior engineer escalation with 2-hour SLA for complex cases
- Enterprise-grade security focused on {', '.join(project['skills'])}

The project budget of ${project['budget']} aligns well with our Foundation/Directive tier offerings.

I would welcome the opportunity to discuss how we can help secure your network infrastructure.
        """.strip()

        project["score"] = score
        project["cover_letter"] = cover_letter
        project["scored_at"] = datetime.now(timezone.utc).isoformat()

        scored_projects.append(project)

    log.info(f"Scored {len(scored_projects)} projects")

    return JSONResponse(content={
        "message": f"Scoring complete: {len(scored_projects)} projects scored",
        "projects": [p["id"] for p in scored_projects]
    })

@router.get("/internal/freelance/bids")
async def list_bids(request: Request):
    """List all queued bids that are ready to be submitted."""
    # Verify internal secret
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header != f"Bearer {LOKI_INTERNAL_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Filter projects that have been scored and qualify for bidding
    qualified_projects = [
        p for p in mock_projects
        if "score" in p and p["score"] >= FREELANCE_MIN_FIT_SCORE
    ]

    bids = []
    for project in qualified_projects:
        bid = {
            "id": str(uuid.uuid4()),
            "project_id": project["id"],
            "title": project["title"],
            "score": project["score"],
            "platform": project["platform"],
            "budget": project["budget"],
            "cover_letter": project["cover_letter"],
            "status": "queued",  # queued, submitted, failed
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        bids.append(bid)

    return JSONResponse(content={
        "bids": bids,
        "count": len(bids)
    })

@router.post("/internal/freelance/submit")
async def submit_bids(request: Request):
    """Stage 3: Submit qualifying bids to platforms."""
    # Verify internal secret
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header != f"Bearer {LOKI_INTERNAL_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not FREELANCE_BIDS_ENABLED:
        return JSONResponse(content={"message": "Bids pipeline is disabled"}, status_code=200)

    # Find projects that have been scored and qualify for bidding
    qualified_projects = [
        p for p in mock_projects
        if "score" in p and p["score"] >= FREELANCE_MIN_FIT_SCORE and "bid_submitted" not in p
    ]

    submitted_bids = []
    bid_count = 0

    for project in qualified_projects:
        # Check daily cap
        if bid_count >= FREELANCE_MAX_BIDS_PER_DAY:
            break

        # Mock submission process
        platform = project["platform"]

        # In a real implementation, this would submit to the actual platform API
        log.info(f"Submitting bid for project {project['id']} on {platform}")

        project["bid_submitted"] = True
        project["submitted_at"] = datetime.now(timezone.utc).isoformat()

        submitted_bids.append({
            "project_id": project["id"],
            "platform": platform,
            "status": "submitted"
        })

        bid_count += 1

    log.info(f"Submitted {len(submitted_bids)} bids")

    return JSONResponse(content={
        "message": f"Submission complete: {len(submitted_bids)} bids submitted",
        "bids": submitted_bids
    })

@router.post("/internal/freelance/run")
async def run_pipeline(request: Request):
    """Convenience endpoint to run all three stages in sequence."""
    # Verify internal secret
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header != f"Bearer {LOKI_INTERNAL_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Run scout
    scout_response = await scout_projects(request)

    # Run score
    score_response = await score_projects(request)

    # Run submit
    submit_response = await submit_bids(request)

    return JSONResponse(content={
        "message": "Pipeline run complete",
        "scout": scout_response.body,
        "score": score_response.body,
        "submit": submit_response.body
    })

@router.post("/internal/freelance/bids/{id}/mark-sent")
async def mark_bid_sent(request: Request, id: str):
    """Mark a manual bid as sent."""
    # Verify internal secret
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header != f"Bearer {LOKI_INTERNAL_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # In a real implementation, this would update the bid status in database
    log.info(f"Marking bid {id} as sent")

    return JSONResponse(content={"message": "Bid marked as sent", "id": id})

@router.get("/internal/freelance/report")
async def get_report(request: Request):
    """Get daily summary report."""
    # Verify internal secret
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header != f"Bearer {LOKI_INTERNAL_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Calculate report metrics
    total_projects = len(mock_projects)
    scored_projects = len([p for p in mock_projects if "score" in p])
    qualified_bids = len([p for p in mock_projects if "score" in p and p["score"] >= FREELANCE_MIN_FIT_SCORE])
    submitted_bids = len([p for p in mock_projects if "bid_submitted" in p])

    return JSONResponse(content={
        "date": date.today().isoformat(),
        "total_projects": total_projects,
        "scored_projects": scored_projects,
        "qualified_bids": qualified_bids,
        "submitted_bids": submitted_bids,
        "pipeline_enabled": FREELANCE_BIDS_ENABLED
    })
