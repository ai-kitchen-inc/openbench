"""
SEMAP compliance agent for the Lighthouser demo.

Uses BaseAgent with GeminiLLMProvider + 16 domain-specific tools for
HUD SEMAP indicators 2, 3, and 10 compliance checking.

Follows the same pattern as examples/chat/gemini_agent.py:
  - ContextVar render isolation
  - Render queue helpers
  - Agent factory function

Requires:
    - GOOGLE_API_KEY environment variable
    - pip install google-genai
"""

import contextvars
import os
import uuid
from pathlib import Path
from typing import Any

from mock_data import (
    HUD_REGULATIONS,
    MARKET_COMPARABLES,
    PAYMENT_STANDARDS,
    TENANT_DATA,
)
from prompt import SYSTEM_PROMPT
from schemas import (
    ANALYZE_DOCUMENT_SCHEMA,
    CALCULATE_DEDUCTIONS_SCHEMA,
    CALCULATE_HAP_SCHEMA,
    CALCULATE_SEMAP2_SCORE_SCHEMA,
    CALCULATE_TTP_SCHEMA,
    CHECK_MINIMUM_RENT_SCHEMA,
    CREATE_CALLOUT_SCHEMA,
    CREATE_CHART_SCHEMA,
    CREATE_RFTA_REVIEW_FORM_SCHEMA,
    CREATE_TABLE_SCHEMA,
    DETERMINE_ADJUSTED_INCOME_SCHEMA,
    FETCH_MARKET_DATA_SCHEMA,
    GENERATE_SEMAP_REPORT_SCHEMA,
    LOOKUP_HUD_REGULATION_SCHEMA,
    VALIDATE_RENT_BURDEN_SCHEMA,
    VALIDATE_RENT_SCHEMA,
    VERIFY_INCOME_SCHEMA,
)
from semap_engine import (
    calculate_hap as _calc_hap,
)
from semap_engine import (
    calculate_hud_deductions,
    validate_rent_reasonableness,
)
from semap_engine import (
    calculate_ttp as _calc_ttp,
)
from semap_engine import (
    check_rent_burden as _check_burden,
)
from semap_engine import (
    semap2_score as _semap2_score,
)

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


# ── Helper: resolve tenant data ──


def _get_tenant(voucher_id: str) -> dict | None:
    """Look up tenant record by voucher ID."""
    return TENANT_DATA.get(voucher_id)


def _resolve_attachment(filename: str) -> dict | None:
    """Find an attachment by filename."""
    attachments = _current_attachments_var.get()
    if not attachments:
        return None
    return next((a for a in attachments if a["name"] == filename), None)


def _format_not_found(filename: str) -> str:
    """Format a 'file not found' error with available filenames."""
    available = ", ".join(a["name"] for a in (_current_attachments_var.get() or []))
    return f"File '{filename}' not found. Available files: {available}"


# ── SEMAP 2: Rent Reasonableness Tools ──


def validate_rent(
    voucher_id: str,
    proposed_rent: float = 0,
    bedrooms: int = 0,
    area: str = "",
) -> str:
    """Validate rent reasonableness per 24 CFR 982.507."""
    tenant = _get_tenant(voucher_id)
    if not tenant:
        return f"Voucher {voucher_id} not found. Available: {', '.join(TENANT_DATA.keys())}"

    unit = tenant["unit"]
    rent = proposed_rent or unit["contract_rent"]
    beds = bedrooms or unit["bedrooms"]
    market_area = area or unit["area"]

    comps = MARKET_COMPARABLES.get(market_area, {}).get(beds, [])
    if not comps:
        return f"No comparables found for {beds}BR in {market_area}"

    result = validate_rent_reasonableness(rent, comps)

    # Render bar chart
    chart_data = [
        {"unit": f"Comp {i + 1} ({c['address']})", "rent": c["rent"]} for i, c in enumerate(comps)
    ]
    chart_data.insert(0, {"unit": "Proposed", "rent": rent})
    chart_data.append({"unit": "Average", "rent": result["average_comparable"]})

    items = _get_render_list()
    items[:] = [i for i in items if not (i.get("title") == "Rent Comparison" and "data" in i)]
    items.append(
        {
            "type": "bar",
            "title": "Rent Comparison",
            "data": chart_data,
            "options": {"xKey": "unit", "series": ["rent"]},
        }
    )

    # Render callout
    if result["passes"]:
        items[:] = [i for i in items if "calloutContent" not in i]
        items.append(
            {
                "calloutContent": (
                    f"**PASSED** - Proposed rent ${rent:.0f} is at "
                    f"{result['ratio']:.1%} of market average ${result['average_comparable']:.0f} "
                    f"(24 CFR 982.507)"
                ),
                "variant": "success",
                "title": "Rent Reasonableness",
            }
        )
    else:
        items[:] = [i for i in items if "calloutContent" not in i]
        items.append(
            {
                "calloutContent": (
                    f"**FAILED** - Proposed rent ${rent:.0f} exceeds market average "
                    f"${result['average_comparable']:.0f} by "
                    f"{(result['ratio'] - 1) * 100:.1f}% (24 CFR 982.507)"
                ),
                "variant": "warning",
                "title": "Rent Reasonableness",
            }
        )

    status = "PASSED" if result["passes"] else "FAILED"
    return (
        f"Rent reasonableness {status}: ${rent:.0f} proposed vs "
        f"${result['average_comparable']:.0f} market average "
        f"(ratio: {result['ratio']:.3f})"
    )


