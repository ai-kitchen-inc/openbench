"""Tool schemas for the Lighthouser SEMAP compliance agent.

Each schema follows the OpenAI function-calling format used by BaseAgent's
ToolExecutor to describe tool parameters to the LLM.

17 tools grouped by SEMAP indicator.
"""

from typing import Any

# ── SEMAP 2: Rent Reasonableness ──

VALIDATE_RENT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "validate_rent",
        "description": (
            "Validate rent reasonableness per 24 CFR 982.507. Compares proposed "
            "contract rent against comparable unassisted units in the area. "
            "Returns comparison data and renders a bar chart of rents."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "voucher_id": {
                    "type": "string",
                    "description": "Voucher ID (e.g. 'V-2024-001') to look up unit details",
                },
                "proposed_rent": {
                    "type": "number",
                    "description": (
                        "Proposed monthly rent. If omitted, uses the contract rent "
                        "from the voucher record."
                    ),
                },
                "bedrooms": {
                    "type": "integer",
                    "description": "Number of bedrooms (auto-detected from voucher if omitted)",
                },
                "area": {
                    "type": "string",
                    "description": (
                        "Market area: 'downtown', 'suburban_east', or 'suburban_west'. "
                        "Auto-detected from voucher if omitted."
                    ),
                },
            },
            "required": ["voucher_id"],
        },
    },
}

FETCH_MARKET_DATA_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "fetch_market_data",
        "description": (
            "Retrieve comparable unassisted rental data for a specific area "
            "and bedroom count. Returns a table of comparable units with "
            "address, rent, size, and condition."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "area": {
                    "type": "string",
                    "enum": ["downtown", "suburban_east", "suburban_west"],
                    "description": "Market area to search",
                },
                "bedrooms": {
                    "type": "integer",
                    "description": "Number of bedrooms (1-4)",
                },
            },
            "required": ["area", "bedrooms"],
        },
    },
}

CALCULATE_SEMAP2_SCORE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "calculate_semap2_score",
        "description": (
            "Calculate SEMAP Indicator 2 (Rent Reasonableness) score per "
            "24 CFR 985.3. PHA needs >= 98% pass rate for full 20 points."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "total_units": {
                    "type": "integer",
                    "description": "Total number of units reviewed",
                },
                "passed_units": {
                    "type": "integer",
                    "description": "Number of units that passed rent reasonableness",
                },
            },
            "required": ["total_units", "passed_units"],
        },
    },
}

# ── SEMAP 3: Income Determination ──

VERIFY_INCOME_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "verify_income",
        "description": (
            "Verify income sources for a voucher holder per 24 CFR 5.609. "
            "Retrieves income records and displays them in a table."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "voucher_id": {
                    "type": "string",
                    "description": "Voucher ID (e.g. 'V-2024-001')",
                },
                "income_sources": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Optional override: income sources to verify. "
                        "If omitted, uses data from tenant record."
                    ),
                },
            },
            "required": ["voucher_id"],
        },
    },
}

CALCULATE_DEDUCTIONS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "calculate_deductions",
        "description": (
            "Calculate HUD-allowable deductions per 24 CFR 5.611. "
            "Includes dependent deduction ($480/each), elderly/disabled ($400), "
            "medical expenses (excess over 3% for elderly/disabled), childcare, "
            "and disability assistance."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "gross_income": {
                    "type": "number",
                    "description": "Annual gross income",
                },
                "dependents": {
                    "type": "integer",
                    "description": "Number of dependents (not head/spouse)",
                },
                "elderly_disabled": {
                    "type": "boolean",
                    "description": "Whether head/spouse is elderly (62+) or disabled",
                },
                "medical_expenses": {
                    "type": "number",
                    "description": "Annual unreimbursed medical expenses (elderly/disabled only)",
                },
                "childcare_expenses": {
                    "type": "number",
                    "description": "Annual childcare expenses for children under 13",
                },
                "disability_assistance": {
                    "type": "number",
                    "description": "Annual disability assistance expenses",
                },
            },
            "required": ["gross_income"],
        },
    },
}

