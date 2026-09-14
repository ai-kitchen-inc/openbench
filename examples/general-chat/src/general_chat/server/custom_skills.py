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
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from openbench.intelligence.skill import Skill

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:[-+][a-zA-Z0-9.-]+)?$")
MAX_TEXT_BYTES = 64 * 1024
MAX_RESOURCE_FILE_BYTES = 10 * 1024 * 1024
TEXT_RESOURCE_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}
BINARY_ASSET_EXTENSIONS = {
    ".doc",
    ".docx",
    ".pdf",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".svg",
    ".zip",
}
SPREADSHEET_TEMPLATE_EXTENSIONS = {".xlsx", ".xlsm"}
DOCUMENT_TEMPLATE_EXTENSIONS = {".docx", ".pptx", ".pdf", ".txt", ".md"}
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


def _empty_tooling() -> dict[str, Any]:
    return {"required": [], "created_functions": [], "reused_tools": []}


def _empty_resources() -> dict[str, Any]:
    return {"references": [], "assets": [], "examples": [], "scripts": []}


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


def _safe_filename(value: str, *, fallback: str = "resource") -> str:
    raw = Path(str(value or "")).name.strip()
    stem = Path(raw).stem if raw else fallback
    suffix = Path(raw).suffix.lower()
    cleaned_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    if not cleaned_stem:
        cleaned_stem = fallback
    return f"{cleaned_stem[:80]}{suffix[:16]}"


def _unique_child_path(directory: Path, filename: str) -> Path:
    filename = _safe_filename(filename)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        next_candidate = directory / f"{stem[:70]}-{counter}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        counter += 1


def _resource_bucket(filename: str, hint: str = "") -> str:
    hint_text = _normalized_haystack(hint)
    suffix = Path(filename).suffix.lower()
    if suffix in {".py", ".js", ".ts", ".sh", ".ps1"}:
        return "scripts"
    if suffix in BINARY_ASSET_EXTENSIONS:
        return "assets"
    if suffix in TEXT_RESOURCE_EXTENSIONS:
        return "references"
    if any(
        term in hint_text
        for term in ("example", "contoh input", "contoh output", "sample")
    ):
        return "examples"
    if any(term in hint_text for term in ("asset", "template", "aset")):
        return "assets"
    if any(
        term in hint_text
        for term in ("reference", "referensi", "sop", "knowledge", "aturan")
    ):
        return "references"
    return "assets"


def _summarize_uploaded_resource(filename: str, content: bytes, hint: str = "") -> dict[str, Any]:
    safe_name = _safe_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    bucket = _resource_bucket(safe_name, hint)
    size = len(content)
    text_preview = ""
    if suffix in TEXT_RESOURCE_EXTENSIONS or bucket == "references":
        try:
            text_preview = content[:12000].decode("utf-8")
        except UnicodeDecodeError:
            try:
                text_preview = content[:12000].decode("latin-1")
            except UnicodeDecodeError:
                text_preview = ""
    return {
        "source_name": safe_name,
        "filename": safe_name,
        "kind": bucket[:-1] if bucket.endswith("s") else bucket,
        "bucket": bucket,
        "size_bytes": size,
        "hint": _clean_single_line(hint, max_len=160),
        "text_preview": text_preview.strip(),
    }


def _prompt_resource_plan(prompt: str) -> dict[str, Any]:
    haystack = _normalized_haystack(prompt)
    resources = _empty_resources()
    if any(
        term in haystack
        for term in ("sop", "aturan", "policy", "kebijakan", "knowledge")
    ):
        resources["references"].append(
            {
                "filename": "prompt-rules.md",
                "description": "Aturan dan knowledge yang diekstrak dari prompt admin.",
                "generated": True,
                "content": (
                    "# Prompt Rules\n\n"
                    "Gunakan poin berikut sebagai referensi domain saat skill aktif:\n\n"
                    + "\n".join(f"- {line}" for line in _prompt_detail_lines(prompt))
                    + "\n"
                ),
            }
        )
    if any(
        term in haystack
        for term in ("template", "format laporan", "format output", "bab 1", "bab i")
    ):
        resources["references"].append(
            {
                "filename": "output-template.md",
                "description": "Template output yang dijelaskan langsung di prompt admin.",
                "generated": True,
                "content": (
                    "# Output Template\n\n"
                    "Ikuti struktur/template berikut saat user meminta output final:\n\n"
                    + "\n".join(f"- {line}" for line in _prompt_detail_lines(prompt))
                    + "\n"
                ),
            }
        )
    return resources


