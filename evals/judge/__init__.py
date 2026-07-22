"""LLM-as-a-Judge — config y prompt versionados aparte (ADR-0007).

Prohibido: compartir models.yaml / instancias con los agentes evaluados.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

JUDGE_DIR = Path(__file__).resolve().parent
EVALS_DIR = JUDGE_DIR.parent
DEFAULT_MODELS_YAML = JUDGE_DIR / "models.yaml"
DEFAULT_PROMPT = JUDGE_DIR / "prompt_v1.md"
PROMPT_VERSION = "v1"


def _judge_models_path(path: str | None = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get("PORTFOLIOSENTINEL_JUDGE_MODELS_YAML")
    if env:
        return Path(env)
    return DEFAULT_MODELS_YAML


class JudgeScore(BaseModel):
    faithfulness: int = Field(ge=1, le=5)
    relevancy: int = Field(ge=1, le=5)
    completitud: int = Field(ge=1, le=5)
    rationale: str = ""
    prompt_version: str = PROMPT_VERSION
    model_id: str = ""

    @field_validator("faithfulness", "relevancy", "completitud", mode="before")
    @classmethod
    def _coerce_int(cls, v: Any) -> int:
        return int(v)

    @property
    def average(self) -> float:
        return (self.faithfulness + self.relevancy + self.completitud) / 3.0


class JudgeConfigError(ValueError):
    """evals/judge/models.yaml inválido."""


def load_judge_models_config(path: str | None = None) -> dict[str, Any]:
    return _load_judge_models_config(str(_judge_models_path(path).resolve()))


@lru_cache(maxsize=4)
def _load_judge_models_config(yaml_path: str) -> dict[str, Any]:
    path = Path(yaml_path)
    if not path.is_file():
        raise JudgeConfigError(f"No se encontró judge models.yaml en {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "roles" not in raw:
        raise JudgeConfigError("judge models.yaml debe tener 'roles'")
    roles = raw["roles"]
    if "judge" not in roles:
        raise JudgeConfigError("Falta rol 'judge' en evals/judge/models.yaml")
    cfg = roles["judge"]
    for key in ("provider", "model"):
        if key not in cfg or not cfg[key]:
            raise JudgeConfigError(f"Rol judge requiere '{key}'")
    cfg.setdefault("params", {})
    if not isinstance(cfg["params"], dict):
        raise JudgeConfigError("params del judge debe ser mapping")
    # Garantía: temperature 0 (SPEC §9 / ADR-0007).
    cfg["params"] = {**cfg["params"], "temperature": 0}
    return raw


def get_judge_model(*, config_path: str | None = None) -> BaseChatModel:
    """Instancia el judge desde evals/judge/models.yaml — NUNCA desde models.yaml agentes."""
    config = load_judge_models_config(config_path)
    cfg = config["roles"]["judge"]
    model_id = f"{cfg['provider']}:{cfg['model']}"
    return init_chat_model(model_id, **cfg["params"])


def judge_model_label(*, config_path: str | None = None) -> str:
    cfg = load_judge_models_config(config_path)["roles"]["judge"]
    return f"{cfg['provider']}:{cfg['model']}"


def load_judge_prompt(*, version: str = PROMPT_VERSION) -> str:
    path = JUDGE_DIR / f"prompt_{version}.md"
    if not path.is_file():
        path = DEFAULT_PROMPT
    return path.read_text(encoding="utf-8")


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence:
        return fence.group(1).strip()
    # Algunos modelos locales envuelven thinking; buscar el primer objeto JSON.
    brace = re.search(r"\{[\s\S]*\}", text)
    if brace:
        return brace.group(0)
    return text


def _content_to_str(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def build_judge_user_message(
    *,
    report: str,
    snapshot_summary: str,
    constraints_summary: str,
    case_id: str,
) -> str:
    return f"""\
Caso: {case_id}

=== SNAPSHOT (fuente de verdad — no recalcules, solo contrastá) ===
{snapshot_summary}

=== RESTRICCIONES ACTIVAS ===
{constraints_summary}

=== INFORME A EVALUAR ===
{report}
"""


def run_judge(
    *,
    report: str,
    snapshot_summary: str,
    constraints_summary: str,
    case_id: str,
    model: BaseChatModel | None = None,
    config_path: str | None = None,
) -> JudgeScore:
    """Evalúa faithfulness / relevancy / completitud (1–5)."""
    llm = model or get_judge_model(config_path=config_path)
    system = load_judge_prompt()
    user = build_judge_user_message(
        report=report,
        snapshot_summary=snapshot_summary,
        constraints_summary=constraints_summary,
        case_id=case_id,
    )
    raw = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    text = _strip_fences(_content_to_str(getattr(raw, "content", raw)))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Judge no devolvió JSON parseable: {text[:500]}") from exc
    label = judge_model_label(config_path=config_path)
    return JudgeScore(
        faithfulness=int(data["faithfulness"]),
        relevancy=int(data["relevancy"]),
        completitud=int(data["completitud"]),
        rationale=str(data.get("rationale") or ""),
        prompt_version=PROMPT_VERSION,
        model_id=label,
    )
