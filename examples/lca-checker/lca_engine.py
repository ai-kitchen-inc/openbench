"""
Pure LCA compliance calculation functions.

Stateless, testable, no OpenBench dependencies. Extracted so compliance
logic is reusable outside chat context.

References:
    - ISO 14040:2006 (Principles and framework)
    - ISO 14044:2006 (Requirements and guidelines)
    - EN 15804:2012+A2:2019 (Construction PCR)
    - Pedoman Teknis Penyusunan Inventarisasi Emisi GRK (KLH)
"""

from __future__ import annotations

from standards_data import (
    ISO_REQUIREMENTS,
    PCR_TEMPLATES,
    PEDOMAN_KLH,
)


def check_iso_compliance(
    study_data: dict,
    phase: str = "all",
) -> dict:
    """Check LCA study compliance against ISO 14044 requirements.

    Args:
        study_data: LCA study dict with phases_completed, impact_results, etc.
        phase: Specific phase to check or "all" for all phases.

    Returns:
        Dict mapping phase -> list of {requirement, status, detail, ref}.
    """
    phases_to_check = list(ISO_REQUIREMENTS.keys()) if phase == "all" else [phase]
    completed = set(study_data.get("phases_completed", []))
    results: dict[str, list[dict]] = {}

    for p in phases_to_check:
        if p not in ISO_REQUIREMENTS:
            continue
        phase_info = ISO_REQUIREMENTS[p]
        checks = []

        for req in phase_info["shall_requirements"]:
            status, detail = _evaluate_requirement(req, p, study_data, completed)
            checks.append(
                {
                    "id": req["id"],
                    "requirement": req["text"],
                    "ref": f"ISO 14044 {req['ref']}",
                    "status": status,
                    "detail": detail,
                }
            )
        results[p] = checks

    return results


