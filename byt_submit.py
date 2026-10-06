#!/usr/bin/env python3
"""Submit a completed inpatient-survey record to the BYT webform.

The module only uses the Python standard library so it can run in the service
process.  Credentials live in ``data/byt_credentials.json`` (mode 0600) and
are deliberately outside the web root.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import ssl
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "data" / "byt_credentials.json"
BASE_URL = "https://hailong.chatluongbenhvien.vn"
LOGIN_URL = f"{BASE_URL}/user/login"
FORM_URLS = {
    "1": f"{BASE_URL}/nguoi-benh-noi-tru-v2",
    "2": f"{BASE_URL}/nguoi-benh-ngoai-tru-v2",
}
HOSPITAL_CODE = "60242"


class BYTSubmissionError(RuntimeError):
    """The BYT site could not accept a survey submission."""


class _Inputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs):
        if tag != "input":
            return
        data = dict(attrs)
        name = data.get("name")
        if name:
            self.values[name] = data.get("value", "")


def _form_inputs(html: str) -> dict[str, str]:
    parser = _Inputs()
    parser.feed(html)
    return parser.values


def _post(opener, url: str, fields: dict[str, Any]):
    data = urlencode({key: str(value) for key, value in fields.items()}).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "NTP-Survey-Bridge/1.0"})
    with opener.open(request, timeout=35) as response:
        return response.geturl(), response.read().decode("utf-8", "replace")


def _get(opener, url: str):
    request = Request(url, headers={"User-Agent": "NTP-Survey-Bridge/1.0"})
    with opener.open(request, timeout=35) as response:
        return response.geturl(), response.read().decode("utf-8", "replace")


def load_config() -> dict[str, Any]:
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BYTSubmissionError("Chưa cấu hình tài khoản đồng bộ Bộ Y tế trên máy chủ.") from exc
    except json.JSONDecodeError as exc:
        raise BYTSubmissionError("Tệp cấu hình đồng bộ Bộ Y tế không hợp lệ.") from exc
    if not isinstance(config, dict) or not config.get("enabled"):
        raise BYTSubmissionError("Đồng bộ tự động Bộ Y tế chưa được bật.")
    for key in ("username", "password", "survey_type"):
        if not isinstance(config.get(key), str) or not config[key]:
            raise BYTSubmissionError("Thiếu cấu hình tài khoản hoặc kiểu khảo sát Bộ Y tế.")
    if config["survey_type"] not in {"1", "2", "3", "4", "5", "6"}:
        raise BYTSubmissionError("Kiểu khảo sát Bộ Y tế trong cấu hình không hợp lệ.")
    return config


def _payload(record_id: str, answers: dict[str, Any], tokens: dict[str, str], survey_type: str) -> dict[str, str]:
    profile = answers["profile"]
    ratings = answers["ratings"]
    now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    payload = {
        "details[sid]": tokens.get("details[sid]", ""),
        "details[page_num]": tokens.get("details[page_num]", "1"),
        "details[page_count]": tokens.get("details[page_count]", "1"),
        "details[finished]": tokens.get("details[finished]", "0"),
        "form_build_id": tokens.get("form_build_id", ""),
        "form_token": tokens.get("form_token", ""),
        "form_id": "webform_client_form_206847",
        "submitted[kieu_khao_sat]": survey_type,
        "submitted[guibyt]": "1",
        "submitted[ttp][masophieu]": record_id,
        "submitted[ttp][bvn][1_ten_benh_vien]": HOSPITAL_CODE,
        "submitted[ttp][bvn][mabv]": HOSPITAL_CODE,
        "submitted[ttp][bvn][ngay_dien_phieu][day]": str(now.day),
        "submitted[ttp][bvn][ngay_dien_phieu][month]": str(now.month),
        "submitted[ttp][bvn][ngay_dien_phieu][year]": str(now.year),
        "submitted[ttp][mdt][nguoipv]": "1",
        "submitted[ttp][mdt][doituong]": profile["respondent"],
        "submitted[ttp][kmk][khoa_phong]": profile.get("ward", ""),
        "submitted[ttp][kmk][ma_khoa]": profile.get("ward_code", ""),
        "submitted[thong_tin_nguoi_dien_phieu][ten_ma][tenbn]": profile.get("patient_name", ""),
        "submitted[thong_tin_nguoi_dien_phieu][ten_ma][mabn]": profile.get("patient_code", ""),
        "submitted[thong_tin_nguoi_dien_phieu][gioi_tuoi][gioi_tinh]": profile["gender"],
        "submitted[thong_tin_nguoi_dien_phieu][gioi_tuoi][tuoi]": profile["age"],
        "submitted[thong_tin_nguoi_dien_phieu][dien_thoai___ngay__nam_vien][hca3]": profile.get("phone", ""),
        "submitted[thong_tin_nguoi_dien_phieu][dien_thoai___ngay__nam_vien][thoigian]": profile["stay_days"],
        "submitted[thong_tin_nguoi_dien_phieu][5]": profile["bhyt"],
        "submitted[thong_tin_nguoi_dien_phieu][6]": profile["residence"],
        "submitted[thong_tin_nguoi_dien_phieu][7]": profile["living_standard"],
        "submitted[thong_tin_nguoi_dien_phieu][8]": profile["treatment_count"],
        "submitted[danh_gia][e][z0][select]": "select_or_other" if ratings["e7"] == "6" else ratings["e7"],
        "submitted[danh_gia][e][z0][other]": ratings.get("cost_other", "") if ratings["e7"] == "6" else "",
        "submitted[danh_gia][z1]": ratings["overall_percent"],
        "submitted[danh_gia][z2][select]": "select_or_other" if ratings["return_intent"] == "6" else ratings["return_intent"],
        "submitted[danh_gia][z2][other]": ratings.get("return_other", "") if ratings["return_intent"] == "6" else "",
        "submitted[danh_gia][z3]": ratings.get("unhappy_detail", ""),
        "submitted[danh_gia][z4]": ratings.get("suggestions", ""),
        "op": "Gửi đi",
    }
    for group in "abcde":
        for key, value in ratings.items():
            if key != "e7" and re.fullmatch(rf"{group}\d+", key):
                payload[f"submitted[danh_gia][{group}][{key}]"] = value
    if not payload["form_build_id"] or not payload["form_token"]:
        raise BYTSubmissionError("Không lấy được mã bảo vệ của biểu mẫu Bộ Y tế.")
    return payload


def _outpatient_payload(record_id: str, answers: dict[str, Any], tokens: dict[str, str]) -> dict[str, str]:
    profile = answers["profile"]
    ratings = answers["ratings"]
    now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    payload = {
        "details[sid]": tokens.get("details[sid]", ""), "details[page_num]": tokens.get("details[page_num]", "1"),
        "details[page_count]": tokens.get("details[page_count]", "1"), "details[finished]": tokens.get("details[finished]", "0"),
        "form_build_id": tokens.get("form_build_id", ""), "form_token": tokens.get("form_token", ""),
        "form_id": tokens.get("form_id", ""), "submitted[kieu_khao_sat]": "2", "submitted[guibyt]": "1",
        "submitted[ttp][masophieu]": record_id, "submitted[ttp][bvn][1_ten_benh_vien]": HOSPITAL_CODE,
        "submitted[ttp][bvn][mabv]": HOSPITAL_CODE, "submitted[ttp][bvn][ngay_dien_phieu][day]": str(now.day),
        "submitted[ttp][bvn][ngay_dien_phieu][month]": str(now.month), "submitted[ttp][bvn][ngay_dien_phieu][year]": str(now.year),
        "submitted[ttp][mdt][nguoipv]": "1", "submitted[ttp][mdt][doituong]": profile["respondent"],
        "submitted[thong_tin_nguoi_dien_phieu][gioi_tuoi][gioi_tinh]": profile["gender"],
        "submitted[thong_tin_nguoi_dien_phieu][gioi_tuoi][tuoi]": profile["age"],
        "submitted[thong_tin_nguoi_dien_phieu][hca3]": profile.get("phone", ""),
        "submitted[thong_tin_nguoi_dien_phieu][khoangcach]": profile["distance"],
        "submitted[thong_tin_nguoi_dien_phieu][baohiem]": profile["bhyt"],
        "submitted[thong_tin_nguoi_dien_phieu][6]": profile["residence"],
        "submitted[thong_tin_nguoi_dien_phieu][7]": profile["living_standard"],
        "submitted[thong_tin_nguoi_dien_phieu][8]": profile["treatment_count"],
        "submitted[danh_gia][e][z0][select]": "select_or_other" if ratings["e5_cost"] == "6" else ratings["e5_cost"],
        "submitted[danh_gia][e][z0][other]": ratings.get("cost_other", "") if ratings["e5_cost"] == "6" else "",
        "submitted[danh_gia][z1]": ratings["overall_percent"],
        "submitted[danh_gia][z2][select]": "select_or_other" if ratings["return_intent"] == "6" else ratings["return_intent"],
        "submitted[danh_gia][z2][other]": ratings.get("return_other", "") if ratings["return_intent"] == "6" else "",
        "submitted[danh_gia][z3]": ratings.get("unhappy_detail", ""), "submitted[danh_gia][z4]": ratings.get("suggestions", ""), "op": "Gửi đi",
    }
    for group in "abcde":
        for key, value in ratings.items():
            if re.fullmatch(rf"{group}\d+", key): payload[f"submitted[danh_gia][{group}][{key}]"] = value
    if not payload["form_build_id"] or not payload["form_token"] or not payload["form_id"]:
        raise BYTSubmissionError("Không lấy được mã bảo vệ của biểu mẫu Bộ Y tế.")
    return payload


def submit(record_id: str, answers: dict[str, Any], survey_form: str = "1") -> dict[str, str]:
    """Log in and submit a record. Raises BYTSubmissionError on any uncertainty."""
    try:
        config = load_config()
        cookies = http.cookiejar.CookieJar()
        context = ssl.create_default_context()
        opener = build_opener(HTTPCookieProcessor(cookies), HTTPSHandler(context=context))
        _, login_page = _get(opener, LOGIN_URL)
        login_tokens = _form_inputs(login_page)
        _, after_login = _post(opener, LOGIN_URL, {
            "name": config["username"], "pass": config["password"],
            "form_build_id": login_tokens.get("form_build_id", ""),
            "form_id": login_tokens.get("form_id", "user_login"), "op": "Đăng nhập",
        })
        if "user-login-form" in after_login or "Tài khoản hoặc mật khẩu không đúng" in after_login:
            raise BYTSubmissionError("Không đăng nhập được cổng Bộ Y tế bằng cấu hình hiện tại.")
        form_url = FORM_URLS.get(survey_form)
        if not form_url:
            raise BYTSubmissionError("Loại biểu mẫu chưa được hỗ trợ.")
        _, form_page = _get(opener, form_url)
        if "webform-client-form" not in form_page:
            raise BYTSubmissionError("Cổng Bộ Y tế không mở được biểu mẫu khảo sát.")
        tokens = _form_inputs(form_page)
        payload = _outpatient_payload(record_id, answers, tokens) if survey_form == "2" else _payload(record_id, answers, tokens, config["survey_type"])
        _, submitted_page = _post(opener, form_url, payload)
        if "webform-client-form" in submitted_page:
            raise BYTSubmissionError("Cổng Bộ Y tế chưa xác nhận phiếu; bản ghi không được đánh dấu đã gửi.")
        return {"message": "Đã gửi phiếu lên cổng Bộ Y tế."}
    except BYTSubmissionError:
        raise
    except Exception as exc:
        raise BYTSubmissionError("Không kết nối được cổng Bộ Y tế để gửi phiếu.") from exc
