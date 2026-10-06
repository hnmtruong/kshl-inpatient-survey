#!/usr/bin/env python3
"""Prefill a reviewed local response into the official BYT form.

This script intentionally leaves the final BYT submit action to a staff member.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "submissions.sqlite3"
LOGIN_URL = "https://hailong.chatluongbenhvien.vn/user/login"
FORM_URL = "https://hailong.chatluongbenhvien.vn/nguoi-benh-noi-tru-v2"
HOSPITAL_CODE = "60242"


def load_response(record_id: str):
    candidate = Path(record_id)
    if candidate.is_file():
        try:
            package = json.loads(candidate.read_text(encoding="utf-8"))
            response = package.get("answers") if isinstance(package, dict) else None
            if not isinstance(response, dict) or not isinstance(response.get("profile"), dict) or not isinstance(response.get("ratings"), dict):
                raise ValueError("Tệp JSON không phải gói phiếu khảo sát hợp lệ.")
            return response, str(package.get("id") or candidate.stem), str(package.get("survey_type") or "")
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Không đọc được tệp gói phiếu: {exc}") from exc
    if not DB.exists():
        raise ValueError(f"Chưa thấy cơ sở dữ liệu khảo sát: {DB}")
    with sqlite3.connect(DB) as connection:
        row = connection.execute("SELECT answers_json FROM submissions WHERE id=?", (record_id,)).fetchone()
    if not row:
        raise ValueError("Không tìm thấy mã phiếu trong cơ sở dữ liệu trên máy này.")
    return json.loads(row[0]), record_id, ""


def choose(driver, name: str, value: str):
    if value in (None, ""):
        return
    controls = driver.find_elements(By.NAME, name)
    if not controls:
        raise ValueError(f"Không tìm thấy trường trên trang BYT: {name}")
    if controls[0].tag_name.lower() == "select":
        Select(controls[0]).select_by_value(str(value))
        return
    if controls[0].get_attribute("type") == "radio":
        match = next((control for control in controls if control.get_attribute("value") == str(value)), None)
        if match is None:
            raise ValueError(f"Không có lựa chọn '{value}' cho trường {name}")
        if not match.is_selected():
            driver.execute_script("arguments[0].click()", match)
        return
    controls[0].clear()
    controls[0].send_keys(str(value))


def main():
    parser = argparse.ArgumentParser(description="Điền phiếu đã nhận trên máy bệnh viện vào biểu mẫu BYT.")
    parser.add_argument("response_id", help="Mã phiếu trong cơ sở dữ liệu hoặc đường dẫn tệp JSON tải từ trang review")
    parser.add_argument("--survey-type", choices=["1", "2", "3", "4", "5", "6"], help="Kiểu khảo sát; nếu không truyền, đọc từ gói JSON tải ở trang review")
    args = parser.parse_args()
    try:
        response, response_id, package_survey_type = load_response(args.response_id)
    except (ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    survey_type = args.survey_type or package_survey_type
    if not survey_type:
        parser.error("Cần chọn kiểu khảo sát bằng --survey-type hoặc tải gói JSON từ trang review.")

    profile = response["profile"]
    ratings = response["ratings"]
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(LOGIN_URL)
        input("Đăng nhập tài khoản bệnh viện trong cửa sổ Chrome, rồi nhấn Enter tại đây... ")
        driver.get(FORM_URL)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "webform-client-form-206847")))

        choose(driver, "submitted[kieu_khao_sat]", survey_type)
        choose(driver, "submitted[guibyt]", "1")
        choose(driver, "submitted[ttp][masophieu]", response_id)
        choose(driver, "submitted[ttp][bvn][1_ten_benh_vien]", HOSPITAL_CODE)
        choose(driver, "submitted[ttp][bvn][mabv]", HOSPITAL_CODE)
        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        choose(driver, "submitted[ttp][bvn][ngay_dien_phieu][day]", str(now.day))
        choose(driver, "submitted[ttp][bvn][ngay_dien_phieu][month]", str(now.month))
        choose(driver, "submitted[ttp][bvn][ngay_dien_phieu][year]", str(now.year))
        choose(driver, "submitted[ttp][mdt][nguoipv]", "1")
        choose(driver, "submitted[ttp][mdt][doituong]", profile["respondent"])
        choose(driver, "submitted[ttp][kmk][khoa_phong]", profile.get("ward", ""))
        choose(driver, "submitted[ttp][kmk][ma_khoa]", profile.get("ward_code", ""))

        choose(driver, "submitted[thong_tin_nguoi_dien_phieu][ten_ma][tenbn]", profile.get("patient_name", ""))
        choose(driver, "submitted[thong_tin_nguoi_dien_phieu][ten_ma][mabn]", profile.get("patient_code", ""))
        choose(driver, "submitted[thong_tin_nguoi_dien_phieu][gioi_tuoi][gioi_tinh]", profile["gender"])
        choose(driver, "submitted[thong_tin_nguoi_dien_phieu][gioi_tuoi][tuoi]", profile["age"])
        choose(driver, "submitted[thong_tin_nguoi_dien_phieu][dien_thoai___ngay__nam_vien][hca3]", profile.get("phone", ""))
        choose(driver, "submitted[thong_tin_nguoi_dien_phieu][dien_thoai___ngay__nam_vien][thoigian]", profile["stay_days"])
        choose(driver, "submitted[thong_tin_nguoi_dien_phieu][5]", profile["bhyt"])
        choose(driver, "submitted[thong_tin_nguoi_dien_phieu][6]", profile["residence"])
        choose(driver, "submitted[thong_tin_nguoi_dien_phieu][7]", profile["living_standard"])
        choose(driver, "submitted[thong_tin_nguoi_dien_phieu][8]", profile["treatment_count"])

        for group in "abcde":
            for key, value in ratings.items():
                if key != "e7" and len(key) >= 2 and key.startswith(group) and key[1:].isdigit():
                    choose(driver, f"submitted[danh_gia][{group}][{key}]", value)
        cost_value = "select_or_other" if ratings["e7"] == "6" else ratings["e7"]
        choose(driver, "submitted[danh_gia][e][z0][select]", cost_value)
        if ratings.get("e7") == "6":
            choose(driver, "submitted[danh_gia][e][z0][other]", ratings.get("cost_other", ""))
        choose(driver, "submitted[danh_gia][z1]", ratings["overall_percent"])
        return_value = "select_or_other" if ratings["return_intent"] == "6" else ratings["return_intent"]
        choose(driver, "submitted[danh_gia][z2][select]", return_value)
        if ratings.get("return_intent") == "6":
            choose(driver, "submitted[danh_gia][z2][other]", ratings.get("return_other", ""))
        choose(driver, "submitted[danh_gia][z3]", ratings.get("unhappy_detail", ""))
        choose(driver, "submitted[danh_gia][z4]", ratings.get("suggestions", ""))

        print(f"Đã điền phiếu {response_id} vào biểu mẫu BYT.")
        print("Kiểm tra lại các trường hiển thị. Script không bấm nút Gửi đi.")
        input("Sau khi kiểm tra (và tự bấm Gửi đi nếu phù hợp), nhấn Enter để đóng Chrome... ")
        return 0
    except KeyboardInterrupt:
        print("Đã dừng theo yêu cầu.")
        return 130
    except Exception as exc:
        print(f"Không điền xong biểu mẫu: {exc}", file=sys.stderr)
        input("Chrome sẽ giữ mở để kiểm tra trạng thái. Nhấn Enter để đóng... ")
        return 1
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
