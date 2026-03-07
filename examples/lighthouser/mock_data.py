"""
Mock domain data for the Lighthouser SEMAP compliance demo.

Contains realistic tenant records, market comparables, HUD regulation
text, and payment standards. V-2024-003 intentionally fails rent
burden to demonstrate warning callouts.
"""

from __future__ import annotations

# ── Tenant / Voucher Data ──

TENANT_DATA: dict[str, dict] = {
    "V-2024-001": {
        "voucher_id": "V-2024-001",
        "tenant_name": "Maria Santos",
        "household_size": 4,
        "dependents": 2,
        "elderly_disabled": False,
        "gross_income": 36000,
        "income_sources": [
            {"source": "Employment", "employer": "City Hospital", "annual": 28800},
            {"source": "Child Support", "payer": "State", "annual": 7200},
        ],
        "medical_expenses": 0,
        "childcare_expenses": 4800,
        "disability_assistance": 0,
        "unit": {
            "address": "1250 Market St, Apt 4B",
            "bedrooms": 2,
            "area": "downtown",
            "contract_rent": 1400,
            "utility_allowance": 125,
        },
    },
    "V-2024-002": {
        "voucher_id": "V-2024-002",
        "tenant_name": "James Washington",
        "household_size": 2,
        "dependents": 0,
        "elderly_disabled": True,
        "gross_income": 22000,
        "income_sources": [
            {"source": "Social Security", "annual": 18000},
            {"source": "Pension", "payer": "USPS", "annual": 4000},
        ],
        "medical_expenses": 3200,
        "childcare_expenses": 0,
        "disability_assistance": 0,
        "unit": {
            "address": "845 Elm Dr, Unit 12",
            "bedrooms": 1,
            "area": "suburban_east",
            "contract_rent": 1050,
            "utility_allowance": 95,
        },
    },
    "V-2024-003": {
        "voucher_id": "V-2024-003",
        "tenant_name": "Aisha Johnson",
        "household_size": 5,
        "dependents": 3,
        "elderly_disabled": False,
        "gross_income": 28000,
        "income_sources": [
            {"source": "Employment", "employer": "QuickMart", "annual": 22000},
            {"source": "TANF", "annual": 6000},
        ],
        "medical_expenses": 0,
        "childcare_expenses": 6000,
        "disability_assistance": 0,
        "unit": {
            "address": "320 West Oak Blvd, Apt 7",
            "bedrooms": 3,
            "area": "suburban_west",
            "contract_rent": 1850,  # High rent -- intentionally fails burden test
            "utility_allowance": 175,
        },
    },
}

# ── Market Comparables ──

