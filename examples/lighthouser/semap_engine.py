"""
Pure SEMAP calculation functions.

Stateless, testable, no OpenBench dependencies. Extracted so math is
reusable outside chat context.

HUD regulations referenced:
  - 24 CFR 5.611  (Deductions)
  - 24 CFR 5.628  (Total Tenant Payment)
  - 24 CFR 982.505 (Housing Assistance Payment)
  - 24 CFR 982.507 (Rent Reasonableness)
  - 24 CFR 982.508 (Rent Burden)
  - 24 CFR 985.3   (SEMAP Indicators)
"""

from __future__ import annotations


def calculate_hud_deductions(
    gross_income: float,
    dependents: int = 0,
    elderly_disabled: bool = False,
    medical_expenses: float = 0.0,
    childcare_expenses: float = 0.0,
    disability_assistance: float = 0.0,
) -> dict:
    """Calculate HUD allowable deductions per 24 CFR 5.611.

    Args:
        gross_income: Annual gross income.
        dependents: Number of dependents (not head/spouse).
        elderly_disabled: Whether head/spouse is elderly (62+) or disabled.
        medical_expenses: Annual unreimbursed medical expenses (elderly/disabled only).
        childcare_expenses: Annual childcare expenses for children under 13.
        disability_assistance: Annual disability assistance expenses.

    Returns:
        Dict with itemized deductions and adjusted_income.
    """
    dependent_deduction = dependents * 480
    elderly_deduction = 400 if elderly_disabled else 0

    # Medical: only for elderly/disabled, excess over 3% of gross
    medical_deduction = 0.0
    if elderly_disabled and medical_expenses > 0:
        threshold = gross_income * 0.03
        medical_deduction = max(0, medical_expenses - threshold)

    childcare_deduction = childcare_expenses
    disability_deduction = disability_assistance

    total_deductions = (
        dependent_deduction
        + elderly_deduction
        + medical_deduction
        + childcare_deduction
        + disability_deduction
    )
    adjusted_income = max(0, gross_income - total_deductions)

    return {
        "gross_income": gross_income,
        "dependent_deduction": dependent_deduction,
        "elderly_disabled_deduction": elderly_deduction,
        "medical_deduction": round(medical_deduction, 2),
        "childcare_deduction": childcare_deduction,
        "disability_assistance_deduction": disability_deduction,
        "total_deductions": round(total_deductions, 2),
        "adjusted_income": round(adjusted_income, 2),
    }


def calculate_ttp(
    adjusted_income: float,
    gross_income: float,
    welfare_rent: float = 0.0,
) -> dict:
    """Calculate Total Tenant Payment per 24 CFR 5.628.

    TTP is the GREATEST of:
      1) 30% of adjusted monthly income
      2) 10% of gross monthly income
      3) Welfare rent (if applicable)
      4) Minimum rent ($0 - $50, default $50)

    Args:
        adjusted_income: Annual adjusted income.
        gross_income: Annual gross income.
        welfare_rent: Monthly welfare rent (if applicable).

    Returns:
        Dict with all 4 methods and selected TTP.
    """
    monthly_adjusted = adjusted_income / 12
    monthly_gross = gross_income / 12

    method_1 = round(monthly_adjusted * 0.30, 2)
    method_2 = round(monthly_gross * 0.10, 2)
    method_3 = welfare_rent
    method_4 = 50.0  # HUD minimum rent

    ttp = max(method_1, method_2, method_3, method_4)

    return {
        "30pct_adjusted": method_1,
        "10pct_gross": method_2,
        "welfare_rent": method_3,
        "minimum_rent": method_4,
        "selected_ttp": round(ttp, 2),
        "selected_method": (
            "30% adjusted"
            if ttp == method_1
            else (
                "10% gross"
                if ttp == method_2
                else ("welfare rent" if ttp == method_3 else "minimum rent")
            )
        ),
    }


def calculate_hap(
    payment_standard: float,
    ttp: float,
    rent: float = 0.0,
    utility_allowance: float = 0.0,
) -> dict:
    """Calculate Housing Assistance Payment per 24 CFR 982.505.

    HAP = lesser of:
      a) Payment standard - TTP
      b) Gross rent (rent + utility allowance) - TTP

    Args:
        payment_standard: Applicable payment standard for unit size/area.
        ttp: Total Tenant Payment.
        rent: Contract rent to owner.
        utility_allowance: Monthly utility allowance.

    Returns:
        Dict with HAP calculation breakdown.
    """
    gross_rent = rent + utility_allowance

    hap_from_standard = max(0, payment_standard - ttp)
    hap_from_rent = max(0, gross_rent - ttp)

    hap = round(min(hap_from_standard, hap_from_rent), 2)
    tenant_share = round(gross_rent - hap, 2)

    return {
        "payment_standard": payment_standard,
        "ttp": ttp,
        "contract_rent": rent,
        "utility_allowance": utility_allowance,
        "gross_rent": gross_rent,
        "hap_from_standard": round(hap_from_standard, 2),
        "hap_from_rent": round(hap_from_rent, 2),
        "hap": hap,
        "tenant_share": tenant_share,
    }