DETERMINE_ADJUSTED_INCOME_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "determine_adjusted_income",
        "description": (
            "Full income determination pipeline for a voucher holder. "
            "Verifies income sources, calculates deductions, and determines "
            "adjusted annual income. Displays results in a summary table."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "voucher_id": {
                    "type": "string",
                    "description": "Voucher ID (e.g. 'V-2024-001')",
                },
            },
            "required": ["voucher_id"],
        },
    },
}

# ── SEMAP 10: Tenant Rent / TTP ──

CALCULATE_TTP_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "calculate_ttp",
        "description": (
            "Calculate Total Tenant Payment per 24 CFR 5.628. Shows all 4 HUD "
            "methods (30% adjusted, 10% gross, welfare rent, minimum rent) and "
            "selects the greatest. Displays results in a table."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "annual_adjusted_income": {
                    "type": "number",
                    "description": "Annual adjusted income after deductions",
                },
                "annual_gross_income": {
                    "type": "number",
                    "description": "Annual gross income (for 10% method)",
                },
                "welfare_rent": {
                    "type": "number",
                    "description": "Monthly welfare rent, if applicable (default: 0)",
                },
            },
            "required": ["annual_adjusted_income", "annual_gross_income"],
        },
    },
}

CALCULATE_HAP_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "calculate_hap",
        "description": (
            "Calculate Housing Assistance Payment per 24 CFR 982.505. "
            "HAP = lesser of (payment standard - TTP) or (gross rent - TTP). "
            "Displays full calculation breakdown in a table."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "payment_standard": {
                    "type": "number",
                    "description": "Payment standard for unit size and area",
                },
                "ttp": {
                    "type": "number",
                    "description": "Total Tenant Payment (monthly)",
                },
                "rent": {
                    "type": "number",
                    "description": "Contract rent to owner (monthly)",
                },
                "utility_allowance": {
                    "type": "number",
                    "description": "Monthly utility allowance",
                },
            },
            "required": ["payment_standard", "ttp"],
        },
    },
}

VALIDATE_RENT_BURDEN_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "validate_rent_burden",
        "description": (
            "Check rent burden per 24 CFR 982.508. At initial occupancy, "
            "family share must not exceed 40% of adjusted monthly income. "
            "Renders a success or warning callout."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "proposed_rent": {
                    "type": "number",
                    "description": "Contract rent to owner",
                },
                "utility_allowance": {
                    "type": "number",
                    "description": "Monthly utility allowance",
                },
                "hap": {
                    "type": "number",
                    "description": "Housing Assistance Payment",
                },
                "annual_adjusted_income": {
                    "type": "number",
                    "description": "Annual adjusted income",
                },
            },
            "required": ["proposed_rent", "utility_allowance", "hap", "annual_adjusted_income"],
        },
    },
}

CHECK_MINIMUM_RENT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "check_minimum_rent",
        "description": (
            "Check minimum rent applicability per 24 CFR 5.630. "
            "If TTP falls below the PHA minimum ($50), determines if "
            "hardship exemption applies."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ttp": {
                    "type": "number",
                    "description": "Calculated TTP before minimum rent floor",
                },
                "has_hardship": {
                    "type": "boolean",
                    "description": "Whether family qualifies for hardship exemption",
                },
            },
            "required": ["ttp"],
        },
    },
}

# ── Cross-cutting ──

LOOKUP_HUD_REGULATION_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "lookup_hud_regulation",
        "description": (
            "Look up HUD regulation text by section. Sections: rent_reasonableness, "
            "income_determination, deductions, ttp_calculation, hap_calculation, "
            "rent_burden, minimum_rent, payment_standards."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": [
                        "rent_reasonableness",
                        "income_determination",
                        "deductions",
                        "ttp_calculation",
                        "hap_calculation",
                        "rent_burden",
                        "minimum_rent",
                        "payment_standards",
                    ],
                    "description": "HUD regulation section to look up",
                },
                "topic": {
                    "type": "string",
                    "description": "Optional specific topic within the section",
                },
            },
            "required": ["section"],
        },
    },
}

ANALYZE_DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "analyze_document",
        "description": (
            "Read and analyze uploaded HUD documents (RFTA forms, paystubs, "
            "lease agreements). Call with a filename to read a specific file, "
            "or without to list all uploaded files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the uploaded file to analyze (optional)",
                },
            },
            "required": [],
        },
    },
}

