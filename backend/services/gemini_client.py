"""
gemini_client.py — Root cause analysis via Gemini

Sends job failure logs + commit context to Gemini and requests a
structured JSON root-cause analysis.
"""
import os
import json
import google.generativeai as genai

_MODEL = "gemini-flash-latest"

# Configure once at module import time
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))


_SYSTEM_PROMPT = """You are an expert DevOps engineer specializing in CI/CD pipeline failures.
You will be given:
1. A GitLab CI/CD job failure log (last 150 lines)
2. The commit SHA and author that triggered the pipeline
3. The branch name

Analyze the failure and respond with ONLY a valid JSON object matching this schema exactly:
{
  "root_cause": "<one-sentence description of the failure root cause>",
  "affected_file": "<most likely file or component causing the failure, or 'unknown'>",
  "fix_suggestion": "<concrete, actionable fix suggestion in 1-3 sentences>",
  "severity": "<one of: critical | high | medium | low>",
  "failure_category": "<one of: test_failure | build_error | lint_error | dependency_error | infrastructure | timeout | permission | unknown>",
  "issue_title": "<a concise GitLab issue title, max 80 chars>",
  "issue_body": "<full markdown body for the GitLab issue, with ## sections for Root Cause, Logs, Fix Suggestion>"
}

Be precise. Do not include any text outside the JSON object."""


async def analyze_failure(
    job_log: str,
    commit_sha: str,
    commit_author: str,
    branch: str,
    project_id: str,
    pipeline_id: int,
    job_name: str,
) -> dict:
    """
    Send failure context to Gemini and return a parsed analysis dict.
    Raises RuntimeError if Gemini fails or returns invalid JSON.
    """
    user_message = f"""
**Project:** {project_id}
**Branch:** {branch}
**Pipeline ID:** {pipeline_id}
**Failed Job:** {job_name}
**Commit:** {commit_sha}
**Author:** {commit_author}

**Job Failure Log (last 150 lines):**
```
{job_log}
```

Analyze this CI/CD failure and return the JSON response.
"""

    model = genai.GenerativeModel(
        model_name=_MODEL,
        system_instruction=_SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )

    response = await model.generate_content_async(user_message)
    raw = response.text.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned invalid JSON: {e}\nRaw: {raw[:500]}")