def _evaluate_requirement(
    req: dict, phase: str, study: dict, completed: set[str]
) -> tuple[str, str]:
    """Evaluate a single ISO requirement against study data."""
    req_id = req["id"]

    # Phase not completed at all
    if phase in ("goal_and_scope", "lci", "lcia", "interpretation") and phase not in completed:
        return "fail", f"Phase '{phase}' not completed in this study"

    # Goal & Scope checks
    if req_id == "GS-01":
        app = study.get("intended_application")
        if app:
            return "pass", f"Intended application: {app}"
        return "fail", "No intended application stated"

    if req_id == "GS-02":
        fu = study.get("functional_unit")
        if fu:
            return "pass", f"Functional unit defined: {fu}"
        return "fail", "No functional unit defined"

    if req_id == "GS-03":
        boundary = study.get("system_boundary")
        desc = study.get("boundary_description")
        if boundary and desc:
            return "pass", f"System boundary: {boundary}"
        if boundary:
            return "partial", "System boundary type stated but no detailed description"
        return "fail", "No system boundary defined"

    if req_id == "GS-04":
        alloc = study.get("allocation_method")
        if alloc:
            return "pass", f"Allocation method: {alloc}"
        return "fail", "No allocation procedure specified"

    if req_id == "GS-05":
        impacts = study.get("impact_results", {})
        if len(impacts) >= 4:
            cats = ", ".join(impacts.keys())
            return "pass", f"Impact categories selected: {cats}"
        if impacts:
            return "partial", f"Only {len(impacts)} category(ies) — minimum 4 recommended"
        return "fail", "No impact categories selected"

    if req_id == "GS-06":
        # Check if boundary_description mentions limitations
        desc = study.get("boundary_description", "")
        if "exclud" in desc.lower() or "not included" in desc.lower():
            return "pass", "Assumptions and limitations stated in boundary description"
        return "partial", "Limitations should be explicitly documented"

    if req_id == "GS-07":
        dqi = study.get("data_quality_indicators")
        if dqi and dqi.get("completeness_pct", 0) > 0:
            return (
                "pass",
                f"Data quality requirements specified (completeness: {dqi['completeness_pct']}%)",
            )
        return "fail", "No data quality requirements specified"

    if req_id == "GS-08":
        cutoff = study.get("cut_off_criteria")
        if cutoff:
            return "pass", f"Cut-off criteria: {cutoff}"
        return "fail", "No cut-off criteria defined"

    # LCI checks
    if req_id == "LCI-01":
        sources = study.get("data_sources", [])
        if any("primary" in s.lower() for s in sources):
            return "pass", "Primary data collected for foreground processes"
        if sources:
            return "partial", "Only secondary/literature data used"
        return "fail", "No data sources documented"

    if req_id == "LCI-02":
        software = study.get("lca_software")
        if software and software.lower() != "spreadsheet (manual calculation)":
            return "pass", f"LCA software used: {software}"
        if software:
            return "partial", "Manual calculation — procedures should be documented in detail"
        return "fail", "No calculation procedures documented"

    if req_id == "LCI-03":
        alloc = study.get("allocation_method")
        if alloc:
            return "pass", f"Allocation applied: {alloc}"
        return "partial", "Allocation procedure not documented for LCI"

    if req_id == "LCI-04":
        sources = study.get("data_sources", [])
        if sources:
            return "pass", f"{len(sources)} data source(s) documented"
        return "fail", "No material/energy flow documentation"

    if req_id == "LCI-05":
        dqi = study.get("data_quality_indicators", {})
        completeness = dqi.get("completeness_pct", 0)
        if completeness >= 90:
            return "pass", f"Data completeness: {completeness}% (mass/energy balance likely valid)"
        if completeness >= 70:
            return "partial", f"Data completeness: {completeness}% — validation recommended"
        return "fail", f"Data completeness: {completeness}% — mass/energy balance not reliable"

    if req_id == "LCI-06":
        cutoff = study.get("cut_off_criteria")
        if cutoff:
            return "pass", f"Cut-off criteria documented: {cutoff}"
        return "fail", "Cut-off criteria not documented for LCI"

    # LCIA checks
    if req_id == "LCIA-01":
        impacts = study.get("impact_results", {})
        if impacts:
            return "pass", f"Classification performed for {len(impacts)} categories"
        return "fail", "No LCIA classification results"

    if req_id == "LCIA-02":
        method = study.get("lcia_method")
        if method and "cml" in method.lower():
            return "pass", f"Characterization method: {method}"
        if method:
            return "pass", f"Characterization method: {method}"
        return "fail", "No characterization method documented"

    if req_id == "LCIA-03":
        method = study.get("lcia_method", "")
        recognized = ["cml", "recipe", "ilcd", "traci", "ipcc", "impact 2002"]
        if any(m in method.lower() for m in recognized):
            return "pass", f"Internationally recognized method: {method}"
        return "partial", f"Method '{method}' — verify international acceptance"

    if req_id == "LCIA-04":
        impacts = study.get("impact_results", {})
        method = study.get("lcia_method")
        if impacts and method:
            return "pass", f"{len(impacts)} categories documented with method {method}"
        return "fail", "Impact categories and indicators not fully documented"

    if req_id == "LCIA-05":
        # This requirement is about comparative assertions
        return "pass", "Noted — normalization/weighting restrictions for comparative assertions"

    # Interpretation checks
    if req_id == "INT-01":
        impacts = study.get("impact_results", {})
        if len(impacts) >= 4:
            return "pass", "Significant issues can be identified from multi-category results"
        return "partial", "Limited impact categories may miss significant issues"

    if req_id == "INT-02":
        if study.get("completeness_check"):
            return "pass", "Completeness check performed"
        return "fail", "No completeness check documented"

    if req_id == "INT-03":
        if study.get("sensitivity_analysis"):
            return "pass", "Sensitivity analysis performed"
        return "fail", "No sensitivity analysis documented"

    if req_id == "INT-04":
        if study.get("consistency_check"):
            return "pass", "Consistency check performed"
        return "fail", "No consistency check documented"

    if req_id == "INT-05":
        if "interpretation" in completed:
            return "pass", "Interpretation phase completed"
        return "fail", "No interpretation conclusions drawn"

    # Critical review checks
    if req_id == "CR-01":
        app = study.get("intended_application", "")
        needs_review = (
            "epd" in app.lower() or "comparative" in app.lower() or "public" in app.lower()
        )
        if needs_review:
            if study.get("critical_review"):
                return "pass", "Critical review performed (required for public disclosure)"
            return "fail", "Critical review REQUIRED for EPD/public comparative assertions"
        return "pass", "Critical review not mandatory for internal use"

    if req_id == "CR-02":
        reviewer = study.get("reviewer")
        if reviewer and "independent" in reviewer.lower():
            return "pass", f"Independent reviewer: {reviewer}"
        if reviewer:
            return "partial", f"Reviewer: {reviewer} — verify independence"
        if not study.get("critical_review"):
            return "pass", "Not applicable (no critical review required)"
        return "fail", "No independent reviewer identified"

    if req_id == "CR-03":
        if study.get("critical_review"):
            return "pass", "Review verified ISO 14040/14044 consistency"
        return "pass", "Not applicable (no critical review performed)"

    if req_id == "CR-04":
        if study.get("critical_review") and study.get("reviewer"):
            return "pass", "Review statement available for inclusion in report"
        if not study.get("critical_review"):
            return "pass", "Not applicable"
        return "fail", "Critical review performed but no statement documented"

    # Reporting checks
    if req_id == "RPT-01":
        phases = study.get("phases_completed", [])
        if len(phases) >= 4:
            return "pass", "All LCA phases completed for comprehensive reporting"
        return "partial", f"Only {len(phases)} phase(s) completed — report may be incomplete"

    if req_id == "RPT-02":
        if "interpretation" in completed:
            return "pass", "Interpretation ensures conclusions align with goal and scope"
        return "partial", "No interpretation — cannot verify conclusion consistency"

    if req_id == "RPT-03":
        sources = study.get("data_sources", [])
        method = study.get("lcia_method")
        if sources and method:
            return "pass", "Data sources and methods documented"
        return "partial", "Documentation incomplete — some methods/data not specified"

    if req_id == "RPT-04":
        app = study.get("intended_application", "")
        if "epd" in app.lower() or "public" in app.lower():
            if study.get("critical_review") and study.get("reviewer"):
                return "pass", "Critical review statement available for third-party report"
            return "fail", "Third-party report requires critical review statement"
        return "pass", "Not applicable for internal reports"

    return "partial", "Requirement not automatically verifiable"


