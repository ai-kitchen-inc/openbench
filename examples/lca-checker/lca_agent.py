"""
LCA compliance agent for the LCA Checker demo.

Uses BaseAgent with GeminiLLMProvider + up to 24 domain-specific tools for
ISO 14040/14044, PCR, and Pedoman KLH Indonesia compliance checking.

Core: 21 tools (always available)
RAG:  3 tools (optional, enabled when Pinecone is configured)

Follows the same pattern as examples/lighthouser/semap_agent.py:
  - ContextVar render isolation
  - Render queue helpers
  - Agent factory function

Requires:
    - GOOGLE_API_KEY environment variable
    - pip install google-genai
    - (RAG) PINECONE_API_KEY environment variable
    - (RAG) pip install openbench[vector,google]
"""

import contextvars
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from lca_engine import (
    calculate_data_quality_score,
    check_iso_compliance,
    check_pcr_compliance,
    check_pedoman_klh_compliance,
    compare_with_benchmarks,
    generate_compliance_summary,
)
from mock_data import COMPANY_PROFILES, LCA_STUDIES
from prompt import SYSTEM_PROMPT
from schemas import (
    ANALYZE_DOCUMENT_SCHEMA,
    ASSESS_DATA_QUALITY_SCHEMA,
    CHECK_FULL_ISO_COMPLIANCE_SCHEMA,
    CHECK_GOAL_SCOPE_SCHEMA,
    CHECK_INTERPRETATION_SCHEMA,
    CHECK_KLH_COMPLIANCE_SCHEMA,
    CHECK_LCI_SCHEMA,
    CHECK_LCIA_SCHEMA,
    CHECK_PCR_COMPLIANCE_SCHEMA,
    COMPARE_BENCHMARKS_SCHEMA,
    CREATE_CALLOUT_SCHEMA,
    CREATE_CHART_SCHEMA,
    CREATE_COMPLIANCE_REVIEW_FORM_SCHEMA,
    CREATE_TABLE_SCHEMA,
    GENERATE_COMPLIANCE_REPORT_SCHEMA,
    GENERATE_MARKDOWN_REPORT_SCHEMA,
    INDEX_DOCUMENT_SCHEMA,
    LIST_PCR_CATEGORIES_SCHEMA,
    LOOKUP_COMPANY_PROFILE_SCHEMA,
    LOOKUP_LCA_STUDY_SCHEMA,
    LOOKUP_STANDARD_REFERENCE_SCHEMA,
    READ_EXCEL_SCHEMA,
    SEARCH_DOCUMENTS_SCHEMA,
    SEARCH_STANDARDS_SCHEMA,
)
from standards_data import IMPACT_CATEGORIES, ISO_REQUIREMENTS, PCR_TEMPLATES, PEDOMAN_KLH

from openbench.core.providers import ProviderType, configure_provider
from openbench.data.sources import PDFSource
from openbench.intelligence.base import BaseAgent
from openbench.output.generators import PDFGenerator

# ── Per-request context (ContextVar for async isolation) ──

_current_attachments_var: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "current_attachments", default=None
)
_render_items_var: contextvars.ContextVar[list[dict]] = contextvars.ContextVar("render_items")


def _get_render_list() -> list[dict]:
    """Get per-request render items list, creating if needed."""
    try:
        return _render_items_var.get()
    except LookupError:
        items: list[dict] = []
        _render_items_var.set(items)
        return items


def set_attachments(attachments: list[dict] | None) -> None:
    """Set file attachments for the current request."""
    _current_attachments_var.set(attachments)


def get_render_items() -> list[dict]:
    """Return accumulated render items from visualization tools."""
    return list(_get_render_list())


def clear_render_items() -> None:
    """Clear render items queue. Called before each request."""
    _render_items_var.set([])


# ── Helpers ──


def _get_study(study_id: str) -> dict | None:
    """Look up LCA study by ID."""
    return LCA_STUDIES.get(study_id)


def _get_company(company_id: str) -> dict | None:
    """Look up company profile by ID."""
    return COMPANY_PROFILES.get(company_id)


def _resolve_attachment(filename: str) -> dict | None:
    """Find an attachment by filename."""
    attachments = _current_attachments_var.get()
    if not attachments:
        return None
    return next((a for a in attachments if a["name"] == filename), None)


def _format_not_found(entity: str, entity_id: str, available: list[str]) -> str:
    """Format a 'not found' error with available IDs."""
    return f"{entity} '{entity_id}' not found. Available: {', '.join(available)}"


def _status_icon(status: str) -> str:
    """Return unicode icon for compliance status."""
    icons = {"pass": "\u2705", "fail": "\u274c", "partial": "\u26a0\ufe0f"}
    return icons.get(status, "\u2753")


# ── ISO Compliance Tools ──


def check_goal_scope(study_id: str) -> str:
    """Check Goal & Scope compliance per ISO 14044 Section 4.2."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    result = check_iso_compliance(study, "goal_and_scope")
    checks = result.get("goal_and_scope", [])

    headers = ["ID", "Requirement", "Status", "Detail"]
    rows = [[c["id"], c["requirement"][:60], c["status"].upper(), c["detail"][:80]] for c in checks]
    pass_count = sum(1 for c in checks if c["status"] == "pass")

    items = _get_render_list()
    title = f"Goal & Scope Compliance: {study_id}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"ISO 14044:2006 Section 4.2 | {pass_count}/{len(checks)} passed",
        }
    )

    return (
        f"Goal & Scope check: {pass_count}/{len(checks)} requirements passed "
        f"for {study_id} (ISO 14044 Section 4.2)"
    )


def check_lci(study_id: str) -> str:
    """Check LCI compliance per ISO 14044 Section 4.3."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    result = check_iso_compliance(study, "lci")
    checks = result.get("lci", [])

    headers = ["ID", "Requirement", "Status", "Detail"]
    rows = [[c["id"], c["requirement"][:60], c["status"].upper(), c["detail"][:80]] for c in checks]
    pass_count = sum(1 for c in checks if c["status"] == "pass")

    items = _get_render_list()
    title = f"LCI Compliance: {study_id}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"ISO 14044:2006 Section 4.3 | {pass_count}/{len(checks)} passed",
        }
    )

    return (
        f"LCI check: {pass_count}/{len(checks)} requirements passed "
        f"for {study_id} (ISO 14044 Section 4.3)"
    )


