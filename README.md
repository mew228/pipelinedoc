---
title: Pipelinedoc
emoji: 🚀
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# pipelinedoc

**GitLab CI/CD Pipeline Triage Agent** — detects failed pipelines, reads job logs via MCP, traces the triggering commit, performs root-cause analysis with Gemini, and creates a GitLab issue + MR comment.

---

## Architecture

```
Browser (Firebase Hosting)
  fetch() + ReadableStream → live terminal output
        ↓ POST /triage (streaming NDJSON)
FastAPI Backend (Cloud Run, :8080)
  TriageOrchestrator (async generator)
    → gitlab_client.py  [MCP Python SDK]
         └→ npx @gitlab-org/gitlab-mcp-server (stdio subprocess)
    → gemini_client.py  [google-generativeai]
```

## Triage Steps (streamed live)

| Step | Description | MCP Tool |
|------|-------------|----------|
| 1 | Detect latest failed pipeline | `list_pipelines` |
| 2 | List failed jobs | `list_pipeline_jobs` |
| 3 | Read job logs (last 150 lines) | `get_pipeline_job_output` |
| 4 | Trace triggering commit + MR | `get_project_commits`, `list_merge_requests` |
| 5 | Gemini root-cause analysis | — Gemini API — |
| 6 | Create GitLab issue + MR comment | `create_issue`, `create_note` |

---

## Setup

### 1. Backend (local dev)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your keys
uvicorn main:app --reload --port 8080
```

### 2. Frontend (local)

Open `frontend/index.html` directly in your browser.  
The `API_BASE_URL` in `frontend/app.js` defaults to `http://localhost:8080`.

### 3. MCP server (local, runs as subprocess)

The backend spawns this automatically via `npx`. No manual start needed.  
Node.js must be installed on your machine (or in the Docker image).

```bash
# Manually test the MCP server (optional)
npx @gitlab-org/gitlab-mcp-server
```

### 4. Docker

```bash
docker build -t pipelinedoc .
docker run -p 8080:8080 \
  -e GEMINI_API_KEY=... \
  -e GITLAB_PERSONAL_ACCESS_TOKEN=... \
  -e GITLAB_BASE_URL=https://gitlab.com \
  pipelinedoc
```

### 5. Cloud Run deploy

```bash
gcloud run deploy pipelinedoc \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=...,GITLAB_PERSONAL_ACCESS_TOKEN=...,GITLAB_BASE_URL=https://gitlab.com,GOOGLE_CLOUD_PROJECT=...
```

### 6. Firebase Hosting (frontend)

After Cloud Run deploy, update `API_BASE_URL` in `frontend/app.js` to the Cloud Run URL, then:

```bash
firebase init hosting   # select "frontend/" as public dir, SPA: yes
firebase deploy --only hosting
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google AI Studio or Vertex AI API key |
| `GITLAB_PERSONAL_ACCESS_TOKEN` | GitLab PAT with `api` + `read_repository` scopes |
| `GITLAB_BASE_URL` | GitLab instance URL (default: `https://gitlab.com`) |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID (for Cloud Run / Vertex) |

---

## Project Structure

```
pipelinedoc/
├── backend/
│   ├── main.py                  # FastAPI app
│   ├── routes/triage.py         # POST /triage → streaming NDJSON
│   ├── services/
│   │   ├── gitlab_client.py     # MCP stdio client
│   │   ├── gemini_client.py     # Gemini root-cause analysis
│   │   └── orchestrator.py      # 6-step triage async generator
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html               # Terminal-style SPA
│   ├── style.css                # Dark terminal aesthetic
│   └── app.js                   # ReadableStream NDJSON consumer
├── Dockerfile                   # Node.js + Python (Cloud Run)
├── firebase.json
└── README.md
```
