"""FastAPI A2A: Agent Card + JSON-RPC tasks (message/send, tasks/get)."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from a2a_compliance.agent_card import DEFAULT_HOST, DEFAULT_PORT, build_agent_card
from a2a_compliance.reviewer import review_plan

app = FastAPI(title="A2A Compliance (consultivo)", version="0.1.0")

# Tasks en memoria (demo single-user; no es store de dominio).
_TASKS: dict[str, dict[str, Any]] = {}


def _extract_plan_payload(params: dict[str, Any]) -> dict[str, Any]:
    """Acepta plan en metadata.plan, message.parts JSON, o params.plan directo."""
    if isinstance(params.get("plan"), dict):
        return params["plan"]
    meta = params.get("metadata") or {}
    if isinstance(meta, dict) and isinstance(meta.get("plan"), dict):
        return meta["plan"]
    message = params.get("message") or {}
    parts = message.get("parts") if isinstance(message, dict) else None
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text") or part.get("data")
            if isinstance(text, dict):
                return text
            if isinstance(text, str) and text.strip().startswith("{"):
                try:
                    data = json.loads(text)
                    if isinstance(data, dict):
                        return data.get("plan", data) if "actions" not in data else data
                except json.JSONDecodeError:
                    continue
    return {}


def _task_result(task_id: str, review: dict[str, Any]) -> dict[str, Any]:
    artifact = {
        "artifactId": f"review-{task_id[:8]}",
        "name": "compliance_review",
        "parts": [
            {
                "kind": "data",
                "data": review,
            }
        ],
    }
    state = "completed"
    return {
        "id": task_id,
        "contextId": task_id,
        "status": {
            "state": state,
            "message": {
                "role": "agent",
                "parts": [
                    {
                        "kind": "text",
                        "text": json.dumps(review, ensure_ascii=False),
                    }
                ],
            },
        },
        "artifacts": [artifact],
        "metadata": {"skill": "review_plan"},
        "kind": "task",
    }


def _handle_message_send(params: dict[str, Any], req_id: Any) -> dict[str, Any]:
    plan = _extract_plan_payload(params)
    review = review_plan(plan)
    task_id = str(uuid.uuid4())
    task = _task_result(task_id, review)
    _TASKS[task_id] = task
    return {"jsonrpc": "2.0", "id": req_id, "result": task}


def _handle_tasks_get(params: dict[str, Any], req_id: Any) -> dict[str, Any]:
    task_id = str(params.get("id") or params.get("taskId") or "")
    task = _TASKS.get(task_id)
    if task is None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32001, "message": f"Task not found: {task_id}"},
        }
    return {"jsonrpc": "2.0", "id": req_id, "result": task}


@app.get("/.well-known/agent.json")
def agent_card() -> dict[str, Any]:
    host = os.environ.get("A2A_HOST", DEFAULT_HOST)
    port = int(os.environ.get("A2A_PORT", str(DEFAULT_PORT)))
    return build_agent_card(host=host, port=port)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/a2a")
async def a2a_rpc(request: Request) -> JSONResponse:
    """Endpoint JSON-RPC 2.0 del Agent Card (`url`)."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )

    if not isinstance(body, dict):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request"},
            },
            status_code=400,
        )

    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if method in {"message/send", "tasks/send", "review_plan"}:
        return JSONResponse(_handle_message_send(params, req_id))
    if method in {"tasks/get", "tasks/getTask"}:
        return JSONResponse(_handle_tasks_get(params, req_id))

    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    )


def create_app() -> FastAPI:
    return app