def check_lcia(study_id: str) -> str:
    """Check LCIA compliance per ISO 14044 Section 4.4."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    result = check_iso_compliance(study, "lcia")
    checks = result.get("lcia", [])

    headers = ["ID", "Requirement", "Status", "Detail"]
    rows = [[c["id"], c["requirement"][:60], c["status"].upper(), c["detail"][:80]] for c in checks]
    pass_count = sum(1 for c in checks if c["status"] == "pass")

    items = _get_render_list()
    title = f"LCIA Compliance: {study_id}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"ISO 14044:2006 Section 4.4 | {pass_count}/{len(checks)} passed",
        }
    )

    return (
        f"LCIA check: {pass_count}/{len(checks)} requirements passed "
        f"for {study_id} (ISO 14044 Section 4.4)"
    )


def check_interpretation(study_id: str) -> str:
    """Check Interpretation compliance per ISO 14044 Section 4.5."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    result = check_iso_compliance(study, "interpretation")
    checks = result.get("interpretation", [])

    headers = ["ID", "Requirement", "Status", "Detail"]
    rows = [[c["id"], c["requirement"][:60], c["status"].upper(), c["detail"][:80]] for c in checks]
    pass_count = sum(1 for c in checks if c["status"] == "pass")

    items = _get_render_list()
    title = f"Interpretation Compliance: {study_id}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"ISO 14044:2006 Section 4.5 | {pass_count}/{len(checks)} passed",
        }
    )

    return (
        f"Interpretation check: {pass_count}/{len(checks)} requirements passed "
        f"for {study_id} (ISO 14044 Section 4.5)"
    )


def check_full_iso_compliance(study_id: str) -> str:
    """Run all ISO 14044 compliance checks at once."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    result = check_iso_compliance(study, "all")

    # Build summary table
    headers = ["Phase", "Passed", "Partial", "Failed", "Total"]
    rows = []
    total_pass = 0
    total_partial = 0
    total_fail = 0
    total_all = 0

    for phase, checks in result.items():
        p = sum(1 for c in checks if c["status"] == "pass")
        partial = sum(1 for c in checks if c["status"] == "partial")
        f = sum(1 for c in checks if c["status"] == "fail")
        t = len(checks)
        total_pass += p
        total_partial += partial
        total_fail += f
        total_all += t

        phase_title = ISO_REQUIREMENTS.get(phase, {}).get("title", phase)
        rows.append([phase_title, str(p), str(partial), str(f), str(t)])

    rows.append(["TOTAL", str(total_pass), str(total_partial), str(total_fail), str(total_all)])

    items = _get_render_list()
    title = f"ISO 14044 Full Compliance: {study_id}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"Study: {study.get('product', study_id)}",
        }
    )

    # Add overall callout
    score = round((total_pass / total_all) * 100, 1) if total_all > 0 else 0
    items[:] = [i for i in items if "calloutContent" not in i]
    if score >= 80:
        items.append(
            {
                "calloutContent": (
                    f"**Overall ISO Compliance: {score}%**\n\n"
                    f"{total_pass} passed, {total_partial} partial, "
                    f"{total_fail} failed out of {total_all} requirements"
                ),
                "variant": "success",
                "title": "ISO 14044 Compliance Summary",
            }
        )
    else:
        items.append(
            {
                "calloutContent": (
                    f"**Overall ISO Compliance: {score}%**\n\n"
                    f"{total_pass} passed, {total_partial} partial, "
                    f"{total_fail} failed out of {total_all} requirements\n\n"
                    f"**Action needed**: Address failed requirements before publication."
                ),
                "variant": "warning",
                "title": "ISO 14044 Compliance Summary",
            }
        )

    return f"Full ISO compliance: {total_pass}/{total_all} passed ({score}%) for {study_id}"


# ── PCR Tools ──


def check_pcr(study_id: str, pcr_category: str) -> str:
    """Check PCR compliance for a study."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    result = check_pcr_compliance(study, pcr_category)
    if "error" in result:
        return result["error"]

    headers = ["Check", "Status", "Detail"]
    rows = [[c["check"], c["status"].upper(), c["detail"][:80]] for c in result["details"]]

    items = _get_render_list()
    title = f"PCR Compliance: {result['pcr_name']}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": (
                f"Study: {study_id} | "
                f"Pass rate: {result['pass_rate']}% ({result['passed']}/{result['total_requirements']})"
            ),
        }
    )

    return (
        f"PCR compliance ({pcr_category}): {result['passed']}/{result['total_requirements']} "
        f"passed ({result['pass_rate']}%) for {study_id}"
    )


def list_pcr_categories() -> str:
    """List available PCR templates."""
    headers = ["Category", "PCR Name", "System Boundary", "Mandatory Categories"]
    rows = []
    for key, pcr in PCR_TEMPLATES.items():
        cats = ", ".join(pcr["mandatory_categories"])
        rows.append([key, pcr["name"], pcr["system_boundary"], cats])

    items = _get_render_list()
    title = "Available PCR Templates"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append({"headers": headers, "rows": rows, "title": title})

    return f"Available PCR categories: {', '.join(PCR_TEMPLATES.keys())}"


# ── Pedoman KLH Tool ──