def _spreadsheet_template_reference(upload: dict[str, Any], filename: str) -> dict[str, Any] | None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SPREADSHEET_TEMPLATE_EXTENSIONS:
        return None
    source_path = upload.get("source_path")
    if not source_path:
        return None
    path = Path(str(source_path))
    if not path.is_file():
        return None
    try:
        from openpyxl import load_workbook
    except ImportError:
        return None

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return None

    lines = [
        f"# Excel Template Schema: {filename}",
        "",
        f"Asset file: `assets/{filename}`.",
        "",
        "When creating an Excel output for this skill, follow this template schema exactly.",
        "Use the same sheet intent, column names, and column order unless the user explicitly asks otherwise.",
        "",
    ]
    try:
        for sheet_name in workbook.sheetnames[:5]:
            worksheet = workbook[sheet_name]
            rows = list(worksheet.iter_rows(min_row=1, max_row=6, values_only=True))
            non_empty_rows = [
                [cell for cell in row]
                for row in rows
                if any(cell not in (None, "") for cell in row)
            ]
            if not non_empty_rows:
                continue
            header_row = non_empty_rows[0]
            headers = [
                str(cell).strip()
                for cell in header_row
                if cell not in (None, "") and str(cell).strip()
            ]
            lines.extend([f"## Sheet: {sheet_name}", ""])
            if headers:
                lines.append("Columns, in order:")
                lines.extend(f"{index}. {header}" for index, header in enumerate(headers, start=1))
                lines.append("")
            sample_rows = non_empty_rows[1:3]
            if sample_rows:
                lines.append("Sample rows from the template:")
                for row in sample_rows:
                    values = [str(cell).strip() for cell in row[: len(headers)]]
                    lines.append("- " + " | ".join(values))
                lines.append("")
    finally:
        workbook.close()

    if len(lines) <= 7:
        return None
    return {
        "filename": f"excel-template-{Path(filename).stem}.md",
        "description": f"Extracted Excel template schema for {filename}.",
        "generated": True,
        "content": "\n".join(lines).strip() + "\n",
    }


def _xml_text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


