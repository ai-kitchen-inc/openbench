"""
Domain constants for LCA (Life Cycle Assessment) compliance checking.

Contains ISO 14040/14044 "shall" requirements, PCR (Product Category Rules)
templates, Pedoman LCA KLH Indonesia requirements, and impact category
reference data.

References:
    - ISO 14040:2006 / SNI ISO 14040:2016
    - ISO 14044:2006 / SNI ISO 14044:2017
    - EN 15804:2012+A2:2019 (Construction PCR)
    - Pedoman Teknis Penyusunan Inventarisasi Emisi GRK (KLH)
"""

from __future__ import annotations

from typing import Any

# ── ISO 14044 "shall" requirements by LCA phase ──

ISO_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "goal_and_scope": {
        "iso_ref": "ISO 14044:2006 Section 4.2",
        "title": "Goal and Scope Definition",
        "shall_requirements": [
            {
                "id": "GS-01",
                "text": "Clearly state the intended application of the study",
                "ref": "4.2.2",
            },
            {
                "id": "GS-02",
                "text": "Define the functional unit and reference flow",
                "ref": "4.2.3.2",
            },
            {
                "id": "GS-03",
                "text": "Define the system boundary including processes and flows",
                "ref": "4.2.3.3",
            },
            {
                "id": "GS-04",
                "text": "Specify allocation procedures for shared processes",
                "ref": "4.2.3.4",
            },
            {
                "id": "GS-05",
                "text": "Select impact categories, category indicators, and characterization models",
                "ref": "4.2.3.5",
            },
            {
                "id": "GS-06",
                "text": "State assumptions and limitations of the study",
                "ref": "4.2.3.7",
            },
            {
                "id": "GS-07",
                "text": "Specify data quality requirements",
                "ref": "4.2.3.6",
            },
            {
                "id": "GS-08",
                "text": "Define cut-off criteria for inputs and outputs",
                "ref": "4.2.3.3.3",
            },
        ],
    },
    "lci": {
        "iso_ref": "ISO 14044:2006 Section 4.3",
        "title": "Life Cycle Inventory Analysis",
        "shall_requirements": [
            {
                "id": "LCI-01",
                "text": "Collect data for each unit process within the system boundary",
                "ref": "4.3.2",
            },
            {
                "id": "LCI-02",
                "text": "Describe data collection and calculation procedures",
                "ref": "4.3.2.2",
            },
            {
                "id": "LCI-03",
                "text": "Apply allocation procedures consistently with goal and scope",
                "ref": "4.3.4",
            },
            {
                "id": "LCI-04",
                "text": "Document energy and material flows for each process",
                "ref": "4.3.2.1",
            },
            {
                "id": "LCI-05",
                "text": "Validate data through mass/energy balance checks",
                "ref": "4.3.3",
            },
            {
                "id": "LCI-06",
                "text": "Document cut-off criteria and their justification",
                "ref": "4.3.2.3",
            },
        ],
    },
    "lcia": {
        "iso_ref": "ISO 14044:2006 Section 4.4",
        "title": "Life Cycle Impact Assessment",
        "shall_requirements": [
            {
                "id": "LCIA-01",
                "text": "Perform classification of LCI results to impact categories",
                "ref": "4.4.2.2",
            },
            {
                "id": "LCIA-02",
                "text": "Perform characterization using selected models and factors",
                "ref": "4.4.2.3",
            },
            {
                "id": "LCIA-03",
                "text": "Use internationally accepted characterization models",
                "ref": "4.4.2.1",
            },
            {
                "id": "LCIA-04",
                "text": "Document impact categories and category indicators selected",
                "ref": "4.4.2.1",
            },
            {
                "id": "LCIA-05",
                "text": "Normalization and weighting shall not be used for comparative assertions",
                "ref": "4.4.3",
            },
        ],
    },
    "interpretation": {
        "iso_ref": "ISO 14044:2006 Section 4.5",
        "title": "Life Cycle Interpretation",
        "shall_requirements": [
            {
                "id": "INT-01",
                "text": "Identify significant issues based on LCI and LCIA results",
                "ref": "4.5.2",
            },
            {
                "id": "INT-02",
                "text": "Perform completeness check to ensure sufficient information",
                "ref": "4.5.3.1",
            },
            {
                "id": "INT-03",
                "text": "Perform sensitivity check on key assumptions and data",
                "ref": "4.5.3.2",
            },
            {
                "id": "INT-04",
                "text": "Perform consistency check on methods and data sources",
                "ref": "4.5.3.3",
            },
            {
                "id": "INT-05",
                "text": "Draw conclusions consistent with the goal and scope",
                "ref": "4.5.4",
            },
        ],
    },
    "critical_review": {
        "iso_ref": "ISO 14044:2006 Section 6",
        "title": "Critical Review",
        "shall_requirements": [
            {
                "id": "CR-01",
                "text": "Critical review required for comparative assertions disclosed to public",
                "ref": "6.1",
            },
            {
                "id": "CR-02",
                "text": "Review panel shall include independent external expert(s)",
                "ref": "6.2",
            },
            {
                "id": "CR-03",
                "text": "Review shall verify consistency with ISO 14040/14044",
                "ref": "6.1",
            },
            {
                "id": "CR-04",
                "text": "Review statement shall be included in the LCA report",
                "ref": "6.3",
            },
        ],
    },
    "reporting": {
        "iso_ref": "ISO 14044:2006 Section 5",
        "title": "Reporting",
        "shall_requirements": [
            {
                "id": "RPT-01",
                "text": "Report shall be complete, transparent, and unbiased",
                "ref": "5.1",
            },
            {
                "id": "RPT-02",
                "text": "Report results and conclusions consistent with goal and scope",
                "ref": "5.2",
            },
            {
                "id": "RPT-03",
                "text": "Include all data, methods, assumptions, and limitations",
                "ref": "5.2",
            },
            {
                "id": "RPT-04",
                "text": "Third-party report shall include critical review statement",
                "ref": "5.3",
            },
        ],
    },
}