def fetch_market_data(area: str, bedrooms: int) -> str:
    """Retrieve comparable rental data for an area."""
    comps = MARKET_COMPARABLES.get(area, {}).get(bedrooms, [])
    if not comps:
        return f"No comparables found for {bedrooms}BR in {area}"

    # Render table
    headers = ["Address", "Rent", "Sq Ft", "Condition"]
    rows = [[c["address"], f"${c['rent']:,.0f}", str(c["sqft"]), c["condition"]] for c in comps]
    avg_rent = sum(c["rent"] for c in comps) / len(comps)
    rows.append(["Average", f"${avg_rent:,.0f}", "--", "--"])

    items = _get_render_list()
    title = f"Market Comparables: {area} ({bedrooms}BR)"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append({"headers": headers, "rows": rows, "title": title})

    return (
        f"Found {len(comps)} comparable {bedrooms}BR units in {area}. "
        f"Average rent: ${avg_rent:,.0f}"
    )


def calculate_semap2_score(total_units: int, passed_units: int) -> str:
    """Calculate SEMAP Indicator 2 score per 24 CFR 985.3."""
    result = _semap2_score(total_units, passed_units)

    # Render callout
    items = _get_render_list()
    if result["score"] == 20:
        items[:] = [i for i in items if "calloutContent" not in i]
        items.append(
            {
                "calloutContent": (
                    f"**SEMAP 2 Score: {result['score']}/{result['max_score']}**\n\n"
                    f"Pass rate: {result['pass_rate']}% (threshold: {result['threshold']}%)\n"
                    f"{result['passed_units']}/{result['total_units']} units passed"
                ),
                "variant": "success",
                "title": "SEMAP Indicator 2 - Rent Reasonableness",
            }
        )
    else:
        items[:] = [i for i in items if "calloutContent" not in i]
        items.append(
            {
                "calloutContent": (
                    f"**SEMAP 2 Score: {result['score']}/{result['max_score']}**\n\n"
                    f"Pass rate: {result['pass_rate']}% (threshold: {result['threshold']}%)\n"
                    f"{result['passed_units']}/{result['total_units']} units passed\n\n"
                    f"**Action needed**: Pass rate below {result['threshold']}% threshold."
                ),
                "variant": "warning",
                "title": "SEMAP Indicator 2 - Rent Reasonableness",
            }
        )

    return (
        f"SEMAP 2 score: {result['score']}/{result['max_score']} "
        f"(pass rate: {result['pass_rate']}%)"
    )


# ── SEMAP 3: Income Determination Tools ──


def verify_income(voucher_id: str, income_sources: list[dict] | None = None) -> str:
    """Verify income sources for a voucher holder per 24 CFR 5.609."""
    tenant = _get_tenant(voucher_id)
    if not tenant:
        return f"Voucher {voucher_id} not found. Available: {', '.join(TENANT_DATA.keys())}"

    sources = income_sources or tenant["income_sources"]
    total = sum(s["annual"] for s in sources)

    # Render table
    headers = ["Source", "Details", "Annual Amount"]
    rows = []
    for s in sources:
        details = s.get("employer", s.get("payer", "--"))
        rows.append([s["source"], str(details), f"${s['annual']:,.0f}"])
    rows.append(["TOTAL", "--", f"${total:,.0f}"])

    items = _get_render_list()
    title = f"Income Verification: {voucher_id}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"Tenant: {tenant['tenant_name']} | Household size: {tenant['household_size']}",
        }
    )

    return (
        f"Income verified for {tenant['tenant_name']} ({voucher_id}): "
        f"{len(sources)} sources totaling ${total:,.0f}/year"
    )


