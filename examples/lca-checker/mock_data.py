"""
Mock domain data for the LCA Compliance Checker demo.

Contains company profiles with LCA studies at different compliance levels,
industry benchmarks for impact comparison, and sample data for tool testing.

CP-001: Good compliance (packaging, all phases completed)
CP-002: Partial compliance (construction, missing LCIA interpretation)
CP-003: Poor compliance (electronics, missing critical items)
"""

from __future__ import annotations

# ── Company Profiles ──

COMPANY_PROFILES: dict[str, dict] = {
    "CP-001": {
        "company_id": "CP-001",
        "company_name": "PT Green Packaging Indonesia",
        "industry": "packaging",
        "location": "Tangerang, Banten, Indonesia",
        "products": ["Corrugated cardboard boxes", "Recycled paper bags"],
        "certifications": ["ISO 14001:2015", "FSC Chain of Custody", "PROPER Hijau (KLHK)"],
        "lca_studies": ["LCA-2024-001"],
        "contact": "Ibu Sari Wijaya, Environmental Manager",
    },
    "CP-002": {
        "company_id": "CP-002",
        "company_name": "PT Beton Nusantara",
        "industry": "construction",
        "location": "Cibinong, Jawa Barat, Indonesia",
        "products": ["Ready-mix concrete", "Precast concrete panels"],
        "certifications": ["ISO 14001:2015", "ISO 9001:2015"],
        "lca_studies": ["LCA-2024-002"],
        "contact": "Pak Ahmad Fauzi, Sustainability Director",
    },
    "CP-003": {
        "company_id": "CP-003",
        "company_name": "PT Elektronik Maju",
        "industry": "electronics",
        "location": "Batam, Kepulauan Riau, Indonesia",
        "products": ["Smartphone chargers", "USB cables", "Power adapters"],
        "certifications": ["ISO 9001:2015"],
        "lca_studies": ["LCA-2024-003"],
        "contact": "Pak Rudi Hartono, QA Manager",
    },
}

# ── LCA Study Data ──

LCA_STUDIES: dict[str, dict] = {
    "LCA-2024-001": {
        "study_id": "LCA-2024-001",
        "company_id": "CP-001",
        "product": "Corrugated cardboard box",
        "functional_unit": "1 kg corrugated cardboard box, 3-layer, B-flute, 600x400x300mm",
        "system_boundary": "cradle-to-gate",
        "boundary_description": (
            "Raw material extraction (pulpwood harvesting, recycled fiber collection), "
            "transport to mill, pulping, corrugating, converting, and packaging. "
            "Excludes distribution to customer and end-of-life."
        ),
        "phases_completed": ["goal_and_scope", "lci", "lcia", "interpretation"],
        "intended_application": "EPD (Environmental Product Declaration) publication",
        "impact_results": {
            "GWP": {"value": 0.89, "unit": "kg CO2 eq"},
            "AP": {"value": 0.0045, "unit": "kg SO2 eq"},
            "EP": {"value": 0.0012, "unit": "kg PO4 eq"},
            "POCP": {"value": 0.00035, "unit": "kg C2H4 eq"},
            "ODP": {"value": 2.1e-8, "unit": "kg CFC-11 eq"},
            "ADP": {"value": 0.0028, "unit": "kg Sb eq"},
        },
        "data_sources": [
            "Primary data from PT Green Packaging production records (2023)",
            "Ecoinvent 3.9.1 for background processes",
            "PLN grid emission factor (0.794 kg CO2eq/kWh)",
        ],
        "data_quality_indicators": {
            "age_years": 1,
            "geographic_match": "exact",
            "technological_match": "current",
            "completeness_pct": 95.0,
        },
        "allocation_method": "mass-based",
        "cut_off_criteria": "1% mass, 1% energy, 1% environmental relevance",
        "sensitivity_analysis": True,
        "consistency_check": True,
        "completeness_check": True,
        "critical_review": True,
        "reviewer": "Dr. Budi Santoso, ITB (independent)",
        "lca_software": "SimaPro 9.5",
        "lcia_method": "CML-IA baseline v4.8",
        "year": 2024,
    },
    "LCA-2024-002": {
        "study_id": "LCA-2024-002",
        "company_id": "CP-002",
        "product": "Ready-mix concrete C30",
        "functional_unit": "1 m3 ready-mix concrete, compressive strength C30/37, delivered",
        "system_boundary": "cradle-to-gate (A1-A3)",
        "boundary_description": (
            "Raw material extraction (cement, aggregate, water, admixtures), "
            "transport to batching plant, and concrete production. "
            "Transport to construction site (A4) not included."
        ),
        "phases_completed": ["goal_and_scope", "lci", "lcia"],
        "intended_application": "Internal benchmarking and supplier comparison",
        "impact_results": {
            "GWP": {"value": 285.0, "unit": "kg CO2 eq"},
            "AP": {"value": 0.42, "unit": "kg SO2 eq"},
            "EP": {"value": 0.065, "unit": "kg PO4 eq"},
            "POCP": {"value": 0.025, "unit": "kg C2H4 eq"},
            "ODP": {"value": 8.5e-6, "unit": "kg CFC-11 eq"},
            "ADP": {"value": 1.15, "unit": "kg Sb eq"},
        },
        "data_sources": [
            "Primary data from PT Beton Nusantara batching plant (2023)",
            "Ecoinvent 3.9.1 for cement and aggregate",
            "PLN grid emission factor (0.794 kg CO2eq/kWh)",
        ],
        "data_quality_indicators": {
            "age_years": 2,
            "geographic_match": "regional",
            "technological_match": "current",
            "completeness_pct": 88.0,
        },
        "allocation_method": "mass-based",
        "cut_off_criteria": "1% mass",
        "sensitivity_analysis": False,
        "consistency_check": False,
        "completeness_check": True,
        "critical_review": False,
        "reviewer": None,
        "lca_software": "openLCA 2.0",
        "lcia_method": "CML-IA baseline v4.8",
        "year": 2024,
    },
    "LCA-2024-003": {
        "study_id": "LCA-2024-003",
        "company_id": "CP-003",
        "product": "USB-C charger 20W",
        "functional_unit": "1 unit USB-C charger, 20W output, GaN technology",
        "system_boundary": "cradle-to-gate",
        "boundary_description": (
            "Component manufacturing and assembly only. "
            "Raw material extraction data from secondary sources."
        ),
        "phases_completed": ["goal_and_scope", "lci"],
        "intended_application": "Customer sustainability questionnaire response",
        "impact_results": {
            "GWP": {"value": 3.2, "unit": "kg CO2 eq"},
        },
        "data_sources": [
            "Secondary data from supplier datasheets",
            "Literature values for electronic components",
        ],
        "data_quality_indicators": {
            "age_years": 4,
            "geographic_match": "global",
            "technological_match": "outdated",
            "completeness_pct": 45.0,
        },
        "allocation_method": None,
        "cut_off_criteria": None,
        "sensitivity_analysis": False,
        "consistency_check": False,
        "completeness_check": False,
        "critical_review": False,
        "reviewer": None,
        "lca_software": "Spreadsheet (manual calculation)",
        "lcia_method": "IPCC AR5 GWP100 only",
        "year": 2024,
    },
}

