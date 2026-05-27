"""
triage.py — POST /triage route
Returns a streaming NDJSON response; each line is one agent step.
"""
import json
import asyncio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.orchestrator import run_triage

router = APIRouter()


class TriageRequest(BaseModel):
    project_id: str          # e.g. "mygroup/myrepo" or numeric ID
    branch: str = "main"


async def ndjson_stream(project_id: str, branch: str):
    """Wrap the orchestrator async generator into newline-delimited JSON lines."""
    async for step in run_triage(project_id, branch):
        yield json.dumps(step) + "\n"
        await asyncio.sleep(0)  # Yield control to event loop so flush propagates


@router.post("/triage")
async def triage(req: TriageRequest):
    return StreamingResponse(
        ndjson_stream(req.project_id, req.branch),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