def check_klh(study_id: str) -> str:
    """Check Pedoman KLH Indonesia compliance."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    result = check_pedoman_klh_compliance(study)

    headers = ["ID", "Check", "Status", "Detail"]
    rows = [
        [c["id"], c["check"][:50], c["status"].upper(), c["detail"][:70]] for c in result["details"]
    ]

    items = _get_render_list()
    title = f"Pedoman KLH Compliance: {study_id}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": (
                f"Pedoman Teknis KLH | "
                f"Pass rate: {result['pass_rate']}% ({result['passed']}/{result['total_checks']})"
            ),
        }
    )

    return (
        f"Pedoman KLH compliance: {result['passed']}/{result['total_checks']} "
        f"passed ({result['pass_rate']}%) for {study_id}"
    )


# ── Data Quality Tool ──


def assess_data_quality(
    study_id: str = "",
    age_years: int = 0,
    geographic_match: str = "",
    technological_match: str = "",
    completeness_pct: float = 0,
) -> str:
    """Calculate data quality score using pedigree matrix."""
    if study_id:
        study = _get_study(study_id)
        if not study:
            return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))
        dqi = study.get("data_quality_indicators", {})
        age_years = dqi.get("age_years", age_years)
        geographic_match = dqi.get("geographic_match", geographic_match)
        technological_match = dqi.get("technological_match", technological_match)
        completeness_pct = dqi.get("completeness_pct", completeness_pct)

    if not geographic_match:
        geographic_match = "global"
    if not technological_match:
        technological_match = "outdated"

    result = calculate_data_quality_score(
        age_years=age_years,
        geographic_match=geographic_match,
        technological_match=technological_match,
        completeness_pct=completeness_pct,
    )

    # Render table
    headers = ["Dimension", "Score (1-5)", "Value"]
    rows = [
        [
            "Time representativeness",
            str(result["breakdown"]["time_representativeness"]["score"]),
            result["breakdown"]["time_representativeness"]["value"],
        ],
        [
            "Geographic representativeness",
            str(result["breakdown"]["geographic_representativeness"]["score"]),
            result["breakdown"]["geographic_representativeness"]["value"],
        ],
        [
            "Technological representativeness",
            str(result["breakdown"]["technological_representativeness"]["score"]),
            result["breakdown"]["technological_representativeness"]["value"],
        ],
        [
            "Completeness",
            str(result["breakdown"]["completeness"]["score"]),
            result["breakdown"]["completeness"]["value"],
        ],
        [
            "OVERALL",
            str(result["overall_score"]),
            result["rating"],
        ],
    ]

    items = _get_render_list()
    label = study_id or "Manual Input"
    title = f"Data Quality Assessment: {label}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": "Pedigree matrix approach (1 = best, 5 = worst)",
        }
    )

    # Callout
    items[:] = [i for i in items if "calloutContent" not in i]
    variant = "success" if result["overall_score"] <= 2.5 else "warning"
    items.append(
        {
            "calloutContent": (
                f"**Data Quality Rating: {result['rating']}** "
                f"(Score: {result['overall_score']}/5)\n\n"
                f"Scale: 1 (Excellent) to 5 (Very Poor)"
            ),
            "variant": variant,
            "title": "Data Quality Assessment",
        }
    )

    return f"Data quality score: {result['overall_score']}/5 ({result['rating']}) for {label}"


# ── Benchmarking Tool ──


def compare_benchmarks_tool(study_id: str, industry: str = "") -> str:
    """Compare LCA results with industry benchmarks."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    # Auto-detect industry from company profile
    if not industry:
        company_id = study.get("company_id")
        company = _get_company(company_id) if company_id else None
        industry = company["industry"] if company else ""

    if not industry:
        return f"Cannot determine industry for {study_id}. Please specify industry parameter."

    result = compare_with_benchmarks(study.get("impact_results", {}), industry)
    if "error" in result:
        return result["error"]

    comparisons = result.get("comparisons", {})
    if not comparisons:
        return f"No matching impact categories for benchmark comparison in {industry}"

    # Render bar chart
    chart_data = []
    for cat, comp in comparisons.items():
        chart_data.append(
            {
                "category": cat,
                "Study": comp["value"],
                "P25": comp["benchmark_p25"],
                "Median": comp["benchmark_median"],
                "P75": comp["benchmark_p75"],
            }
        )

    items = _get_render_list()
    chart_title = f"Impact Benchmark: {study_id} vs {industry}"
    items[:] = [i for i in items if not (i.get("title") == chart_title and "data" in i)]
    items.append(
        {
            "type": "bar",
            "title": chart_title,
            "data": chart_data,
            "options": {"xKey": "category", "series": ["Study", "P25", "Median", "P75"]},
        }
    )

    # Render detail table
    headers = ["Category", "Value", "Median", "Percentile", "Assessment"]
    rows = [
        [
            cat,
            f"{comp['value']}",
            f"{comp['benchmark_median']}",
            comp["percentile_estimate"],
            comp["assessment"],
        ]
        for cat, comp in comparisons.items()
    ]

    table_title = f"Benchmark Details: {study_id}"
    items[:] = [
        i for i in items if not (i.get("title") == table_title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": table_title,
            "caption": f"Source: {result.get('benchmark_source', 'N/A')}",
        }
    )

    return (
        f"Benchmark comparison for {study_id} against {industry}: "
        f"{len(comparisons)} categories compared"
    )


# ── Company / Study Lookup ──


def lookup_company_profile(company_id: str) -> str:
    """Retrieve company profile by ID."""
    company = _get_company(company_id)
    if not company:
        return _format_not_found("Company", company_id, list(COMPANY_PROFILES.keys()))

    headers = ["Field", "Value"]
    rows = [
        ["Company Name", company["company_name"]],
        ["Industry", company["industry"]],
        ["Location", company["location"]],
        ["Products", ", ".join(company["products"])],
        ["Certifications", ", ".join(company["certifications"])],
        ["LCA Studies", ", ".join(company["lca_studies"])],
        ["Contact", company["contact"]],
    ]

    items = _get_render_list()
    title = f"Company Profile: {company_id}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append({"headers": headers, "rows": rows, "title": title})

    return (
        f"Company: {company['company_name']} ({company['industry']}) "
        f"with {len(company['lca_studies'])} LCA study(ies)"
    )