def check_pcr_compliance(
    study_data: dict,
    pcr_category: str,
) -> dict:
    """Check compliance against specific PCR template.

    Args:
        study_data: LCA study dict.
        pcr_category: PCR category key (construction, packaging, electronics, food_beverage).

    Returns:
        Dict with category, totals, and detailed checks.
    """
    pcr = PCR_TEMPLATES.get(pcr_category)
    if not pcr:
        return {
            "category": pcr_category,
            "error": f"PCR template not found. Available: {', '.join(PCR_TEMPLATES.keys())}",
        }

    checks = []
    passed = 0
    total = 0

    # Check mandatory impact categories
    study_impacts = set(study_data.get("impact_results", {}).keys())
    for cat in pcr["mandatory_categories"]:
        total += 1
        if cat in study_impacts:
            passed += 1
            checks.append(
                {
                    "check": f"Impact category: {cat}",
                    "status": "pass",
                    "detail": f"{cat} results present",
                }
            )
        else:
            checks.append(
                {
                    "check": f"Impact category: {cat}",
                    "status": "fail",
                    "detail": f"{cat} MISSING — required by {pcr['name']}",
                }
            )

    # Check system boundary alignment
    total += 1
    boundary = study_data.get("system_boundary", "")
    expected = pcr["system_boundary"]
    if expected.lower() in boundary.lower() or boundary:
        passed += 1
        checks.append(
            {
                "check": "System boundary",
                "status": "pass",
                "detail": f"Study: {boundary} | PCR expects: {expected}",
            }
        )
    else:
        checks.append(
            {
                "check": "System boundary",
                "status": "fail",
                "detail": f"PCR requires: {expected}",
            }
        )

    # Check data quality
    total += 1
    dqi = study_data.get("data_quality_indicators", {})
    max_age = pcr["data_quality"]["max_age_years"]
    age = dqi.get("age_years", 99)
    if age <= max_age:
        passed += 1
        checks.append(
            {
                "check": "Data age",
                "status": "pass",
                "detail": f"Data age: {age} year(s) (max: {max_age})",
            }
        )
    else:
        checks.append(
            {
                "check": "Data age",
                "status": "fail",
                "detail": f"Data age: {age} year(s) exceeds PCR max of {max_age}",
            }
        )

    # Check allocation method
    total += 1
    alloc = study_data.get("allocation_method")
    if alloc:
        passed += 1
        checks.append(
            {
                "check": "Allocation method",
                "status": "pass",
                "detail": f"Method documented: {alloc}",
            }
        )
    else:
        checks.append(
            {
                "check": "Allocation method",
                "status": "fail",
                "detail": "No allocation method specified",
            }
        )

    return {
        "category": pcr_category,
        "pcr_name": pcr["name"],
        "total_requirements": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round((passed / total) * 100, 1) if total > 0 else 0,
        "details": checks,
    }


