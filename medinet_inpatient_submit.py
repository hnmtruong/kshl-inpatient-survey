"""Submit an approved Mẫu số 4 response to the current Medinet inpatient form."""
from __future__ import annotations

import re
import urllib.parse
import urllib.request

from medinet_submit import MedinetSubmissionError


class MedinetDeliveryUncertain(RuntimeError):
    """The POST was attempted but its outcome cannot be confirmed safely."""


FORM_URL = "https://tnnb.medinet.org.vn/phieu-khao-sat/697ae20ac134eb50e91ede61/58d37041080f8a0dac8e55d6"
SUBMIT_URL = "https://tnnb.medinet.org.vn/KhaoSat/GuiBaiKhaoSat"
FORM_ID = "697ae20ac134eb50e91ede61"


def _choices(page: str, question_id: str) -> dict[str, str]:
    values = re.findall(rf'<input[^>]+name="{re.escape(question_id)}(?:\[\])?"[^>]+value="([^"]+)"', page)
    return {value.split("==")[1]: value for value in values}


def submit(record_id: str, answers: dict) -> tuple[str, str]:
    from app import MEDINET_INPATIENT_QUESTIONS

    profile, ratings, notes = answers["profile"], answers["ratings"], answers.get("notes", {})
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    try:
        with opener.open(urllib.request.Request(FORM_URL, headers={"User-Agent": "NTP-survey-bridge/1.0"}), timeout=30) as response:
            page = response.read().decode("utf-8", "replace")
    except Exception as exc:
        raise MedinetSubmissionError("Không tải được biểu mẫu nội trú Medinet để gửi phiếu.") from exc
    fields = [
        ("danhSachKhoaPhong", profile["department"]), ("ngaykhaosat", profile["survey_date"]),
        ("DotKhaoSatId", FORM_ID), ("keyThongTin", ""), ("DonViKhaoSatId", "58d37041080f8a0dac8e55d6"),
        ("DonViConId", profile["department"]), ("nhomDonViId", ""), ("tenKiosk", ""), ("nhomKhaoSat", ""), ("save", "save"),
    ]
    for question in MEDINET_INPATIENT_QUESTIONS:
        key = question["key"]
        value = ratings[key]
        if question["options"]:
            choices = _choices(page, key)
            selected = value if question.get("multiple") else [value]
            for item in selected:
                raw = choices.get(item)
                if not raw:
                    raise MedinetSubmissionError("Cấu trúc phiếu nội trú Medinet đã thay đổi. Vui lòng cập nhật biểu mẫu trước khi gửi.")
                fields.append((key + ("[]" if question.get("multiple") else ""), raw))
        elif question.get("freeTextKey"):
            fields.append((question["freeTextKey"], value))
        if question.get("freeTextKey") and key in notes:
            fields.append((question["freeTextKey"], notes[key]))
    request = urllib.request.Request(SUBMIT_URL, data=urllib.parse.urlencode(fields).encode(), headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": FORM_URL, "User-Agent": "NTP-survey-bridge/1.0"})
    try:
        with opener.open(request, timeout=90) as response:
            body = response.read().decode("utf-8", "replace")
            final_url = response.geturl()
    except Exception as exc:
        raise MedinetDeliveryUncertain("Đã gọi gửi Medinet nhưng kết nối bị gián đoạn hoặc quá thời gian chờ. Cần đối chiếu trên Medinet trước khi gửi lại để tránh trùng phiếu.") from exc
    if "/KhaoSat/ThongBao/" not in final_url and not any(text in body.lower() for text in ("cảm ơn", "cám ơn", "thành công")):
        # Keep the response private for diagnosing receiver validation without resubmitting.
        from pathlib import Path
        diagnostics = Path(__file__).resolve().parent / "data" / "delivery-diagnostics"
        diagnostics.mkdir(parents=True, exist_ok=True, mode=0o700)
        diagnostic = diagnostics / f"{record_id}.html"
        diagnostic.write_text(body, encoding="utf-8")
        diagnostic.chmod(0o600)
        raise MedinetSubmissionError("Medinet chưa xác nhận phiếu nội trú. Phiếu được giữ để kiểm tra lại.")
    return final_url, "Đã gửi Medinet thành công."
