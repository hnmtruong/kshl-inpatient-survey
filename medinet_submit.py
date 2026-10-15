"""Submit an approved Mẫu số 3 response to the supplied Medinet form."""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from datetime import datetime

FORM_URL = "https://tnnb.medinet.org.vn/phieu-khao-sat/697ae1ccc134eb50e91ede42/58d37041080f8a0dac8e55d6"
SUBMIT_URL = "https://tnnb.medinet.org.vn/KhaoSat/GuiBaiKhaoSat"
FORM_ID = "697ae1ccc134eb50e91ede42"
DEFAULT_GROUP = "58d0e15723c903322c41663c"


class MedinetSubmissionError(RuntimeError):
    pass


def _choices(page: str, question_id: str) -> dict[str, str]:
    pattern = rf'<input[^>]+name="{re.escape(question_id)}(?:\[\])?"[^>]+value="([^"]+)"'
    values = re.findall(pattern, page)
    result = {}
    for value in values:
        parts = value.split("==", 3)
        if len(parts) >= 2:
            result[parts[1]] = value
    return result


def submit(record_id: str, answers: dict) -> tuple[str, str]:
    profile, ratings = answers["profile"], answers["ratings"]
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    try:
        with opener.open(FORM_URL, timeout=30) as response:
            page = response.read().decode("utf-8", "replace")
    except Exception as exc:
        raise MedinetSubmissionError("Không tải được biểu mẫu Medinet để gửi phiếu.") from exc
    fields = [
        ("danhSachKhoaPhong", profile["department"]),
        ("ngaydienphieu", datetime.now().strftime("%d/%m/%Y")),
        ("tenkhoadanamdieutri(neuco)", ""), ("makhoa(dodvghi)", ""), ("manguoibenh(dodonviquydinh)", ""),
        ("DotKhaoSatId", FORM_ID), ("keyThongTin", "ngaydienphieu;;tenkhoadanamdieutri(neuco);;makhoa(dodvghi);;manguoibenh(dodonviquydinh);;"),
        ("DonViKhaoSatId", ""), ("DonViConId", profile["department"]), ("nhomDonViId", ""), ("tenKiosk", ""), ("nhomKhaoSat", DEFAULT_GROUP),
        ("697ae1ccc134eb50e91ede44_tuluan", profile["birth_year"]),
        ("697ae1ccc134eb50e91ede4a_tuluan", ratings.get("comment", "")), ("save", "save"),
    ]
    for question_id, value in (("697ae1ccc134eb50e91ede43", profile["gender"]), ("697ae1ccc134eb50e91ede4b", profile["certificate"])):
        choice = _choices(page, question_id).get(value)
        if not choice: raise MedinetSubmissionError("Cấu trúc câu hỏi Medinet đã thay đổi. Vui lòng cập nhật biểu mẫu trước khi gửi.")
        fields.append((question_id, choice))
    service_choices = _choices(page, "697ae1ccc134eb50e91ede45")
    for value in profile["services"]:
        choice = service_choices.get(value)
        if not choice: raise MedinetSubmissionError("Danh mục dịch vụ Medinet đã thay đổi.")
        fields.append(("697ae1ccc134eb50e91ede45[]", choice))
    for question_id, value in ratings.items():
        if question_id in {"comment"}: continue
        choice = _choices(page, question_id).get(value)
        if not choice: raise MedinetSubmissionError("Cấu trúc câu hỏi Medinet đã thay đổi. Vui lòng cập nhật biểu mẫu trước khi gửi.")
        fields.append((question_id, choice))
    request = urllib.request.Request(SUBMIT_URL, data=urllib.parse.urlencode(fields).encode(), headers={"Content-Type":"application/x-www-form-urlencoded", "Referer":FORM_URL, "User-Agent":"NTP-survey-bridge/1.0"})
    try:
        with opener.open(request, timeout=90) as response:
            body = response.read().decode("utf-8", "replace")
            final_url = response.geturl()
    except Exception as exc:
        raise MedinetSubmissionError(f"Medinet không nhận được phiếu ({type(exc).__name__}: {exc}).") from exc
    if "/KhaoSat/ThongBao/" not in final_url and "cảm ơn" not in body.lower() and "cám ơn" not in body.lower() and "thành công" not in body.lower():
        raise MedinetSubmissionError("Medinet chưa xác nhận phiếu. Phiếu được giữ ở trạng thái chưa gửi để kiểm tra lại.")
    return final_url, "Đã gửi Medinet thành công."
