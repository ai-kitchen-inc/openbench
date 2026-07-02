"""Vision-capable agents for image understanding workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult, LLMResponse
from openbench.core.providers import ProviderType, get_provider_service


def extract_image_inputs(data: Any) -> list[dict[str, Any]]:
    """Extract image attachment dictionaries from execution context data."""
    if not isinstance(data, dict):
        return []

    images: list[dict[str, Any]] = []
    for item in data.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        mime_type = str(item.get("mime_type") or item.get("mimeType") or "")
        item_type = str(item.get("type") or "")
        has_image_mime = mime_type.startswith("image/")
        has_image_type = item_type == "image"
        has_image_ref = any(item.get(key) for key in ("path", "url", "data_url", "dataUrl"))
        if (has_image_mime or has_image_type) and has_image_ref:
            images.append(item)
    return images


class VisionAgent(Agent):
    """General-purpose image understanding agent backed by a VLM provider."""

    def __init__(
        self,
        goal: str = "Answer questions about images.",
        model: str | None = None,
        provider_name: str | None = None,
        temperature: float = 0.2,
        system_prompt: str | None = None,
        skills: list[str | Path] | None = None,
    ):
        self.goal = goal
        self.model = model or "gemini-2.5-flash"
        self.provider_name = provider_name
        self.temperature = temperature
        self.system_prompt = system_prompt or (
            "You are a vision-language assistant. Answer using the image content "
            "and the user's request. If the image is unclear, say what is uncertain."
        )
        self._skill_registry = None
        if skills:
            from openbench.intelligence.skill import Skill
            from openbench.intelligence.skill_registry import SkillRegistry

            self._skill_registry = SkillRegistry()
            selected: list[Skill] = []
            for skill_ref in skills:
                p = Path(str(skill_ref))
                if isinstance(skill_ref, Path) or "/" in str(skill_ref) or "\\" in str(skill_ref) or p.is_dir():
                    selected.append(Skill.from_dir(p))
                    continue
                lookup = SkillRegistry()
                lookup.load_sdk_skills()
                lookup.load_user_skills()
                selected.append(lookup.resolve(str(skill_ref)))
            self._skill_registry._project = {skill.name: skill for skill in selected}
            skill_context = self._skill_registry.compose_context()
            if skill_context:
                self.system_prompt = f"{self.system_prompt}\n\n{skill_context}"
        self._vlm = None

    @property
    def agent_type(self) -> str:
        return "vision"

    def _get_vlm(self):
        if self._vlm is None:
            self._vlm = get_provider_service().resolve(
                ProviderType.VLM,
                name=self.provider_name,
                model=self.model,
                temperature=self.temperature,
            )
        return self._vlm

    def _build_prompt(self, context: ExecutionContext) -> str:
        prompt = f"{self.system_prompt}\n\nTask: {context.goal}"
        if isinstance(context.data, dict):
            text_attachments = []
            for item in context.data.get("attachments") or []:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                name = item.get("name") or "attachment"
                if content and not str(item.get("mime_type") or "").startswith("image/"):
                    text_attachments.append(f"## {name}\n{content}")
            if text_attachments:
                prompt += "\n\nAdditional text context:\n" + "\n\n".join(text_attachments)
        return prompt

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        images = extract_image_inputs(context.data)
        if not images:
            return ExecutionResult(
                output=None,
                status="failed",
                metadata={"error": "VisionAgent requires at least one image attachment."},
            )

        vlm = None
        try:
            vlm = self._get_vlm()
            response: LLMResponse = vlm.generate(
                prompt=self._build_prompt(context),
                images=images,
                model=self.model,
                temperature=self.temperature,
            )
        except Exception as exc:
            return ExecutionResult(
                output=None,
                status="failed",
                metadata={
                    "error": str(exc),
                    "agent": self.agent_type,
                    "model": self.model,
                    "provider": getattr(vlm, "provider_name", None),
                },
            )

        return ExecutionResult(
            output=response.text,
            status="completed",
            metadata={
                "agent": self.agent_type,
                "model": response.model,
                "provider": response.metadata.get("provider"),
                "image_count": len(images),
                "prompt_tokens": response.metadata.get("prompt_tokens", 0),
                "completion_tokens": response.metadata.get("completion_tokens", 0),
            },
            cost=response.cost,
            tokens_used=response.tokens_used,
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0
