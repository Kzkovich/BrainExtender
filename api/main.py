"""
Brain Expander — HTTP Ingest API
Accepts content, runs the full classify → format → link → save pipeline.
Used by Claude Code skill and other integrations.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from brain.classifier import classify
from brain.formatter import format_content
from brain.indexer import update_index, update_brain_summary
from brain.linker import link_and_inject
from brain.profiles import ProfileLoader
from brain.storage import BrainStorage
from db.models import SessionLocal, User, create_tables

app = FastAPI(title="Brain Expander API", version="1.0")


class IngestRequest(BaseModel):
    content: str
    user_id: str = "390604543"
    workspace: Optional[str] = None        # override active workspace
    hint: Optional[str] = None             # optional context hint for classifier
    auto_save: bool = True                 # False = dry-run, returns preview only


class IngestResponse(BaseModel):
    saved: bool
    saved_to: str
    title: str
    content_type: str
    workspace: str
    links_added: list[str]
    note_mode: str
    confidence: float
    preview: str                           # first 400 chars of formatted content


@app.on_event("startup")
def startup():
    create_tables()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest):
    user_id = req.user_id

    # Verify user exists
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found. Run /start in the bot first.")

    storage = BrainStorage(user_id)

    # Optionally override workspace
    if req.workspace:
        original_ws = storage.get_meta().get("active_workspace")
        storage.update_meta({"active_workspace": req.workspace})

    # Prepend hint to content if provided
    content = req.content
    if req.hint:
        content = f"[Контекст: {req.hint}]\n\n{content}"

    # Full pipeline
    classification = await classify(content, user_id)
    meta = storage.get_meta()
    profile = ProfileLoader.load(meta.get("profile_id", "universal"))
    body, frontmatter = await format_content(content, classification, profile, user_id)

    # Restore workspace if overridden
    if req.workspace:
        storage.update_meta({"active_workspace": original_ws})

    links_added = []
    import re
    links_added = re.findall(r"\[\[([^\]|]+)\]\]", body)

    if req.auto_save:
        storage.write_file(classification.target_path, body, frontmatter)
        update_index(storage, classification.target_path, frontmatter, body)
        update_brain_summary(storage)

    return IngestResponse(
        saved=req.auto_save,
        saved_to=classification.target_path,
        title=classification.raw_title or "Без названия",
        content_type=classification.content_type,
        workspace=classification.workspace,
        links_added=links_added,
        note_mode=classification.note_mode,
        confidence=classification.confidence,
        preview=body[:400],
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="127.0.0.1", port=8001, reload=False)
