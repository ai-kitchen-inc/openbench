"""CRUD store for admin-defined General Chat skills.

Custom skills are saved as regular OpenBench project skills so the existing
``SkillRegistry`` can load them without a special runtime path:

    <root>/<skill-id>/
    ├── SKILL.md
    └── metadata.json

These skills are knowledge-only for now. Tool execution remains in the existing
custom-function/MCP flow, while this store gives admins a durable way to add
task-specific instructions, triggers, and SOPs to the shared chat agent.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbench.intelligence.skill import Skill

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:[-+][a-zA-Z0-9.-]+)?$")
MAX_TEXT_BYTES = 64 * 1024
TITLE_STOPWORDS = {
    "agar",
    "akan",
    "atau",
    "bisa",
    "buat",
    "buatkan",
    "bikin",
    "dalam",
    "dan",
    "dengan",
    "jadi",
    "kustom",
    "mau",
    "membantu",
    "membuat",
    "menjadi",
    "saya",
    "skill",
    "supaya",
    "untuk",
    "user",
    "yang",
}


class CustomSkillError(ValueError):
    """Validation error surfaced to the UI as HTTP 400."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_single_line(value: Any, *, max_len: int) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", text)[:max_len]


def _clean_multiline(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise CustomSkillError(f"text exceeds {MAX_TEXT_BYTES // 1024}KB limit")
    return text


def _clean_triggers(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.splitlines()
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    triggers: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = _clean_single_line(raw, max_len=160).lstrip("-* ").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        triggers.append(item)
    return triggers[:20]


def _section_text(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    wanted = heading.strip().lower()
    collecting = False
    section_lines: list[str] = []
    for line in lines:
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            if collecting:
                break
            collecting = match.group(1).strip().lower() == wanted
            continue
        if collecting:
            section_lines.append(line)
    return "\n".join(section_lines).strip()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not cleaned:
        cleaned = "custom-skill"
    if not cleaned[0].isalpha():
        cleaned = f"skill-{cleaned}"
    if len(cleaned) < 2:
        cleaned = f"{cleaned}-skill"
    return cleaned[:64].strip("-") or "custom-skill"


def _display_name(value: str) -> str:
    words: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9]+", value):
        if raw.lower() in TITLE_STOPWORDS:
            continue
        words.append(raw.upper() if raw.isupper() else raw.capitalize())
        if len(words) >= 5:
            break
    return " ".join(words) or "Skill Kustom"


def _topic_from_prompt(prompt: str) -> str:
    first_line = next((line.strip() for line in prompt.splitlines() if line.strip()), prompt)
    text = _clean_single_line(first_line, max_len=180)
    text = re.sub(
        r"^(tolong\s+)?(buatkan|buat|bikin|mohon|saya\s+mau)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(skill\s+kustom\s+|skill\s+untuk\s+|skill\s+yang\s+)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.split(r"\b(agar|supaya|dengan|untuk menghasilkan|yang bisa)\b", text, maxsplit=1)[0]
    return _display_name(text)


def _keywords_from_prompt(prompt: str) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{3,}", prompt.lower()):
        if word in TITLE_STOPWORDS or word in seen:
            continue
        seen.add(word)
        keywords.append(word)
        if len(keywords) >= 6:
            break
    return keywords


def _prompt_detail_lines(prompt: str) -> list[str]:
    details: list[str] = []
    for line in prompt.splitlines():
        cleaned = _clean_single_line(line.lstrip("-*0123456789. "), max_len=180)
        if cleaned:
            details.append(cleaned)
        if len(details) >= 8:
            break
    if not details:
        details.append(_clean_single_line(prompt, max_len=220))
    return details


def _skill_spec_from_prompt(prompt: str) -> dict[str, Any]:
    prompt = _clean_multiline(prompt)
    if not prompt:
        raise CustomSkillError("prompt is required")
    name = _topic_from_prompt(prompt)
    topic = name.lower()
    keywords = _keywords_from_prompt(prompt)
    keyword_text = ", ".join(keywords[:4]) if keywords else topic
    details = _prompt_detail_lines(prompt)
    detail_block = "\n".join(f"- {line}" for line in details)
    description = (
        f"Skill kustom untuk membantu agent menangani permintaan terkait {topic} "
        "berdasarkan kebutuhan yang ditulis admin."
    )
    triggers = [
        f"User meminta bantuan terkait {topic}.",
        f"User ingin agent mengikuti SOP, gaya, atau batasan khusus untuk {topic}.",
        f"Permintaan user memuat konteks atau kata kunci seperti {keyword_text}.",
    ]
    instructions = (
        "Gunakan skill ini hanya saat permintaan user cocok dengan trigger.\n\n"
        "SOP:\n"
        "1. Pahami tujuan user, data yang tersedia, dan hasil akhir yang diminta.\n"
        "2. Terapkan detail kebutuhan berikut sebagai aturan kerja utama:\n"
        f"{detail_block}\n"
        "3. Susun jawaban dengan struktur yang jelas, praktis, dan langsung bisa dipakai.\n"
        "4. Jika informasi penting belum tersedia, jelaskan asumsi dan minta input lanjutan "
        "yang spesifik.\n"
        "5. Jangan mengklaim sudah menjalankan alat, mengakses data, atau membuat file jika "
        "hal itu belum benar-benar dilakukan."
    )
    return {
        "name": name,
        "description": description,
        "triggers": triggers,
        "instructions": instructions,
        "version": "0.1.0",
    }


def _render_skill_md(
    *,
    name: str,
    description: str,
    triggers: list[str],
    instructions: str,
    version: str,
) -> str:
    trigger_block = "\n".join(f"- {trigger}" for trigger in triggers) or "- Use when relevant."
    return (
        f"# {name}\n\n"
        f"{description or 'Custom General Chat skill.'}\n\n"
        "## Triggers\n\n"
        f"{trigger_block}\n\n"
        "## Instructions\n\n"
        f"{instructions}\n\n"
        "## Version\n\n"
        f"{version}\n"
    )


class CustomSkillStore:
    """Manage admin-defined project-skill directories."""

    def __init__(self, storage_root: str) -> None:
        configured = os.getenv("GENERAL_CHAT_CUSTOM_SKILLS_DIR", "").strip()
        self.root = Path(configured) if configured else Path(storage_root) / "custom-skills"
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id(skill_id: str) -> str:
        cleaned = str(skill_id or "").strip().lower()
        if not ID_RE.match(cleaned):
            raise CustomSkillError(
                "invalid skill id: use lowercase letters, digits, and hyphen; "
                "must start with a letter; length 2-64"
            )
        return cleaned

    @staticmethod
    def _validate_version(version: str) -> str:
        cleaned = _clean_single_line(version or "0.1.0", max_len=32) or "0.1.0"
        if not VERSION_RE.match(cleaned):
            raise CustomSkillError("invalid version: use a semver-like value such as 0.1.0")
        return cleaned

    def _path_for(self, skill_id: str) -> Path:
        return self.root / self._validate_id(skill_id)

    def _unique_id(self, seed: str) -> str:
        base = self._validate_id(_slugify(seed))
        candidate = base
        counter = 2
        while (self.root / candidate / "SKILL.md").is_file():
            suffix = f"-{counter}"
            candidate = f"{base[: 64 - len(suffix)]}{suffix}".strip("-")
            counter += 1
        return candidate

    def paths(self) -> list[Path]:
        return [
            entry
            for entry in sorted(self.root.iterdir())
            if entry.is_dir() and (entry / "SKILL.md").is_file()
        ]

    def save(
        self,
        skill_id: str,
        *,
        name: str,
        description: str = "",
        triggers: Any = None,
        instructions: str = "",
        version: str = "0.1.0",
    ) -> dict[str, Any]:
        skill_id = self._validate_id(skill_id)
        name = _clean_single_line(name, max_len=80)
        if not name:
            raise CustomSkillError("skill name is required")
        description = _clean_single_line(description, max_len=500)
        instructions = _clean_multiline(instructions)
        if not instructions:
            raise CustomSkillError("instructions are required")
        triggers = _clean_triggers(triggers)
        version = self._validate_version(version)

        skill_dir = self._path_for(skill_id)
        existing = self.get(skill_id, include_markdown=False)
        created_at = existing.get("created_at") if existing else _utc_now()
        updated_at = _utc_now()
        skill_md = _render_skill_md(
            name=name,
            description=description,
            triggers=triggers,
            instructions=instructions,
            version=version,
        )

        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        # Validate with the same loader the agent will use before persisting
        # metadata or returning success.
        loaded = Skill.from_dir(skill_dir)
        meta = {
            "id": skill_id,
            "name": loaded.name,
            "description": loaded.description,
            "triggers": list(loaded.triggers),
            "instructions": instructions,
            "version": loaded.version,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        (skill_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        return self._serialize(skill_dir, include_markdown=True)

    def save_from_prompt(self, prompt: str) -> dict[str, Any]:
        spec = _skill_spec_from_prompt(prompt)
        return self.save(
            self._unique_id(spec["name"]),
            name=spec["name"],
            description=spec["description"],
            triggers=spec["triggers"],
            instructions=spec["instructions"],
            version=spec["version"],
        )

    def save_markdown(self, skill_id: str, markdown: str) -> dict[str, Any]:
        skill_id = self._validate_id(skill_id)
        markdown = _clean_multiline(markdown)
        if not markdown:
            raise CustomSkillError("skill markdown is required")

        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp) / skill_id
            temp_dir.mkdir(parents=True, exist_ok=True)
            (temp_dir / "SKILL.md").write_text(markdown, encoding="utf-8")
            loaded = Skill.from_dir(temp_dir)
        version = self._validate_version(loaded.version)

        skill_dir = self._path_for(skill_id)
        existing = self.get(skill_id, include_markdown=False)
        created_at = existing.get("created_at") if existing else _utc_now()
        updated_at = _utc_now()
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(markdown.strip() + "\n", encoding="utf-8")
        loaded = Skill.from_dir(skill_dir)
        meta = {
            "id": skill_id,
            "name": loaded.name,
            "description": loaded.description,
            "triggers": list(loaded.triggers),
            "instructions": _section_text(loaded.raw_skill_md, "Instructions"),
            "version": version,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        (skill_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        return self._serialize(skill_dir, include_markdown=True)

    def _serialize(self, skill_dir: Path, *, include_markdown: bool) -> dict[str, Any]:
        skill = Skill.from_dir(skill_dir)
        metadata: dict[str, Any] = {}
        meta_path = skill_dir / "metadata.json"
        if meta_path.is_file():
            try:
                raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(raw_meta, dict):
                    metadata = raw_meta
            except (OSError, ValueError):
                metadata = {}
        item = {
            "id": str(metadata.get("id") or skill_dir.name),
            "name": skill.name,
            "description": skill.description,
            "triggers": list(skill.triggers),
            "instructions": str(metadata.get("instructions") or ""),
            "version": skill.version,
            "created_at": str(metadata.get("created_at") or ""),
            "updated_at": str(metadata.get("updated_at") or ""),
            "source": str(skill_dir.resolve()),
            "context_chars": len(skill.get_context()),
        }
        if include_markdown:
            item["skill_md"] = skill.raw_skill_md
        return item

    def get(self, skill_id: str, *, include_markdown: bool = True) -> dict[str, Any] | None:
        skill_dir = self._path_for(skill_id)
        if not (skill_dir / "SKILL.md").is_file():
            return None
        return self._serialize(skill_dir, include_markdown=include_markdown)

    def list(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for skill_dir in self.paths():
            try:
                result.append(self._serialize(skill_dir, include_markdown=True))
            except Exception:
                continue
        return result

    def delete(self, skill_id: str) -> bool:
        skill_dir = self._path_for(skill_id)
        if not skill_dir.is_dir():
            return False
        for filename in ("SKILL.md", "metadata.json"):
            path = skill_dir / filename
            if path.is_file():
                path.unlink()
        try:
            skill_dir.rmdir()
        except OSError:
            pass
        return True