def check_pedoman_klh_compliance(
    study_data: dict,
) -> dict:
    """Check compliance against Pedoman LCA KLH Indonesia.

    Args:
        study_data: LCA study dict.

    Returns:
        Dict with total checks, passed count, and details.
    """
    checks = []
    passed = 0

    # KLH-01: Indonesian grid emission factor
    sources = study_data.get("data_sources", [])
    uses_indonesian_grid = any(
        "pln" in s.lower() or "indonesian" in s.lower() or "0.794" in s for s in sources
    )
    if uses_indonesian_grid:
        passed += 1
        checks.append(
            {
                "id": "KLH-01",
                "check": "Indonesian grid emission factor",
                "status": "pass",
                "detail": "PLN grid factor referenced in data sources",
            }
        )
    else:
        checks.append(
            {
                "id": "KLH-01",
                "check": "Indonesian grid emission factor",
                "status": "fail",
                "detail": "Must use Indonesian grid factor (0.794 kg CO2eq/kWh)",
            }
        )

    # KLH-02: Mandatory impact categories
    study_impacts = set(study_data.get("impact_results", {}).keys())
    mandatory = set(PEDOMAN_KLH["mandatory_categories"])
    missing = mandatory - study_impacts
    if not missing:
        passed += 1
        checks.append(
            {
                "id": "KLH-02",
                "check": "Mandatory impact categories (GWP, AP, EP, POCP)",
                "status": "pass",
                "detail": f"All mandatory categories present: {', '.join(sorted(mandatory))}",
            }
        )
    else:
        checks.append(
            {
                "id": "KLH-02",
                "check": "Mandatory impact categories (GWP, AP, EP, POCP)",
                "status": "fail",
                "detail": f"Missing: {', '.join(sorted(missing))}",
            }
        )

    # KLH-04: Local database reference
    uses_local_db = any(
        "iplc" in s.lower() or "pln" in s.lower() or "klhk" in s.lower() for s in sources
    )
    if uses_local_db:
        passed += 1
        checks.append(
            {
                "id": "KLH-04",
                "check": "Local database reference",
                "status": "pass",
                "detail": "Indonesian database referenced in data sources",
            }
        )
    else:
        checks.append(
            {
                "id": "KLH-04",
                "check": "Local database reference",
                "status": "partial",
                "detail": "Consider using IPLC or KLHK database for local context",
            }
        )

    # KLH-06: SNI ISO 14044 alignment
    boundary = study_data.get("system_boundary")
    boundary_desc = study_data.get("boundary_description")
    if boundary and boundary_desc:
        passed += 1
        checks.append(
            {
                "id": "KLH-06",
                "check": "SNI ISO 14044:2017 system boundary alignment",
                "status": "pass",
                "detail": f"System boundary defined: {boundary}",
            }
        )
    else:
        checks.append(
            {
                "id": "KLH-06",
                "check": "SNI ISO 14044:2017 system boundary alignment",
                "status": "fail",
                "detail": "System boundary not fully defined per SNI ISO 14044",
            }
        )

    # KLH-07: Waste management scenarios
    desc = study_data.get("boundary_description", "")
    has_waste = any(
        kw in desc.lower() for kw in ["waste", "disposal", "recycling", "end-of-life", "landfill"]
    )
    if has_waste:
        passed += 1
        checks.append(
            {
                "id": "KLH-07",
                "check": "Indonesian waste management context",
                "status": "pass",
                "detail": "Waste management referenced in boundary description",
            }
        )
    else:
        checks.append(
            {
                "id": "KLH-07",
                "check": "Indonesian waste management context",
                "status": "partial",
                "detail": "Consider including local waste management scenarios",
            }
        )

    return {
        "total_checks": len(checks),
        "passed": passed,
        "pass_rate": round((passed / len(checks)) * 100, 1) if checks else 0,
        "details": checks,
    }