def _docx_template_reference(path: Path, filename: str) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            document_xml = archive.read("word/document.xml")
    except Exception:
        return None

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError:
        return None

    lines = [
        f"# Document Template Map: {filename}",
        "",
        f"Asset file: `assets/{filename}`.",
        "",
        "Use this map to decide which `fields` or `records` to send to the template asset tool.",
        "The final output must still be produced from the original asset file, not rebuilt from this map.",
        "",
    ]

    content_controls: list[str] = []
    for sdt in root.findall(".//w:sdt", ns)[:40]:
        props = sdt.find("w:sdtPr", ns)
        if props is None:
            continue
        alias = props.find("w:alias", ns)
        tag = props.find("w:tag", ns)
        alias_value = alias.get(f"{{{ns['w']}}}val") if alias is not None else ""
        tag_value = tag.get(f"{{{ns['w']}}}val") if tag is not None else ""
        label = alias_value or tag_value
        if label:
            content_controls.append(label)

    if content_controls:
        lines.extend(["## Content Controls", ""])
        lines.extend(f"- `{label}`" for label in content_controls)
        lines.append("")

    form_labels: list[str] = []
    for table_index, table in enumerate(root.findall(".//w:tbl", ns)[:20], start=1):
        rows = table.findall("w:tr", ns)
        table_rows: list[list[str]] = []
        for row in rows[:30]:
            cells = [
                _xml_text(cell)
                for cell in row.findall("w:tc", ns)
            ]
            if any(cells):
                table_rows.append(cells)
                for cell_index, cell_text in enumerate(cells):
                    cleaned = re.sub(r"[:：._-]+$", "", cell_text).strip()
                    next_cells_empty = all(not value.strip() for value in cells[cell_index + 1:])
                    if cleaned and (next_cells_empty or re.search(r"[:：]\\s*$|[_\\. ]{3,}", cell_text)):
                        form_labels.append(cleaned)
        if not table_rows:
            continue
        lines.extend([f"## Table {table_index}", ""])
        for row in table_rows[:12]:
            lines.append("- " + " | ".join(value or "[empty]" for value in row[:8]))
        lines.append("")

    paragraphs = []
    for paragraph in root.findall(".//w:p", ns):
        text = _xml_text(paragraph)
        if text and len(text) <= 180:
            paragraphs.append(text)
        if len(paragraphs) >= 30:
            break
    if paragraphs:
        lines.extend(["## Visible Text", ""])
        lines.extend(f"- {text}" for text in paragraphs[:30])
        lines.append("")
        for text in paragraphs:
            cleaned = re.sub(r"[:：._-]+$", "", text).strip()
            if cleaned and re.search(r"[:：]\\s*$|[_\\. ]{3,}", text):
                form_labels.append(cleaned)

    unique_labels = []
    seen: set[str] = set()
    for label in content_controls + form_labels:
        normalized = _normalized_haystack(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_labels.append(label)
    if unique_labels:
        lines.extend(["## Suggested Field Keys", ""])
        lines.append("Send these as `fields` keys when calling the template tool:")
        lines.extend(f"- `{label}`" for label in unique_labels[:40])
        lines.append("")

    if len(lines) <= 7:
        return None
    return {
        "filename": f"document-template-{Path(filename).stem}.md",
        "description": f"Extracted document template map for {filename}.",
        "generated": True,
        "content": "\n".join(lines).strip() + "\n",
    }


def _pptx_template_reference(path: Path, filename: str) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            slide_names = sorted(
                name for name in archive.namelist()
                if re.match(r"ppt/slides/slide\\d+\\.xml$", name)
            )
            slide_xml = [(name, archive.read(name)) for name in slide_names[:20]]
    except Exception:
        return None
    if not slide_xml:
        return None

    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    lines = [
        f"# Presentation Template Map: {filename}",
        "",
        f"Asset file: `assets/{filename}`.",
        "",
        "Use this map to choose `fields` values for the template asset tool.",
        "The final output must still be produced from the original PPTX asset.",
        "",
    ]
    for index, (_, data) in enumerate(slide_xml, start=1):
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            continue
        texts = [
            _xml_text(node)
            for node in root.findall(".//a:t", ns)
            if _xml_text(node)
        ]
        if not texts:
            continue
        lines.extend([f"## Slide {index}", ""])
        lines.extend(f"- {text}" for text in texts[:30])
        placeholders = re.findall(r"\\{\\{\\s*([^{}]+?)\\s*\\}\\}", "\n".join(texts))
        if placeholders:
            lines.append("")
            lines.append("Suggested field keys:")
            lines.extend(f"- `{placeholder.strip()}`" for placeholder in placeholders[:20])
        lines.append("")

    if len(lines) <= 7:
        return None
    return {
        "filename": f"presentation-template-{Path(filename).stem}.md",
        "description": f"Extracted presentation template map for {filename}.",
        "generated": True,
        "content": "\n".join(lines).strip() + "\n",
    }


def _pdf_template_reference(path: Path, filename: str) -> dict[str, Any] | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
    except Exception:
        return None
    lines = [
        f"# PDF Template Map: {filename}",
        "",
        f"Asset file: `assets/{filename}`.",
        "",
        "Use this map to choose `fields` values for the template asset tool.",
        "PDF filling is supported for fillable AcroForm fields. Flat/scanned PDFs need manual field mapping before they can be filled precisely.",
        "",
    ]
    fields = reader.get_fields() or {}
    if fields:
        lines.extend(["## Fillable Form Fields", ""])
        lines.extend(f"- `{name}`" for name in fields.keys())
        lines.append("")
    visible_text: list[str] = []
    for page in reader.pages[:3]:
        with contextlib.suppress(Exception):
            text = (page.extract_text() or "").strip()
            if text:
                visible_text.extend(line.strip() for line in text.splitlines() if line.strip())
    if visible_text:
        lines.extend(["## Visible Text Preview", ""])
        lines.extend(f"- {line}" for line in visible_text[:40])
        lines.append("")
    if len(lines) <= 7:
        return None
    return {
        "filename": f"pdf-template-{Path(filename).stem}.md",
        "description": f"Extracted PDF template map for {filename}.",
        "generated": True,
        "content": "\n".join(lines).strip() + "\n",
    }


def _document_template_reference(upload: dict[str, Any], filename: str) -> dict[str, Any] | None:
    suffix = Path(filename).suffix.lower()
    if suffix not in DOCUMENT_TEMPLATE_EXTENSIONS:
        return None
    source_path = upload.get("source_path")
    if not source_path:
        return None
    path = Path(str(source_path))
    if not path.is_file():
        return None
    if suffix == ".docx":
        return _docx_template_reference(path, filename)
    if suffix == ".pptx":
        return _pptx_template_reference(path, filename)
    if suffix == ".pdf":
        return _pdf_template_reference(path, filename)
    if suffix in {".txt", ".md"}:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
        placeholders = re.findall(r"\\{\\{\\s*([^{}]+?)\\s*\\}\\}", text)
        if not placeholders:
            return None
        lines = [
            f"# Text Template Map: {filename}",
            "",
            f"Asset file: `assets/{filename}`.",
            "",
            "Suggested field keys:",
            *[f"- `{placeholder.strip()}`" for placeholder in placeholders[:60]],
            "",
        ]
        return {
            "filename": f"text-template-{Path(filename).stem}.md",
            "description": f"Extracted text template map for {filename}.",
            "generated": True,
            "content": "\n".join(lines),
        }
    return None


def _resources_from_uploads(uploads: list[dict[str, Any]] | None) -> dict[str, Any]:
    resources = _empty_resources()
    for upload in uploads or []:
        if not isinstance(upload, dict):
            continue
        filename = _safe_filename(
            str(upload.get("filename") or upload.get("source_name") or "resource")
        )
        bucket = str(
            upload.get("bucket") or _resource_bucket(filename, str(upload.get("hint") or ""))
        )
        if bucket not in resources:
            bucket = "assets"
        item = {
            "filename": filename,
            "description": _clean_single_line(
                upload.get("description")
                or upload.get("hint")
                or f"Resource uploaded as {filename}.",
                max_len=220,
            ),
            "source_name": str(upload.get("source_name") or filename),
            "size_bytes": int(upload.get("size_bytes") or 0),
            "generated": False,
        }
        if upload.get("source_path"):
            item["source_path"] = str(upload.get("source_path"))
        text_preview = str(upload.get("text_preview") or "").strip()
        if bucket == "references" and text_preview:
            item["content"] = (
                f"# {Path(filename).stem.replace('-', ' ').title()}\n\n"
                f"Source upload: `{filename}`.\n\n"
                f"{text_preview}\n"
            )
            if Path(filename).suffix.lower() != ".md":
                item["filename"] = f"{Path(filename).stem}.md"
        resources[bucket].append(item)
        template_reference = _spreadsheet_template_reference(upload, filename)
        if template_reference is not None:
            resources["references"].append(template_reference)
        document_reference = _document_template_reference(upload, filename)
        if document_reference is not None:
            resources["references"].append(document_reference)
    return resources


def _merge_resources(*plans: dict[str, Any] | None) -> dict[str, Any]:
    merged = _empty_resources()
    seen: set[tuple[str, str]] = set()
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        for bucket in merged:
            for item in plan.get(bucket) or []:
                if not isinstance(item, dict):
                    continue
                filename = _safe_filename(str(item.get("filename") or "resource"))
                key = (bucket, filename)
                if key in seen:
                    continue
                seen.add(key)
                copy = dict(item)
                copy["filename"] = filename
                merged[bucket].append(copy)
    return merged


def _resource_section(resources: dict[str, Any] | None) -> str:
    resources = resources or _empty_resources()
    lines: list[str] = []
    for title, bucket, guidance in (
        (
            "References",
            "references",
            "Read these files only when the task needs the detailed SOP, rules, examples, or template.",
        ),
        (
            "Assets",
            "assets",
            "Use these static files as templates or supporting resources when producing artifacts. "
            "If a matching Excel template schema reference exists, mirror its columns exactly.",
        ),
        (
            "Examples",
            "examples",
            "Use these examples to match input/output shape and quality expectations.",
        ),
        (
            "Scripts",
            "scripts",
            "Run these scripts only when deterministic execution is required and the runtime supports it.",
        ),
    ):
        items = list(resources.get(bucket) or [])
        if not items:
            continue
        if not lines:
            lines.extend(["## Resources", ""])
        lines.extend([f"### {title}", "", guidance, ""])
        for item in items:
            filename = _safe_filename(str(item.get("filename") or "resource"))
            description = _clean_single_line(item.get("description") or "", max_len=220)
            lines.append(f"- `{bucket}/{filename}`" + (f" - {description}" if description else ""))
        lines.append("")
    return "\n".join(lines)


def _template_tool_name(skill_id: str) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", skill_id.lower()).strip("_")
    if not base:
        base = "custom_skill"
    name = f"fill_{base[:42]}_template"
    if not re.match(r"^[a-z_]", name):
        name = f"fill_{name}"
    return name[:64].rstrip("_")


def _template_tool_section(tool_name: str | None, resources: dict[str, Any] | None) -> str:
    if not tool_name:
        return ""
    assets = list((resources or {}).get("assets") or [])
    if not assets:
        return ""
    lines = [
        "## Template Asset Tool",
        "",
        (
            f"Untuk output yang harus mengikuti template asset secara presisi, panggil "
            f"`{tool_name}`. Jangan membuat ulang file dari nol jika template asset tersedia."
        ),
        "",
        "Asset yang bisa dipakai:",
    ]
    for asset in assets:
        path = str(asset.get("path") or f"assets/{_safe_filename(str(asset.get('filename') or 'template'))}")
        lines.append(f"- `{path}`")
    lines.extend(
        [
            "",
            "Aturan:",
            "0. Output harus memakai format yang sama dengan asset template: DOCX menghasilkan DOCX, PDF menghasilkan PDF, PPTX menghasilkan PPTX, XLSX menghasilkan XLSX.",
            "1. Untuk Excel, tool akan menyalin workbook template asli dan mengisi data pada kolom/sheet template.",
            "2. Untuk Word/PPT/TXT, kirim data lewat `fields` atau `records`; tool akan mengisi placeholder `{{nama_field}}` bila ada.",
            "3. Untuk Word DOCX berbentuk tabel/form, tool juga akan mencocokkan label seperti Nama/Kelas/Fisika lalu mengisi cell kosong terdekat.",
            "4. Untuk PDF, tool akan mencoba mengisi AcroForm field bila field tersedia.",
            "5. Jika tool mengembalikan error, jelaskan error tersebut dan jangan mengklaim file selesai.",
            "6. Jangan mengirim file output jika `filledFields`/`filledColumns` tidak ada atau bernilai 0.",
            "",
        ]
    )
    return "\n".join(lines)


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
    resources: dict[str, Any] | None = None,
    template_tool_name: str | None = None,
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
        f"{_resource_section(resources)}"
        f"{_template_tool_section(template_tool_name, resources)}"
        f"{tooling_block}"
        "## Version\n\n"
        f"{version}\n"
    )


