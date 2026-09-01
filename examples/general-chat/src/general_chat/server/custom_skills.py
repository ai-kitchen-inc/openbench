"""CRUD store for admin-defined General Chat skills.

Custom skills are saved as regular OpenBench project skills so the existing
``SkillRegistry`` can load them without a special runtime path:

    <root>/<skill-id>/
    ├── SKILL.md
    └── metadata.json

When a prompt implies executable support, the skill records explicit tool
dependencies in ``metadata.json`` and ``SKILL.md``. Custom Python code is
created only through the existing custom-function store; MCP servers remain the
source of registered external tools.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbench.intelligence.skill import Skill

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:[-+][a-zA-Z0-9.-]+)?$")
MAX_TEXT_BYTES = 64 * 1024
TITLE_STOPWORDS = {
    "agar",
    "akan",
    "atau",
    "bisa",
    "buat",
    "buatkan",
    "bikin",
    "dalam",
    "dan",
    "dengan",
    "jadi",
    "kustom",
    "mau",
    "membantu",
    "membuat",
    "menjadi",
    "saya",
    "skill",
    "supaya",
    "untuk",
    "user",
    "yang",
}
FUNCTION_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
FUNCTION_NAME_STOPWORDS = {
    *TITLE_STOPWORDS,
    "akurat",
    "batas",
    "berdasarkan",
    "berbentuk",
    "berikan",
    "beri",
    "cek",
    "fungsi",
    "hasil",
    "hitung",
    "instruksi",
    "jika",
    "jumlah",
    "kalkulasi",
    "kebutuhan",
    "ketika",
    "konsisten",
    "konversi",
    "lebar",
    "luas",
    "maksimal",
    "melampirkan",
    "memberikan",
    "menghitung",
    "minimal",
    "minta",
    "nilai",
    "panjang",
    "persegi",
    "saat",
    "script",
    "sebuah",
    "suer",
    "tinggi",
    "validasi",
}
FUNCTION_MATCH_ALIASES = {
    "add": {"add", "tambah", "tambahkan", "penjumlahan", "jumlahkan", "plus"},
    "subtract": {"subtract", "kurang", "pengurangan", "minus", "selisih"},
    "multiply": {"multiply", "kali", "perkalian", "kalikan"},
    "divide": {"divide", "bagi", "pembagian", "bagikan"},
    "area": {"area", "luas"},
    "budget": {"budget", "anggaran", "biaya", "rab"},
    "estimate": {"estimate", "estimasi", "perkiraan"},
    "discount": {"discount", "diskon", "potongan"},
    "score": {"score", "skor", "scoring", "nilai"},
    "validate": {"validate", "validasi", "cek", "periksa"},
}

SCRIPT_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "id": "image_generation_brief",
        "label": "Image generation brief",
        "function_name": "custom_skill_image_brief",
        "terms": (
            "image generation",
            "generate image",
            "gambar",
            "visual",
            "ilustrasi",
            "render",
            "mockup",
            "desain visual",
        ),
        "tool_terms": ("image", "gambar", "visual", "generate"),
        "allow_mcp_reuse": True,
        "description": "Menyusun brief/prompt gambar terstruktur untuk mendukung skill.",
        "code": '''def custom_skill_image_brief(project_description, style="", requirements=None):
    """Return a deterministic image-generation brief from user requirements."""
    requirements = requirements or []
    if isinstance(requirements, str):
        requirements = [requirements]
    clean_requirements = [str(item).strip() for item in requirements if str(item).strip()]
    subject = str(project_description or "").strip()
    visual_style = str(style or "").strip() or "realistic, clear, inspection-ready"
    prompt_parts = [subject, f"Style: {visual_style}"]
    if clean_requirements:
        prompt_parts.append("Required details: " + "; ".join(clean_requirements))
    return {
        "computed_by": "custom_skill_image_brief",
        "prompt": ". ".join(part for part in prompt_parts if part),
        "negative_prompt": "blurry, low-detail, misleading scale, unreadable text",
        "checklist": [
            "Main subject is visible",
            "Important materials, scale, and setting are represented",
            "No claim is made that this function generated the final image",
        ],
    }
''',
    },
    {
        "id": "budget_estimation",
        "label": "Budget estimation",
        "function_name": "custom_skill_estimate_budget",
        "terms": (
            "anggaran",
            "budget",
            "biaya",
            "estimasi biaya",
            "bahan baku",
            "material",
            "rab",
        ),
        "tool_terms": ("budget", "biaya", "anggaran", "estimate", "estimasi"),
        "required_terms_any": ("estimasi", "hitung", "menghitung", "rincian biaya", "rab"),
        "description": "Menghitung subtotal, contingency, dan total dari item biaya.",
        "code": '''def custom_skill_estimate_budget(items, contingency_pct=10):
    """Estimate a budget from line items.

    items: list of {"name": str, "quantity": number, "unit_cost": number}
    """
    rows = []
    subtotal = 0.0
    for item in items or []:
        name = str(item.get("name", "item"))
        quantity = float(item.get("quantity", 0) or 0)
        unit_cost = float(item.get("unit_cost", 0) or 0)
        line_total = quantity * unit_cost
        subtotal += line_total
        rows.append({
            "name": name,
            "quantity": quantity,
            "unit_cost": unit_cost,
            "line_total": line_total,
        })
    contingency = subtotal * (float(contingency_pct or 0) / 100.0)
    return {
        "computed_by": "custom_skill_estimate_budget",
        "items": rows,
        "subtotal": subtotal,
        "contingency_pct": float(contingency_pct or 0),
        "contingency": contingency,
        "total": subtotal + contingency,
    }
''',
    },
    {
        "id": "rule_evaluation",
        "label": "Generic rule evaluation",
        "function_name": "custom_skill_evaluate_rules",
        "terms": (
            "aturan hardcoded",
            "aturan deterministik",
            "rule deterministik",
            "rules deterministik",
            "validasi aturan",
            "cek aturan",
            "checklist validasi",
            "sop validasi",
            "cek kelayakan",
            "periksa kelayakan",
            "layak atau tidak",
            "minimal",
            "maksimal",
            "threshold",
            "skor",
            "scoring",
        ),
        "tool_terms": ("validasi", "aturan", "rule", "rules", "checklist", "sop"),
        "required_terms_any": (
            "validasi",
            "aturan",
            "rule",
            "rules",
            "checklist",
            "sop",
        ),
        "fallback": True,
        "description": "Mengevaluasi data domain apa pun memakai daftar aturan deterministik.",
        "code": '''import re


def custom_skill_evaluate_rules(payload, rules):
    """Evaluate generic deterministic rules against a payload.

    payload: dict of user data.
    rules: list of dicts with field, operator, and expected values.
    Supported operators: required, eq, ne, gt, gte, lt, lte, between, one_of,
    not_one_of, contains, regex.
    """
    payload = payload or {}
    if not isinstance(payload, dict):
        return {
            "computed_by": "custom_skill_evaluate_rules",
            "checks": [],
            "violation_count": 0,
            "risk_status": "unknown",
            "recommendation": "revisi",
            "error": "payload must be a dict",
        }
    if not isinstance(rules, list):
        return {
            "computed_by": "custom_skill_evaluate_rules",
            "checks": [],
            "violation_count": 0,
            "risk_status": "unknown",
            "recommendation": "revisi",
            "error": "rules must be a list",
        }

    def number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def as_list(value):
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    checks = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            checks.append({
                "rule": f"Rule #{index + 1}",
                "field": None,
                "operator": None,
                "passed": False,
                "value": None,
                "expected": None,
                "severity": "high",
                "message": "rule must be a dict",
            })
            continue

        field = str(rule.get("field") or "").strip()
        operator = str(rule.get("operator") or "required").strip().lower()
        value = payload.get(field)
        expected = rule.get("value")
        severity = str(rule.get("severity") or "medium").strip().lower()
        passed = False

        if operator == "required":
            passed = value not in (None, "")
        elif operator == "eq":
            passed = value == expected
        elif operator == "ne":
            passed = value != expected
        elif operator in {"gt", "gte", "lt", "lte"}:
            current_number = number(value)
            expected_number = number(expected)
            if current_number is not None and expected_number is not None:
                if operator == "gt":
                    passed = current_number > expected_number
                elif operator == "gte":
                    passed = current_number >= expected_number
                elif operator == "lt":
                    passed = current_number < expected_number
                elif operator == "lte":
                    passed = current_number <= expected_number
        elif operator == "between":
            current_number = number(value)
            minimum = number(rule.get("min"))
            maximum = number(rule.get("max"))
            passed = (
                current_number is not None
                and minimum is not None
                and maximum is not None
                and minimum <= current_number <= maximum
            )
            expected = {"min": rule.get("min"), "max": rule.get("max")}
        elif operator == "one_of":
            expected = as_list(rule.get("allowed", expected))
            passed = value in expected
        elif operator == "not_one_of":
            expected = as_list(rule.get("blocked", expected))
            passed = value not in expected
        elif operator == "contains":
            passed = str(expected) in str(value or "")
        elif operator == "regex":
            try:
                passed = re.search(str(expected or ""), str(value or "")) is not None
            except re.error:
                passed = False

        checks.append({
            "rule": str(rule.get("label") or field or f"Rule #{index + 1}"),
            "field": field,
            "operator": operator,
            "passed": bool(passed),
            "value": value,
            "expected": expected,
            "severity": severity,
            "message": str(rule.get("message") or ""),
        })

    failed = [check for check in checks if not check["passed"]]
    high_failures = [check for check in failed if check.get("severity") == "high"]
    violation_count = len(failed)
    if high_failures or violation_count >= 3:
        risk_status = "tinggi"
        recommendation = "tunda"
    elif violation_count:
        risk_status = "sedang"
        recommendation = "revisi"
    else:
        risk_status = "rendah"
        recommendation = "lanjut"
    return {
        "computed_by": "custom_skill_evaluate_rules",
        "checks": checks,
        "violation_count": violation_count,
        "risk_status": risk_status,
        "recommendation": recommendation,
    }
''',
    },
    {
        "id": "record_summary",
        "label": "Record summary",
        "function_name": "custom_skill_summarize_records",
        "terms": (
            "data",
            "spreadsheet",
            "csv",
            "excel",
            "tabel",
            "analisis data",
            "olah data",
        ),
        "tool_terms": ("data", "spreadsheet", "csv", "excel", "table", "tabel"),
        "description": "Meringkas record tabular sederhana untuk SOP skill kustom.",
        "code": '''def custom_skill_summarize_records(records):
    """Return row count, columns, and missing-value counts for tabular records."""
    records = records or []
    if not isinstance(records, list):
        return {
            "computed_by": "custom_skill_summarize_records",
            "row_count": 0,
            "columns": [],
            "missing": {},
            "error": "records must be a list",
        }
    columns = []
    seen = set()
    for row in records:
        if isinstance(row, dict):
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    columns.append(key)
    missing = {key: 0 for key in columns}
    for row in records:
        if not isinstance(row, dict):
            continue
        for key in columns:
            if row.get(key) in (None, ""):
                missing[key] += 1
    return {
        "computed_by": "custom_skill_summarize_records",
        "row_count": len(records),
        "columns": columns,
        "missing": missing,
    }
''',
    },
)


class CustomSkillError(ValueError):
    """Validation error surfaced to the UI as HTTP 400."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_single_line(value: Any, *, max_len: int) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", text)[:max_len]


