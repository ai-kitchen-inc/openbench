"""Admin-managed agent profiles (the "AI department heads").

Each profile configures one specialist agent: identity (name +
description feed the protocol router), persona (same shape as the
``persona`` settings value; empty means "inherit the global admin
persona"), model/temperature, skill selection, agent-scoped sources,
and low-confidence escalation to another profile.

Store pattern mirrors ``group_store``: JSON file for local development,
Postgres for deployed environments. The Postgres table keeps the full
record JSON in one ``config`` column so adding a profile field never
needs a schema migration (``from_dict`` defaults every missing key).
Cascade behavior on delete (purging the profile's sources, blanking
escalation references) lives at the route layer — the store stays dumb.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")

DEFAULT_CONFIDENCE_THRESHOLD = 0.5


class DuplicateAgentProfileError(ValueError):
    """Raised when adding a profile whose id already exists."""


class UnknownAgentProfileError(KeyError):
    """Raised when updating a profile that does not exist."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify_agent_name(name: str) -> str:
    """Derive the profile id from its display name."""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:64]


def validate_agent_id(agent_id: str) -> str:
    value = agent_id.strip().lower()
    if not _SLUG_RE.fullmatch(value):
        raise ValueError(f"Invalid agent id {agent_id!r}; expected 1-64 chars of [a-z0-9-]")
    return value


def _clamp_threshold(value: Any) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE_THRESHOLD
    return min(max(threshold, 0.0), 1.0)


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


@dataclass
class AgentProfileRecord:
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    #: Same shape as the persona settings value (template/soul/style/
    #: agents/goal/source_context_label). Empty dict = inherit the global
    #: admin persona.
    persona: dict[str, Any] = field(default_factory=dict)
    model: str = ""  # "" = runtime settings llm_model
    temperature: float | None = None
    skills: list[str] = field(default_factory=list)  # SDK skill dir names
    custom_skill_ids: list[str] = field(default_factory=list)
    #: MCP registry server ids whose enabled tools attach to this agent.
    mcp_server_ids: list[str] = field(default_factory=list)
    use_sources: bool = True
    #: Extra per-agent rules appended to the persona's agents text at
    #: build time. "" = no extra guardrails.
    guardrails: str = ""
    escalation_agent_id: str = ""  # another profile id, "" = none
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    created_at: str = field(default_factory=_utcnow_iso)
    created_by: str = ""
    updated_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "persona": dict(self.persona),
            "model": self.model,
            "temperature": self.temperature,
            "skills": list(self.skills),
            "customSkillIds": list(self.custom_skill_ids),
            "mcpServerIds": list(self.mcp_server_ids),
            "useSources": self.use_sources,
            "guardrails": self.guardrails,
            "escalationAgentId": self.escalation_agent_id,
            "confidenceThreshold": self.confidence_threshold,
            "createdAt": self.created_at,
            "createdBy": self.created_by,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentProfileRecord:
        persona = data.get("persona")
        temperature = data.get("temperature")
        try:
            temperature = float(temperature) if temperature is not None else None
        except (TypeError, ValueError):
            temperature = None
        now = _utcnow_iso()
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            description=str(data.get("description", "") or ""),
            enabled=bool(data.get("enabled", True)),
            persona=dict(persona) if isinstance(persona, dict) else {},
            model=str(data.get("model", "") or ""),
            temperature=temperature,
            skills=_str_list(data.get("skills")),
            custom_skill_ids=_str_list(data.get("customSkillIds")),
            mcp_server_ids=_str_list(data.get("mcpServerIds")),
            use_sources=bool(data.get("useSources", True)),
            guardrails=str(data.get("guardrails", "") or ""),
            escalation_agent_id=str(data.get("escalationAgentId", "") or "").strip().lower(),
            confidence_threshold=_clamp_threshold(
                data.get("confidenceThreshold", DEFAULT_CONFIDENCE_THRESHOLD)
            ),
            created_at=str(data.get("createdAt", "") or now),
            created_by=str(data.get("createdBy", "") or ""),
            updated_at=str(data.get("updatedAt", "") or now),
        )

    def apply_changes(self, changes: dict[str, Any]) -> None:
        """Overlay known fields from ``changes`` (snake_case keys)."""
        if "name" in changes and str(changes["name"]).strip():
            self.name = str(changes["name"]).strip()
        if "description" in changes:
            self.description = str(changes["description"] or "").strip()
        if "enabled" in changes:
            self.enabled = bool(changes["enabled"])
        if "persona" in changes:
            persona = changes["persona"]
            self.persona = dict(persona) if isinstance(persona, dict) else {}
        if "model" in changes:
            self.model = str(changes["model"] or "").strip()
        if "temperature" in changes:
            raw = changes["temperature"]
            with contextlib.suppress(TypeError, ValueError):
                self.temperature = float(raw) if raw is not None else None
        if "skills" in changes:
            self.skills = _str_list(changes["skills"])
        if "custom_skill_ids" in changes:
            self.custom_skill_ids = _str_list(changes["custom_skill_ids"])
        if "mcp_server_ids" in changes:
            self.mcp_server_ids = _str_list(changes["mcp_server_ids"])
        if "use_sources" in changes:
            self.use_sources = bool(changes["use_sources"])
        if "guardrails" in changes:
            self.guardrails = str(changes["guardrails"] or "").strip()
        if "escalation_agent_id" in changes:
            self.escalation_agent_id = str(changes["escalation_agent_id"] or "").strip().lower()
        if "confidence_threshold" in changes:
            self.confidence_threshold = _clamp_threshold(changes["confidence_threshold"])
        self.updated_at = _utcnow_iso()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


