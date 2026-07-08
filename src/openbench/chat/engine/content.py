"""Content detection, A2UI rendering, dedup, and error panels for ChatEngine."""

from __future__ import annotations

import logging
from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.core.abstractions import ExecutionResult

logger = logging.getLogger(__name__)


class _A2UIContentMixin:
    """Mixin for ChatEngine; not instantiated directly."""

    def _render_content(
        self, content: Any, extra_items: list[dict] | None = None
    ) -> tuple[list[A2UIComponent], dict[str, Any] | None]:
        """Auto-detect content type and render to A2UI components.

        Args:
            content: Main agent output (text, chart dict, etc.).
            extra_items: Additional structured items from render queue
                (visualization tools). Each item is rendered through the
                renderer pipeline independently and combined with main content.

        Returns:
            Tuple of (components, data_model). data_model is None if no
            renderer provides initial values.
        """
        # Render main content (skip when content is None — text already streamed)
        main_components: list[A2UIComponent] = []
        data_model: dict[str, Any] | None = None
        if content is not None:
            for renderer in self.renderers:
                if renderer.detect(content):
                    main_components = renderer.render(content, surface_id="")
                    dm = renderer.get_data_model(content)
                    if dm:
                        data_model = dm
                    break
            if not main_components:
                main_components = [
                    A2UIComponent(
                        id="txt-fallback",
                        component="Text",
                        properties={"text": str(content), "variant": "body"},
                    )
                ]

        # Render extra items from render queue
        if not extra_items:
            return main_components, data_model

        # Deduplicate: agents may call visualization tools multiple times in
        # reasoning loops. Keep only the last item per content type to avoid
        # rendering the same form/chart/file card multiple times.
        deduped = self._deduplicate_render_items(extra_items)

        extra_components: list[A2UIComponent] = []
        for item in deduped:
            rendered = False
            for renderer in self.renderers:
                if renderer.detect(item):
                    extra_components.extend(renderer.render(item, surface_id=""))
                    dm = renderer.get_data_model(item)
                    if dm:
                        if data_model is None:
                            data_model = {}
                        data_model.update(dm)
                    rendered = True
                    break
            if not rendered:
                logger.warning(f"No renderer matched render item: {list(item.keys())}")

        if not extra_components:
            return main_components, data_model

        return main_components + extra_components, data_model

    def _build_surface_record(
        self,
        surface_id: str,
        components: list[A2UIComponent],
        data_model: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the persistable snapshot of a rendered A2UI surface.

        Stored in ``ChatMessage.surfaces`` so reloaded sessions can replay
        rich content (charts, dashboards, files) instead of dropping it.
        ``components`` uses the exact A2UI wire format the frontend streams
        into its Map (flat ``{id, component, ...properties}`` dicts), so
        rehydration needs no transformation beyond array → Map.
        """
        record: dict[str, Any] = {
            "surfaceId": surface_id,
            "catalogId": self.builder.catalog_id,
            "components": [c.to_dict() for c in components],
        }
        if data_model:
            record["dataModel"] = data_model
        return record

    def _build_error_components(
        self, error_message: str, error_title: str = "Agent execution failed"
    ) -> list[A2UIComponent]:
        """Build an ObCallout error panel from a failed ExecutionResult.

        This is used when agent.execute() catches an exception internally
        and returns ExecutionResult(status="failed", output=None). Without
        this, the UI just shows an empty assistant message (which some
        frontends render as "." or blank), hiding the real failure from
        the user. With this, the user sees the actual error text.
        """
        return [
            A2UIComponent(
                id="error-callout",
                component="ObCallout",
                properties={
                    "variant": "error",
                    "title": error_title,
                    "message": error_message,
                },
            )
        ]

    def _result_failed(self, result: Any) -> tuple[bool, str]:
        """Check if an agent result represents a failed execution.

        Returns (is_failed, error_message). error_message is empty when
        is_failed is False.
        """
        if isinstance(result, ExecutionResult) and result.status == "failed":
            err = result.metadata.get("error") if result.metadata else None
            return True, str(err or "Agent execution failed with no error message.")
        return False, ""

    def _ensure_root(self, components: list[A2UIComponent]) -> list[A2UIComponent]:
        """Ensure there's a component with id='root'.

        Identifies top-level components (not referenced as children by others)
        and wraps them in a root Column, or renames a single top-level to 'root'.
        """
        has_root = any(c.id == "root" for c in components)
        if has_root:
            return components

        if len(components) == 1:
            components[0] = A2UIComponent(
                id="root",
                component=components[0].component,
                properties=components[0].properties,
            )
            return components

        # Find IDs referenced as children by other components
        referenced_ids: set[str] = set()
        for c in components:
            children = c.properties.get("children")
            if isinstance(children, list):
                referenced_ids.update(children)

        # Top-level = components not referenced as children of anything
        top_level_ids = [c.id for c in components if c.id not in referenced_ids]

        if len(top_level_ids) == 1:
            # Single top-level: rename it to root
            target_id = top_level_ids[0]
            result: list[A2UIComponent] = []
            for c in components:
                if c.id == target_id:
                    result.append(
                        A2UIComponent(
                            id="root",
                            component=c.component,
                            properties=c.properties,
                        )
                    )
                else:
                    result.append(c)
            return result

        # Multiple top-level components: wrap in Column
        root = A2UIComponent(
            id="root",
            component="Column",
            properties={"children": top_level_ids},
        )
        return [root, *components]

    @staticmethod
    def _deduplicate_render_items(items: list[dict]) -> list[dict]:
        """Deduplicate render items from visualization tools.

        Agents may call the same tool multiple times during reasoning
        iterations (e.g. refining a form). For forms, only keep the last one.
        For charts, keep multiple but deduplicate by title.
        For dashboard artifacts, deduplicate by URL/name/title.
        For file cards, deduplicate by name.
        For code blocks, deduplicate by title (if present); keep all untitled.
        For media, deduplicate by src URL (last wins).
        For lists, only keep the last one (one list per response).

        Detection order matters:
        1. Form: "fields" in item
        2. Tabs: "tabs" in item and isinstance(item.get("tabs"), list)
        3. Modal: "modalContent" in item
        4. List: "items" in item and "listType" in item
        5. Table: "headers" in item and "rows" in item
        6. Callout: "calloutContent" in item
        7. Code: "code" in item and "language" in item
        8. Media: "src" in item and "mediaType" in item
        9. Chart: "data" in item and "title" in item
        10. Dashboard: type == "dashboard" and URL or ViewModel present
        11. File: "url" in item and "name" in item
        12. Other: fallthrough
        """
        forms: list[dict] = []
        tabs: list[dict] = []
        modals: list[dict] = []
        lists: list[dict] = []
        tables: dict[str, dict] = {}  # keyed by title
        callouts: list[dict] = []
        charts: dict[str, dict] = {}  # keyed by title
        dashboards: dict[str, dict] = {}  # keyed by URL/name
        files: dict[str, dict] = {}  # keyed by name
        media: dict[str, dict] = {}  # keyed by src URL
        code_titled: dict[str, dict] = {}  # keyed by title
        code_untitled: list[dict] = []
        other: list[dict] = []

        for item in items:
            if not isinstance(item, dict):
                other.append(item)
                continue
            if "fields" in item:
                forms.append(item)
            elif "tabs" in item and isinstance(item.get("tabs"), list):
                tabs.append(item)
            elif "modalContent" in item:
                modals.append(item)
            elif "items" in item and "listType" in item:
                lists.append(item)
            elif "headers" in item and "rows" in item:
                title = item.get("title", "")
                tables[title] = item  # last one wins per title
            elif "calloutContent" in item:
                callouts.append(item)
            elif "code" in item and "language" in item:
                title = item.get("title")
                if title:
                    code_titled[title] = item  # last one wins per title
                else:
                    code_untitled.append(item)
            elif "src" in item and "mediaType" in item:
                media[item["src"]] = item  # last one wins per src URL
            elif "data" in item and "title" in item:
                charts[item["title"]] = item  # last one wins per title
            elif item.get("type") == "dashboard" and (
                item.get("url")
                or item.get("dashboardUrl")
                or item.get("viewModel")
                or item.get("view_model")
                or item.get("datasets")
                or item.get("kpis")
                or item.get("sections")
            ):
                key = str(
                    item.get("url")
                    or item.get("dashboardUrl")
                    or item.get("name")
                    or item.get("title")
                    or ""
                )
                dashboards[key] = item  # last one wins per artifact
            elif "url" in item and "name" in item:
                files[item["name"]] = item  # last one wins per name
            else:
                other.append(item)

        result: list[dict] = []
        # Only keep the last form (one form per response)
        if forms:
            result.append(forms[-1])
        # Only keep the last tabs (one tabs per response)
        if tabs:
            result.append(tabs[-1])
        # Only keep the last modal (one modal per response)
        if modals:
            result.append(modals[-1])
        # Only keep the last list (one list per response)
        if lists:
            result.append(lists[-1])
        result.extend(tables.values())
        # Only keep the last callout (one callout per response)
        if callouts:
            result.append(callouts[-1])
        result.extend(media.values())
        result.extend(charts.values())
        result.extend(dashboards.values())
        result.extend(files.values())
        result.extend(code_titled.values())
        result.extend(code_untitled)
        result.extend(other)
        return result

    def _extract_text_content(self, output: Any) -> str:
        """Extract plain text content for session history.

        Returns empty string for None output so that a failed agent
        execution (output=None) doesn't leave the literal string ``None``
        in the session history.
        """
        if output is None:
            return ""
        if isinstance(output, str):
            return output
        if isinstance(output, dict):
            if "text" in output:
                return str(output["text"])
            if "content" in output:
                return str(output["content"])
        return str(output)
