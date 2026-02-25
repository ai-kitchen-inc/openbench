"""Tool schemas for the LCA Compliance Checker agent.

Each schema follows the OpenAI function-calling format used by BaseAgent's
ToolExecutor to describe tool parameters to the LLM.

24 tools grouped by domain area (21 core + 3 RAG).
"""

from typing import Any

# ── ISO Compliance Tools ──

CHECK_GOAL_SCOPE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "check_goal_scope",
        "description": (
            "Check Goal and Scope Definition compliance against ISO 14044:2006 "
            "Section 4.2. Evaluates functional unit, system boundary, allocation "
            "procedures, impact category selection, and data quality requirements."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID (e.g. 'LCA-2024-001') to check",
                },
            },
            "required": ["study_id"],
        },
    },
}

CHECK_LCI_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "check_lci",
        "description": (
            "Check Life Cycle Inventory (LCI) compliance against ISO 14044:2006 "
            "Section 4.3. Evaluates data collection, calculation procedures, "
            "allocation, material/energy flows, and validation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID (e.g. 'LCA-2024-001') to check",
                },
            },
            "required": ["study_id"],
        },
    },
}

CHECK_LCIA_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "check_lcia",
        "description": (
            "Check Life Cycle Impact Assessment (LCIA) compliance against "
            "ISO 14044:2006 Section 4.4. Evaluates classification, "
            "characterization, and impact method documentation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID (e.g. 'LCA-2024-001') to check",
                },
            },
            "required": ["study_id"],
        },
    },
}

CHECK_INTERPRETATION_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "check_interpretation",
        "description": (
            "Check Interpretation phase compliance against ISO 14044:2006 "
            "Section 4.5. Evaluates completeness check, sensitivity analysis, "
            "consistency check, and conclusion validity."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID (e.g. 'LCA-2024-001') to check",
                },
            },
            "required": ["study_id"],
        },
    },
}

CHECK_FULL_ISO_COMPLIANCE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "check_full_iso_compliance",
        "description": (
            "Run all ISO 14044 compliance checks at once — Goal & Scope, LCI, "
            "LCIA, Interpretation, Critical Review, and Reporting. Returns a "
            "comprehensive compliance table with pass/fail for each requirement."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID (e.g. 'LCA-2024-001') to check",
                },
            },
            "required": ["study_id"],
        },
    },
}

# ── PCR Tools ──

CHECK_PCR_COMPLIANCE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "check_pcr_compliance",
        "description": (
            "Check compliance against Product Category Rules (PCR) for a "
            "specific industry. Evaluates mandatory impact categories, system "
            "boundary, data quality, and allocation requirements."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID to check",
                },
                "pcr_category": {
                    "type": "string",
                    "enum": ["construction", "packaging", "electronics", "food_beverage"],
                    "description": "PCR template to check against",
                },
            },
            "required": ["study_id", "pcr_category"],
        },
    },
}

LIST_PCR_CATEGORIES_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_pcr_categories",
        "description": (
            "List all available PCR (Product Category Rules) templates with "
            "their mandatory categories, system boundary scope, and data "
            "quality requirements."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

# ── Pedoman KLH Tool ──

CHECK_KLH_COMPLIANCE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "check_klh_compliance",
        "description": (
            "Check compliance against Pedoman LCA KLH Indonesia. Evaluates "
            "use of Indonesian grid emission factor, mandatory impact categories, "
            "local database references, and SNI ISO alignment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID to check",
                },
            },
            "required": ["study_id"],
        },
    },
}

# ── Data Quality Tool ──

ASSESS_DATA_QUALITY_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "assess_data_quality",
        "description": (
            "Calculate data quality score using the pedigree matrix approach. "
            "Evaluates time, geographic, and technological representativeness "
            "plus data completeness. Score: 1 (best) to 5 (worst)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": (
                        "LCA study ID to assess. If provided, uses the study's "
                        "data quality indicators. If omitted, use manual parameters."
                    ),
                },
                "age_years": {
                    "type": "integer",
                    "description": "Age of data in years (if no study_id)",
                },
                "geographic_match": {
                    "type": "string",
                    "enum": ["exact", "regional", "global"],
                    "description": "Geographic representativeness",
                },
                "technological_match": {
                    "type": "string",
                    "enum": ["current", "recent", "outdated"],
                    "description": "Technological representativeness",
                },
                "completeness_pct": {
                    "type": "number",
                    "description": "Data completeness percentage (0-100)",
                },
            },
            "required": [],
        },
    },
}

# ── Benchmarking Tool ──

COMPARE_BENCHMARKS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "compare_benchmarks",
        "description": (
            "Compare LCA impact results with industry benchmarks. Shows "
            "percentile ranking against p25/median/p75 values from EPD "
            "databases. Creates a bar chart for visual comparison."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID to compare",
                },
                "industry": {
                    "type": "string",
                    "enum": ["packaging", "construction", "electronics"],
                    "description": (
                        "Industry benchmark to compare against. If omitted, "
                        "auto-detected from study's company profile."
                    ),
                },
            },
            "required": ["study_id"],
        },
    },
}

# ── Company / Study Lookup ──

LOOKUP_COMPANY_PROFILE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "lookup_company_profile",
        "description": (
            "Retrieve company profile by ID. Returns company name, industry, "
            "location, products, certifications, and associated LCA studies."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "string",
                    "description": "Company ID (e.g. 'CP-001', 'CP-002', 'CP-003')",
                },
            },
            "required": ["company_id"],
        },
    },
}