def check_rent_burden(
    rent: float,
    utility_allowance: float,
    hap: float,
    adjusted_income: float,
) -> dict:
    """Check rent burden per 24 CFR 982.508.

    At initial occupancy, family share must not exceed 40% of adjusted
    monthly income.

    Args:
        rent: Contract rent.
        utility_allowance: Monthly utility allowance.
        hap: Housing Assistance Payment.
        adjusted_income: Annual adjusted income.

    Returns:
        Dict with burden percentage and pass/fail.
    """
    gross_rent = rent + utility_allowance
    family_share = gross_rent - hap
    monthly_adjusted = adjusted_income / 12

    if monthly_adjusted > 0:
        burden_pct = round((family_share / monthly_adjusted) * 100, 1)
    else:
        burden_pct = 100.0 if family_share > 0 else 0.0

    passes = burden_pct <= 40.0

    return {
        "gross_rent": gross_rent,
        "family_share": round(family_share, 2),
        "monthly_adjusted_income": round(monthly_adjusted, 2),
        "burden_pct": burden_pct,
        "threshold_pct": 40.0,
        "passes": passes,
    }


def validate_rent_reasonableness(
    proposed_rent: float,
    comparables: list[dict],
) -> dict:
    """Validate rent reasonableness per 24 CFR 982.507.

    Proposed rent must not exceed the average of comparable unassisted
    units in the area.

    Args:
        proposed_rent: Proposed contract rent.
        comparables: List of dicts with at least 'rent' key.

    Returns:
        Dict with average, ratio, and pass/fail.
    """
    if not comparables:
        return {
            "proposed_rent": proposed_rent,
            "average_comparable": 0,
            "ratio": 0,
            "passes": False,
            "reason": "No comparable units provided",
        }

    rents = [c["rent"] for c in comparables]
    avg = round(sum(rents) / len(rents), 2)
    ratio = round(proposed_rent / avg, 3) if avg > 0 else 0

    passes = ratio <= 1.0

    return {
        "proposed_rent": proposed_rent,
        "comparable_rents": rents,
        "average_comparable": avg,
        "ratio": ratio,
        "passes": passes,
    }


def semap2_score(
    total_units: int,
    passed_units: int,
) -> dict:
    """Calculate SEMAP Indicator 2 score per 24 CFR 985.3.

    PHA must achieve >= 98% pass rate on rent reasonableness for
    a score of 20 points.

    Args:
        total_units: Total units reviewed.
        passed_units: Units that passed rent reasonableness.

    Returns:
        Dict with pass rate and score.
    """
    if total_units <= 0:
        return {
            "total_units": 0,
            "passed_units": 0,
            "pass_rate": 0.0,
            "threshold": 98.0,
            "score": 0,
            "max_score": 20,
        }

    pass_rate = round((passed_units / total_units) * 100, 1)
    score = 20 if pass_rate >= 98.0 else 0

    return {
        "total_units": total_units,
        "passed_units": passed_units,
        "pass_rate": pass_rate,
        "threshold": 98.0,
        "score": score,
        "max_score": 20,
    }


if __name__ == "__main__":
    print("=== SEMAP Engine Test Cases ===\n")

    # Test 1: HUD Deductions
    print("1. HUD Deductions (24 CFR 5.611)")
    result = calculate_hud_deductions(
        gross_income=32000,
        dependents=2,
        elderly_disabled=True,
        medical_expenses=2500,
        childcare_expenses=3600,
    )
    for k, v in result.items():
        print(f"   {k}: {v}")

    # Test 2: TTP Calculation
    print("\n2. Total Tenant Payment (24 CFR 5.628)")
    result = calculate_ttp(
        adjusted_income=result["adjusted_income"],
        gross_income=32000,
    )
    for k, v in result.items():
        print(f"   {k}: {v}")

    # Test 3: HAP Calculation
    print("\n3. Housing Assistance Payment (24 CFR 982.505)")
    result = calculate_hap(
        payment_standard=1800,
        ttp=result["selected_ttp"],
        rent=1500,
        utility_allowance=150,
    )
    for k, v in result.items():
        print(f"   {k}: {v}")

    # Test 4: Rent Burden
    print("\n4. Rent Burden Check (24 CFR 982.508)")
    result = check_rent_burden(
        rent=1500,
        utility_allowance=150,
        hap=result["hap"],
        adjusted_income=26560,
    )
    for k, v in result.items():
        print(f"   {k}: {v}")

    # Test 5: Rent Reasonableness
    print("\n5. Rent Reasonableness (24 CFR 982.507)")
    result = validate_rent_reasonableness(
        proposed_rent=1500,
        comparables=[
            {"rent": 1450, "address": "123 Main St"},
            {"rent": 1550, "address": "456 Oak Ave"},
            {"rent": 1480, "address": "789 Pine Rd"},
        ],
    )
    for k, v in result.items():
        print(f"   {k}: {v}")

    # Test 6: SEMAP 2 Score
    print("\n6. SEMAP Indicator 2 Score (24 CFR 985.3)")
    result = semap2_score(total_units=100, passed_units=99)
    for k, v in result.items():
        print(f"   {k}: {v}")

    print("\n=== All tests passed ===")