GENERATE_SEMAP_REPORT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_semap_report",
        "description": (
            "Generate a PDF SEMAP compliance report for a voucher. "
            "Includes income determination, TTP calculation, HAP, rent "
            "burden check, and rent reasonableness results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "voucher_id": {
                    "type": "string",
                    "description": "Voucher ID (e.g. 'V-2024-001')",
                },
                "indicators": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "SEMAP indicators to include: '2', '3', '10' (default: all)",
                },
            },
            "required": ["voucher_id"],
        },
    },
}

# ── Visualization (reused from chat demo) ──

CREATE_CHART_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_chart",
        "description": (
            "Create a visual chart for data comparison. Use this when comparing "
            "rent values, showing trends, or visualizing distributions. "
            "Data must be an array of objects in Recharts format."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "scatter", "area"],
                    "description": "Type of chart to create",
                },
                "title": {
                    "type": "string",
                    "description": "Chart title displayed above the chart",
                },
                "data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Array of data objects in Recharts format. "
                        'Example: [{"unit": "Proposed", "rent": 1400}]'
                    ),
                },
                "options": {
                    "type": "object",
                    "description": (
                        "Optional chart configuration: "
                        "xKey (string), series (array of strings), "
                        "width (string), height (string)"
                    ),
                },
            },
            "required": ["chart_type", "title", "data"],
        },
    },
}

CREATE_TABLE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_table",
        "description": (
            "Display structured tabular data. Use for SEMAP calculations, "
            "income breakdowns, TTP methods comparison, deduction itemization."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Table title",
                },
                "headers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Column header names",
                },
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "description": "Table rows as arrays of cell values",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional description below the title",
                },
            },
            "required": ["title", "headers", "rows"],
        },
    },
}

CREATE_RFTA_REVIEW_FORM_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_rfta_review_form",
        "description": (
            "Generate a pre-filled interactive review form for SEMAP compliance review. "
            "The user can review/edit fields before submitting for SEMAP calculations. "
            "Call after analyze_document when a file is uploaded, or call directly "
            "when the user provides tenant data in text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "voucher_id": {
                    "type": "string",
                    "description": "Voucher/HCV number from Section 2 of the RFTA",
                },
                "tenant_name": {
                    "type": "string",
                    "description": "Tenant full name from Section 2 of the RFTA",
                },
                "proposed_rent": {
                    "type": "number",
                    "description": "Proposed monthly contract rent from Section 5",
                },
                "utility_allowance": {
                    "type": "number",
                    "description": "Monthly utility allowance from Section 5",
                },
                "bedrooms": {
                    "type": "integer",
                    "description": "Number of bedrooms from Section 3",
                },
                "area": {
                    "type": "string",
                    "enum": ["downtown", "suburban_east", "suburban_west"],
                    "description": "Market area inferred from the unit address",
                },
                "lease_start_date": {
                    "type": "string",
                    "description": "Lease start date from Section 5 (YYYY-MM-DD)",
                },
                "household_size": {
                    "type": "integer",
                    "description": "Number of household members from Section 2",
                },
                "dependents": {
                    "type": "integer",
                    "description": "Number of dependents (not head/spouse)",
                },
                "elderly_disabled": {
                    "type": "boolean",
                    "description": "Whether head/spouse is elderly (62+) or disabled",
                },
                "annual_gross_income": {
                    "type": "number",
                    "description": "Annual gross income from paystub or Section 2",
                },
                "medical_expenses": {
                    "type": "number",
                    "description": "Annual unreimbursed medical expenses (elderly/disabled only)",
                },
                "childcare_expenses": {
                    "type": "number",
                    "description": "Annual childcare expenses for children under 13",
                },
                "disability_assistance": {
                    "type": "number",
                    "description": "Annual disability assistance expenses",
                },
            },
            "required": [],
        },
    },
}

CREATE_CALLOUT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_callout",
        "description": (
            "Display a compliance status callout. Use 'success' for passed checks, "
            "'warning' for failed/flagged issues, 'info' for regulation references."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Callout body content (supports markdown)",
                },
                "variant": {
                    "type": "string",
                    "enum": ["default", "info", "success", "warning"],
                    "description": "Visual style variant",
                },
                "title": {
                    "type": "string",
                    "description": "Optional bold title above the content",
                },
            },
            "required": ["content"],
        },
    },
}
