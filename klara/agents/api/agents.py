"""
app/api/agents.py
──────────────────
Agent introspection endpoints.

GET /api/v1/agents/          — list all registered agents with metadata
GET /api/v1/agents/{name}    — get a single agent's metadata

These are read-only, informational endpoints used by the admin dashboard.
They do NOT execute agents — that happens through the pipeline endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.agents.registry import registry
from app.core.security import verify_api_key

router = APIRouter()


@router.get("/", dependencies=[Depends(verify_api_key)])
async def list_agents():
    """Return metadata for all registered agents."""
    return {
        "count": len(registry),
        "agents": registry.list_meta(),
    }


@router.get("/{agent_name}", dependencies=[Depends(verify_api_key)])
async def get_agent(agent_name: str):
    """Return metadata for a single agent by name."""
    try:
        agent = registry.get(agent_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")
    return agent.meta()