class JsonAgentProfileStore:
    """JSON-file-backed profile store at ``<root>/admin/agent_profiles.json``."""

    def __init__(self, root: str | Path):
        self._path = Path(root).expanduser().resolve() / "admin" / "agent_profiles.json"

    def list(self) -> list[AgentProfileRecord]:
        return sorted(self._read().values(), key=lambda record: record.id)

    def get(self, agent_id: str) -> AgentProfileRecord | None:
        return self._read().get(agent_id.strip().lower())

    def add(self, record: AgentProfileRecord) -> AgentProfileRecord:
        record.id = validate_agent_id(record.id)
        profiles = self._read()
        if record.id in profiles:
            raise DuplicateAgentProfileError(f"Agent profile already exists: {record.id}")
        profiles[record.id] = record
        self._write(profiles)
        return record

    def update(self, agent_id: str, changes: dict[str, Any]) -> AgentProfileRecord:
        agent_id = validate_agent_id(agent_id)
        profiles = self._read()
        record = profiles.get(agent_id)
        if record is None:
            raise UnknownAgentProfileError(agent_id)
        record.apply_changes(changes)
        self._write(profiles)
        return record

    def remove(self, agent_id: str) -> bool:
        agent_id = agent_id.strip().lower()
        profiles = self._read()
        if agent_id not in profiles:
            return False
        del profiles[agent_id]
        self._write(profiles)
        return True

    def _read(self) -> dict[str, AgentProfileRecord]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load agent profile store file %s", self._path)
            return {}
        profiles: dict[str, AgentProfileRecord] = {}
        for item in data.get("agents", []):
            record = AgentProfileRecord.from_dict(item)
            if record.id:
                profiles[record.id] = record
        return profiles

    def _write(self, profiles: dict[str, AgentProfileRecord]) -> None:
        payload = {
            "agents": [record.to_dict() for record in sorted(profiles.values(), key=lambda r: r.id)]
        }
        _atomic_write_json(self._path, payload)


class PostgresAgentProfileStore:
    """PostgreSQL-backed profile store for deployed environments.

    The full record JSON lives in ``config``; ``id`` and ``enabled`` are
    real columns for lookups and filtering.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = "openbench_agent_profiles",
    ):
        if conn is None and not database_url:
            raise ValueError("Either database_url= or conn= must be provided.")
        self.database_url = database_url
        self._conn = conn
        self.table_name = table_name
        self._init_db()

    def list(self) -> list[AgentProfileRecord]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT config FROM {self.table_name} ORDER BY id")
            rows = cur.fetchall()
        return [self._record_from_row(row) for row in rows]

    def get(self, agent_id: str) -> AgentProfileRecord | None:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT config FROM {self.table_name} WHERE id = %s",
                (agent_id.strip().lower(),),
            )
            row = cur.fetchone()
        return self._record_from_row(row) if row else None

    def add(self, record: AgentProfileRecord) -> AgentProfileRecord:
        record.id = validate_agent_id(record.id)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name} (id, enabled, config)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (record.id, record.enabled, json.dumps(record.to_dict())),
                )
                inserted = cur.rowcount
            conn.commit()
        if not inserted:
            raise DuplicateAgentProfileError(f"Agent profile already exists: {record.id}")
        return record

    def update(self, agent_id: str, changes: dict[str, Any]) -> AgentProfileRecord:
        agent_id = validate_agent_id(agent_id)
        record = self.get(agent_id)
        if record is None:
            raise UnknownAgentProfileError(agent_id)
        record.apply_changes(changes)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {self.table_name} SET enabled = %s, config = %s WHERE id = %s",
                    (record.enabled, json.dumps(record.to_dict()), agent_id),
                )
                updated = cur.rowcount
            conn.commit()
        if not updated:
            raise UnknownAgentProfileError(agent_id)
        return record

    def remove(self, agent_id: str) -> bool:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.table_name} WHERE id = %s",
                    (agent_id.strip().lower(),),
                )
                rowcount = cur.rowcount
            conn.commit()
        return bool(rowcount)

    def _init_db(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id TEXT PRIMARY KEY,
                        enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        config TEXT NOT NULL
                    )
                    """)
            conn.commit()

    def _connection(self):
        if self._conn is not None:
            return _ExternalConnection(self._conn)
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "PostgresAgentProfileStore requires psycopg. Install openbench[gcp]."
            ) from exc
        return psycopg.connect(self.database_url)

    @staticmethod
    def _record_from_row(row: Any) -> AgentProfileRecord:
        raw = row[0]
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Malformed agent profile config row; skipping fields")
            data = {}
        return AgentProfileRecord.from_dict(data)


class _ExternalConnection:
    """Context manager that never closes a borrowed connection."""

    def __init__(self, conn: Any):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc_info):
        return False


def build_agent_profile_store(root: str | Path):
    """Postgres when ``GENERAL_CHAT_DATABASE_URL`` is set, JSON otherwise."""
    database_url = os.getenv("GENERAL_CHAT_DATABASE_URL", "").strip()
    if database_url:
        return PostgresAgentProfileStore(database_url)
    return JsonAgentProfileStore(root)
