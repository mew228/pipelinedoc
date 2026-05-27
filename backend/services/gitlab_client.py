"""
gitlab_client.py — MCP stdio client for @gitlab-org/gitlab-mcp-server

Spawns the GitLab MCP server as an npx subprocess over stdio using the
official MCP Python SDK (pip: mcp>=1.0).

Each public method opens a fresh MCP session, calls one tool, and returns
the raw content. The session is torn down after each call — this avoids
shared state across concurrent triage requests.

Env vars required (loaded from .env via main.py):
  GITLAB_PERSONAL_ACCESS_TOKEN
  GITLAB_BASE_URL            (default: https://gitlab.com)
"""
import os
import json
import shutil
import traceback
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _server_params() -> StdioServerParameters:
    """Build StdioServerParameters for npx @gitlab-org/gitlab-mcp-server."""
    token = os.environ["GITLAB_PERSONAL_ACCESS_TOKEN"]
    base_url = os.environ.get("GITLAB_BASE_URL", "https://gitlab.com")

    npx_path = shutil.which("npx") or "npx"

    return StdioServerParameters(
        command=npx_path,
        args=["-y", "gitlab-mcp"],
        env={
            **os.environ,                          # inherit PATH etc.
            "GITLAB_PERSONAL_ACCESS_TOKEN": token,
            "GITLAB_BASE_URL": base_url,
            "GITLAB_API_URL": f"{base_url.rstrip('/')}/api/v4",
            "USE_PIPELINE": "true",                # enable pipeline tools
        },
    )


async def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
    """
    Open a stdio MCP session, call one tool, return the first text content.
    Raises RuntimeError if the tool call fails.
    """
    try:
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
    except BaseException as e:
        print(f"MCP Session Exception: {e}")
        print(traceback.format_exc())
        raise

    # MCP tool results carry a list of content blocks
    if result.isError:
        raise RuntimeError(f"MCP tool '{tool_name}' returned error: {result.content}")

    # Extract text from first content block
    if not result.content:
        return None

    block = result.content[0]
    # ContentBlock has a .text attribute for text type
    raw = getattr(block, "text", None) or str(block)

    # Try to parse as JSON; return dict if possible, else raw string
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def list_pipelines(project_id: str, status: str = "failed", per_page: int = 5) -> list[dict]:
    """Return the most recent pipelines for a project filtered by status."""
    result = await _call(
        "gitlab_list_pipelines",
        {
            "project_id": project_id,
            "status": status,
            "per_page": per_page,
            "order_by": "id",
            "sort": "desc",
        },
    )
    if isinstance(result, list):
        return result
    # Some MCP server versions wrap in {"pipelines": [...]}
    if isinstance(result, dict):
        return result.get("pipelines", result.get("data", []))
    return []


async def get_pipeline(project_id: str, pipeline_id: int) -> dict:
    """Return pipeline details."""
    result = await _call(
        "gitlab_get_pipeline",
        {"project_id": project_id, "pipeline_id": str(pipeline_id)},
    )
    return result if isinstance(result, dict) else {"raw": result}


async def list_pipeline_jobs(project_id: str, pipeline_id: int) -> list[dict]:
    """Return all jobs for a given pipeline."""
    result = await _call(
        "gitlab_list_pipeline_jobs",
        {"project_id": project_id, "pipeline_id": str(pipeline_id)},
    )
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("jobs", result.get("data", []))
    return []


async def get_job_output(project_id: str, job_id: int, tail_lines: int = 150) -> str:
    """Return the last `tail_lines` lines of a job's log."""
    raw = await _call(
        "gitlab_get_pipeline_job_output",
        {"project_id": project_id, "job_id": str(job_id)},
    )
    if not raw:
        return ""
    text = raw if isinstance(raw, str) else json.dumps(raw)
    lines = text.splitlines()
    return "\n".join(lines[-tail_lines:])


async def get_project_commits(project_id: str, ref_name: str, per_page: int = 5) -> list[dict]:
    """Return the most recent commits on a branch."""
    result = await _call(
        "gitlab_list_commits",
        {"project_id": project_id, "ref_name": ref_name, "per_page": per_page},
    )
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("commits", result.get("data", []))
    return []


async def list_merge_requests(
    project_id: str,
    state: str = "opened",
    source_branch: str | None = None,
) -> list[dict]:
    """List merge requests; optionally filter by source branch."""
    args: dict[str, Any] = {"project_id": project_id, "state": state}
    if source_branch:
        args["source_branch"] = source_branch
    result = await _call("gitlab_list_merge_requests", args)
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("merge_requests", result.get("data", []))
    return []


async def create_issue(project_id: str, title: str, description: str, labels: list[str] | None = None) -> dict:
    """Create a GitLab issue and return the created issue dict."""
    args: dict[str, Any] = {
        "project_id": project_id,
        "title": title,
        "description": description,
    }
    if labels:
        args["labels"] = ",".join(labels)
    result = await _call("gitlab_create_issue", args)
    return result if isinstance(result, dict) else {"raw": result}


async def create_note(project_id: str, noteable_type: str, noteable_id: int, body: str) -> dict:
    """
    Create a note (comment) on an issue or merge request.
    noteable_type: "issues" | "merge_requests"
    noteable_id:   issue iid or MR iid
    """
    result = await _call(
        "gitlab_create_note",
        {
            "project_id": project_id,
            "noteable_type": noteable_type,
            "noteable_id": str(noteable_id),
            "body": body,
        },
    )
    return result if isinstance(result, dict) else {"raw": result}
