# Dashboard Persistence Memory

OpenBench dashboard generation stores every successful dashboard ViewModel in a
small SQLite persistence database. The same implementation is used by the SDK
skill and by MCP, so dashboard consistency works the same way whether the agent
calls local SDK tools or MCP tools.

## Where It Lives

The persistence logic is in:

- `src/openbench/skills/dashboard-generator/tools.py`
- SQLite database: `OPENBENCH_DASHBOARD_MEMORY_DB`, or
  `GENERAL_CHAT_DASHBOARD_MEMORY_DB`, or `.openbench/dashboard_memory.db`

Set `OPENBENCH_DASHBOARD_MEMORY_ENABLED=0` to disable persistence.

The stored record contains:

- `dashboard_id`: stable reference returned as `dashboardId`
- `source_signature`: functional schema signature for the uploaded table
- `viewModel`: the canonical rendered dashboard ViewModel
- artifact metadata such as URL, path, template info, and render mode
- revision metadata such as `revision_of` and `revision_notes`

## Functional Data Matching

`extract_metadata(path=...)` computes `source_signature` from the source format,
sheet, column names, dtypes, and role hints. It intentionally does not include
row count, file hash, or sample values.

That means a table uploaded on day two with the same columns but additional rows
matches the dashboard generated on day one. The agent should:

1. Call `extract_metadata`.
2. Inspect `dashboard_memory.matches`.
3. Call `load_dashboard_memory` for the matched `dashboard_id` or `source_path`.
4. Run fresh `aggregate_data` queries on the new file.
5. Reuse the previous layout while replacing panel data with new aggregate rows.
6. Call `generate_dashboard(..., source_path=...)` to persist the refreshed result.

## Revisions Without Losing Panels

For a dashboard with five panels, a user may ask to revise only one panel. The
agent should load the old dashboard and send a small patch:

```json
{
  "previous_dashboard_id": "dash-abc123",
  "revision_notes": "Change Revenue Share from pie to bar.",
  "revision_panel_titles": ["Revenue Share"],
  "view_model": {
    "title": "Sales Dashboard",
    "sections": [
      {
        "title": "Dashboard",
        "items": [
          {"title": "Revenue Share", "type": "chart", "chart_type": "bar"}
        ]
      }
    ]
  }
}
```

`generate_dashboard` merges the patch into the stored ViewModel. Sections,
panels, and KPIs are matched by `id`, `panel_id`, `panelId`, `title`, or
`label`. Only items listed in `revision_panel_titles`, or clearly inferable from
`revision_notes`, are updated. All unspecified panels remain unchanged.

If a revision payload includes multiple changed panels but does not clearly name
which panel the user requested, OpenBench preserves the old dashboard panels
instead of accepting ambiguous drift. Top-level `datasets` are also merged
selectively: only datasets referenced by revised panels are replaced, while
datasets used by preserved panels stay unchanged.

If an agent sends a full regenerated dashboard without `previous_dashboard_id`
but the title matches dashboard memory, `generate_dashboard` still performs an
auto-revision pass. Non-canonical payloads such as `components` are normalized
for comparison, the prior matching dashboard is loaded, and only the first
semantically changed panel is applied. Other panels keep their stored chart type,
data bindings, and datasets so accidental model drift does not rewrite the
whole dashboard.

## SDK and MCP Behavior

SDK path:

```python
from openbench.intelligence import BaseAgent

agent = BaseAgent(skills=["dashboard-generator"])
```

MCP path:

```text
dashboard_generator.extract_metadata
dashboard_generator.aggregate_data
dashboard_generator.load_dashboard_memory
dashboard_generator.generate_dashboard
```

Both routes call the same `tools.py` functions and write to the same dashboard
memory database, as long as they share the same environment/path configuration.
