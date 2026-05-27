"""
pipelinedoc — GitLab Pipeline Triage Agent
FastAPI entry point
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from routes.triage import router as triage_router

app = FastAPI(
    title="pipelinedoc",
    description="GitLab CI/CD Pipeline Triage Agent",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock down to Firebase Hosting domain post-deploy
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(triage_router)


@app.get("/")
async def health():
    return {"status": "ok", "service": "pipelinedoc"}