def calculate_deductions(
    gross_income: float,
    dependents: int = 0,
    elderly_disabled: bool = False,
    medical_expenses: float = 0,
    childcare_expenses: float = 0,
    disability_assistance: float = 0,
) -> str:
    """Calculate HUD-allowable deductions per 24 CFR 5.611."""
    result = calculate_hud_deductions(
        gross_income=gross_income,
        dependents=dependents,
        elderly_disabled=elderly_disabled,
        medical_expenses=medical_expenses,
        childcare_expenses=childcare_expenses,
        disability_assistance=disability_assistance,
    )

    # Render table
    headers = ["Deduction Type", "Amount", "CFR Reference"]
    rows = [
        [
            f"Dependent deduction ({dependents} x $480)",
            f"${result['dependent_deduction']:,.0f}",
            "24 CFR 5.611(a)",
        ],
        [
            "Elderly/Disabled deduction",
            f"${result['elderly_disabled_deduction']:,.0f}",
            "24 CFR 5.611(b)",
        ],
        [
            "Medical expenses (excess over 3%)",
            f"${result['medical_deduction']:,.2f}",
            "24 CFR 5.611(c)",
        ],
        [
            "Childcare deduction",
            f"${result['childcare_deduction']:,.0f}",
            "24 CFR 5.611(d)",
        ],
        [
            "Disability assistance",
            f"${result['disability_assistance_deduction']:,.0f}",
            "24 CFR 5.611(e)",
        ],
        ["TOTAL DEDUCTIONS", f"${result['total_deductions']:,.2f}", "--"],
        ["ADJUSTED INCOME", f"${result['adjusted_income']:,.2f}", "--"],
    ]

    items = _get_render_list()
    title = "HUD Deductions (24 CFR 5.611)"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"Gross income: ${gross_income:,.0f}",
        }
    )

    return (
        f"Deductions calculated: ${result['total_deductions']:,.2f} total. "
        f"Adjusted income: ${result['adjusted_income']:,.2f}"
    )


def determine_adjusted_income(voucher_id: str) -> str:
    """Full income determination pipeline for a voucher."""
    tenant = _get_tenant(voucher_id)
    if not tenant:
        return f"Voucher {voucher_id} not found. Available: {', '.join(TENANT_DATA.keys())}"

    # Step 1: Income verification
    sources = tenant["income_sources"]
    total_income = sum(s["annual"] for s in sources)

    # Step 2: Calculate deductions
    result = calculate_hud_deductions(
        gross_income=total_income,
        dependents=tenant["dependents"],
        elderly_disabled=tenant["elderly_disabled"],
        medical_expenses=tenant["medical_expenses"],
        childcare_expenses=tenant["childcare_expenses"],
        disability_assistance=tenant["disability_assistance"],
    )

    # Render summary table
    headers = ["Item", "Amount"]
    rows = [
        ["Gross Annual Income", f"${total_income:,.0f}"],
    ]
    rows.extend([[f"  - {s['source']}", f"${s['annual']:,.0f}"] for s in sources])
    rows.append(["", ""])
    rows.append(["Dependent Deduction", f"-${result['dependent_deduction']:,.0f}"])
    rows.append(["Elderly/Disabled Deduction", f"-${result['elderly_disabled_deduction']:,.0f}"])
    if result["medical_deduction"] > 0:
        rows.append(["Medical Expense Deduction", f"-${result['medical_deduction']:,.2f}"])
    if result["childcare_deduction"] > 0:
        rows.append(["Childcare Deduction", f"-${result['childcare_deduction']:,.0f}"])
    if result["disability_assistance_deduction"] > 0:
        rows.append(
            [
                "Disability Assistance",
                f"-${result['disability_assistance_deduction']:,.0f}",
            ]
        )
    rows.append(["TOTAL DEDUCTIONS", f"-${result['total_deductions']:,.2f}"])
    rows.append(["ADJUSTED ANNUAL INCOME", f"${result['adjusted_income']:,.2f}"])

    items = _get_render_list()
    title = f"Income Determination: {voucher_id}"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": f"Tenant: {tenant['tenant_name']} | Household: {tenant['household_size']}",
        }
    )

    return (
        f"Income determined for {tenant['tenant_name']} ({voucher_id}): "
        f"Gross ${total_income:,.0f} -> Adjusted ${result['adjusted_income']:,.2f}"
    )