MARKET_COMPARABLES: dict[str, dict[int, list[dict]]] = {
    "downtown": {
        1: [
            {"address": "100 Main St #2A", "rent": 1200, "sqft": 650, "condition": "Good"},
            {"address": "220 Park Ave #5", "rent": 1250, "sqft": 680, "condition": "Good"},
            {"address": "315 Broad St #3C", "rent": 1180, "sqft": 620, "condition": "Fair"},
        ],
        2: [
            {"address": "100 Main St #4D", "rent": 1450, "sqft": 900, "condition": "Good"},
            {"address": "220 Park Ave #8", "rent": 1480, "sqft": 920, "condition": "Excellent"},
            {"address": "418 Union Sq #2", "rent": 1420, "sqft": 880, "condition": "Good"},
        ],
        3: [
            {"address": "500 Center Blvd", "rent": 1750, "sqft": 1200, "condition": "Good"},
            {"address": "620 River Rd #1", "rent": 1800, "sqft": 1250, "condition": "Good"},
            {"address": "710 Lake Dr", "rent": 1720, "sqft": 1180, "condition": "Fair"},
        ],
    },
    "suburban_east": {
        1: [
            {"address": "45 Oak Lane", "rent": 1000, "sqft": 700, "condition": "Good"},
            {"address": "78 Maple Ct", "rent": 1050, "sqft": 720, "condition": "Good"},
            {"address": "120 Pine St", "rent": 980, "sqft": 680, "condition": "Fair"},
        ],
        2: [
            {"address": "45 Oak Lane #B", "rent": 1250, "sqft": 950, "condition": "Good"},
            {"address": "200 Birch Ave", "rent": 1300, "sqft": 980, "condition": "Good"},
            {"address": "310 Cedar Dr", "rent": 1220, "sqft": 930, "condition": "Fair"},
        ],
        3: [
            {"address": "500 Willow Rd", "rent": 1550, "sqft": 1300, "condition": "Good"},
            {"address": "615 Ash Blvd", "rent": 1600, "sqft": 1350, "condition": "Good"},
            {"address": "720 Spruce Ct", "rent": 1520, "sqft": 1280, "condition": "Fair"},
        ],
    },
    "suburban_west": {
        1: [
            {"address": "30 Valley View", "rent": 1100, "sqft": 680, "condition": "Good"},
            {"address": "85 Sunset Dr", "rent": 1150, "sqft": 710, "condition": "Good"},
            {"address": "140 Hilltop Rd", "rent": 1080, "sqft": 660, "condition": "Fair"},
        ],
        2: [
            {"address": "30 Valley View #C", "rent": 1350, "sqft": 920, "condition": "Good"},
            {"address": "200 Ridge Ave", "rent": 1400, "sqft": 960, "condition": "Good"},
            {"address": "315 Creek Ln", "rent": 1320, "sqft": 900, "condition": "Fair"},
        ],
        3: [
            {"address": "500 Mountain Rd", "rent": 1650, "sqft": 1250, "condition": "Good"},
            {"address": "620 Forest Dr", "rent": 1700, "sqft": 1300, "condition": "Good"},
            {"address": "730 Meadow Ct", "rent": 1620, "sqft": 1220, "condition": "Fair"},
        ],
    },
}

# ── HUD Regulations ──

