import sys
import os
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

app = FastAPI(title="Local LLM Computer-Use API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = Orchestrator()


@app.on_event("startup")
async def startup_event():
    skill_registry.load_skills()
    print("[Server] Skills loaded.")


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str = "gpt-4"
    stream: bool = False


class SkillRunRequest(BaseModel):
    args: dict = {}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(
    request: Request,
    body: ChatRequest,
    x_llm_endpoint: str | None = Header(default=None),
    x_llm_key: str | None = Header(default=None),
):
    endpoint_url = x_llm_endpoint or os.getenv("LLM_ENDPOINT", "http://localhost:11434")
    api_key = x_llm_key or os.getenv("LLM_KEY", "")

    user_messages = body.messages
    user_content = ""
    for msg in reversed(user_messages):
        if msg.get("role") == "user":
            user_content = msg.get("content", "")
            break

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
                )
                async for chunk in gen:
                    payload = json.dumps({"content": chunk, "done": False})
                    yield f"data: {payload}\n\n"
                yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"
            except Exception as e:
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
            )
            return {"content": result, "done": True}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/chat/reset")
async def reset_chat():
    orchestrator.reset()
    return {"status": "ok", "message": "Conversation context reset."}


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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