# ── Industry Benchmarks (per functional unit) ──

INDUSTRY_BENCHMARKS: dict[str, dict[str, dict]] = {
    "packaging": {
        "functional_unit": "per kg product",
        "GWP": {"p25": 0.50, "median": 0.85, "p75": 1.20, "unit": "kg CO2 eq/kg"},
        "AP": {"p25": 0.003, "median": 0.005, "p75": 0.008, "unit": "kg SO2 eq/kg"},
        "EP": {"p25": 0.0008, "median": 0.0013, "p75": 0.0020, "unit": "kg PO4 eq/kg"},
        "POCP": {"p25": 0.0002, "median": 0.0004, "p75": 0.0006, "unit": "kg C2H4 eq/kg"},
        "source": "EPD International, corrugated packaging sector (2023)",
    },
    "construction": {
        "functional_unit": "per m3 concrete C30",
        "GWP": {"p25": 240.0, "median": 290.0, "p75": 350.0, "unit": "kg CO2 eq/m3"},
        "AP": {"p25": 0.30, "median": 0.45, "p75": 0.65, "unit": "kg SO2 eq/m3"},
        "EP": {"p25": 0.04, "median": 0.07, "p75": 0.10, "unit": "kg PO4 eq/m3"},
        "POCP": {"p25": 0.015, "median": 0.028, "p75": 0.040, "unit": "kg C2H4 eq/m3"},
        "source": "GCCA EPD Programme, ready-mix concrete (2023)",
    },
    "electronics": {
        "functional_unit": "per unit charger",
        "GWP": {"p25": 2.0, "median": 3.5, "p75": 5.5, "unit": "kg CO2 eq/unit"},
        "AP": {"p25": 0.010, "median": 0.020, "p75": 0.035, "unit": "kg SO2 eq/unit"},
        "EP": {"p25": 0.003, "median": 0.006, "p75": 0.010, "unit": "kg PO4 eq/unit"},
        "POCP": {"p25": 0.001, "median": 0.002, "p75": 0.004, "unit": "kg C2H4 eq/unit"},
        "source": "PEF pilot, chargers and external power supplies (2022)",
    },
}
