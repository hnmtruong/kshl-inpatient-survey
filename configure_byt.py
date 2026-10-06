#!/usr/bin/env python3
"""Create the BYT bridge configuration without exposing a password in a command line."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "data" / "byt_credentials.json"

username = input("Tài khoản BYT: ").strip()
password = getpass.getpass("Mật khẩu BYT: ")
survey_type = input("Kiểu khảo sát BYT [1]: ").strip() or "1"
if not username or not password or survey_type not in {"1", "2", "3", "4", "5", "6"}:
    raise SystemExit("Cấu hình chưa hợp lệ; không ghi tệp.")
TARGET.parent.mkdir(parents=True, exist_ok=True)
temp = TARGET.with_suffix(".tmp")
temp.write_text(json.dumps({"enabled": True, "username": username, "password": password, "survey_type": survey_type}, ensure_ascii=False) + "\n", encoding="utf-8")
os.chmod(temp, 0o600)
temp.replace(TARGET)
os.chmod(TARGET, 0o600)
print(f"Đã lưu cấu hình bảo mật tại {TARGET}.")