def lookup_lca_study(study_id: str) -> str:
    """Retrieve LCA study data by ID."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    headers = ["Field", "Value"]
    rows = [
        ["Product", study["product"]],
        ["Functional Unit", study["functional_unit"]],
        ["System Boundary", study["system_boundary"]],
        ["Phases Completed", ", ".join(study["phases_completed"])],
        ["Intended Application", study.get("intended_application", "N/A")],
        ["LCA Software", study.get("lca_software", "N/A")],
        ["LCIA Method", study.get("lcia_method", "N/A")],
        ["Allocation", study.get("allocation_method", "N/A")],
        ["Cut-off Criteria", study.get("cut_off_criteria", "N/A")],
        ["Critical Review", "Yes" if study.get("critical_review") else "No"],
        ["Year", str(study.get("year", "N/A"))],
    ]

    # Add impact results
    impacts = study.get("impact_results", {})
    if impacts:
        rows.append(["", ""])
        rows.append(["--- Impact Results ---", ""])
        for cat, val in impacts.items():
            rows.append([cat, f"{val['value']} {val['unit']}"])

    items = _get_render_list()
    title = f"LCA Study: {study_id}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"Product: {study['product']}",
        }
    )

    return (
        f"Study {study_id}: {study['product']} | "
        f"Phases: {', '.join(study['phases_completed'])} | "
        f"Impacts: {len(impacts)} categories"
    )


# ── Cross-cutting Tools ──


def lookup_standard_reference(section: str) -> str:
    """Look up regulation/standard text by section."""
    # Check ISO requirements
    if section in ISO_REQUIREMENTS:
        info = ISO_REQUIREMENTS[section]
        reqs = "\n".join(
            f"- [{r['id']}] {r['text']} ({r['ref']})" for r in info["shall_requirements"]
        )
        content = f"**{info['iso_ref']} - {info['title']}**\n\n**Shall requirements:**\n{reqs}"

        items = _get_render_list()
        items[:] = [i for i in items if "calloutContent" not in i]
        items.append(
            {
                "calloutContent": content,
                "variant": "info",
                "title": f"ISO Standard: {info['title']}",
            }
        )
        return (
            f"{info['iso_ref']} - {info['title']}: {len(info['shall_requirements'])} requirements"
        )

    # Check PCR templates
    if section in PCR_TEMPLATES:
        pcr = PCR_TEMPLATES[section]
        stages = "\n".join(f"- **{k}**: {v}" for k, v in pcr["stages"].items())
        cats = ", ".join(pcr["mandatory_categories"])
        alloc = "\n".join(f"- {r}" for r in pcr["allocation_rules"])
        content = (
            f"**{pcr['name']}**\n\n"
            f"**System boundary:** {pcr['system_boundary']}\n\n"
            f"**Mandatory categories:** {cats}\n\n"
            f"**Life cycle stages:**\n{stages}\n\n"
            f"**Allocation rules:**\n{alloc}"
        )

        items = _get_render_list()
        items[:] = [i for i in items if "calloutContent" not in i]
        items.append(
            {
                "calloutContent": content,
                "variant": "info",
                "title": f"PCR: {pcr['name']}",
            }
        )
        return f"PCR: {pcr['name']} ({pcr['system_boundary']})"

    # Check impact categories
    if section.upper() in IMPACT_CATEGORIES:
        cat = IMPACT_CATEGORIES[section.upper()]
        content = (
            f"**{cat['name']} ({section.upper()})**\n\n"
            f"**Unit:** {cat['unit']}\n"
            f"**Method:** {cat['method']}\n\n"
            f"{cat['description']}"
        )

        items = _get_render_list()
        items[:] = [i for i in items if "calloutContent" not in i]
        items.append(
            {
                "calloutContent": content,
                "variant": "info",
                "title": f"Impact Category: {cat['name']}",
            }
        )
        return f"{cat['name']}: {cat['unit']} ({cat['method']})"

    # Check Pedoman KLH
    if section == "pedoman_klh":
        reqs = "\n".join(f"- [{r['id']}] {r['text']}" for r in PEDOMAN_KLH["requirements"])
        sni = "\n".join(f"- {s}" for s in PEDOMAN_KLH["sni_references"])
        content = (
            f"**{PEDOMAN_KLH['regulation_ref']}**\n\n"
            f"**SNI references:**\n{sni}\n\n"
            f"**Grid emission factor:** {PEDOMAN_KLH['grid_emission_factor']} kg CO2eq/kWh\n\n"
            f"**Requirements:**\n{reqs}"
        )

        items = _get_render_list()
        items[:] = [i for i in items if "calloutContent" not in i]
        items.append(
            {
                "calloutContent": content,
                "variant": "info",
                "title": "Pedoman LCA KLH Indonesia",
            }
        )
        return f"Pedoman KLH: {len(PEDOMAN_KLH['requirements'])} requirements"

    available = (
        list(ISO_REQUIREMENTS.keys())
        + list(PCR_TEMPLATES.keys())
        + list(IMPACT_CATEGORIES.keys())
        + ["pedoman_klh"]
    )
    return f"Section '{section}' not found. Available: {', '.join(available)}"


def analyze_document(filename: str = "") -> str:
    """Read and analyze uploaded LCA documents."""
    attachments = _current_attachments_var.get()
    if not attachments:
        return "No files have been uploaded in this message."

    targets = attachments
    if filename:
        att = _resolve_attachment(filename)
        if not att:
            available = ", ".join(a["name"] for a in attachments)
            return f"File '{filename}' not found. Available: {available}"
        targets = [att]

    parts = []
    for a in targets:
        file_path = a["path"]
        mime = a.get("mime_type", "")
        name = a["name"]

        if mime == "application/pdf":
            raw = PDFSource(path=file_path).extract()
            pages = raw.metadata.get("total_pages", "?")
            parts.append(f"**{name}** ({pages} pages)\n\n{raw.content}")
        elif mime in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        ):
            try:
                import pandas as pd

                sheets = pd.read_excel(file_path, sheet_name=None)
                sheet_parts = []
                for sheet_name, df in sheets.items():
                    total = len(df)
                    preview = df.head(50)
                    md = preview.to_markdown(index=False)
                    header = f"### Sheet: {sheet_name} ({total} rows)"
                    if total > 50:
                        header += " — showing first 50"
                    sheet_parts.append(f"{header}\n\n{md}")
                parts.append(f"**{name}** ({len(sheets)} sheet(s))\n\n" + "\n\n".join(sheet_parts))
            except ImportError:
                parts.append(f"[{name}] Excel support requires pandas + openpyxl")
            except Exception as exc:
                parts.append(f"[{name}] Excel read failed: {exc}")
        elif mime.startswith("text/"):
            content = Path(file_path).read_text(encoding="utf-8")
            parts.append(f"**{name}**\n\n{content}")
        else:
            parts.append(f"[{name}] ({mime}) -- binary file, text extraction not supported")

    return "\n\n---\n\n".join(parts)


def read_excel(
    filename: str,
    sheet_name: str = "",
    columns: list[str] | None = None,
    limit: int = 100,
) -> str:
    """Read Excel file with optional sheet/column filtering, render as ObTable."""
    attachments = _current_attachments_var.get()
    if not attachments:
        return "No files have been uploaded in this message."

    att = _resolve_attachment(filename)
    if not att:
        available = ", ".join(a["name"] for a in attachments)
        return f"File '{filename}' not found. Available: {available}"

    file_path = att["path"]
    mime = att.get("mime_type", "")
    if mime not in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ):
        return f"'{filename}' is not an Excel file (MIME: {mime}). Use analyze_document instead."

    try:
        import pandas as pd

        target_sheet = sheet_name if sheet_name else 0
        df = pd.read_excel(file_path, sheet_name=target_sheet)
    except ImportError:
        return "Excel support requires pandas + openpyxl. Install with: pip install pandas openpyxl"
    except Exception as exc:
        return f"Failed to read Excel file: {exc}"

    if columns:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            return (
                f"Columns not found: {', '.join(missing)}. "
                f"Available: {', '.join(str(c) for c in df.columns)}"
            )
        df = df[columns]

    total = len(df)
    df = df.head(limit)
    headers = [str(c) for c in df.columns]
    rows = [[str(v) for v in row] for row in df.values.tolist()]

    actual_sheet = sheet_name if sheet_name else "Sheet1"
    caption = f"{total} total rows"
    if total > limit:
        caption += f" — showing first {limit}"

    items = _get_render_list()
    title = f"{att['name']} — {actual_sheet}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append({"headers": headers, "rows": rows, "title": title, "caption": caption})

    return f"Excel data loaded: {len(headers)} columns, {len(rows)} rows from '{actual_sheet}'."


def create_compliance_review_form(study_id: str) -> str:
    """Generate interactive compliance review form."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    # Build form fields
    fields: list[dict[str, Any]] = [
        {
            "name": "study_id",
            "label": "Study ID",
            "type": "text",
            "default": study_id,
        },
        {
            "name": "product",
            "label": "Product",
            "type": "text",
            "default": study["product"],
        },
        {
            "name": "functional_unit",
            "label": "Functional Unit",
            "type": "text",
            "default": study["functional_unit"],
        },
        {
            "name": "system_boundary",
            "label": "System Boundary",
            "type": "text",
            "default": study["system_boundary"],
        },
    ]

    # Add phase completion checkboxes
    all_phases = ["goal_and_scope", "lci", "lcia", "interpretation"]
    completed = set(study.get("phases_completed", []))
    fields.extend(
        {
            "name": f"phase_{phase}",
            "label": f"Phase: {phase.replace('_', ' ').title()}",
            "type": "checkbox",
            "default": phase in completed,
        }
        for phase in all_phases
    )

    # Add compliance notes
    fields.append(
        {
            "name": "reviewer_notes",
            "label": "Reviewer Notes",
            "type": "textarea",
            "default": "",
            "placeholder": "Add review comments here...",
        }
    )

    items = _get_render_list()
    items[:] = [i for i in items if "fields" not in i]
    items.append(
        {
            "fields": fields,
            "title": f"Compliance Review: {study_id}",
            "submitLabel": "Submit Review",
            "submitAction": "submit_compliance_review",
        }
    )

    return f"Compliance review form generated for {study_id}"