def _write_resource_files(skill_dir: Path, resources: dict[str, Any] | None) -> dict[str, Any]:
    resources = resources or _empty_resources()
    persisted = _empty_resources()
    for bucket, items in resources.items():
        if bucket not in persisted:
            continue
        target_dir = skill_dir / bucket
        for item in items or []:
            if not isinstance(item, dict):
                continue
            filename = _safe_filename(str(item.get("filename") or "resource"))
            if bucket == "references" and Path(filename).suffix.lower() != ".md":
                filename = f"{Path(filename).stem}.md"
            content = item.get("content")
            source_path = item.get("source_path")
            if content is None and not source_path:
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = _unique_child_path(target_dir, filename)
            if source_path:
                src = Path(str(source_path))
                if not src.is_file():
                    continue
                if src.stat().st_size > MAX_RESOURCE_FILE_BYTES:
                    raise CustomSkillError(
                        f"resource file exceeds {MAX_RESOURCE_FILE_BYTES // (1024 * 1024)}MB limit"
                    )
                shutil.copyfile(src, target_path)
            else:
                text = _clean_multiline(content)
                target_path.write_text(text.strip() + "\n", encoding="utf-8")
            persisted_item = {
                key: value
                for key, value in item.items()
                if key not in {"content", "source_path", "text_preview"}
            }
            persisted_item["filename"] = target_path.name
            persisted_item["path"] = f"{bucket}/{target_path.name}"
            persisted_item["size_bytes"] = target_path.stat().st_size
            persisted[bucket].append(persisted_item)
    return persisted


