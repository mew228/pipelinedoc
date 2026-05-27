"""
orchestrator.py — 6-step triage async generator

Each step yields a dict:
  {"step": str, "content": str, "status": "running" | "done" | "error"}

The FastAPI route serialises each dict to a JSON line (NDJSON).
"""
from __future__ import annotations

from typing import AsyncGenerator

from services import gitlab_client as gl
from services.gemini_client import analyze_failure


StepDict = dict[str, str]


def _step(step: str, content: str, status: str = "done") -> StepDict:
    return {"step": step, "content": content, "status": status}


async def run_triage(project_id: str, branch: str) -> AsyncGenerator[StepDict, None]:
    """
    Full 6-step triage pipeline for a GitLab project.
    Yields one NDJSON-ready dict per agent step.
    """

    pipeline_obj = None

    # ── Step 1: Detect latest failed pipeline ────────────────────────────────
    yield _step("detect_pipeline", f"Scanning for failed pipelines on '{branch}'...", "running")
    try:
        pipelines = await gl.list_pipelines(project_id, status="failed")
        if not pipelines:
            yield _step("detect_pipeline", "No failed pipelines found. All green! 🟢", "done")
            return
        pipeline = pipelines[0]
        pipeline_id = pipeline.get("id") or pipeline.get("pipeline_id")
        yield _step(
            "detect_pipeline",
            f"Found failed pipeline #{pipeline_id} "
            f"(created: {pipeline.get('created_at', 'unknown')})",
            "done",
        )
    except Exception as exc:
        yield _step("detect_pipeline", f"ERROR: {exc}", "error")
        return

    # ── Step 2: List failed jobs ──────────────────────────────────────────────
    yield _step("list_jobs", f"Fetching jobs for pipeline #{pipeline_id}...", "running")
    try:
        jobs = await gl.list_pipeline_jobs(project_id, pipeline_id)
        failed_statuses = {"failed", "cancelled", "error", "canceled"}
        failed_jobs = [j for j in jobs if j.get("status") in failed_statuses]
        
        job_id = None
        job_name = "pipeline-failure"
        
        if not jobs:
            pipeline_obj = await gl.get_pipeline(project_id, pipeline_id)
            yaml_errors = pipeline_obj.get("yaml_errors")
            msg = f"No jobs found. Pipeline status: {pipeline_obj.get('status')}"
            if yaml_errors:
                msg += f" (YAML error: {yaml_errors})"
            yield _step("list_jobs", msg, "done")
        elif not failed_jobs:
            yield _step("list_jobs", "No individual failed jobs found.", "done")
            return
        else:
            job_names = ", ".join(j.get("name", str(j.get("id"))) for j in failed_jobs)
            yield _step("list_jobs", f"Failed jobs: {job_names}", "done")
            # Triage the first failed job
            target_job = failed_jobs[0]
            job_id = target_job.get("id")
            job_name = target_job.get("name", str(job_id))
    except Exception as exc:
        yield _step("list_jobs", f"ERROR: {exc}", "error")
        return

    # ── Step 3: Read job failure logs (last 150 lines) ────────────────────────
    if job_id:
        yield _step("read_logs", f"Reading logs for job '{job_name}' (id: {job_id})...", "running")
        try:
            log_tail = await gl.get_job_output(project_id, job_id, tail_lines=150)
            if not log_tail:
                log_tail = "(no log output available)"
            preview = log_tail.splitlines()[-5:]
            yield _step(
                "read_logs",
                f"Captured {len(log_tail.splitlines())} log lines. Last lines:\n" + "\n".join(preview),
                "done",
            )
        except Exception as exc:
            yield _step("read_logs", f"ERROR: {exc}", "error")
            return
    else:
        yield _step("read_logs", "Skipping job logs (no failed job). Using pipeline failure context.", "done")
        yaml_errors = pipeline_obj.get("yaml_errors") if pipeline_obj else None
        if yaml_errors:
            log_tail = f"YAML Error:\n{yaml_errors}"
        else:
            log_tail = f"Pipeline {pipeline_id} failed without executing any individual jobs. Check CI configuration."

    # ── Step 4: Trace triggering commit + MR author ───────────────────────────
    yield _step("trace_commit", f"Tracing triggering commit on branch '{branch}'...", "running")
    try:
        commits = await gl.get_project_commits(project_id, ref_name=branch, per_page=3)
        commit_sha = "unknown"
        commit_author = "unknown"
        mr_iid: int | None = None
        mr_title = ""

        if commits:
            latest = commits[0]
            commit_sha = latest.get("id", latest.get("short_id", "unknown"))
            commit_author = latest.get("author_name", latest.get("committer_name", "unknown"))

        # Try to find associated MR by source branch
        mrs = await gl.list_merge_requests(project_id, state="opened", source_branch=branch)
        if mrs:
            mr = mrs[0]
            mr_iid = mr.get("iid")
            mr_title = mr.get("title", "")

        mr_info = f"MR !{mr_iid} '{mr_title}'" if mr_iid else "no open MR found"
        yield _step(
            "trace_commit",
            f"Commit {commit_sha[:8]} by {commit_author}. Associated: {mr_info}",
            "done",
        )
    except Exception as exc:
        yield _step("trace_commit", f"ERROR: {exc}", "error")
        # Continue with partial data
        commit_sha = "unknown"
        commit_author = "unknown"
        mr_iid = None

    # ── Step 5: Gemini root cause analysis ───────────────────────────────────
    yield _step("gemini_analysis", "Sending logs to Gemini for root cause analysis...", "running")
    try:
        analysis = await analyze_failure(
            job_log=log_tail,
            commit_sha=commit_sha,
            commit_author=commit_author,
            branch=branch,
            project_id=project_id,
            pipeline_id=pipeline_id,
            job_name=job_name,
        )
        severity = analysis.get("severity", "unknown").upper()
        root_cause = analysis.get("root_cause", "unknown")
        fix = analysis.get("fix_suggestion", "")
        category = analysis.get("failure_category", "unknown")
        yield _step(
            "gemini_analysis",
            f"[{severity}] {category.upper()}: {root_cause}\nFix: {fix}",
            "done",
        )
    except Exception as exc:
        yield _step("gemini_analysis", f"ERROR: {exc}", "error")
        return

    # ── Step 6a: Create GitLab issue ─────────────────────────────────────────
    yield _step("create_issue", "Creating GitLab issue with diagnosis...", "running")
    try:
        issue_title = analysis.get("issue_title", f"Pipeline #{pipeline_id} failed: {job_name}")
        issue_body = analysis.get("issue_body", f"## Root Cause\n{root_cause}\n\n## Fix\n{fix}")
        issue = await gl.create_issue(
            project_id,
            title=issue_title,
            description=issue_body,
            labels=["pipeline-failure", f"severity::{analysis.get('severity', 'medium')}"],
        )
        issue_url = issue.get("web_url", issue.get("url", "created"))
        yield _step("create_issue", f"Issue created: {issue_url}", "done")
        issue_iid = issue.get("iid")
    except Exception as exc:
        yield _step("create_issue", f"ERROR: {exc}", "error")
        issue_iid = None

    # ── Step 6b: Comment on MR ───────────────────────────────────────────────
    if mr_iid:
        yield _step("comment_mr", f"Commenting on MR !{mr_iid}...", "running")
        try:
            note_body = (
                f"## 🚨 Pipeline Triage Report — Pipeline #{pipeline_id}\n\n"
                f"**Failed Job:** `{job_name}`  \n"
                f"**Severity:** `{analysis.get('severity', 'unknown').upper()}`  \n"
                f"**Category:** `{analysis.get('failure_category', 'unknown')}`  \n\n"
                f"### Root Cause\n{root_cause}\n\n"
                f"### Affected File/Component\n`{analysis.get('affected_file', 'unknown')}`\n\n"
                f"### Fix Suggestion\n{analysis.get('fix_suggestion', '')}\n\n"
                f"---\n*Generated by [pipelinedoc](https://github.com) triage agent*"
            )
            await gl.create_note(project_id, "merge_requests", mr_iid, note_body)
            yield _step("comment_mr", f"Comment posted on MR !{mr_iid}", "done")
        except Exception as exc:
            yield _step("comment_mr", f"ERROR: {exc}", "error")
    else:
        yield _step("comment_mr", "No open MR found — skipping MR comment.", "done")

    # ── Final summary ────────────────────────────────────────────────────────
    yield _step(
        "triage_complete",
        f"Triage complete. Severity: {analysis.get('severity', '?').upper()} | "
        f"Issue: {'created' if issue_iid else 'failed'} | "
        f"MR comment: {'posted' if mr_iid else 'skipped'}",
        "done",
    )