HUD_REGULATIONS: dict[str, dict] = {
    "rent_reasonableness": {
        "cfr": "24 CFR 982.507",
        "title": "Rent Reasonableness",
        "summary": (
            "The PHA must determine that the rent to owner is reasonable in comparison "
            "to rent for comparable unassisted units. Factors include location, quality, "
            "size, unit type, age of unit, amenities, housing services, and maintenance."
        ),
        "key_points": [
            "Must be determined before initial lease and annually",
            "Compare to at least 3 unassisted comparable units",
            "Rent must not exceed rents for comparable unassisted units",
            "Owner may not charge HCV tenants more than comparable unassisted tenants",
            "PHA must document the basis for each rent reasonableness determination",
        ],
    },
    "income_determination": {
        "cfr": "24 CFR 5.609",
        "title": "Annual Income",
        "summary": (
            "Annual income includes all amounts anticipated to be received during the "
            "12 months following certification, including wages, Social Security, pensions, "
            "welfare, alimony, child support, and asset income."
        ),
        "key_points": [
            "Income must be verified by third-party sources when possible",
            "All household members 18+ must have income verified",
            "Self-employment income: net income from business",
            "Asset income included if assets exceed $5,000",
            "Reexamination required at least annually",
        ],
    },
    "deductions": {
        "cfr": "24 CFR 5.611",
        "title": "Allowable Deductions",
        "summary": (
            "HUD allows specific deductions from annual income to calculate adjusted "
            "income: $480 per dependent, $400 elderly/disabled deduction, medical expenses "
            "(elderly/disabled only, excess over 3% of gross), childcare for children "
            "under 13, and disability assistance expenses."
        ),
        "key_points": [
            "$480 for each dependent (not head, spouse, or sole member)",
            "$400 for any elderly (62+) or disabled family",
            "Medical expenses for elderly/disabled: amount exceeding 3% of gross income",
            "Childcare for children under 13 to enable work/education",
            "Disability assistance expenses that enable a household member to work",
        ],
    },
    "ttp_calculation": {
        "cfr": "24 CFR 5.628",
        "title": "Total Tenant Payment (TTP)",
        "summary": (
            "TTP is the greatest of: (1) 30% of adjusted monthly income, "
            "(2) 10% of gross monthly income, (3) welfare rent, or (4) minimum rent "
            "($0-$50, PHA sets amount). The TTP determines the family's share of rent."
        ),
        "key_points": [
            "TTP = greatest of 4 methods",
            "30% of adjusted monthly income is most common",
            "Minimum rent set by PHA ($0-$50, typically $50)",
            "Hardship exemption available for minimum rent",
            "Mixed families: prorated assistance based on eligible members",
        ],
    },
    "hap_calculation": {
        "cfr": "24 CFR 982.505",
        "title": "Housing Assistance Payment (HAP)",
        "summary": (
            "HAP = lesser of (a) payment standard minus TTP, or (b) gross rent minus "
            "TTP. Payment standard is based on FMR for the unit size and may be between "
            "90% and 110% of the FMR (with HUD approval for higher)."
        ),
        "key_points": [
            "HAP cannot exceed the gross rent",
            "Payment standard based on Fair Market Rent (FMR)",
            "PHA may set payment standards between 90-110% of FMR",
            "Utility allowance included in gross rent calculation",
            "HAP paid directly to landlord by PHA",
        ],
    },
    "rent_burden": {
        "cfr": "24 CFR 982.508",
        "title": "Maximum Family Share at Initial Occupancy",
        "summary": (
            "At initial occupancy, the family share (gross rent minus HAP) must not "
            "exceed 40% of the family's adjusted monthly income. This protects families "
            "from excessive rent burden."
        ),
        "key_points": [
            "40% cap applies at initial lease-up only",
            "Family share = gross rent - HAP",
            "Does not apply at annual reexamination",
            "PHA must deny unit approval if burden exceeds 40%",
            "Exception: if payment standard is >= gross rent, no burden test needed",
        ],
    },
    "minimum_rent": {
        "cfr": "24 CFR 5.630",
        "title": "Minimum Rent",
        "summary": (
            "PHA may establish a minimum rent between $0 and $50. If a family "
            "requests a hardship exemption, the PHA must suspend minimum rent for "
            "90 days while determining if hardship exists."
        ),
        "key_points": [
            "PHA sets minimum rent amount ($0-$50)",
            "Hardship exemptions required for qualifying families",
            "Qualifying hardships: loss of employment, death, hospitalization",
            "90-day suspension during hardship determination",
            "If hardship confirmed, minimum rent waived or reduced",
        ],
    },
    "payment_standards": {
        "cfr": "24 CFR 982.503",
        "title": "Payment Standards",
        "summary": (
            "The payment standard is the maximum subsidy the PHA may pay. It is based "
            "on the Fair Market Rent (FMR) published annually by HUD. PHAs may set "
            "payment standards between 90% and 110% of FMR without HUD approval."
        ),
        "key_points": [
            "Based on HUD-published Fair Market Rents (FMR)",
            "Set at 90-110% of FMR by PHA",
            "Higher payment standards require HUD approval",
            "Different standards for each bedroom size",
            "Small Area FMRs (SAFMRs) allow ZIP-code-level standards",
        ],
    },
}

# ── Payment Standards (based on FMR by area and bedrooms) ──

PAYMENT_STANDARDS: dict[str, dict[int, float]] = {
    "downtown": {
        0: 1100,
        1: 1300,
        2: 1550,
        3: 1900,
        4: 2200,
    },
    "suburban_east": {
        0: 900,
        1: 1100,
        2: 1350,
        3: 1650,
        4: 1900,
    },
    "suburban_west": {
        0: 950,
        1: 1150,
        2: 1400,
        3: 1700,
        4: 1950,
    },
}