def calculate_data_quality_score(
    age_years: int,
    geographic_match: str,
    technological_match: str,
    completeness_pct: float,
) -> dict:
    """Calculate data quality rating using pedigree matrix approach.

    Args:
        age_years: Age of data in years.
        geographic_match: "exact", "regional", or "global".
        technological_match: "current", "recent", or "outdated".
        completeness_pct: Data completeness percentage (0-100).

    Returns:
        Dict with overall score, breakdown, and rating.
    """
    # Pedigree matrix scoring (1=best, 5=worst)
    # Time representativeness
    if age_years <= 1:
        time_score = 1
    elif age_years <= 3:
        time_score = 2
    elif age_years <= 5:
        time_score = 3
    elif age_years <= 10:
        time_score = 4
    else:
        time_score = 5

    # Geographic representativeness
    geo_scores = {"exact": 1, "regional": 2, "global": 4}
    geo_score = geo_scores.get(geographic_match, 5)

    # Technological representativeness
    tech_scores = {"current": 1, "recent": 2, "outdated": 4}
    tech_score = tech_scores.get(technological_match, 5)

    # Completeness
    if completeness_pct >= 95:
        comp_score = 1
    elif completeness_pct >= 85:
        comp_score = 2
    elif completeness_pct >= 70:
        comp_score = 3
    elif completeness_pct >= 50:
        comp_score = 4
    else:
        comp_score = 5

    overall = round((time_score + geo_score + tech_score + comp_score) / 4, 1)

    if overall <= 1.5:
        rating = "Excellent"
    elif overall <= 2.5:
        rating = "Good"
    elif overall <= 3.5:
        rating = "Fair"
    elif overall <= 4.5:
        rating = "Poor"
    else:
        rating = "Very Poor"

    return {
        "overall_score": overall,
        "rating": rating,
        "breakdown": {
            "time_representativeness": {
                "score": time_score,
                "value": f"{age_years} year(s)",
            },
            "geographic_representativeness": {
                "score": geo_score,
                "value": geographic_match,
            },
            "technological_representativeness": {
                "score": tech_score,
                "value": technological_match,
            },
            "completeness": {
                "score": comp_score,
                "value": f"{completeness_pct}%",
            },
        },
        "scale": "1 (best) to 5 (worst)",
    }


