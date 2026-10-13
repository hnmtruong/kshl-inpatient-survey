"""Build the checked-in Mẫu số 4 schema from the public Medinet form.

Run manually when Medinet changes this active form.  The output has no patient
data and is used by the cloned patient-facing survey and its delivery bridge.
"""
from __future__ import annotations

import html
import json
import re
import urllib.request
from pathlib import Path


SOURCE_URL = "https://tnnb.medinet.org.vn/phieu-khao-sat/697ae20ac134eb50e91ede61/58d37041080f8a0dac8e55d6"
ROOT = Path(__file__).resolve().parent


def plain(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).replace("&nbsp;", " ").split())


def attrs(markup: str) -> dict[str, str]:
    return {key.lower(): html.unescape(value) for key, _, value in re.findall(r'''([\w-]+)\s*=\s*(["'])(.*?)\2''', markup, re.S)}


def build() -> dict:
    cached = ROOT / "medinet4-source.html"
    if cached.exists():
        page = cached.read_text(encoding="utf-8", errors="replace")
    else:
        request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "NTP-survey-schema/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            page = response.read().decode("utf-8", "replace")
    title = plain(re.search(r'<h2 class="tieu-de">(.*?)</h2>', page, re.S).group(1))
    intro = plain(re.search(r'<div class="gioi-thieu">(.*?)</div>\s*<div class="clearfix"', page, re.S).group(1))
    department_block = re.search(r'<select id="danhSachKhoaPhong".*?</select>', page, re.S).group(0)
    departments = []
    for value, label in re.findall(r'<option\s+value="([^"]+)">(.*?)</option>', department_block, re.S):
        if value != "0":
            departments.append({"value": html.unescape(value), "label": plain(label)})

    groups = []
    page_starts = list(re.finditer(r'<div id="page\d+" class="question-group"[^>]*>', page))
    for page_index, page_match in enumerate(page_starts):
        block = page[page_match.end():page_starts[page_index + 1].start() if page_index + 1 < len(page_starts) else len(page)]
        title_match = re.search(r'<div class="tieu-de-nhom[^"]*">(.*?)</div>', block, re.S)
        if not title_match:
            continue
        questions = []
        starts = list(re.finditer(r'<div id="([a-f0-9]{24})" class="form-cauhoi[^>]*?(?:data-required="([^"]*)")?[^>]*>', block, re.S))
        for index, start in enumerate(starts):
            fragment = block[start.end(): starts[index + 1].start() if index + 1 < len(starts) else len(block)]
            question_match = re.search(r'<div class="cauhoi">(.*?)</div>', fragment, re.S)
            label = plain(question_match.group(1)) if question_match else start.group(1)
            question = {"key": start.group(1), "label": label, "required": start.group(2) != "0", "options": []}
            for input_tag in re.findall(r'<input\b[^>]*>', fragment, re.S):
                item = attrs(input_tag)
                input_type = item.get("type", "text").lower()
                if input_type in {"radio", "checkbox"} and item.get("value"):
                    input_id = item.get("id", "")
                    label_match = re.search(rf'<label\s+for="{re.escape(input_id)}"[^>]*>(.*?)</label>', fragment, re.S)
                    raw = item["value"]
                    value = raw.rsplit("==", 1)[-1]
                    question["options"].append({"value": value, "label": plain(label_match.group(1)) if label_match else value, "inputType": input_type})
                elif input_type in {"text", "number"}:
                    question["freeTextKey"] = item.get("name") or item.get("id")
                    question["freeTextLabel"] = label
            if question["options"]:
                types = {option["inputType"] for option in question["options"]}
                question["multiple"] = types == {"checkbox"}
                for option in question["options"]:
                    option.pop("inputType", None)
            questions.append(question)
        groups.append({"title": plain(title_match.group(1)), "questions": questions})
    return {
        "formNumber": "4", "formTitle": title, "officialIntro": intro, "sourceUrl": SOURCE_URL,
        "dotKhaoSatId": "697ae20ac134eb50e91ede61", "departments": departments, "groups": groups,
    }


if __name__ == "__main__":
    (ROOT / "schema4.json").write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