def _clean_multiline(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise CustomSkillError(f"text exceeds {MAX_TEXT_BYTES // 1024}KB limit")
    return text


def _clean_triggers(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.splitlines()
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    triggers: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = _clean_single_line(raw, max_len=160).lstrip("-* ").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        triggers.append(item)
    return triggers[:20]


def _section_text(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    wanted = heading.strip().lower()
    collecting = False
    section_lines: list[str] = []
    for line in lines:
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            if collecting:
                break
            collecting = match.group(1).strip().lower() == wanted
            continue
        if collecting:
            section_lines.append(line)
    return "\n".join(section_lines).strip()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not cleaned:
        cleaned = "custom-skill"
    if not cleaned[0].isalpha():
        cleaned = f"skill-{cleaned}"
    if len(cleaned) < 2:
        cleaned = f"{cleaned}-skill"
    return cleaned[:64].strip("-") or "custom-skill"


def _display_name(value: str) -> str:
    words: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9]+", value):
        if raw.lower() in TITLE_STOPWORDS:
            continue
        words.append(raw.upper() if raw.isupper() else raw.capitalize())
        if len(words) >= 5:
            break
    return " ".join(words) or "Skill Kustom"


def _topic_from_prompt(prompt: str) -> str:
    first_line = next((line.strip() for line in prompt.splitlines() if line.strip()), prompt)
    text = _clean_single_line(first_line, max_len=180)
    text = re.sub(
        r"^(tolong\s+)?(buatkan|buat|bikin|mohon|saya\s+mau)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(skill\s+kustom\s+|skill\s+untuk\s+|skill\s+yang\s+)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.split(r"\b(agar|supaya|dengan|untuk menghasilkan|yang bisa)\b", text, maxsplit=1)[0]
    return _display_name(text)


def _keywords_from_prompt(prompt: str) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{3,}", prompt.lower()):
        if word in TITLE_STOPWORDS or word in seen:
            continue
        seen.add(word)
        keywords.append(word)
        if len(keywords) >= 6:
            break
    return keywords


def _prompt_detail_lines(prompt: str) -> list[str]:
    details: list[str] = []
    for line in prompt.splitlines():
        cleaned = _clean_single_line(line.lstrip("-*0123456789. "), max_len=180)
        if cleaned:
            details.append(cleaned)
        if len(details) >= 8:
            break
    if not details:
        details.append(_clean_single_line(prompt, max_len=220))
    return details


def _normalized_haystack(*parts: str) -> str:
    return " ".join(part.lower() for part in parts if part)


def _word_terms(*parts: str) -> set[str]:
    terms: set[str] = set()
    for part in parts:
        for token in re.findall(r"[a-z][a-z0-9_]{1,}", part.lower()):
            terms.add(token)
            terms.update(piece for piece in token.split("_") if piece)
    expanded = set(terms)
    for canonical, aliases in FUNCTION_MATCH_ALIASES.items():
        if terms.intersection(aliases):
            expanded.add(canonical)
            expanded.update(aliases)
    return {
        term
        for term in expanded
        if term not in FUNCTION_NAME_STOPWORDS and len(term) >= 2
    }


def _matching_capabilities(prompt: str) -> list[dict[str, Any]]:
    haystack = _normalized_haystack(prompt)
    matches: list[dict[str, Any]] = []
    for capability in SCRIPT_CAPABILITIES:
        required_terms = tuple(
            str(term).lower() for term in capability.get("required_terms_any") or ()
        )
        if required_terms and not any(term in haystack for term in required_terms):
            continue
        if any(term in haystack for term in capability["terms"]):
            matches.append(capability)
    primary_matches = [
        capability for capability in matches if not capability.get("fallback")
    ]
    return primary_matches or matches


def _explicit_function_name_from_prompt(prompt: str) -> str | None:
    patterns = (
        r"\bnama\s+fungsi\s+[`'\"]?([A-Za-z_][A-Za-z0-9_]{0,63})[`'\"]?",
        r"\bfungsi\s+bernama\s+[`'\"]?([A-Za-z_][A-Za-z0-9_]{0,63})[`'\"]?",
    )
    for pattern in patterns:
        match = re.search(pattern, prompt, flags=re.IGNORECASE)
        if not match:
            continue
        name = match.group(1).strip().lower()
        if FUNCTION_NAME_RE.match(name):
            return name
    return None


def _explicit_custom_function_requested(prompt: str) -> bool:
    haystack = _normalized_haystack(prompt)
    request_terms = (
        "fungsi kustom",
        "custom function",
        "membuat fungsi",
        "buat fungsi",
        "membaut fungsi",
        "harus membuat fungsi",
        "wajib membuat fungsi",
        "gunakan fungsi",
        "pakai fungsi",
        "jalankan fungsi",
        "run fungsi",
        "tidak boleh dihitung",
        "tidak boleh dihitumng",
        "bukan dihitung agent",
    )
    return any(term in haystack for term in request_terms)


def _implicit_custom_function_recommended(prompt: str) -> bool:
    haystack = _normalized_haystack(prompt)
    deterministic_terms = (
        "hitung",
        "menghitung",
        "tambah",
        "penjumlahan",
        "jumlahkan",
        "kurang",
        "pengurangan",
        "kali",
        "perkalian",
        "bagi",
        "pembagian",
        "kalkulasi",
        "rumus",
        "luas",
        "keliling",
        "volume",
        "konversi",
        "persentase",
        "total",
        "subtotal",
        "validasi",
        "cek kelayakan",
        "layak atau tidak",
        "minimal",
        "maksimal",
        "threshold",
        "skor",
        "scoring",
        "ranking",
    )
    consistency_terms = (
        "akurat",
        "konsisten",
        "otomatis",
        "berdasarkan data",
        "jika user",
        "jika user kasih",
        "ketika user",
        "saat user",
    )
    has_deterministic_intent = any(term in haystack for term in deterministic_terms)
    has_input_hint = any(term in haystack for term in consistency_terms) or bool(
        re.search(
            r"\b(angka|panjang|lebar|tinggi|jumlah|harga|nilai|rating|skor|batas)\b",
            haystack,
        )
    )
    return has_deterministic_intent and has_input_hint


def _implicit_function_name_from_prompt(prompt: str) -> str:
    haystack = _normalized_haystack(prompt)
    name_source = haystack
    if any(term in haystack for term in ("validasi", "cek kelayakan", "layak atau tidak")):
        action_parts = ["validasi"]
    elif "konversi" in haystack:
        action_parts = ["konversi"]
    elif any(term in haystack for term in ("skor", "scoring", "ranking")):
        action_parts = ["hitung", "skor"]
    elif "keliling" in haystack:
        action_parts = ["hitung", "keliling"]
    elif "volume" in haystack:
        action_parts = ["hitung", "volume"]
    elif "luas" in haystack:
        action_parts = ["hitung", "luas"]
    elif any(term in haystack for term in ("persentase", "persen")):
        action_parts = ["hitung", "persentase"]
    else:
        action_parts = ["hitung"]

    for cue in reversed(action_parts):
        position = haystack.find(cue)
        if position >= 0:
            name_source = haystack[position + len(cue) :]
            break

    nouns: list[str] = []
    seen: set[str] = set(action_parts)
    noun_limit = 1 if any(
        part in action_parts for part in ("luas", "keliling", "volume", "persentase")
    ) else 2
    for token in re.findall(r"[a-z][a-z0-9_]{2,}", name_source):
        if token in FUNCTION_NAME_STOPWORDS or token in seen:
            continue
        seen.add(token)
        nouns.append(token)
        if len(nouns) >= noun_limit:
            break

    name = "_".join(action_parts + nouns)
    if not FUNCTION_NAME_RE.match(name):
        name = "custom_skill_deterministic_function"
    return name[:64].rstrip("_") or "custom_skill_deterministic_function"


def _function_code_for_prompt(name: str, prompt: str) -> tuple[str, str]:
    haystack = _normalized_haystack(prompt)
    if name == "custom_skill_evaluate_rules":
        for capability in SCRIPT_CAPABILITIES:
            if capability["function_name"] == "custom_skill_evaluate_rules":
                return str(capability["code"]), str(capability["description"])

    if "luas" in haystack and "panjang" in haystack and "lebar" in haystack:
        return (
            f'''def {name}(panjang, lebar, unit=""):
    """Calculate rectangular area deterministically from length and width."""
    panjang_value = float(panjang or 0)
    lebar_value = float(lebar or 0)
    luas = panjang_value * lebar_value
    return {{
        "computed_by": "{name}",
        "panjang": panjang_value,
        "lebar": lebar_value,
        "luas": luas,
        "unit": str(unit or ""),
    }}
''',
            "Menghitung luas persegi panjang dari panjang dan lebar.",
        )

    if "keliling" in haystack and "panjang" in haystack and "lebar" in haystack:
        return (
            f'''def {name}(panjang, lebar, unit=""):
    """Calculate rectangular perimeter deterministically from length and width."""
    panjang_value = float(panjang or 0)
    lebar_value = float(lebar or 0)
    keliling = 2 * (panjang_value + lebar_value)
    return {{
        "computed_by": "{name}",
        "panjang": panjang_value,
        "lebar": lebar_value,
        "keliling": keliling,
        "unit": str(unit or ""),
    }}
''',
            "Menghitung keliling persegi panjang dari panjang dan lebar.",
        )

    return (
        f'''def {name}(operation, values=None):
    """Run a deterministic arithmetic operation.

    Supported operations: add, subtract, multiply, divide, area_rectangle,
    area_triangle, area_circle, percentage.
    """
    values = values or {{}}
    if not isinstance(values, dict):
        return {{"computed_by": "{name}", "error": "values must be a dict"}}

    def number(key, default=0):
        try:
            return float(values.get(key, default) or default)
        except (TypeError, ValueError):
            return float(default)

    op = str(operation or "").strip().lower()
    if op == "add":
        result = sum(float(item or 0) for item in values.get("items", []))
    elif op == "subtract":
        result = number("a") - number("b")
    elif op == "multiply":
        result = number("a", 1) * number("b", 1)
    elif op == "divide":
        divisor = number("b")
        result = None if divisor == 0 else number("a") / divisor
    elif op == "area_rectangle":
        result = number("panjang") * number("lebar")
    elif op == "area_triangle":
        result = number("alas") * number("tinggi") / 2
    elif op == "area_circle":
        result = 3.141592653589793 * number("radius") * number("radius")
    elif op == "percentage":
        result = number("value") * number("percent") / 100
    else:
        return {{
            "computed_by": "{name}",
            "error": "unsupported operation",
            "supported_operations": [
                "add",
                "subtract",
                "multiply",
                "divide",
                "area_rectangle",
                "area_triangle",
                "area_circle",
                "percentage",
            ],
        }}
    return {{"computed_by": "{name}", "operation": op, "result": result}}
''',
        "Menjalankan operasi aritmetika deterministik umum.",
    )


def _requested_or_recommended_function_capability(prompt: str) -> dict[str, Any] | None:
    should_create = _explicit_custom_function_requested(
        prompt
    ) or _implicit_custom_function_recommended(prompt)
    if not should_create:
        return None
    function_name = _explicit_function_name_from_prompt(prompt)
    if not function_name:
        function_name = _implicit_function_name_from_prompt(prompt)
    code, description = _function_code_for_prompt(function_name, prompt)
    return {
        "id": f"recommended_{function_name}",
        "label": f"Custom function {function_name}",
        "function_name": function_name,
        "terms": (),
        "tool_terms": (),
        "description": description,
        "code": code,
    }


def _available_mcp_tools(mcp_registry: Any | None) -> list[dict[str, str]]:
    if mcp_registry is None:
        return []
    try:
        payload = mcp_registry.list_payload()
    except Exception:
        return []
    tools: list[dict[str, str]] = []
    for server in payload.get("servers") or []:
        if not isinstance(server, dict) or not server.get("enabled", True):
            continue
        for tool in server.get("tools") or []:
            if not isinstance(tool, dict) or not tool.get("enabled", True):
                continue
            registered = tool.get("registered_tool_name") or tool.get("registeredToolName")
            tools.append(
                {
                    "name": str(
                        registered or tool.get("namespaced_name") or tool.get("name") or ""
                    ),
                    "raw_name": str(tool.get("name") or ""),
                    "description": str(tool.get("description") or ""),
                    "server": str(server.get("name") or server.get("id") or ""),
                }
            )
    return [tool for tool in tools if tool["name"]]


def _available_custom_function_tools(custom_functions: Any | None) -> list[dict[str, str]]:
    if custom_functions is None:
        return []
    try:
        payload = custom_functions.list()
    except Exception:
        return []
    tools: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not FUNCTION_NAME_RE.match(name):
            continue
        tools.append(
            {
                "name": name,
                "description": str(item.get("description") or ""),
            }
        )
    return tools


def _find_matching_custom_function(
    capability: dict[str, Any],
    *,
    prompt: str,
    custom_function_tools: list[dict[str, str]],
) -> dict[str, str] | None:
    function_name = str(capability["function_name"])
    for tool in custom_function_tools:
        if tool["name"] == function_name:
            return {"type": "custom_function", "name": function_name}

    prompt_terms = _word_terms(prompt)
    capability_terms = _word_terms(
        str(capability.get("label") or ""),
        str(capability.get("function_name") or ""),
        " ".join(str(term) for term in capability.get("terms") or ()),
        " ".join(str(term) for term in capability.get("tool_terms") or ()),
        str(capability.get("description") or ""),
    )
    desired_terms = prompt_terms | capability_terms
    best_tool: dict[str, str] | None = None
    best_score = 0
    for tool in custom_function_tools:
        name_terms = _word_terms(tool["name"])
        description_terms = _word_terms(tool["description"])
        score = len(desired_terms.intersection(name_terms)) * 4
        score += len(desired_terms.intersection(description_terms))
        if tool["name"].lower() in _normalized_haystack(prompt):
            score += 6
        if score > best_score:
            best_score = score
            best_tool = tool

    if best_tool is not None and best_score >= 4:
        return {"type": "custom_function", "name": best_tool["name"]}
    return None


def _find_matching_tool(
    capability: dict[str, Any],
    *,
    prompt: str,
    custom_function_tools: list[dict[str, str]],
    mcp_tools: list[dict[str, str]],
) -> dict[str, str] | None:
    custom_function_match = _find_matching_custom_function(
        capability,
        prompt=prompt,
        custom_function_tools=custom_function_tools,
    )
    if custom_function_match is not None:
        return custom_function_match

    if not bool(capability.get("allow_mcp_reuse")):
        return None

    terms = tuple(str(term).lower() for term in capability.get("tool_terms") or ())
    for tool in mcp_tools:
        server = tool["server"].lower()
        if server in {"custom_function", "filesystem", "openbench"}:
            continue
        haystack = _normalized_haystack(tool["name"], tool["raw_name"], tool["description"])
        if any(term in haystack for term in terms):
            return {"type": "mcp", "name": tool["name"], "server": tool["server"]}
    return None


def _tooling_plan_from_prompt(
    prompt: str,
    *,
    custom_functions: Any | None = None,
    mcp_registry: Any | None = None,
) -> dict[str, Any]:
    custom_function_tools = _available_custom_function_tools(custom_functions)
    custom_function_names = {tool["name"] for tool in custom_function_tools}
    mcp_tools = _available_mcp_tools(mcp_registry)
    required: list[dict[str, Any]] = []
    created: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    created_names: set[str] = set()
    capabilities = _matching_capabilities(prompt)

    explicit_capability = None
    if _explicit_custom_function_requested(prompt) or not capabilities:
        explicit_capability = _requested_or_recommended_function_capability(prompt)
    if explicit_capability:
        capabilities = [
            capability
            for capability in capabilities
            if capability["function_name"] != explicit_capability["function_name"]
        ]
        capabilities.insert(0, explicit_capability)

    for capability in capabilities:
        match = _find_matching_tool(
            capability,
            prompt=prompt,
            custom_function_tools=custom_function_tools,
            mcp_tools=mcp_tools,
        )
        if match is None and custom_functions is not None:
            function_name = str(capability["function_name"])
            custom_functions.save(
                function_name,
                str(capability["code"]),
                str(capability["description"]),
            )
            custom_function_names.add(function_name)
            custom_function_tools.append(
                {"name": function_name, "description": str(capability["description"])}
            )
            match = {"type": "custom_function", "name": function_name}
            created.append(
                {
                    "capability": capability["id"],
                    "name": function_name,
                    "type": "custom_function",
                }
            )
            created_names.add(function_name)
        if match is None:
            required.append(
                {
                    "capability": capability["id"],
                    "label": capability["label"],
                    "status": "missing",
                    "instruction": (
                        "Tambahkan fungsi lewat menu Fungsi Kustom atau aktifkan tool MCP "
                        "yang relevan sebelum mengklaim capability ini tersedia."
                    ),
                }
            )
            continue
        dependency = {
            "capability": capability["id"],
            "label": capability["label"],
            "status": "available",
            **match,
        }
        required.append(dependency)
        if dependency.get("name") not in created_names:
            reused.append(dependency)

    return {
        "required": required,
        "created_functions": created,
        "reused_tools": reused,
    }


def _skill_spec_from_prompt(prompt: str) -> dict[str, Any]:
    prompt = _clean_multiline(prompt)
    if not prompt:
        raise CustomSkillError("prompt is required")
    name = _topic_from_prompt(prompt)
    topic = name.lower()
    keywords = _keywords_from_prompt(prompt)
    keyword_text = ", ".join(keywords[:4]) if keywords else topic
    details = _prompt_detail_lines(prompt)
    detail_block = "\n".join(f"- {line}" for line in details)
    description = (
        f"Skill kustom untuk membantu agent menangani permintaan terkait {topic} "
        "berdasarkan kebutuhan yang ditulis admin."
    )
    triggers = [
        f"User meminta bantuan terkait {topic}.",
        f"User ingin agent mengikuti SOP, gaya, atau batasan khusus untuk {topic}.",
        f"Permintaan user memuat konteks atau kata kunci seperti {keyword_text}.",
    ]
    instructions = (
        "Gunakan skill ini hanya saat permintaan user cocok dengan trigger.\n\n"
        "SOP:\n"
        "1. Pahami tujuan user, data yang tersedia, dan hasil akhir yang diminta.\n"
        "2. Terapkan detail kebutuhan berikut sebagai aturan kerja utama:\n"
        f"{detail_block}\n"
        "3. Susun jawaban dengan struktur yang jelas, praktis, dan langsung bisa dipakai.\n"
        "4. Jika informasi penting belum tersedia, jelaskan asumsi dan minta input lanjutan "
        "yang spesifik.\n"
        "5. Jangan mengklaim sudah menjalankan alat, mengakses data, atau membuat file jika "
        "hal itu belum benar-benar dilakukan."
    )
    return {
        "name": name,
        "description": description,
        "triggers": triggers,
        "instructions": instructions,
        "version": "0.1.0",
    }


def _render_skill_md(
    *,
    name: str,
    description: str,
    triggers: list[str],
    instructions: str,
    version: str,
    tooling: dict[str, Any] | None = None,
) -> str:
    trigger_block = "\n".join(f"- {trigger}" for trigger in triggers) or "- Use when relevant."
    tooling_block = ""
    required_tools = list((tooling or {}).get("required") or [])
    if required_tools:
        lines = [
            "## Tooling",
            "",
            "Skill ini boleh menjalankan tool/fungsi berikut saat SOP membutuhkan eksekusi nyata:",
            "",
        ]
        for tool in required_tools:
            if tool.get("status") == "available":
                if tool.get("type") == "custom_function":
                    lines.append(
                        f"- {tool['label']}: panggil `custom_function_run_function` "
                        f"dengan `name=\"{tool['name']}\"` dan `kwargs_json` sesuai "
                        "input user."
                    )
                else:
                    lines.append(f"- {tool['label']}: gunakan `{tool['name']}` dari MCP.")
            else:
                lines.append(f"- {tool['label']}: belum tersedia; {tool['instruction']}")
        lines.extend(
            [
                "",
                "Aturan eksekusi:",
                "1. Panggil tool hanya ketika output user benar-benar membutuhkan hasil eksekusi.",
                "2. Untuk Fungsi Kustom, gunakan hasil `custom_function_run_function` "
                "sebagai sumber keputusan.",
                "3. Jika tool yang dibutuhkan belum tersedia, jangan berpura-pura "
                "menjalankannya.",
                "4. Jangan membuat MCP baru dari skill; fungsi baru harus dibuat lewat "
                "menu Fungsi Kustom.",
                "",
            ]
        )
        tooling_block = "\n".join(lines)
    return (
        f"# {name}\n\n"
        f"{description or 'Custom General Chat skill.'}\n\n"
        "## Triggers\n\n"
        f"{trigger_block}\n\n"
        "## Instructions\n\n"
        f"{instructions}\n\n"
        f"{tooling_block}"
        "## Version\n\n"
        f"{version}\n"
    )


class CustomSkillStore:
    """Manage admin-defined project-skill directories."""

    def __init__(self, storage_root: str) -> None:
        configured = os.getenv("GENERAL_CHAT_CUSTOM_SKILLS_DIR", "").strip()
        self.root = Path(configured) if configured else Path(storage_root) / "custom-skills"
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id(skill_id: str) -> str:
        cleaned = str(skill_id or "").strip().lower()
        if not ID_RE.match(cleaned):
            raise CustomSkillError(
                "invalid skill id: use lowercase letters, digits, and hyphen; "
                "must start with a letter; length 2-64"
            )
        return cleaned

    @staticmethod
    def _validate_version(version: str) -> str:
        cleaned = _clean_single_line(version or "0.1.0", max_len=32) or "0.1.0"
        if not VERSION_RE.match(cleaned):
            raise CustomSkillError("invalid version: use a semver-like value such as 0.1.0")
        return cleaned

    def _path_for(self, skill_id: str) -> Path:
        return self.root / self._validate_id(skill_id)

    def _unique_id(self, seed: str) -> str:
        base = self._validate_id(_slugify(seed))
        candidate = base
        counter = 2
        while (self.root / candidate / "SKILL.md").is_file():
            suffix = f"-{counter}"
            candidate = f"{base[: 64 - len(suffix)]}{suffix}".strip("-")
            counter += 1
        return candidate

    def paths(self) -> list[Path]:
        return [
            entry
            for entry in sorted(self.root.iterdir())
            if entry.is_dir() and (entry / "SKILL.md").is_file()
        ]

    def save(
        self,
        skill_id: str,
        *,
        name: str,
        description: str = "",
        triggers: Any = None,
        instructions: str = "",
        version: str = "0.1.0",
        tooling: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        skill_id = self._validate_id(skill_id)
        name = _clean_single_line(name, max_len=80)
        if not name:
            raise CustomSkillError("skill name is required")
        description = _clean_single_line(description, max_len=500)
        instructions = _clean_multiline(instructions)
        if not instructions:
            raise CustomSkillError("instructions are required")
        triggers = _clean_triggers(triggers)
        version = self._validate_version(version)

        skill_dir = self._path_for(skill_id)
        existing = self.get(skill_id, include_markdown=False)
        created_at = existing.get("created_at") if existing else _utc_now()
        updated_at = _utc_now()
        skill_md = _render_skill_md(
            name=name,
            description=description,
            triggers=triggers,
            instructions=instructions,
            version=version,
            tooling=tooling,
        )

        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        # Validate with the same loader the agent will use before persisting
        # metadata or returning success.
        loaded = Skill.from_dir(skill_dir)
        meta = {
            "id": skill_id,
            "name": loaded.name,
            "description": loaded.description,
            "triggers": list(loaded.triggers),
            "instructions": instructions,
            "tooling": tooling or {"required": [], "created_functions": [], "reused_tools": []},
            "version": loaded.version,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        (skill_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        return self._serialize(skill_dir, include_markdown=True)

    def save_from_prompt(
        self,
        prompt: str,
        *,
        custom_functions: Any | None = None,
        mcp_registry: Any | None = None,
    ) -> dict[str, Any]:
        spec = _skill_spec_from_prompt(prompt)
        tooling = _tooling_plan_from_prompt(
            prompt,
            custom_functions=custom_functions,
            mcp_registry=mcp_registry,
        )
        return self.save(
            self._unique_id(spec["name"]),
            name=spec["name"],
            description=spec["description"],
            triggers=spec["triggers"],
            instructions=spec["instructions"],
            version=spec["version"],
            tooling=tooling,
        )

    def save_markdown(self, skill_id: str, markdown: str) -> dict[str, Any]:
        skill_id = self._validate_id(skill_id)
        markdown = _clean_multiline(markdown)
        if not markdown:
            raise CustomSkillError("skill markdown is required")

        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp) / skill_id
            temp_dir.mkdir(parents=True, exist_ok=True)
            (temp_dir / "SKILL.md").write_text(markdown, encoding="utf-8")
            loaded = Skill.from_dir(temp_dir)
        version = self._validate_version(loaded.version)

        skill_dir = self._path_for(skill_id)
        existing = self.get(skill_id, include_markdown=False)
        created_at = existing.get("created_at") if existing else _utc_now()
        existing_tooling = existing.get("tooling") if existing else None
        updated_at = _utc_now()
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(markdown.strip() + "\n", encoding="utf-8")
        loaded = Skill.from_dir(skill_dir)
        meta = {
            "id": skill_id,
            "name": loaded.name,
            "description": loaded.description,
            "triggers": list(loaded.triggers),
            "instructions": _section_text(loaded.raw_skill_md, "Instructions"),
            "tooling": existing_tooling
            if isinstance(existing_tooling, dict)
            else {"required": [], "created_functions": [], "reused_tools": []},
            "version": version,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        (skill_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        return self._serialize(skill_dir, include_markdown=True)

    def _serialize(self, skill_dir: Path, *, include_markdown: bool) -> dict[str, Any]:
        skill = Skill.from_dir(skill_dir)
        metadata: dict[str, Any] = {}
        meta_path = skill_dir / "metadata.json"
        if meta_path.is_file():
            try:
                raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(raw_meta, dict):
                    metadata = raw_meta
            except (OSError, ValueError):
                metadata = {}
        item = {
            "id": str(metadata.get("id") or skill_dir.name),
            "name": skill.name,
            "description": skill.description,
            "triggers": list(skill.triggers),
            "instructions": str(metadata.get("instructions") or ""),
            "tooling": metadata.get("tooling")
            if isinstance(metadata.get("tooling"), dict)
            else {"required": [], "created_functions": [], "reused_tools": []},
            "version": skill.version,
            "created_at": str(metadata.get("created_at") or ""),
            "updated_at": str(metadata.get("updated_at") or ""),
            "source": str(skill_dir.resolve()),
            "context_chars": len(skill.get_context()),
        }
        if include_markdown:
            item["skill_md"] = skill.raw_skill_md
        return item

    def get(self, skill_id: str, *, include_markdown: bool = True) -> dict[str, Any] | None:
        skill_dir = self._path_for(skill_id)
        if not (skill_dir / "SKILL.md").is_file():
            return None
        return self._serialize(skill_dir, include_markdown=include_markdown)

    def list(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for skill_dir in self.paths():
            try:
                result.append(self._serialize(skill_dir, include_markdown=True))
            except Exception:
                continue
        return result

    def delete(self, skill_id: str) -> bool:
        skill_dir = self._path_for(skill_id)
        if not skill_dir.is_dir():
            return False
        for filename in ("SKILL.md", "metadata.json"):
            path = skill_dir / filename
            if path.is_file():
                path.unlink()
        try:
            skill_dir.rmdir()
        except OSError:
            pass
        return True
