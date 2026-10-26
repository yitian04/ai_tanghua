from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_STAGE_SELECTIONS: dict[str, dict[str, str]] = {
    "sample": {
        "source": "siliconflow",
        "provider_id": "siliconflow",
        "model_id": "Qwen/Qwen-Image",
    },
    "line_art": {
        "source": "bananapro",
        "provider_id": "bananapro",
        "model_id": "seedream-5-pro",
    },
}


class ProjectDefaultsStore:
    """Git-trackable defaults containing no credentials or generated artifacts."""

    def __init__(self, root_dir: str | Path) -> None:
        self.path = Path(root_dir) / "config" / "ai_generation_defaults.json"

    def load(self) -> dict[str, Any]:
        payload = self._read_payload()
        stages = payload.get("stages") if isinstance(payload.get("stages"), dict) else {}
        prompts = payload.get("prompts") if isinstance(payload.get("prompts"), dict) else {}
        return {
            "version": 1,
            "stages": {
                stage: {
                    **defaults,
                    **(
                        stages.get(stage)
                        if isinstance(stages.get(stage), dict)
                        else {}
                    ),
                }
                for stage, defaults in DEFAULT_STAGE_SELECTIONS.items()
            },
            "prompts": {
                language: dict(prompts.get(language) or {})
                for language in ("zh", "en")
            },
        }

    def stage(self, stage: str) -> dict[str, str]:
        key = _normalize_stage(stage)
        raw = self.load()["stages"][key]
        return {
            "source": str(raw.get("source") or DEFAULT_STAGE_SELECTIONS[key]["source"]),
            "provider_id": str(
                raw.get("provider_id") or DEFAULT_STAGE_SELECTIONS[key]["provider_id"]
            ),
            "model_id": str(
                raw.get("model_id") or DEFAULT_STAGE_SELECTIONS[key]["model_id"]
            ),
        }

    def prompt(
        self,
        stage: str,
        language: str,
        *,
        fallback_positive: str,
        fallback_negative: str,
    ) -> tuple[str, str]:
        stage_key = _normalize_stage(stage)
        language_key = "en" if str(language).lower().startswith("en") else "zh"
        values = self.load()["prompts"].get(language_key) or {}
        positive_value = values.get(f"{stage_key}_positive")
        negative_key = f"{stage_key}_negative"
        negative_value = values.get(negative_key)
        return (
            str(positive_value or fallback_positive),
            str(negative_value) if negative_key in values and negative_value is not None else fallback_negative,
        )

    def save_stage(self, stage: str, *, source: str, provider_id: str, model_id: str) -> Path:
        stage_key = _normalize_stage(stage)
        if not source.strip() or not provider_id.strip() or not model_id.strip():
            raise ValueError("服务商和模型 ID 不能为空。")
        payload = self._merged_payload()
        payload["stages"][stage_key] = {
            "source": source.strip(),
            "provider_id": provider_id.strip(),
            "model_id": model_id.strip(),
        }
        return self._write_payload(payload)

    def save_prompt(
        self,
        stage: str,
        language: str,
        *,
        positive: str,
        negative: str,
    ) -> Path:
        stage_key = _normalize_stage(stage)
        language_key = "en" if str(language).lower().startswith("en") else "zh"
        if not positive.strip():
            raise ValueError("默认提示词正文不能为空。")
        if "{{OBJECT}}" in positive:
            raise ValueError("主体名称由固定首行自动加入，默认提示词正文中不要使用 {{OBJECT}}。")
        payload = self._merged_payload()
        payload["prompts"][language_key][f"{stage_key}_positive"] = positive.strip()
        payload["prompts"][language_key][f"{stage_key}_negative"] = negative.strip()
        return self._write_payload(payload)

    def _merged_payload(self) -> dict[str, Any]:
        loaded = self.load()
        return {
            "version": 1,
            "stages": deepcopy(loaded["stages"]),
            "prompts": deepcopy(loaded["prompts"]),
        }

    def _read_payload(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_payload(self, payload: dict[str, Any]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return self.path


def _normalize_stage(stage: str) -> str:
    value = str(stage).strip().lower()
    if value in {"sample", "stage1", "1"}:
        return "sample"
    if value in {"line_art", "lineart", "stage2", "2"}:
        return "line_art"
    raise ValueError(f"未知阶段：{stage}")
