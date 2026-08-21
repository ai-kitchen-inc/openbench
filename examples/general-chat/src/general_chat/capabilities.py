"""Role-scoped capability flags controlled by the admin.

Each route-kind capability maps to a set of URL prefixes. The auth
middleware consults the resolved flags after Firebase verification:
admins bypass everything, other roles get 403 on prefixes whose flag
is disabled for their role. Global-kind capabilities (currently
``file_generation``) are not route gates — they steer agent
construction (which skills load) and require an agent rebuild when
toggled.

The resolved state persists in the settings store under the
``"capabilities"`` key:

    {"roles": {"user": {"attachments": true, ...}},
     "global": {"file_generation": true}}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SETTINGS_KEY = "capabilities"


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    kind: str  # "route" | "global"
    prefixes: tuple[str, ...]
    default: bool
    label: str
    description: str


CAPABILITY_DEFINITIONS: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        id="attachments",
        kind="route",
        prefixes=("/chat/upload", "/chat/uploads", "/chat/attachments", "/chat/transcribe"),
        default=True,
        label="Lampiran",
        description="Unggah berkas dan rekaman suara di ruang percakapan.",
    ),
    CapabilityDefinition(
        id="session_sources",
        kind="route",
        # /auth/drive/callback stays open: it is the browser redirect from
        # Google and carries no Bearer header for role resolution.
        prefixes=(
            "/chat/sources",
            "/auth/drive/connect",
            "/auth/drive/disconnect",
            "/auth/drive/status",
        ),
        default=True,
        label="Sumber Sesi",
        description="Kelola sumber pengetahuan milik sendiri per sesi.",
    ),
    CapabilityDefinition(
        id="mcp_management",
        kind="route",
        prefixes=("/mcp", "/toolhive"),
        default=False,
        label="Server MCP",
        description="Lihat dan kelola server MCP serta perkakasnya.",
    ),
    CapabilityDefinition(
        id="custom_functions",
        kind="route",
        prefixes=("/functions",),
        default=False,
        label="Fungsi Kustom",
        description="Buat dan jalankan fungsi Python kustom.",
    ),
    CapabilityDefinition(
        id="dashboards",
        kind="route",
        prefixes=("/dashboard",),
        default=True,
        label="Dasbor",
        description="Publikasikan dan ekspor dasbor.",
    ),
    CapabilityDefinition(
        id="image_search",
        kind="route",
        prefixes=("/image-search",),
        default=True,
        label="Pencarian Gambar",
        description="Akses pratinjau hasil pencarian gambar.",
    ),
    CapabilityDefinition(
        id="file_generation",
        kind="global",
        prefixes=(),
        default=True,
        label="Pembuatan Berkas",
        description="Asisten dapat membuat berkas PDF, Excel, dan Markdown.",
    ),
)

_ROUTE_DEFINITIONS = tuple(d for d in CAPABILITY_DEFINITIONS if d.kind == "route")
_GLOBAL_DEFINITIONS = tuple(d for d in CAPABILITY_DEFINITIONS if d.kind == "global")

# Roles that capability toggles apply to. Admins always bypass.
GATED_ROLES = ("user",)


#: Valid route-flag ids, used to validate group overrides.
_ROUTE_FLAG_IDS = frozenset(d.id for d in _ROUTE_DEFINITIONS)


def default_capabilities() -> dict[str, Any]:
    """The fully-resolved default capability state.

    ``groups`` holds sparse per-group overrides of route flags: absence
    of a flag means "inherit the role default". Group ids are validated
    against the group store at the admin PUT, not here.
    """
    return {
        "roles": {
            role: {d.id: d.default for d in _ROUTE_DEFINITIONS} for role in GATED_ROLES
        },
        "groups": {},
        "global": {d.id: d.default for d in _GLOBAL_DEFINITIONS},
    }


def resolve_capabilities(stored: Any) -> dict[str, Any]:
    """Merge a stored (possibly partial/stale) value over the defaults.

    Unknown flags are dropped; missing flags fall back to defaults, so
    adding a new capability definition never requires a data migration.
    """
    resolved = default_capabilities()
    if not isinstance(stored, dict):
        return resolved
    stored_roles = stored.get("roles")
    if isinstance(stored_roles, dict):
        for role, flags in resolved["roles"].items():
            overrides = stored_roles.get(role)
            if not isinstance(overrides, dict):
                continue
            for flag_id in flags:
                if isinstance(overrides.get(flag_id), bool):
                    flags[flag_id] = overrides[flag_id]
    stored_groups = stored.get("groups")
    if isinstance(stored_groups, dict):
        for group_id, overrides in stored_groups.items():
            if not isinstance(group_id, str) or not isinstance(overrides, dict):
                continue
            kept = {
                flag_id: value
                for flag_id, value in overrides.items()
                if flag_id in _ROUTE_FLAG_IDS and isinstance(value, bool)
            }
            if kept:
                resolved["groups"][group_id] = kept
    stored_global = stored.get("global")
    if isinstance(stored_global, dict):
        for flag_id in resolved["global"]:
            if isinstance(stored_global.get(flag_id), bool):
                resolved["global"][flag_id] = stored_global[flag_id]
    return resolved


def blocked_flag_for(path: str) -> str | None:
    """Return the capability id gating ``path``, or None if ungated.

    Longest-prefix wins so ``/chat/uploads`` (attachments) is not
    shadowed by a shorter unrelated prefix.
    """
    best: tuple[int, str] | None = None
    for definition in _ROUTE_DEFINITIONS:
        for prefix in definition.prefixes:
            if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
                if best is None or len(prefix) > best[0]:
                    best = (len(prefix), definition.id)
    return best[1] if best else None


class CapabilityCache:
    """In-memory resolved capability state, backed by the settings store.

    The auth middleware reads ``.value`` on every request, so lookups
    never hit the store; admin saves go through :meth:`update`, which
    persists and atomically swaps the resolved dict. Single-process
    uvicorn deployment makes this safe.
    """

    def __init__(self, settings_store: Any):
        self._store = settings_store
        self.value: dict[str, Any] = resolve_capabilities(settings_store.get(SETTINGS_KEY))

    def role_allows(self, role: str, flag_id: str) -> bool:
        return self.allows(role, "", flag_id)

    def allows(self, role: str, group: str, flag_id: str) -> bool:
        """Effective flag for one requester: group override wins over role."""
        flags = self.value["roles"].get(role)
        if flags is None:
            return True  # unknown/ungated role (e.g. admin) bypasses
        if group:
            override = self.value.get("groups", {}).get(group, {}).get(flag_id)
            if isinstance(override, bool):
                return override
        return bool(flags.get(flag_id, True))

    def global_enabled(self, flag_id: str) -> bool:
        return bool(self.value["global"].get(flag_id, True))

    def update(self, partial: Any, *, updated_by: str = "") -> dict[str, Any]:
        """Overlay a (possibly partial) payload, persist, and swap."""
        merged = resolve_capabilities(_overlay(self.value, partial))
        self._store.set(SETTINGS_KEY, merged, updated_by=updated_by)
        self.value = merged
        return merged


def _overlay(current: dict[str, Any], partial: Any) -> dict[str, Any]:
    result = {
        "roles": {role: dict(flags) for role, flags in current["roles"].items()},
        "groups": {
            group: dict(flags) for group, flags in current.get("groups", {}).items()
        },
        "global": dict(current["global"]),
    }
    if not isinstance(partial, dict):
        return result
    partial_roles = partial.get("roles")
    if isinstance(partial_roles, dict):
        for role, overrides in partial_roles.items():
            if role in result["roles"] and isinstance(overrides, dict):
                result["roles"][role].update(
                    {k: v for k, v in overrides.items() if isinstance(v, bool)}
                )
    partial_groups = partial.get("groups")
    if isinstance(partial_groups, dict):
        for group, overrides in partial_groups.items():
            if not isinstance(group, str) or not isinstance(overrides, dict):
                continue
            flags = result["groups"].setdefault(group, {})
            for flag_id, value in overrides.items():
                if isinstance(value, bool):
                    flags[flag_id] = value
                elif value is None:
                    # Deliberate carve-out from the bool-only rule: null
                    # removes the override ("inherit role default").
                    flags.pop(flag_id, None)
            if not flags:
                result["groups"].pop(group, None)
    partial_global = partial.get("global")
    if isinstance(partial_global, dict):
        result["global"].update({k: v for k, v in partial_global.items() if isinstance(v, bool)})
    return result


def strip_group_overrides(cache: "CapabilityCache", group_id: str, *, updated_by: str = "") -> None:
    """Remove every override for ``group_id`` (used by group deletion)."""
    overrides = cache.value.get("groups", {}).get(group_id)
    if not overrides:
        return
    cache.update(
        {"groups": {group_id: {flag_id: None for flag_id in overrides}}},
        updated_by=updated_by,
    )


def capability_definitions_payload() -> list[dict[str, Any]]:
    """JSON-friendly definition list for the admin UI."""
    return [
        {
            "id": d.id,
            "kind": d.kind,
            "label": d.label,
            "description": d.description,
            "default": d.default,
        }
        for d in CAPABILITY_DEFINITIONS
    ]