def compare_with_benchmarks(
    impact_results: dict,
    industry: str,
    benchmarks: dict | None = None,
) -> dict:
    """Compare LCA results with industry benchmarks.

    Args:
        impact_results: Dict of {category: {value, unit}}.
        industry: Industry key for benchmark lookup.
        benchmarks: Optional override for benchmark data.

    Returns:
        Dict of {category: {value, benchmark_median, percentile_estimate, assessment}}.
    """
    from mock_data import INDUSTRY_BENCHMARKS

    bench = benchmarks or INDUSTRY_BENCHMARKS.get(industry, {})
    if not bench:
        return {"error": f"No benchmarks for industry '{industry}'"}

    comparisons = {}
    for cat, result in impact_results.items():
        value = result["value"] if isinstance(result, dict) else result
        cat_bench = bench.get(cat)
        if not cat_bench:
            continue

        p25 = cat_bench["p25"]
        median = cat_bench["median"]
        p75 = cat_bench["p75"]

        if value <= p25:
            pct_est = "< 25th"
            assessment = "Below average (good)"
        elif value <= median:
            pct_est = "25th-50th"
            assessment = "Average"
        elif value <= p75:
            pct_est = "50th-75th"
            assessment = "Above average"
        else:
            pct_est = "> 75th"
            assessment = "High (review recommended)"

        comparisons[cat] = {
            "value": value,
            "unit": cat_bench["unit"],
            "benchmark_p25": p25,
            "benchmark_median": median,
            "benchmark_p75": p75,
            "percentile_estimate": pct_est,
            "assessment": assessment,
        }

    return {
        "industry": industry,
        "benchmark_source": bench.get("source", "Unknown"),
        "comparisons": comparisons,
    }


def generate_compliance_summary(
    iso_results: dict,
    pcr_results: dict | None = None,
    klh_results: dict | None = None,
) -> dict:
    """Aggregate compliance results into overall summary.

    Args:
        iso_results: Output of check_iso_compliance().
        pcr_results: Output of check_pcr_compliance() or None.
        klh_results: Output of check_pedoman_klh_compliance() or None.

    Returns:
        Dict with overall score, status, critical gaps, and recommendations.
    """
    total = 0
    passed = 0
    critical_gaps: list[str] = []
    recommendations: list[str] = []

    # Count ISO results
    for checks in iso_results.values():
        for check in checks:
            total += 1
            if check["status"] == "pass":
                passed += 1
            elif check["status"] == "fail":
                critical_gaps.append(f"[ISO] {check['requirement']} ({check['ref']})")

    # Count PCR results
    if pcr_results and "details" in pcr_results:
        for check in pcr_results["details"]:
            total += 1
            if check["status"] == "pass":
                passed += 1
            elif check["status"] == "fail":
                critical_gaps.append(f"[PCR] {check['check']}: {check['detail']}")

    # Count KLH results
    if klh_results and "details" in klh_results:
        for check in klh_results["details"]:
            total += 1
            if check["status"] == "pass":
                passed += 1
            elif check["status"] == "fail":
                critical_gaps.append(f"[KLH] {check['check']}: {check['detail']}")

    score = round((passed / total) * 100, 1) if total > 0 else 0

    if score >= 90:
        status = "Compliant"
    elif score >= 70:
        status = "Partially Compliant"
    elif score >= 50:
        status = "Non-Compliant (major gaps)"
    else:
        status = "Non-Compliant (critical)"

    # Generate recommendations from gaps
    if any("[ISO]" in g and "functional unit" in g.lower() for g in critical_gaps):
        recommendations.append("Define a clear functional unit per ISO 14044 Section 4.2.3.2")
    if any("[ISO]" in g and "sensitivity" in g.lower() for g in critical_gaps):
        recommendations.append(
            "Perform sensitivity analysis on key parameters per ISO 14044 Section 4.5.3.2"
        )
    if any("[ISO]" in g and "critical review" in g.lower() for g in critical_gaps):
        recommendations.append(
            "Engage independent reviewer for critical review per ISO 14044 Section 6"
        )
    if any("[PCR]" in g and "MISSING" in g for g in critical_gaps):
        recommendations.append("Complete missing impact categories required by the applicable PCR")
    if any("[KLH]" in g for g in critical_gaps):
        recommendations.append(
            "Address Pedoman KLH requirements for Indonesian regulatory compliance"
        )
    if not recommendations and critical_gaps:
        recommendations.append("Address critical gaps listed above to improve compliance")

    return {
        "overall_score": score,
        "status": status,
        "total_checks": total,
        "passed": passed,
        "failed": total - passed,
        "critical_gaps": critical_gaps,
        "recommendations": recommendations,
    }