# ── SEMAP 10: Tenant Rent / TTP Tools ──


def calculate_ttp(
    annual_adjusted_income: float,
    annual_gross_income: float,
    welfare_rent: float = 0,
) -> str:
    """Calculate Total Tenant Payment per 24 CFR 5.628."""
    result = _calc_ttp(
        adjusted_income=annual_adjusted_income,
        gross_income=annual_gross_income,
        welfare_rent=welfare_rent,
    )

    # Render table showing all 4 methods
    check = "\u2713"  # checkmark
    headers = ["Method", "Calculation", "Monthly Amount", ""]
    rows = [
        [
            "30% Adjusted",
            f"${annual_adjusted_income / 12:,.2f} x 0.30",
            f"${result['30pct_adjusted']:,.2f}",
            check if result["selected_method"] == "30% adjusted" else "",
        ],
        [
            "10% Gross",
            f"${annual_gross_income / 12:,.2f} x 0.10",
            f"${result['10pct_gross']:,.2f}",
            check if result["selected_method"] == "10% gross" else "",
        ],
        [
            "Welfare Rent",
            "--",
            f"${result['welfare_rent']:,.2f}",
            check if result["selected_method"] == "welfare rent" else "",
        ],
        [
            "Minimum Rent",
            "PHA minimum",
            f"${result['minimum_rent']:,.2f}",
            check if result["selected_method"] == "minimum rent" else "",
        ],
        [
            "TTP (Greatest)",
            result["selected_method"],
            f"${result['selected_ttp']:,.2f}",
            check,
        ],
    ]

    items = _get_render_list()
    title = "TTP Calculation (24 CFR 5.628)"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(
        {
            "headers": headers,
            "rows": rows,
            "title": title,
            "caption": "TTP = Greatest of all 4 methods",
        }
    )

    return (
        f"TTP calculated: ${result['selected_ttp']:,.2f}/month "
        f"(method: {result['selected_method']})"
    )


def calculate_hap(
    payment_standard: float,
    ttp: float,
    rent: float = 0,
    utility_allowance: float = 0,
) -> str:
    """Calculate Housing Assistance Payment per 24 CFR 982.505."""
    result = _calc_hap(
        payment_standard=payment_standard,
        ttp=ttp,
        rent=rent,
        utility_allowance=utility_allowance,
    )

    # Render table
    headers = ["Component", "Amount"]
    rows = [
        ["Payment Standard", f"${result['payment_standard']:,.2f}"],
        ["Total Tenant Payment (TTP)", f"${result['ttp']:,.2f}"],
        ["Contract Rent", f"${result['contract_rent']:,.2f}"],
        ["Utility Allowance", f"${result['utility_allowance']:,.2f}"],
        ["Gross Rent (Rent + UA)", f"${result['gross_rent']:,.2f}"],
        ["", ""],
        ["HAP from Standard (PS - TTP)", f"${result['hap_from_standard']:,.2f}"],
        ["HAP from Rent (GR - TTP)", f"${result['hap_from_rent']:,.2f}"],
        ["HAP (Lesser)", f"${result['hap']:,.2f}"],
        ["Tenant Share (GR - HAP)", f"${result['tenant_share']:,.2f}"],
    ]

    items = _get_render_list()
    title = "HAP Calculation (24 CFR 982.505)"
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append({"headers": headers, "rows": rows, "title": title})

    return (
        f"HAP calculated: ${result['hap']:,.2f}/month. "
        f"Tenant share: ${result['tenant_share']:,.2f}/month"
    )


