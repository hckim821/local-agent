import sys
import os
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import json
import asyncio

from skills import skill_registry
from core.orchestrator import Orchestrator
from core.wiki_loader import load_wiki_skills, unload_wiki_skills

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
    force=True,
)

app = FastAPI(title="Local LLM Computer-Use API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = Orchestrator()
_current_wiki_path: str | None = None


@app.on_event("startup")
async def startup_event():
    try:
        skill_registry.load_skills()
        logging.info(f"Skills loaded: {[s['name'] for s in skill_registry.list_all()]}")
    except Exception as e:
        logging.error(f"Skill loading failed: {e}")


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str = "gpt-4"
    stream: bool = False
    image: str | None = None  # base64 data URL from frontend paste


class SkillRunRequest(BaseModel):
    args: dict = {}


@app.get("/api/health")
async def health():
    logging.info("[Health] ping")
    return {"status": "ok", "skills": [s["name"] for s in skill_registry.list_all()]}


@app.post("/api/chat")
async def chat(
    request: Request,
    body: ChatRequest,
    x_llm_endpoint: str | None = Header(default=None),
    x_llm_key: str | None = Header(default=None),
    x_wiki_path: str | None = Header(default=None),
):
    global _current_wiki_path
    endpoint_url = x_llm_endpoint or os.getenv("LLM_ENDPOINT", "http://localhost:11434")
    api_key = x_llm_key or os.getenv("LLM_KEY", "")

    # 위키 경로가 변경되면 위키 스킬 갱신
    if x_wiki_path and x_wiki_path != _current_wiki_path:
        if load_wiki_skills(x_wiki_path, skill_registry):
            _current_wiki_path = x_wiki_path
            logging.info(f"[Wiki] 위키 스킬 갱신: {x_wiki_path}")
        else:
            logging.warning(f"[Wiki] 스킬 로드 실패 (경로 없음?): {x_wiki_path}")
    elif not x_wiki_path and _current_wiki_path:
        unload_wiki_skills(skill_registry)
        _current_wiki_path = None
        logging.info("[Wiki] 위키 경로 해제됨 — 스킬 제거")

    user_messages = body.messages
    user_content = ""
    for msg in reversed(user_messages):
        if msg.get("role") == "user":
            user_content = msg.get("content", "")
            break

    logging.info(f"[Chat] endpoint={endpoint_url} model={body.model} user={user_content[:80]!r}")

    if body.stream:
        async def event_stream():
            try:
                gen = await orchestrator.process(
                    user_message=user_content,
                    endpoint_url=endpoint_url,
                    api_key=api_key,
                    model=body.model,
                    skill_registry=skill_registry,
                    stream=True,
                    image=body.image,
                )
                async for chunk in gen:
                    payload = json.dumps({"content": chunk, "done": False})
                    yield f"data: {payload}\n\n"
                yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"
                logging.info("[Chat] stream completed")
            except Exception as e:
                logging.error(f"[Chat] stream error: {e}")
                yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    else:
        try:
            result = await orchestrator.process(
                user_message=user_content,
                endpoint_url=endpoint_url,
                api_key=api_key,
                model=body.model,
                skill_registry=skill_registry,
                stream=False,
                image=body.image,
            )
            return {"content": result, "done": True}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/chat/reset")
async def reset_chat():
    orchestrator.reset()
    return {"status": "ok", "message": "Conversation context reset."}


@app.post("/api/wiki/connect")
async def wiki_connect(
    x_wiki_path: str | None = Header(default=None),
):
    """위키 경로를 등록/해제하고 갱신된 스킬 목록을 반환합니다."""
    global _current_wiki_path
    if x_wiki_path:
        if x_wiki_path != _current_wiki_path:
            ok = load_wiki_skills(x_wiki_path, skill_registry)
            if ok:
                _current_wiki_path = x_wiki_path
            else:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"경로를 찾을 수 없습니다: {x_wiki_path}"},
                )
    else:
        unload_wiki_skills(skill_registry)
        _current_wiki_path = None

    return {"skills": skill_registry.list_all(), "wiki_path": _current_wiki_path}


@app.get("/api/skills")
async def list_skills():
    return {"skills": skill_registry.list_all()}


@app.post("/api/skills/{skill_name}/run")
async def run_skill(skill_name: str, body: SkillRunRequest):
    skill = skill_registry.get(skill_name)
    if skill is None:
        return JSONResponse(status_code=404, content={"error": f"Skill '{skill_name}' not found."})
    try:
        result = await skill.run(**body.args)
        return {"result": result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    import uvicorn
    # reload=False: reload=True spawns a subprocess which disconnects stdout
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