def _write_template_tools(
    skill_dir: Path,
    *,
    skill_id: str,
    resources: dict[str, Any],
) -> str | None:
    assets = list(resources.get("assets") or [])
    if not assets:
        tools_py = skill_dir / "tools.py"
        if tools_py.is_file():
            tools_py.unlink()
        return None

    tool_name = _template_tool_name(skill_id)
    schema_name = f"{tool_name.upper()}_SCHEMA"
    asset_paths = [
        str(asset.get("path") or f"assets/{_safe_filename(str(asset.get('filename') or 'template'))}")
        for asset in assets
    ]
    tools_code = f'''"""Template asset tools for the {skill_id} custom skill."""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

_SKILL_DIR = Path(__file__).resolve().parent
_ASSET_PATHS = {asset_paths!r}
_OUTPUT_STORE = None
_OUTPUT_URL_BASE = None


def bind(output_store=None, output_url_base=None, **_: object) -> None:
    global _OUTPUT_STORE, _OUTPUT_URL_BASE
    _OUTPUT_STORE = output_store
    _OUTPUT_URL_BASE = output_url_base


def _error(message: str) -> dict[str, Any]:
    return {{"error": message}}


def _safe_name(filename: str, default_suffix: str, *, force_suffix: bool = False) -> str:
    raw = Path(str(filename or "template-output")).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(raw).stem).strip("-._") or "template-output"
    suffix = default_suffix if force_suffix else (Path(raw).suffix or default_suffix)
    return f"{{stem[:72]}}-{{uuid.uuid4().hex[:8]}}{{suffix}}"


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {{
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }}.get(suffix, "application/octet-stream")


def _public_url(path: Path) -> str:
    base = os.environ.get("OPENBENCH_EXPORT_URL_BASE", "").rstrip("/")
    if not base:
        return path.as_posix()
    try:
        from openbench.utils.download_tokens import sign_download_url
        return sign_download_url(f"{{base}}/{{path.name}}")
    except Exception:
        return f"{{base}}/{{path.name}}"


def _persist(path: Path) -> dict[str, Any]:
    mime_type = _mime_for(path)
    if _OUTPUT_STORE is not None:
        content = path.read_bytes()
        stored = _OUTPUT_STORE.store(path.name, content, mime_type)
        if getattr(stored, "web_view_link", ""):
            url = stored.web_view_link
            external = True
        elif _OUTPUT_URL_BASE:
            url = f"{{_OUTPUT_URL_BASE.rstrip('/')}}/{{stored.id}}/{{stored.name}}"
            external = False
        else:
            url = stored.path
            external = False
        item = {{
            "name": stored.name,
            "url": url,
            "mimeType": stored.mime_type or mime_type,
            "size": stored.size_bytes,
        }}
        if external:
            item["external"] = True
        return item

    output_dir = Path(os.environ.get("OPENBENCH_EXPORT_DIR") or tempfile.gettempdir())
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / path.name
    if path.resolve() != target.resolve():
        shutil.copyfile(path, target)
    item = {{
        "name": target.name,
        "url": _public_url(target),
        "mimeType": mime_type,
        "size": target.stat().st_size,
    }}
    return item


def _push_to_render_queue(item: dict[str, Any]) -> None:
    try:
        from openbench.chat.render_queue import push as _push
    except Exception:
        return
    with contextlib.suppress(Exception):
        _push(item)


def _resolve_asset(asset_path: str | None) -> Path:
    selected = str(asset_path or "").strip() or (_ASSET_PATHS[0] if _ASSET_PATHS else "")
    if selected not in _ASSET_PATHS:
        raise ValueError(f"unknown template asset: {{selected}}")
    path = (_SKILL_DIR / selected).resolve()
    assets_root = (_SKILL_DIR / "assets").resolve()
    if not str(path).startswith(str(assets_root)) or not path.is_file():
        raise ValueError(f"template asset not found: {{selected}}")
    return path


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _lookup(record: dict[str, Any], header: str) -> Any:
    if header in record:
        return record[header]
    normalized = _norm(header)
    aliases = {{
        "nama": ["nama", "namasiswa", "studentname"],
        "namasiswa": ["nama", "namasiswa", "studentname"],
        "nilai": ["nilai", "nilaiangka", "nilaidalamangka", "score"],
        "nilaidalamangka": ["nilai", "nilaiangka", "nilaidalamangka", "score"],
        "nilaidalamkata": ["nilaitulisan", "nilaidalamkata", "nilaidalam tulisan"],
        "nilaidalamtulisan": ["nilaitulisan", "nilaidalamkata", "nilaidalamtulisan"],
        "keterangan": ["keterangan", "kategori", "status"],
        "kategori": ["keterangan", "kategori", "status"],
    }}
    candidates = [normalized] + aliases.get(normalized, [])
    by_norm = {{_norm(key): value for key, value in record.items()}}
    for candidate in candidates:
        key = _norm(candidate)
        if key in by_norm:
            return by_norm[key]
    return ""


def _fill_xlsx(asset: Path, records: list[dict[str, Any]], output_filename: str | None, sheet_name: str | None) -> dict[str, Any]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return _error("openpyxl is required to fill Excel templates")
    if not records:
        return _error("records is required for Excel template filling")

    suffix = asset.suffix if asset.suffix.lower() in {{".xlsx", ".xlsm"}} else ".xlsx"
    output_name = _safe_name(output_filename or asset.name, suffix, force_suffix=True)
    work_path = Path(tempfile.gettempdir()) / output_name
    shutil.copyfile(asset, work_path)
    workbook = load_workbook(work_path)
    worksheet = workbook[sheet_name] if sheet_name and sheet_name in workbook.sheetnames else workbook.active

    header_row = None
    headers: list[tuple[int, str]] = []
    for row in range(1, min(worksheet.max_row, 20) + 1):
        current: list[tuple[int, str]] = []
        for col in range(1, worksheet.max_column + 1):
            value = worksheet.cell(row=row, column=col).value
            if value not in (None, ""):
                current.append((col, str(value).strip()))
        if current:
            header_row = row
            headers = current
            break
    if header_row is None or not headers:
        return _error("No header row found in Excel template")

    start_row = header_row + 1
    for offset, record in enumerate(records):
        if not isinstance(record, dict):
            return _error("every record must be an object")
        row_index = start_row + offset
        for col_index, header in headers:
            worksheet.cell(row=row_index, column=col_index).value = _lookup(record, header)

    workbook.save(work_path)
    item = _persist(work_path)
    item["templateAsset"] = f"assets/{{asset.name}}"
    item["filledColumns"] = [header for _, header in headers]
    item["sheet"] = worksheet.title
    _push_to_render_queue(item)
    return item


def _flatten_fields(fields: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    flattened: dict[str, Any] = {{}}

    def add(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                child_prefix = f"{{prefix}} {{child_key}}".strip()
                add(child_prefix, child_value)
                add(str(child_key), child_value)
            return
        if isinstance(value, list):
            flattened[prefix] = ", ".join(str(item) for item in value)
            return
        flattened[prefix] = value

    for key, value in (fields or {{}}).items():
        add(str(key), value)
    if len(records) == 1 and isinstance(records[0], dict):
        for key, value in records[0].items():
            add(str(key), value)
    return {{key: value for key, value in flattened.items() if str(key).strip()}}


def _clean_field_value(value: Any) -> str:
    text = str(value)
    text = text.replace("\\\\n", chr(10)).replace("/n", chr(10))
    while chr(10) * 3 in text:
        text = text.replace(chr(10) * 3, chr(10) * 2)
    return text.strip()


def _field_for_label(label: str, fields: dict[str, Any]) -> tuple[str, Any] | None:
    label_norm = _norm(re.sub(r"[:：._-]+$", "", str(label or "").strip()))
    if not label_norm:
        return None
    for key, value in fields.items():
        key_norm = _norm(key)
        if not key_norm:
            continue
        if label_norm == key_norm:
            return key, value
    label_tokens = set(re.findall(r"[a-z0-9]+", str(label or "").lower()))
    for key, value in fields.items():
        key_tokens = set(re.findall(r"[a-z0-9]+", str(key or "").lower()))
        if key_tokens and key_tokens == label_tokens:
            return key, value
    return None


def _replace_placeholders(text: str, fields: dict[str, Any]) -> tuple[str, int]:
    replacements = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal replacements
        placeholder = match.group(1)
        placeholder_norm = _norm(placeholder)
        for key, value in fields.items():
            if _norm(key) == placeholder_norm:
                replacements += 1
                return _clean_field_value(value)
        return match.group(0)

    return re.sub(r"\\{{\\{{\\s*([^{{}}]+?)\\s*\\}}\\}}", repl, text), replacements


def _fill_text(asset: Path, fields: dict[str, Any], records: list[dict[str, Any]], output_filename: str | None) -> dict[str, Any]:
    text = asset.read_text(encoding="utf-8", errors="replace")
    merged_fields = _flatten_fields(fields, records)
    text, replacements = _replace_placeholders(text, merged_fields)
    if records and "{{{{records}}}}" in text:
        text = text.replace("{{{{records}}}}", json.dumps(records, ensure_ascii=False, indent=2))
        replacements += 1
    if merged_fields and replacements == 0:
        return _error("No matching placeholders were found in the text template; refusing to return an unchanged template")
    output_name = _safe_name(output_filename or asset.name, asset.suffix or ".txt", force_suffix=True)
    work_path = Path(tempfile.gettempdir()) / output_name
    work_path.write_text(text, encoding="utf-8")
    item = _persist(work_path)
    item["templateAsset"] = f"assets/{{asset.name}}"
    item["filledFields"] = replacements
    _push_to_render_queue(item)
    return item


def _fill_docx_tables(asset: Path, fields: dict[str, Any], records: list[dict[str, Any]], output_filename: str | None) -> dict[str, Any] | None:
    try:
        from docx import Document
    except Exception:
        return None

    output_name = _safe_name(output_filename or asset.name, ".docx", force_suffix=True)
    work_path = Path(tempfile.gettempdir()) / output_name

    def cell_text(cell: Any) -> str:
        return chr(10).join(paragraph.text for paragraph in cell.paragraphs).strip()

    def set_cell_text(cell: Any, value: Any) -> None:
        cell.text = _clean_field_value(value)

    def record_value(record: dict[str, Any], header: str) -> Any:
        if header in record:
            return record[header]
        match = _field_for_label(header, record)
        if match is not None:
            return match[1]
        return _lookup(record, header)

    def record_has_header(record: dict[str, Any], header: str) -> bool:
        if header in record:
            return True
        return _field_for_label(header, record) is not None

    def table_headers(cells: list[Any]) -> list[str]:
        return [cell_text(cell) for cell in cells]

    def matching_header_count(headers: list[str], candidate_records: list[dict[str, Any]]) -> int:
        if not candidate_records:
            return 0
        first_record = next((record for record in candidate_records if isinstance(record, dict)), None)
        if not first_record:
            return 0
        return sum(1 for header in headers if header.strip() and record_has_header(first_record, header))

    document = Document(str(asset))
    filled = 0

    for paragraph in document.paragraphs:
        text_value = paragraph.text.strip()
        if not text_value:
            continue
        match = _field_for_label(text_value, fields)
        if match is None:
            continue
        _, value = match
        cleaned_label = re.sub(r"[:：._-]+$", "", text_value).strip()
        if _norm(cleaned_label) and _norm(cleaned_label) in _norm(text_value):
            paragraph.add_run(" " + _clean_field_value(value))
            filled += 1

    for table in document.tables:
        rows = table.rows
        if not rows:
            continue
        headers = table_headers(rows[0].cells)
        is_record_table = bool(records) and matching_header_count(headers, records) >= min(2, len([header for header in headers if header.strip()]))
        if is_record_table:
            while len(table.rows) - 1 < len(records):
                table.add_row()
            for record_index, record in enumerate(records):
                if not isinstance(record, dict):
                    continue
                row = table.rows[record_index + 1]
                for cell_index, header in enumerate(headers[:len(row.cells)]):
                    set_cell_text(row.cells[cell_index], record_value(record, header))
                    filled += 1
            continue

        for row in rows:
            cells = row.cells
            texts = [cell_text(cell) for cell in cells]
            for index, text_value in enumerate(texts):
                match = _field_for_label(text_value, fields)
                if match is None:
                    continue
                _, value = match
                target_cell = None
                for candidate in cells[index + 1:]:
                    if not cell_text(candidate):
                        target_cell = candidate
                        break
                if target_cell is None and index + 1 < len(cells):
                    next_text = cell_text(cells[index + 1])
                    if _norm(next_text) in {{"", "nilai", "value", "isi"}}:
                        target_cell = cells[index + 1]
                if target_cell is None and ("___" in text_value or "....." in text_value):
                    set_cell_text(cells[index], re.sub(r"[_\\. ]{{3,}}", _clean_field_value(value), text_value))
                    filled += 1
                    continue
                if target_cell is not None:
                    set_cell_text(target_cell, value)
                    filled += 1

    if filled == 0:
        return None
    document.save(work_path)
    item = _persist(work_path)
    item["templateAsset"] = f"assets/{{asset.name}}"
    item["filledFields"] = filled
    _push_to_render_queue(item)
    return item


def _fill_zipped_xml(asset: Path, fields: dict[str, Any], records: list[dict[str, Any]], output_filename: str | None) -> dict[str, Any]:
    merged_fields = _flatten_fields(fields, records)
    if not merged_fields:
        return _error("fields or records are required to fill this template asset")
    output_name = _safe_name(output_filename or asset.name, asset.suffix, force_suffix=True)
    work_path = Path(tempfile.gettempdir()) / output_name
    replacement_count = 0
    with zipfile.ZipFile(asset, "r") as source, zipfile.ZipFile(work_path, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.endswith(".xml"):
                text = data.decode("utf-8", errors="replace")
                xml_fields = {{key: escape(_clean_field_value(value)) for key, value in merged_fields.items()}}
                text, count = _replace_placeholders(text, xml_fields)
                replacement_count += count
                data = text.encode("utf-8")
            target.writestr(info, data)
    if replacement_count == 0 and asset.suffix.lower() == ".docx":
        with contextlib.suppress(Exception):
            work_path.unlink()
        table_item = _fill_docx_tables(asset, merged_fields, records, output_filename)
        if table_item is not None:
            return table_item
    if replacement_count == 0:
        with contextlib.suppress(Exception):
            work_path.unlink()
        return _error(
            "No template fields were filled. Add placeholders like {{{{nama}}}} to the template, "
            "or use a table/form layout with labels next to empty cells for DOCX."
        )
    item = _persist(work_path)
    item["templateAsset"] = f"assets/{{asset.name}}"
    item["filledFields"] = replacement_count
    _push_to_render_queue(item)
    return item


def _fill_pdf(asset: Path, fields: dict[str, Any], records: list[dict[str, Any]], output_filename: str | None) -> dict[str, Any]:
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import NameObject
    except ImportError:
        return _error("pypdf is required to fill PDF form fields")
    merged_fields = _flatten_fields(fields, records)
    if not merged_fields:
        return _error("fields or records are required to fill PDF templates")
    output_name = _safe_name(output_filename or asset.name, ".pdf", force_suffix=True)
    work_path = Path(tempfile.gettempdir()) / output_name
    reader = PdfReader(str(asset))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    form_fields = reader.get_fields() or {{}}
    if not form_fields:
        return _error("PDF template has no fillable AcroForm fields; refusing to return an unchanged template")
    values = {{}}
    for field_name in form_fields:
        match = _field_for_label(str(field_name), merged_fields)
        if match is not None:
            values[str(field_name)] = _clean_field_value(match[1])
    if not values:
        return _error("No PDF form fields matched the provided fields; refusing to return an unchanged template")
    for page in writer.pages:
        writer.update_page_form_field_values(page, values)
    with contextlib.suppress(Exception):
        writer.set_need_appearances_writer(True)
    if "/AcroForm" in reader.trailer.get("/Root", {{}}):
        writer._root_object.update({{NameObject("/AcroForm"): reader.trailer["/Root"]["/AcroForm"]}})
    with work_path.open("wb") as handle:
        writer.write(handle)
    item = _persist(work_path)
    item["templateAsset"] = f"assets/{{asset.name}}"
    item["filledFields"] = len(values)
    _push_to_render_queue(item)
    return item


def {tool_name}(
    asset_path: str = "",
    records: list[dict[str, Any]] | None = None,
    fields: dict[str, Any] | None = None,
    output_filename: str = "",
    sheet_name: str = "",
) -> dict[str, Any]:
    """Fill or copy a template asset while preserving the original file structure."""
    records = records or []
    fields = fields or {{}}
    try:
        asset = _resolve_asset(asset_path)
    except ValueError as exc:
        return _error(str(exc))
    suffix = asset.suffix.lower()
    if suffix in {{".xlsx", ".xlsm"}}:
        return _fill_xlsx(asset, records, output_filename or None, sheet_name or None)
    if suffix in {{".txt", ".md"}}:
        return _fill_text(asset, fields, records, output_filename or None)
    if suffix in {{".docx", ".pptx"}}:
        return _fill_zipped_xml(asset, fields, records, output_filename or None)
    if suffix == ".pdf":
        return _fill_pdf(asset, fields, records, output_filename or None)
    if fields or records:
        return _error(f"Template asset type {{suffix or asset.name}} is not fillable by this tool; refusing to return an unchanged template")
    output_name = _safe_name(output_filename or asset.name, asset.suffix or ".bin", force_suffix=True)
    work_path = Path(tempfile.gettempdir()) / output_name
    shutil.copyfile(asset, work_path)
    item = _persist(work_path)
    item["templateAsset"] = f"assets/{{asset.name}}"
    _push_to_render_queue(item)
    return item


{schema_name} = {{
    "type": "function",
    "function": {{
        "name": "{tool_name}",
        "description": (
            "Create a downloadable file by using one of this custom skill's uploaded template assets "
            "as the source of truth. For Excel, copies the original workbook and fills rows under the "
            "existing headers while preserving sheets, column order, names, formulas, widths, and styling. "
            "For TXT/MD/DOCX/PPTX, fills from fields/records by replacing {{{{{{{{field}}}}}}}} placeholders. "
            "For DOCX form tables, it also matches labels and fills nearby empty cells. "
            "For PDF, fills AcroForm fields when available. The output extension always follows the template asset type. "
            "If no field is filled, the tool returns an error instead of an unchanged template."
        ),
        "parameters": {{
            "type": "object",
            "properties": {{
                "asset_path": {{
                    "type": "string",
                    "enum": _ASSET_PATHS,
                    "description": "Template asset path from this skill. Use the uploaded template asset, not a regenerated file."
                }},
                "records": {{
                    "type": "array",
                    "items": {{"type": "object"}},
                    "description": "Rows to insert into Excel templates or flatten into document form fields. Keys should match template headers or labels."
                }},
                "fields": {{
                    "type": "object",
                    "description": "Field values for form/template labels and placeholders. Use exact labels from the template map when possible, such as invoice number, customer, date, or {{{{{{{{field_name}}}}}}}} placeholders."
                }},
                "output_filename": {{
                    "type": "string",
                    "description": "Desired output filename. The tool adds a unique suffix."
                }},
                "sheet_name": {{
                    "type": "string",
                    "description": "Optional Excel sheet name. Defaults to the template's active sheet."
                }}
            }},
            "required": ["asset_path"]
        }}
    }}
}}
'''
    (skill_dir / "tools.py").write_text(tools_code, encoding="utf-8")
    return tool_name


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
        resources: dict[str, Any] | None = None,
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
        resources = resources or _empty_resources()

        skill_dir.mkdir(parents=True, exist_ok=True)
        persisted_resources = _write_resource_files(skill_dir, resources)
        template_tool_name = _write_template_tools(
            skill_dir,
            skill_id=skill_id,
            resources=persisted_resources,
        )
        skill_md = _render_skill_md(
            name=name,
            description=description,
            triggers=triggers,
            instructions=instructions,
            version=version,
            tooling=tooling,
            resources=persisted_resources,
            template_tool_name=template_tool_name,
        )

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
            "tooling": tooling or _empty_tooling(),
            "resources": persisted_resources,
            "template_tool": template_tool_name or "",
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
        uploads: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        spec = _skill_spec_from_prompt(prompt)
        tooling = _tooling_plan_from_prompt(
            prompt,
            custom_functions=custom_functions,
            mcp_registry=mcp_registry,
        )
        resources = _merge_resources(
            _prompt_resource_plan(prompt),
            _resources_from_uploads(uploads),
        )
        return self.save(
            self._unique_id(spec["name"]),
            name=spec["name"],
            description=spec["description"],
            triggers=spec["triggers"],
            instructions=spec["instructions"],
            version=spec["version"],
            tooling=tooling,
            resources=resources,
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
        existing_resources = existing.get("resources") if existing else None
        existing_template_tool = existing.get("template_tool") if existing else None
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
            else _empty_tooling(),
            "resources": existing_resources
            if isinstance(existing_resources, dict)
            else _empty_resources(),
            "template_tool": str(existing_template_tool or ""),
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
            else _empty_tooling(),
            "resources": metadata.get("resources")
            if isinstance(metadata.get("resources"), dict)
            else _empty_resources(),
            "template_tool": str(metadata.get("template_tool") or ""),
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
        shutil.rmtree(skill_dir)
        return True