# ── PCR (Product Category Rules) templates by industry ──

PCR_TEMPLATES: dict[str, dict[str, Any]] = {
    "construction": {
        "name": "Construction Products (EN 15804:2012+A2:2019)",
        "system_boundary": "cradle-to-grave",
        "mandatory_categories": ["GWP", "ODP", "AP", "EP", "POCP", "ADP"],
        "stages": {
            "A1-A3": "Product stage (raw materials, transport, manufacturing)",
            "A4-A5": "Construction process stage",
            "B1-B7": "Use stage (maintenance, repair, replacement, energy/water use)",
            "C1-C4": "End of life (deconstruction, transport, waste processing, disposal)",
            "D": "Benefits beyond system boundary (reuse, recovery, recycling)",
        },
        "data_quality": {
            "max_age_years": 5,
            "geographic_scope": "Europe or country-specific",
            "technological_scope": "Current technology representative of market",
        },
        "allocation_rules": [
            "Physical allocation (mass or volume) preferred",
            "Economic allocation as fallback",
            "System expansion for co-products when possible",
        ],
    },
    "packaging": {
        "name": "Packaging Products (PCR 2019:14)",
        "system_boundary": "cradle-to-gate with end-of-life options",
        "mandatory_categories": ["GWP", "ODP", "AP", "EP", "POCP", "ADP"],
        "stages": {
            "A1-A3": "Raw material extraction, transport, production",
            "C3-C4": "Waste processing and disposal",
            "D": "Recycling potential and recovery credits",
        },
        "data_quality": {
            "max_age_years": 5,
            "geographic_scope": "Country or regional",
            "technological_scope": "Average current technology",
        },
        "allocation_rules": [
            "Mass-based allocation for multi-output processes",
            "Recycled content method for recycled inputs",
            "50/50 allocation for open-loop recycling",
        ],
    },
    "electronics": {
        "name": "Electronics (PCR 2023:09)",
        "system_boundary": "cradle-to-grave",
        "mandatory_categories": ["GWP", "ODP", "AP", "EP", "POCP", "ADP", "WDP"],
        "stages": {
            "A1-A3": "Raw materials, component manufacturing, assembly",
            "A4": "Distribution and transport",
            "B1-B6": "Use stage (energy consumption during lifetime)",
            "C1-C4": "End of life (collection, recycling, disposal)",
            "D": "Recovery and recycling credits",
        },
        "data_quality": {
            "max_age_years": 3,
            "geographic_scope": "Production country or global average",
            "technological_scope": "Specific to product model",
        },
        "allocation_rules": [
            "Mass-based allocation for manufacturing",
            "Economic allocation for critical raw materials",
            "System expansion for WEEE recycling credits",
        ],
    },
    "food_beverage": {
        "name": "Food and Beverage (PCR 2019:01)",
        "system_boundary": "cradle-to-grave",
        "mandatory_categories": ["GWP", "EP", "AP", "WDP", "LU"],
        "stages": {
            "A1": "Agricultural production / raw material sourcing",
            "A2": "Transport to processing",
            "A3": "Processing and packaging",
            "A4": "Distribution",
            "B1": "Retail and consumer storage",
            "C1-C4": "End of life (packaging waste, food waste)",
        },
        "data_quality": {
            "max_age_years": 5,
            "geographic_scope": "Country-specific for agriculture",
            "technological_scope": "Representative of production system",
        },
        "allocation_rules": [
            "Mass-based allocation for agricultural co-products",
            "Economic allocation when mass is not representative",
            "No allocation for food waste (counted as loss)",
        ],
    },
}