def validate_rent_burden(
    proposed_rent: float,
    utility_allowance: float,
    hap: float,
    annual_adjusted_income: float,
) -> str:
    """Check rent burden per 24 CFR 982.508."""
    result = _check_burden(
        rent=proposed_rent,
        utility_allowance=utility_allowance,
        hap=hap,
        adjusted_income=annual_adjusted_income,
    )

    # Render callout
    items = _get_render_list()
    items[:] = [i for i in items if "calloutContent" not in i]

    if result["passes"]:
        items.append(
            {
                "calloutContent": (
                    f"**PASSED** - Rent burden: {result['burden_pct']}% "
                    f"(threshold: {result['threshold_pct']}%)\n\n"
                    f"Family share: ${result['family_share']:,.2f}/month\n"
                    f"Adjusted monthly income: ${result['monthly_adjusted_income']:,.2f}"
                ),
                "variant": "success",
                "title": "Rent Burden Check (24 CFR 982.508)",
            }
        )
    else:
        items.append(
            {
                "calloutContent": (
                    f"**FAILED** - Rent burden: {result['burden_pct']}% "
                    f"exceeds {result['threshold_pct']}% threshold\n\n"
                    f"Family share: ${result['family_share']:,.2f}/month\n"
                    f"Adjusted monthly income: ${result['monthly_adjusted_income']:,.2f}\n\n"
                    f"**Unit cannot be approved at initial occupancy per 24 CFR 982.508.**"
                ),
                "variant": "warning",
                "title": "Rent Burden Check (24 CFR 982.508)",
            }
        )

    status = "PASSED" if result["passes"] else "FAILED"
    return f"Rent burden {status}: {result['burden_pct']}% (threshold: {result['threshold_pct']}%)"


def check_minimum_rent(ttp: float, has_hardship: bool = False) -> str:
    """Check minimum rent applicability per 24 CFR 5.630."""
    minimum = 50.0
    applies = ttp < minimum

    items = _get_render_list()
    items[:] = [i for i in items if "calloutContent" not in i]

    if not applies:
        items.append(
            {
                "calloutContent": (
                    f"TTP of ${ttp:,.2f} exceeds minimum rent of ${minimum:,.2f}. "
                    f"No minimum rent adjustment needed."
                ),
                "variant": "success",
                "title": "Minimum Rent Check (24 CFR 5.630)",
            }
        )
        return f"TTP ${ttp:,.2f} exceeds minimum ${minimum:,.2f}. No adjustment needed."

    if has_hardship:
        items.append(
            {
                "calloutContent": (
                    f"TTP of ${ttp:,.2f} is below minimum rent of ${minimum:,.2f}.\n\n"
                    f"**Hardship exemption applies.** Minimum rent suspended for 90 days "
                    f"pending determination (24 CFR 5.630)."
                ),
                "variant": "info",
                "title": "Minimum Rent - Hardship Exemption",
            }
        )
        return (
            f"TTP ${ttp:,.2f} below minimum ${minimum:,.2f}. "
            f"Hardship exemption applied -- 90-day suspension."
        )

    items.append(
        {
            "calloutContent": (
                f"TTP of ${ttp:,.2f} is below minimum rent of ${minimum:,.2f}.\n\n"
                f"Minimum rent of ${minimum:,.2f} applies. Family should be screened "
                f"for hardship exemption eligibility."
            ),
            "variant": "warning",
            "title": "Minimum Rent Applied (24 CFR 5.630)",
        }
    )
    return (
        f"TTP ${ttp:,.2f} below minimum ${minimum:,.2f}. Minimum rent of ${minimum:,.2f} applies."
    )


# ── Cross-cutting Tools ──


def lookup_hud_regulation(section: str, topic: str = "") -> str:
    """Look up HUD regulation text by section."""
    reg = HUD_REGULATIONS.get(section)
    if not reg:
        available = ", ".join(HUD_REGULATIONS.keys())
        return f"Section '{section}' not found. Available: {available}"

    # Render callout with regulation info
    key_points = "\n".join(f"- {p}" for p in reg["key_points"])
    content = (
        f"**{reg['cfr']} - {reg['title']}**\n\n{reg['summary']}\n\n**Key Points:**\n{key_points}"
    )

    items = _get_render_list()
    items[:] = [i for i in items if "calloutContent" not in i]
    items.append(
        {
            "calloutContent": content,
            "variant": "info",
            "title": f"HUD Regulation: {reg['title']}",
        }
    )

    if topic:
        return f"{reg['cfr']} - {reg['title']}: {reg['summary']} (Topic: {topic})"
    return f"{reg['cfr']} - {reg['title']}: {reg['summary']}"


def analyze_document(filename: str = "") -> str:
    """Read and analyze uploaded HUD documents."""
    attachments = _current_attachments_var.get()
    if not attachments:
        return "No files have been uploaded in this message."

    targets = attachments
    if filename:
        att = _resolve_attachment(filename)
        if not att:
            return _format_not_found(filename)
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
        elif mime.startswith("text/"):
            content = Path(file_path).read_text(encoding="utf-8")
            parts.append(f"**{name}**\n\n{content}")
        else:
            parts.append(f"[{name}] ({mime}) -- binary file, text extraction not supported")

    return "\n\n---\n\n".join(parts)