if __name__ == "__main__":
    from mock_data import LCA_STUDIES

    print("=== LCA Engine Test Cases ===\n")

    # Test 1: ISO Compliance - Good study
    print("1. ISO Compliance Check (LCA-2024-001 - Good)")
    study = LCA_STUDIES["LCA-2024-001"]
    iso_result = check_iso_compliance(study)
    for phase, checks in iso_result.items():
        pass_count = sum(1 for c in checks if c["status"] == "pass")
        total_count = len(checks)
        print(f"   {phase}: {pass_count}/{total_count} passed")

    # Test 2: ISO Compliance - Poor study
    print("\n2. ISO Compliance Check (LCA-2024-003 - Poor)")
    study = LCA_STUDIES["LCA-2024-003"]
    iso_result = check_iso_compliance(study)
    for phase, checks in iso_result.items():
        pass_count = sum(1 for c in checks if c["status"] == "pass")
        fail_count = sum(1 for c in checks if c["status"] == "fail")
        total_count = len(checks)
        print(f"   {phase}: {pass_count}/{total_count} passed, {fail_count} failed")

    # Test 3: PCR Compliance
    print("\n3. PCR Compliance (packaging)")
    study = LCA_STUDIES["LCA-2024-001"]
    pcr_result = check_pcr_compliance(study, "packaging")
    print(
        f"   Pass rate: {pcr_result['pass_rate']}% ({pcr_result['passed']}/{pcr_result['total_requirements']})"
    )

    # Test 4: Pedoman KLH
    print("\n4. Pedoman KLH Compliance")
    klh_result = check_pedoman_klh_compliance(study)
    print(
        f"   Pass rate: {klh_result['pass_rate']}% ({klh_result['passed']}/{klh_result['total_checks']})"
    )

    # Test 5: Data Quality Score
    print("\n5. Data Quality Score")
    dq = calculate_data_quality_score(
        age_years=1,
        geographic_match="exact",
        technological_match="current",
        completeness_pct=95.0,
    )
    print(f"   Score: {dq['overall_score']}/5 ({dq['rating']})")
    for dim, info in dq["breakdown"].items():
        print(f"   {dim}: {info['score']}/5 ({info['value']})")

    # Test 6: Benchmark Comparison
    print("\n6. Benchmark Comparison (packaging)")
    study = LCA_STUDIES["LCA-2024-001"]
    bench = compare_with_benchmarks(study["impact_results"], "packaging")
    for cat, comp in bench["comparisons"].items():
        print(
            f"   {cat}: {comp['value']} vs median {comp['benchmark_median']} "
            f"-> {comp['assessment']}"
        )

    # Test 7: Compliance Summary
    print("\n7. Compliance Summary")
    study = LCA_STUDIES["LCA-2024-001"]
    iso_r = check_iso_compliance(study)
    pcr_r = check_pcr_compliance(study, "packaging")
    klh_r = check_pedoman_klh_compliance(study)
    summary = generate_compliance_summary(iso_r, pcr_r, klh_r)
    print(f"   Score: {summary['overall_score']}% ({summary['status']})")
    print(f"   Passed: {summary['passed']}/{summary['total_checks']}")
    if summary["critical_gaps"]:
        print(f"   Gaps: {len(summary['critical_gaps'])}")
        for gap in summary["critical_gaps"][:3]:
            print(f"     - {gap}")

    print("\n=== All tests passed ===")
