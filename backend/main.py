import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("MODEL", "gemma4:e4b")

app = FastAPI(title="QuoteCraft AI", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class QuoteRequest(BaseModel):
    service: str = Field(min_length=2, max_length=120)
    client_request: str = Field(min_length=10, max_length=4000)
    budget: str = Field(default="Not specified", max_length=100)
    deadline: str = Field(default="Not specified", max_length=100)
    freelancer_name: str = Field(default="Freelancer", max_length=100)

class Quote(BaseModel):
    title: str
    summary: str
    scope: list[str]
    deliverables: list[str]
    timeline: str
    price_note: str
    exclusions: list[str]
    payment_terms: list[str]
    client_message: str

SYSTEM = """You are QuoteCraft, a practical assistant for freelancers and small service businesses. Turn a client's messy request into a clear, professional quote draft. Never invent exact facts that were not supplied. If budget is unspecified, say so. Keep scope realistic. Return ONLY valid JSON with exactly these keys: title, summary, scope, deliverables, timeline, price_note, exclusions, payment_terms, client_message. Lists must contain short strings."""

LIST_FIELDS = ("scope", "deliverables", "exclusions", "payment_terms")


def normalize_quote_lists(data: Any) -> Any:
    """Normalize list-valued fields from inconsistent LLM JSON before validation."""
    if not isinstance(data, dict):
        return data

    for field in LIST_FIELDS:
        value = data.get(field)
        if value is None:
            data[field] = []
        elif isinstance(value, list):
            continue
        else:
            data[field] = [value if isinstance(value, str) else str(value)]
    return data

@app.get("/api/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            names = [m.get("name") for m in r.json().get("models", [])]
            return {"ok": True, "ollama": True, "model": MODEL, "installed": MODEL in names}
    except Exception:
        return {"ok": True, "ollama": False, "model": MODEL, "installed": False}

@app.post("/api/quote", response_model=Quote)
async def generate_quote(req: QuoteRequest):
    prompt = f"""Create a quote draft from these inputs:\nFreelancer: {req.freelancer_name}\nService: {req.service}\nClient request: {req.client_request}\nBudget: {req.budget}\nDeadline: {req.deadline}\n\nMake it useful to a freelancer who wants to send this to a potential client. Do not claim that a client agreed to anything. Use the provided budget/deadline only as context."""
    payload = {"model": MODEL, "system": SYSTEM, "prompt": prompt, "stream": False, "format": "json"}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            r.raise_for_status()
            raw = r.json().get("response", "")
        data: Any = json.loads(raw)
        return Quote.model_validate(normalize_quote_lists(data))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemma generation failed: {exc}")