LOOKUP_LCA_STUDY_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "lookup_lca_study",
        "description": (
            "Retrieve LCA study data by ID. Returns full study metadata: "
            "product, functional unit, system boundary, phases completed, "
            "impact results, data quality, and methods."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID (e.g. 'LCA-2024-001')",
                },
            },
            "required": ["study_id"],
        },
    },
}

# ── Cross-cutting Tools ──

LOOKUP_STANDARD_REFERENCE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "lookup_standard_reference",
        "description": (
            "Look up regulation/standard text. Sections: goal_and_scope, lci, "
            "lcia, interpretation, critical_review, reporting (ISO 14044), or "
            "any PCR category, or 'pedoman_klh' for Indonesian requirements."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Standard section: ISO phases (goal_and_scope, lci, lcia, "
                        "interpretation, critical_review, reporting), PCR categories "
                        "(construction, packaging, electronics, food_beverage), "
                        "impact categories (GWP, AP, etc.), or 'pedoman_klh'"
                    ),
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
            "Read and analyze uploaded LCA documents (reports, company profiles, "
            "data sheets, Excel files). Supports PDF, text, and Excel (.xlsx/.xls). "
            "Call with a filename to read a specific file, "
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

READ_EXCEL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_excel",
        "description": (
            "Read an uploaded Excel file (.xlsx/.xls) with optional sheet and "
            "column filtering. Renders the data as a table. Use when the user "
            "wants to inspect specific sheets or columns from an Excel file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the uploaded Excel file to read",
                },
                "sheet_name": {
                    "type": "string",
                    "description": (
                        "Specific sheet name to read. If omitted, reads the first sheet."
                    ),
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of column names to include. If omitted, includes all columns."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (default: 100)",
                },
            },
            "required": ["filename"],
        },
    },
}

CREATE_COMPLIANCE_REVIEW_FORM_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_compliance_review_form",
        "description": (
            "Generate an interactive compliance review form pre-filled with "
            "study data. Allows user to confirm/edit compliance status for "
            "each phase before generating the final report."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID to review",
                },
            },
            "required": ["study_id"],
        },
    },
}

GENERATE_COMPLIANCE_REPORT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_compliance_report",
        "description": (
            "Generate a PDF compliance report for an LCA study. Includes "
            "ISO 14044 compliance, PCR check, Pedoman KLH check, data quality "
            "assessment, and benchmark comparison."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID to report on",
                },
                "include_pcr": {
                    "type": "boolean",
                    "description": "Include PCR compliance check (default: true)",
                },
                "include_klh": {
                    "type": "boolean",
                    "description": "Include Pedoman KLH check (default: true)",
                },
                "include_benchmarks": {
                    "type": "boolean",
                    "description": "Include benchmark comparison (default: true)",
                },
            },
            "required": ["study_id"],
        },
    },
}

GENERATE_MARKDOWN_REPORT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_markdown_report",
        "description": (
            "Generate a Markdown compliance report for an LCA study. Same content "
            "as the PDF report (ISO 14044, PCR, Pedoman KLH, benchmarks, summary) "
            "but output as a downloadable .md file with inline preview."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "study_id": {
                    "type": "string",
                    "description": "LCA study ID to report on",
                },
                "include_pcr": {
                    "type": "boolean",
                    "description": "Include PCR compliance check (default: true)",
                },
                "include_klh": {
                    "type": "boolean",
                    "description": "Include Pedoman KLH check (default: true)",
                },
                "include_benchmarks": {
                    "type": "boolean",
                    "description": "Include benchmark comparison (default: true)",
                },
            },
            "required": ["study_id"],
        },
    },
}

# ── Visualization Tools ──

CREATE_CHART_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_chart",
        "description": (
            "Create a visual chart for data comparison. Use for impact category "
            "comparisons, benchmark visualization, or data quality radar charts. "
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
                        'Example: [{"category": "GWP", "value": 0.89, "benchmark": 0.85}]'
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
            "Display structured tabular data. Use for compliance check results, "
            "impact category summaries, data quality breakdowns, and study metadata."
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

CREATE_CALLOUT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_callout",
        "description": (
            "Display a compliance status callout. Use 'success' for passed checks, "
            "'warning' for failed/flagged issues, 'info' for standard references."
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

# ── RAG Tools (optional, enabled when Pinecone is configured) ──

SEARCH_STANDARDS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_standards",
        "description": (
            "Semantic search across ISO 14044 requirements, PCR templates, "
            "Pedoman KLH requirements, and impact categories. Use for conceptual "
            "questions like 'what does ISO say about allocation?' or 'requirements "
            "for functional unit'. Returns ranked results with relevance scores."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query about LCA standards",
                },
                "source_type": {
                    "type": "string",
                    "enum": ["iso", "pcr", "klh", "impact_category"],
                    "description": (
                        "Filter by source type. If omitted, searches across all sources."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 5, max: 10)",
                },
            },
            "required": ["query"],
        },
    },
}

SEARCH_DOCUMENTS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_documents",
        "description": (
            "Semantic search across uploaded LCA documents (reports, company profiles). "
            "Documents must be indexed first via index_document. Returns relevant "
            "passages with scores and document names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query about document content",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 5, max: 10)",
                },
            },
            "required": ["query"],
        },
    },
}

INDEX_DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "index_document",
        "description": (
            "Index an uploaded document into the vector store for semantic search. "
            "Call this before search_documents to make file content searchable. "
            "Supports PDF and text files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Name of the uploaded file to index. "
                        "If omitted, indexes all uploaded files."
                    ),
                },
            },
            "required": [],
        },
    },
}