def generate_compliance_report(
    study_id: str,
    include_pcr: bool = True,
    include_klh: bool = True,
    include_benchmarks: bool = True,
) -> str:
    """Generate a PDF compliance report for an LCA study."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    company_id = study.get("company_id")
    company = _get_company(company_id) if company_id else None
    industry = company["industry"] if company else ""

    # Build report content
    lines = [
        "# LCA Compliance Report",
        f"## Study: {study_id}",
        "",
        f"**Product:** {study['product']}",
        f"**Functional Unit:** {study['functional_unit']}",
        f"**System Boundary:** {study['system_boundary']}",
    ]
    if company:
        lines.append(f"**Company:** {company['company_name']}")
    lines.append("")

    # ISO 14044 Compliance
    iso_result = check_iso_compliance(study, "all")
    lines.append("## ISO 14044 Compliance")
    lines.append("")
    for phase, checks in iso_result.items():
        phase_title = ISO_REQUIREMENTS.get(phase, {}).get("title", phase)
        p = sum(1 for c in checks if c["status"] == "pass")
        lines.append(f"### {phase_title} ({p}/{len(checks)} passed)")
        for c in checks:
            icon = _status_icon(c["status"])
            lines.append(f"- {icon} [{c['id']}] {c['requirement']}")
            lines.append(f"  *{c['detail']}*")
        lines.append("")

    # PCR Compliance
    pcr_result = None
    if include_pcr and industry:
        pcr_result = check_pcr_compliance(study, industry)
        if "details" in pcr_result:
            lines.append(f"## PCR Compliance: {pcr_result.get('pcr_name', industry)}")
            lines.append(
                f"Pass rate: {pcr_result['pass_rate']}% "
                f"({pcr_result['passed']}/{pcr_result['total_requirements']})"
            )
            lines.append("")
            for c in pcr_result["details"]:
                icon = _status_icon(c["status"])
                lines.append(f"- {icon} {c['check']}: {c['detail']}")
            lines.append("")

    # Pedoman KLH
    klh_result = None
    if include_klh:
        klh_result = check_pedoman_klh_compliance(study)
        lines.append("## Pedoman KLH Indonesia")
        lines.append(
            f"Pass rate: {klh_result['pass_rate']}% "
            f"({klh_result['passed']}/{klh_result['total_checks']})"
        )
        lines.append("")
        for c in klh_result["details"]:
            icon = _status_icon(c["status"])
            lines.append(f"- {icon} [{c['id']}] {c['check']}: {c['detail']}")
        lines.append("")

    # Benchmark comparison
    if include_benchmarks and industry:
        bench = compare_with_benchmarks(study.get("impact_results", {}), industry)
        if "comparisons" in bench:
            lines.append(f"## Benchmark Comparison ({industry})")
            for cat, comp in bench["comparisons"].items():
                lines.append(
                    f"- **{cat}**: {comp['value']} {comp['unit']} "
                    f"(median: {comp['benchmark_median']}) -> {comp['assessment']}"
                )
            lines.append("")

    # Overall summary
    summary = generate_compliance_summary(iso_result, pcr_result, klh_result)
    lines.append("## Overall Summary")
    lines.append(f"**Score:** {summary['overall_score']}% ({summary['status']})")
    lines.append(f"**Passed:** {summary['passed']}/{summary['total_checks']}")
    if summary["critical_gaps"]:
        lines.append("")
        lines.append("**Critical Gaps:**")
        lines.extend(f"- {gap}" for gap in summary["critical_gaps"])
    if summary["recommendations"]:
        lines.append("")
        lines.append("**Recommendations:**")
        lines.extend(f"- {rec}" for rec in summary["recommendations"])

    content = "\n".join(lines)

    # Generate PDF
    filename = f"lca_compliance_{study_id.lower().replace('-', '_')}.pdf"
    file_id = f"file-{uuid.uuid4().hex[:8]}"
    upload_dir = Path("./uploads") / file_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(upload_dir / filename)

    generator = PDFGenerator(template="report")
    result = generator.generate(
        content=content,
        output_path=output_path,
        title=f"LCA Compliance Report - {study_id}",
        author="LCA Compliance Checker",
    )

    url = f"/uploads/{file_id}/{filename}"
    items = _get_render_list()
    items[:] = [
        i for i in items if not (i.get("name") == filename and "url" in i and "fields" not in i)
    ]
    items.append(
        {
            "name": filename,
            "url": url,
            "mimeType": "application/pdf",
            "size": result.size_bytes,
        }
    )

    return f"Compliance report generated: {filename} ({result.size_bytes} bytes)"


def generate_markdown_report(
    study_id: str,
    include_pcr: bool = True,
    include_klh: bool = True,
    include_benchmarks: bool = True,
) -> str:
    """Generate a Markdown compliance report for an LCA study."""
    study = _get_study(study_id)
    if not study:
        return _format_not_found("Study", study_id, list(LCA_STUDIES.keys()))

    company_id = study.get("company_id")
    company = _get_company(company_id) if company_id else None
    industry = company["industry"] if company else ""

    # Build report content (same logic as PDF)
    lines = [
        "# LCA Compliance Report",
        f"## Study: {study_id}",
        "",
        f"**Product:** {study['product']}",
        f"**Functional Unit:** {study['functional_unit']}",
        f"**System Boundary:** {study['system_boundary']}",
    ]
    if company:
        lines.append(f"**Company:** {company['company_name']}")
    lines.append("")

    # ISO 14044 Compliance
    iso_result = check_iso_compliance(study, "all")
    lines.append("## ISO 14044 Compliance")
    lines.append("")
    for phase, checks in iso_result.items():
        phase_title = ISO_REQUIREMENTS.get(phase, {}).get("title", phase)
        p = sum(1 for c in checks if c["status"] == "pass")
        lines.append(f"### {phase_title} ({p}/{len(checks)} passed)")
        for c in checks:
            icon = _status_icon(c["status"])
            lines.append(f"- {icon} [{c['id']}] {c['requirement']}")
            lines.append(f"  *{c['detail']}*")
        lines.append("")

    # PCR Compliance
    pcr_result = None
    if include_pcr and industry:
        pcr_result = check_pcr_compliance(study, industry)
        if "details" in pcr_result:
            lines.append(f"## PCR Compliance: {pcr_result.get('pcr_name', industry)}")
            lines.append(
                f"Pass rate: {pcr_result['pass_rate']}% "
                f"({pcr_result['passed']}/{pcr_result['total_requirements']})"
            )
            lines.append("")
            for c in pcr_result["details"]:
                icon = _status_icon(c["status"])
                lines.append(f"- {icon} {c['check']}: {c['detail']}")
            lines.append("")

    # Pedoman KLH
    klh_result = None
    if include_klh:
        klh_result = check_pedoman_klh_compliance(study)
        lines.append("## Pedoman KLH Indonesia")
        lines.append(
            f"Pass rate: {klh_result['pass_rate']}% "
            f"({klh_result['passed']}/{klh_result['total_checks']})"
        )
        lines.append("")
        for c in klh_result["details"]:
            icon = _status_icon(c["status"])
            lines.append(f"- {icon} [{c['id']}] {c['check']}: {c['detail']}")
        lines.append("")

    # Benchmark comparison
    if include_benchmarks and industry:
        bench = compare_with_benchmarks(study.get("impact_results", {}), industry)
        if "comparisons" in bench:
            lines.append(f"## Benchmark Comparison ({industry})")
            for cat, comp in bench["comparisons"].items():
                lines.append(
                    f"- **{cat}**: {comp['value']} {comp['unit']} "
                    f"(median: {comp['benchmark_median']}) -> {comp['assessment']}"
                )
            lines.append("")

    # Overall summary
    summary = generate_compliance_summary(iso_result, pcr_result, klh_result)
    lines.append("## Overall Summary")
    lines.append(f"**Score:** {summary['overall_score']}% ({summary['status']})")
    lines.append(f"**Passed:** {summary['passed']}/{summary['total_checks']}")
    if summary["critical_gaps"]:
        lines.append("")
        lines.append("**Critical Gaps:**")
        lines.extend(f"- {gap}" for gap in summary["critical_gaps"])
    if summary["recommendations"]:
        lines.append("")
        lines.append("**Recommendations:**")
        lines.extend(f"- {rec}" for rec in summary["recommendations"])

    content = "\n".join(lines)

    # Render as ObCodeBlock (markdown preview)
    items = _get_render_list()
    items.append(
        {
            "code": content,
            "language": "markdown",
            "title": f"Compliance Report: {study_id}",
        }
    )

    # Save as .md file
    md_filename = f"lca_compliance_{study_id.lower().replace('-', '_')}.md"
    file_id = f"file-{uuid.uuid4().hex[:8]}"
    upload_dir = Path("./uploads") / file_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_path = upload_dir / md_filename
    output_path.write_text(content, encoding="utf-8")
    size_bytes = output_path.stat().st_size

    url = f"/uploads/{file_id}/{md_filename}"
    items.append(
        {
            "name": md_filename,
            "url": url,
            "mimeType": "text/markdown",
            "size": size_bytes,
        }
    )

    return f"Markdown report generated: {md_filename} ({size_bytes} bytes)"


# ── Visualization Tools ──


def create_chart(chart_type: str, title: str, data: list[dict], options: dict | None = None) -> str:
    """Create a visual chart."""
    item: dict[str, Any] = {"type": chart_type, "title": title, "data": data}
    if options:
        if "xKey" in options:
            item["options"] = item.get("options", {})
            item["options"]["xKey"] = options["xKey"]
        if "series" in options:
            item["options"] = item.get("options", {})
            item["options"]["series"] = options["series"]
        if "width" in options:
            item["width"] = options["width"]
        if "height" in options:
            item["height"] = options["height"]
    items = _get_render_list()
    items[:] = [i for i in items if not (i.get("title") == title and "data" in i)]
    items.append(item)
    return f"Chart created: {chart_type} chart titled '{title}' with {len(data)} data points."


def create_table(title: str, headers: list[str], rows: list[list[str]], caption: str = "") -> str:
    """Display structured tabular data."""
    item: dict[str, Any] = {"headers": headers, "rows": rows, "title": title}
    if caption:
        item["caption"] = caption
    items = _get_render_list()
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(item)
    return f"Table created: '{title}' with {len(headers)} columns and {len(rows)} rows."


def create_callout(content: str, variant: str = "default", title: str = "") -> str:
    """Display a styled callout box."""
    item: dict[str, Any] = {"calloutContent": content, "variant": variant}
    if title:
        item["title"] = title
    items = _get_render_list()
    items[:] = [i for i in items if "calloutContent" not in i]
    items.append(item)
    return f"Callout displayed: '{title or variant}' variant."


# ── RAG Store References (module-level, set by server.py) ──

logger = logging.getLogger(__name__)

_standards_store: Any = None
_documents_store: Any = None


def set_rag_stores(
    standards_store: Any = None,
    documents_store: Any = None,
) -> None:
    """Set PineconeStore references for RAG tools.

    Called by server.py during startup when PINECONE_API_KEY is available.
    """
    global _standards_store, _documents_store
    _standards_store = standards_store
    _documents_store = documents_store


# ── RAG Tools ──


def search_standards(
    query: str,
    source_type: str = "",
    limit: int = 5,
) -> str:
    """Semantic search across LCA standards (ISO, PCR, KLH, impact categories)."""
    if _standards_store is None:
        return "RAG not available. Standards search requires Pinecone configuration."

    from openbench.core.abstractions import Query

    limit = min(max(limit, 1), 10)
    filters = {"source_type": source_type} if source_type else None

    try:
        result = _standards_store.search(Query(text=query, limit=limit, filters=filters))
    except Exception as e:
        logger.exception("Standards search failed")
        return f"Standards search error: {e}"

    if not result.items:
        return f"No standards found matching '{query}'."

    # Render as table
    headers = ["Score", "Source", "ID", "Content"]
    rows = []
    for item in result.items:
        meta = item.get("metadata", {})
        score = f"{item.get('score', 0):.3f}"
        source = meta.get("source_type", "?")
        req_id = meta.get("req_id", meta.get("pcr_category", meta.get("category_code", "-")))
        content = meta.get("content", "")[:120]
        rows.append([score, source, req_id, content])

    items = _get_render_list()
    title = f"Standards Search: {query[:50]}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"{len(result.items)} results | filter: {source_type or 'all'}",
        }
    )

    return f"Found {len(result.items)} standards matching '{query}'."


def search_documents(query: str, limit: int = 5) -> str:
    """Semantic search across uploaded LCA documents."""
    if _documents_store is None:
        return "RAG not available. Document search requires Pinecone configuration."

    from openbench.core.abstractions import Query

    limit = min(max(limit, 1), 10)

    try:
        result = _documents_store.search(Query(text=query, limit=limit))
    except Exception as e:
        logger.exception("Document search failed")
        return f"Document search error: {e}"

    if not result.items:
        return f"No documents found matching '{query}'. Have you indexed files with index_document?"

    headers = ["Score", "Document", "Excerpt"]
    rows = []
    for item in result.items:
        meta = item.get("metadata", {})
        score = f"{item.get('score', 0):.3f}"
        doc_name = meta.get("source_name", meta.get("filename", "unknown"))
        content = meta.get("content", "")[:150]
        rows.append([score, doc_name, content])

    items = _get_render_list()
    title = f"Document Search: {query[:50]}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"{len(result.items)} results",
        }
    )

    return f"Found {len(result.items)} passages matching '{query}'."


def index_document(filename: str = "") -> str:
    """Index uploaded documents into the vector store for semantic search."""
    if _documents_store is None:
        return "RAG not available. Document indexing requires Pinecone configuration."

    attachments = _current_attachments_var.get()
    if not attachments:
        return "No files have been uploaded in this message."

    targets = attachments
    if filename:
        att = _resolve_attachment(filename)
        if not att:
            available = ", ".join(a["name"] for a in attachments)
            return f"File '{filename}' not found. Available: {available}"
        targets = [att]

    from openbench.core.abstractions import RawData

    results = []
    for a in targets:
        file_path = a["path"]
        mime = a.get("mime_type", "")
        name = a["name"]

        # Extract text content
        if mime == "application/pdf":
            raw = PDFSource(path=file_path).extract()
            content = raw.content
        elif mime.startswith("text/"):
            content = Path(file_path).read_text(encoding="utf-8")
        else:
            results.append(f"[{name}] Unsupported format ({mime})")
            continue

        if not content or not content.strip():
            results.append(f"[{name}] Empty content, skipped")
            continue

        raw_data = RawData(
            content=content,
            content_type="text",
            metadata={"source_name": name, "filename": name, "mime_type": mime},
        )

        try:
            _documents_store.index(raw_data)
            results.append(f"[{name}] Indexed successfully")
        except Exception as e:
            logger.exception("Failed to index document: %s", name)
            results.append(f"[{name}] Index error: {e}")

    return "\n".join(results)


# ── Agent Factory ──


def create_lca_agent(
    model: str = "gemini-2.5-flash",
    temperature: float = 0.3,
    enable_planning: bool = True,
    parallel_tool_execution: bool = True,
    memory_store: Any = None,
    session_id: str | None = None,
    rag_enabled: bool = False,
) -> BaseAgent:
    """Create a BaseAgent for LCA compliance checking.

    Args:
        model: Gemini model name.
        temperature: Model temperature (lower for compliance accuracy).
        enable_planning: Enable task decomposition before execution.
        parallel_tool_execution: Enable concurrent tool calls.
        memory_store: Optional MemoryStore for persistent memory.
        session_id: Session ID for persistent memory.
        rag_enabled: Register RAG tools (search_standards, search_documents, index_document).

    Requires GOOGLE_API_KEY environment variable.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is required")

    configure_provider(
        name="gemini-lca-checker",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": api_key},
        settings={"model": model},
        is_default=True,
    )

    agent = BaseAgent(
        goal=(
            "You are an LCA Compliance Checker AI assistant. "
            "Help environmental professionals validate LCA studies against "
            "ISO 14040/14044, PCR requirements, and Pedoman LCA KLH Indonesia. "
            "Be precise with standard references and never fabricate compliance status."
        ),
        model=model,
        temperature=temperature,
        max_iterations=15,
        system_prompt=SYSTEM_PROMPT,
        enable_planning=enable_planning,
        parallel_tool_execution=parallel_tool_execution,
        memory_store=memory_store,
        session_id=session_id,
    )

    # ISO Compliance
    agent.tools.register("check_goal_scope", check_goal_scope, schema=CHECK_GOAL_SCOPE_SCHEMA)
    agent.tools.register("check_lci", check_lci, schema=CHECK_LCI_SCHEMA)
    agent.tools.register("check_lcia", check_lcia, schema=CHECK_LCIA_SCHEMA)
    agent.tools.register(
        "check_interpretation", check_interpretation, schema=CHECK_INTERPRETATION_SCHEMA
    )
    agent.tools.register(
        "check_full_iso_compliance",
        check_full_iso_compliance,
        schema=CHECK_FULL_ISO_COMPLIANCE_SCHEMA,
    )

    # PCR
    agent.tools.register("check_pcr_compliance", check_pcr, schema=CHECK_PCR_COMPLIANCE_SCHEMA)
    agent.tools.register(
        "list_pcr_categories", list_pcr_categories, schema=LIST_PCR_CATEGORIES_SCHEMA
    )

    # Pedoman KLH
    agent.tools.register("check_klh_compliance", check_klh, schema=CHECK_KLH_COMPLIANCE_SCHEMA)

    # Data Quality
    agent.tools.register(
        "assess_data_quality", assess_data_quality, schema=ASSESS_DATA_QUALITY_SCHEMA
    )

    # Benchmarking
    agent.tools.register(
        "compare_benchmarks", compare_benchmarks_tool, schema=COMPARE_BENCHMARKS_SCHEMA
    )

    # Company / Study Lookup
    agent.tools.register(
        "lookup_company_profile", lookup_company_profile, schema=LOOKUP_COMPANY_PROFILE_SCHEMA
    )
    agent.tools.register("lookup_lca_study", lookup_lca_study, schema=LOOKUP_LCA_STUDY_SCHEMA)

    # Cross-cutting
    agent.tools.register(
        "lookup_standard_reference",
        lookup_standard_reference,
        schema=LOOKUP_STANDARD_REFERENCE_SCHEMA,
    )
    agent.tools.register("analyze_document", analyze_document, schema=ANALYZE_DOCUMENT_SCHEMA)
    agent.tools.register("read_excel", read_excel, schema=READ_EXCEL_SCHEMA)
    agent.tools.register(
        "create_compliance_review_form",
        create_compliance_review_form,
        schema=CREATE_COMPLIANCE_REVIEW_FORM_SCHEMA,
    )
    agent.tools.register(
        "generate_compliance_report",
        generate_compliance_report,
        schema=GENERATE_COMPLIANCE_REPORT_SCHEMA,
    )
    agent.tools.register(
        "generate_markdown_report",
        generate_markdown_report,
        schema=GENERATE_MARKDOWN_REPORT_SCHEMA,
    )

    # Visualization
    agent.tools.register("create_chart", create_chart, schema=CREATE_CHART_SCHEMA)
    agent.tools.register("create_table", create_table, schema=CREATE_TABLE_SCHEMA)
    agent.tools.register("create_callout", create_callout, schema=CREATE_CALLOUT_SCHEMA)

    # RAG (optional)
    if rag_enabled:
        agent.tools.register("search_standards", search_standards, schema=SEARCH_STANDARDS_SCHEMA)
        agent.tools.register("search_documents", search_documents, schema=SEARCH_DOCUMENTS_SCHEMA)
        agent.tools.register("index_document", index_document, schema=INDEX_DOCUMENT_SCHEMA)

    return agent