def generate_semap_report(voucher_id: str, indicators: list[str] | None = None) -> str:
    """Generate a PDF SEMAP compliance report for a voucher."""
    tenant = _get_tenant(voucher_id)
    if not tenant:
        return f"Voucher {voucher_id} not found. Available: {', '.join(TENANT_DATA.keys())}"

    selected = indicators or ["2", "3", "10"]
    unit = tenant["unit"]

    # Build report content
    lines = [
        "# SEMAP Compliance Report",
        f"## Voucher: {voucher_id}",
        "",
        f"**Tenant:** {tenant['tenant_name']}",
        f"**Household Size:** {tenant['household_size']}",
        f"**Unit:** {unit['address']}",
        f"**Bedrooms:** {unit['bedrooms']} | **Area:** {unit['area']}",
        "",
    ]

    # Income determination (SEMAP 3)
    if "3" in selected:
        sources = tenant["income_sources"]
        total_income = sum(s["annual"] for s in sources)
        deductions = calculate_hud_deductions(
            gross_income=total_income,
            dependents=tenant["dependents"],
            elderly_disabled=tenant["elderly_disabled"],
            medical_expenses=tenant["medical_expenses"],
            childcare_expenses=tenant["childcare_expenses"],
            disability_assistance=tenant["disability_assistance"],
        )
        lines.extend(
            [
                "## SEMAP 3: Income Determination",
                "",
                f"**Gross Annual Income:** ${total_income:,.0f}",
            ]
        )
        lines.extend([f"- {s['source']}: ${s['annual']:,.0f}" for s in sources])
        lines.extend(
            [
                "",
                f"**Deductions:** ${deductions['total_deductions']:,.2f}",
                f"- Dependent: ${deductions['dependent_deduction']:,.0f}",
                f"- Elderly/Disabled: ${deductions['elderly_disabled_deduction']:,.0f}",
                f"- Medical: ${deductions['medical_deduction']:,.2f}",
                f"- Childcare: ${deductions['childcare_deduction']:,.0f}",
                "",
                f"**Adjusted Annual Income:** ${deductions['adjusted_income']:,.2f}",
                "",
            ]
        )
        adjusted = deductions["adjusted_income"]
    else:
        total_income = tenant["gross_income"]
        adjusted = total_income  # Fallback

    # TTP / HAP (SEMAP 10)
    if "10" in selected:
        ttp_result = _calc_ttp(adjusted_income=adjusted, gross_income=total_income)
        ps = PAYMENT_STANDARDS.get(unit["area"], {}).get(unit["bedrooms"], 1500)
        hap_result = _calc_hap(
            payment_standard=ps,
            ttp=ttp_result["selected_ttp"],
            rent=unit["contract_rent"],
            utility_allowance=unit["utility_allowance"],
        )
        burden = _check_burden(
            rent=unit["contract_rent"],
            utility_allowance=unit["utility_allowance"],
            hap=hap_result["hap"],
            adjusted_income=adjusted,
        )
        lines.extend(
            [
                "## SEMAP 10: Tenant Rent Calculation",
                "",
                f"**TTP:** ${ttp_result['selected_ttp']:,.2f}/month ({ttp_result['selected_method']})",
                f"- 30% Adjusted: ${ttp_result['30pct_adjusted']:,.2f}",
                f"- 10% Gross: ${ttp_result['10pct_gross']:,.2f}",
                f"- Welfare Rent: ${ttp_result['welfare_rent']:,.2f}",
                f"- Minimum Rent: ${ttp_result['minimum_rent']:,.2f}",
                "",
                f"**HAP:** ${hap_result['hap']:,.2f}/month",
                f"**Tenant Share:** ${hap_result['tenant_share']:,.2f}/month",
                "",
                f"**Rent Burden:** {burden['burden_pct']}% "
                f"({'PASSED' if burden['passes'] else 'FAILED'} - threshold 40%)",
                "",
            ]
        )

    # Rent Reasonableness (SEMAP 2)
    if "2" in selected:
        comps = MARKET_COMPARABLES.get(unit["area"], {}).get(unit["bedrooms"], [])
        rr = validate_rent_reasonableness(unit["contract_rent"], comps)
        lines.extend(
            [
                "## SEMAP 2: Rent Reasonableness",
                "",
                f"**Proposed Rent:** ${unit['contract_rent']:,.0f}",
                f"**Market Average:** ${rr['average_comparable']:,.0f}",
                f"**Ratio:** {rr['ratio']:.3f}",
                f"**Result:** {'PASSED' if rr['passes'] else 'FAILED'}",
                "",
            ]
        )

    content = "\n".join(lines)

    # Generate PDF
    filename = f"semap_report_{voucher_id.lower().replace('-', '_')}.pdf"
    file_id = f"file-{uuid.uuid4().hex[:8]}"
    upload_dir = Path("./uploads") / file_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(upload_dir / filename)

    generator = PDFGenerator(template="report")
    result = generator.generate(
        content=content,
        output_path=output_path,
        title=f"SEMAP Compliance Report - {voucher_id}",
        author="Lighthouser AI",
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

    return f"SEMAP report generated: {filename} ({result.size_bytes} bytes)"


# ── Visualization Tools (reused pattern from chat demo) ──


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


# ── RFTA Interactive Form ──


def create_rfta_review_form(
    voucher_id: str = "",
    tenant_name: str = "",
    proposed_rent: float = 0,
    utility_allowance: float = 0,
    bedrooms: int = 2,
    area: str = "downtown",
    lease_start_date: str = "",
    household_size: int = 1,
    dependents: int = 0,
    elderly_disabled: bool = False,
    annual_gross_income: float = 0,
    medical_expenses: float = 0,
    childcare_expenses: float = 0,
    disability_assistance: float = 0,
) -> str:
    """Generate a pre-filled RFTA review form for user confirmation.

    The form is rendered as an A2UI surface with editable fields.
    On submit, the `submit_rfta_review` action handler runs SEMAP calculations.
    """
    form_content: dict[str, Any] = {
        "title": "RFTA Review Form",
        "submitLabel": "Run SEMAP Review",
        "submitAction": "submit_rfta_review",
        "fields": [
            {
                "name": "voucher_id",
                "type": "text",
                "label": "Voucher ID",
                "required": True,
                "default": voucher_id,
                "placeholder": "e.g. V-2024-001",
            },
            {
                "name": "tenant_name",
                "type": "text",
                "label": "Tenant Name",
                "required": True,
                "default": tenant_name,
            },
            {
                "name": "proposed_rent",
                "type": "number",
                "label": "Proposed Monthly Rent ($)",
                "required": True,
                "default": proposed_rent,
                "min": 0,
            },
            {
                "name": "utility_allowance",
                "type": "number",
                "label": "Utility Allowance ($)",
                "default": utility_allowance,
                "min": 0,
            },
            {
                "name": "bedrooms",
                "type": "number",
                "label": "Bedrooms",
                "required": True,
                "default": bedrooms,
                "min": 1,
                "max": 6,
            },
            {
                "name": "area",
                "type": "select",
                "label": "Market Area",
                "required": True,
                "default": area,
                "options": ["downtown", "suburban_east", "suburban_west"],
            },
            {
                "name": "lease_start_date",
                "type": "date",
                "label": "Lease Start Date",
                "default": lease_start_date,
            },
            {
                "name": "household_size",
                "type": "number",
                "label": "Household Size",
                "required": True,
                "default": household_size,
                "min": 1,
            },
            {
                "name": "dependents",
                "type": "number",
                "label": "Dependents",
                "default": dependents,
                "min": 0,
            },
            {
                "name": "elderly_disabled",
                "type": "checkbox",
                "label": "Elderly (62+) or Disabled Head/Spouse",
                "default": elderly_disabled,
            },
            {
                "name": "annual_gross_income",
                "type": "number",
                "label": "Annual Gross Income ($)",
                "required": True,
                "default": annual_gross_income,
                "min": 0,
            },
            {
                "name": "medical_expenses",
                "type": "number",
                "label": "Annual Medical Expenses ($)",
                "default": medical_expenses,
                "min": 0,
                "description": "Unreimbursed medical expenses (elderly/disabled only)",
            },
            {
                "name": "childcare_expenses",
                "type": "number",
                "label": "Annual Childcare Expenses ($)",
                "default": childcare_expenses,
                "min": 0,
                "description": "Childcare for children under 13",
            },
            {
                "name": "disability_assistance",
                "type": "number",
                "label": "Annual Disability Assistance ($)",
                "default": disability_assistance,
                "min": 0,
            },
        ],
    }

    items = _get_render_list()
    # Remove any previous form
    items[:] = [i for i in items if "fields" not in i]
    items.append(form_content)

    filled_count = sum(
        1
        for v in [
            voucher_id,
            tenant_name,
            proposed_rent,
            annual_gross_income,
        ]
        if v
    )
    return (
        f"RFTA review form generated with {filled_count}/4 key fields pre-filled. "
        f"The user can review and edit before running SEMAP calculations."
    )


# ── Agent Factory ──


def create_semap_agent(
    model: str = "gemini-2.5-flash",
    temperature: float = 0.3,
    enable_planning: bool = True,
    parallel_tool_execution: bool = True,
    memory_store: Any = None,
    session_id: str | None = None,
) -> BaseAgent:
    """Create a BaseAgent for SEMAP compliance checking.

    Args:
        model: Gemini model name.
        temperature: Model temperature (lower for compliance accuracy).
        enable_planning: Enable task decomposition before execution.
        parallel_tool_execution: Enable concurrent tool calls.
        memory_store: Optional MemoryStore for persistent memory.
        session_id: Session ID for persistent memory.

    Requires GOOGLE_API_KEY environment variable.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is required")

    configure_provider(
        name="gemini-lighthouser",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": api_key},
        settings={"model": model},
        is_default=True,
    )

    agent = BaseAgent(
        goal=(
            "You are Lighthouser AI, a SEMAP compliance copilot for PHAs. "
            "Help housing specialists validate HCV compliance by running "
            "SEMAP indicators 2, 3, and 10. Be precise with HUD calculations."
        ),
        model=model,
        temperature=temperature,
        max_iterations=10,
        system_prompt=SYSTEM_PROMPT,
        enable_planning=enable_planning,
        parallel_tool_execution=parallel_tool_execution,
        memory_store=memory_store,
        session_id=session_id,
    )

    # SEMAP 2: Rent Reasonableness
    agent.tools.register("validate_rent", validate_rent, schema=VALIDATE_RENT_SCHEMA)
    agent.tools.register("fetch_market_data", fetch_market_data, schema=FETCH_MARKET_DATA_SCHEMA)
    agent.tools.register(
        "calculate_semap2_score",
        calculate_semap2_score,
        schema=CALCULATE_SEMAP2_SCORE_SCHEMA,
    )

    # SEMAP 3: Income Determination
    agent.tools.register("verify_income", verify_income, schema=VERIFY_INCOME_SCHEMA)
    agent.tools.register(
        "calculate_deductions", calculate_deductions, schema=CALCULATE_DEDUCTIONS_SCHEMA
    )
    agent.tools.register(
        "determine_adjusted_income",
        determine_adjusted_income,
        schema=DETERMINE_ADJUSTED_INCOME_SCHEMA,
    )

    # SEMAP 10: Tenant Rent / TTP
    agent.tools.register("calculate_ttp", calculate_ttp, schema=CALCULATE_TTP_SCHEMA)
    agent.tools.register("calculate_hap", calculate_hap, schema=CALCULATE_HAP_SCHEMA)
    agent.tools.register(
        "validate_rent_burden", validate_rent_burden, schema=VALIDATE_RENT_BURDEN_SCHEMA
    )
    agent.tools.register("check_minimum_rent", check_minimum_rent, schema=CHECK_MINIMUM_RENT_SCHEMA)

    # Cross-cutting
    agent.tools.register(
        "lookup_hud_regulation", lookup_hud_regulation, schema=LOOKUP_HUD_REGULATION_SCHEMA
    )
    agent.tools.register("analyze_document", analyze_document, schema=ANALYZE_DOCUMENT_SCHEMA)
    agent.tools.register(
        "create_rfta_review_form",
        create_rfta_review_form,
        schema=CREATE_RFTA_REVIEW_FORM_SCHEMA,
    )
    agent.tools.register(
        "generate_semap_report", generate_semap_report, schema=GENERATE_SEMAP_REPORT_SCHEMA
    )

    # Visualization
    agent.tools.register("create_chart", create_chart, schema=CREATE_CHART_SCHEMA)
    agent.tools.register("create_table", create_table, schema=CREATE_TABLE_SCHEMA)
    agent.tools.register("create_callout", create_callout, schema=CREATE_CALLOUT_SCHEMA)

    return agent