# ── Pedoman LCA KLH Indonesia ──

PEDOMAN_KLH: dict[str, Any] = {
    "regulation_ref": "Pedoman Teknis Penyusunan Inventarisasi Emisi GRK (KLH)",
    "sni_references": [
        "SNI ISO 14040:2016 - Manajemen lingkungan - Penilaian daur hidup - Prinsip dan kerangka",
        "SNI ISO 14044:2017 - Manajemen lingkungan - Penilaian daur hidup - Persyaratan dan pedoman",
    ],
    "grid_emission_factor": 0.794,  # kg CO2eq/kWh (Indonesian national grid, 2023)
    "mandatory_categories": ["GWP", "AP", "EP", "POCP"],
    "reporting_language": "Bahasa Indonesia",
    "requirements": [
        {
            "id": "KLH-01",
            "text": "Use Indonesian grid emission factor for electricity consumption",
            "detail": "National grid factor: 0.794 kg CO2eq/kWh (ESDM/PLN, 2023)",
        },
        {
            "id": "KLH-02",
            "text": "Include at minimum GWP, AP, EP, and POCP impact categories",
            "detail": "Additional categories encouraged but not mandatory",
        },
        {
            "id": "KLH-03",
            "text": "Report results in Bahasa Indonesia for domestic publications",
            "detail": "English summary acceptable for international audience",
        },
        {
            "id": "KLH-04",
            "text": "Reference local database for Indonesian-specific emission factors",
            "detail": "Use IPLC (Indonesia Product Life Cycle) database when available",
        },
        {
            "id": "KLH-05",
            "text": "Consider tropical climate conditions in impact assessment",
            "detail": "Temperature, humidity affect degradation rates and transport impacts",
        },
        {
            "id": "KLH-06",
            "text": "Align system boundary with SNI ISO 14044:2017 requirements",
            "detail": "Follow ISO 14044 Section 4.2.3.3 system boundary definition",
        },
        {
            "id": "KLH-07",
            "text": "Include waste management scenarios relevant to Indonesian context",
            "detail": "Consider local recycling rates, landfill practices, informal sector",
        },
    ],
    "local_databases": [
        "IPLC (Indonesia Product Life Cycle) Database",
        "PLN Electricity Grid Data (ESDM)",
        "KLHK Emission Factor Database",
        "SimaPro Indonesia Module",
    ],
}

# ── Impact Category Reference Data ──

IMPACT_CATEGORIES: dict[str, dict[str, str]] = {
    "GWP": {
        "name": "Global Warming Potential",
        "unit": "kg CO2 eq",
        "method": "IPCC AR6 (2021)",
        "description": "Radiative forcing increase from greenhouse gas emissions over 100 years",
    },
    "ODP": {
        "name": "Ozone Depletion Potential",
        "unit": "kg CFC-11 eq",
        "method": "WMO 2022",
        "description": "Stratospheric ozone destruction relative to CFC-11",
    },
    "AP": {
        "name": "Acidification Potential",
        "unit": "kg SO2 eq",
        "method": "CML-IA baseline",
        "description": "Acid deposition from SO2, NOx, and other acidifying substances",
    },
    "EP": {
        "name": "Eutrophication Potential",
        "unit": "kg PO4 eq",
        "method": "CML-IA baseline",
        "description": "Nutrient enrichment of aquatic and terrestrial ecosystems",
    },
    "POCP": {
        "name": "Photochemical Ozone Creation Potential",
        "unit": "kg C2H4 eq",
        "method": "CML-IA baseline",
        "description": "Ground-level ozone formation (smog) from VOC and NOx emissions",
    },
    "ADP": {
        "name": "Abiotic Depletion Potential",
        "unit": "kg Sb eq",
        "method": "CML-IA baseline",
        "description": "Depletion of non-renewable mineral and fossil resources",
    },
    "WDP": {
        "name": "Water Deprivation Potential",
        "unit": "m3 world eq",
        "method": "AWARE (2018)",
        "description": "Water consumption weighted by regional water scarcity",
    },
    "LU": {
        "name": "Land Use",
        "unit": "m2a crop eq",
        "method": "LANCA (2019)",
        "description": "Land occupation and transformation impacts on biodiversity",
    },
}
