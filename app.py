#!/usr/bin/env python3
"""Local, mobile-friendly intake form for the inpatient satisfaction survey."""

from __future__ import annotations

import argparse
import http.cookies
import ipaddress
import json
import re
import secrets
import sqlite3
import ssl
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
DB = DATA / "submissions.sqlite3"
SCHEMA = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
OUTPATIENT_SCHEMA = json.loads((ROOT / "schema2.json").read_text(encoding="utf-8"))
RATING_KEYS = [q["key"] for g in SCHEMA["groups"] for q in g["questions"]]
OUTPATIENT_RATING_KEYS = [q["key"] for g in OUTPATIENT_SCHEMA["groups"] for q in g["questions"]]
SCALE_VALUES = {item["value"] for item in SCHEMA["scale"]}
WARD_VALUES = {item["value"] for item in SCHEMA["wards"]}
WARD_CODES = {item["value"]: item.get("code", "") for item in SCHEMA["wards"]}
MAX_BODY = 96_000
SESSIONS = {}
LOGIN_FAILURES = {}
SESSION_LOCK = threading.Lock()
SESSION_TTL = 8 * 60 * 60
STATE_LABELS = {
    "pending": "Chờ kiểm duyệt",
    "approved": "Đã kiểm duyệt",
    "syncing": "Đang gửi BYT",
    "sent": "Đã gửi BYT",
    "failed": "Gửi BYT chưa thành công",
    # Preserve labels for records from prior versions.
    "reviewed": "Đã kiểm duyệt",
}


def db_connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB, timeout=10)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            answers_json TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            survey_form TEXT NOT NULL DEFAULT '1'
        )
    """)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(submissions)")}
    for name in ("survey_form", "reviewed_at", "reviewed_by", "sent_at", "sent_by", "byt_message"):
        if name not in columns:
            connection.execute(f"ALTER TABLE submissions ADD COLUMN {name} TEXT")
    connection.commit()
    return connection


def _choice(value, allowed, label):
    value = str(value or "")
    if value not in allowed:
        raise ValueError(f"Giá trị cho mục {label} không hợp lệ.")
    return value


def _number(value, label, minimum, maximum=None):
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{1,4}", text):
        raise ValueError(f"Vui lòng nhập số hợp lệ cho mục {label}.")
    number = int(text)
    if number < minimum or (maximum is not None and number > maximum):
        raise ValueError(f"Giá trị cho mục {label} nằm ngoài giới hạn cho phép.")
    return text


def validate_answers(raw):
    if not isinstance(raw, dict):
        raise ValueError("Dữ liệu phiếu không đúng định dạng.")
    profile = raw.get("profile")
    ratings = raw.get("ratings")
    if not isinstance(profile, dict) or not isinstance(ratings, dict):
        raise ValueError("Thiếu phần thông tin người trả lời hoặc phần đánh giá.")
    p = {
        "respondent": _choice(profile.get("respondent"), {"1", "2"}, "người trả lời"),
        "patient_name": str(profile.get("patient_name") or "").strip()[:200],
        "patient_code": str(profile.get("patient_code") or "").strip()[:100],
        "gender": _choice(profile.get("gender"), {"1", "2", "3"}, "giới tính"),
        "age": _number(profile.get("age"), "tuổi hoặc năm sinh", 0, 9999),
        "phone": str(profile.get("phone") or "").strip()[:30],
        "stay_days": _number(profile.get("stay_days"), "số ngày nằm viện", 1, 3650),
        "bhyt": _choice(profile.get("bhyt"), {"1", "2"}, "BHYT"),
        "residence": _choice(profile.get("residence"), {"1", "2", "3"}, "nơi sinh sống"),
        "living_standard": _choice(profile.get("living_standard"), {"1", "2", "3"}, "mức sống gia đình"),
        "treatment_count": _number(profile.get("treatment_count"), "lần điều trị", 1, 9999),
        "ward": str(profile.get("ward") or ""),
    }
    if p["age"].isdigit() and int(p["age"]) > 130 and not (1900 <= int(p["age"]) <= datetime.now().year):
        raise ValueError("Tuổi phải từ 0 đến 130, hoặc nhập năm sinh từ 1900 đến nay.")
    if p["ward"] and p["ward"] not in WARD_VALUES:
        raise ValueError("Khoa điều trị không nằm trong danh sách hiện hành.")
    p["ward_code"] = WARD_CODES.get(p["ward"], "")

    clean_ratings = {}
    for key in RATING_KEYS:
        clean_ratings[key] = _choice(ratings.get(key), SCALE_VALUES, f"câu {key.upper()}")
    clean_ratings["e7"] = _choice(ratings.get("e7"), {"1", "2", "3", "4", "5", "6"}, "câu E7")
    clean_ratings["overall_percent"] = _number(ratings.get("overall_percent"), "đánh giá chung", 0, 9999)
    clean_ratings["return_intent"] = _choice(ratings.get("return_intent"), {"1", "2", "3", "4", "5", "6"}, "khả năng quay lại")
    clean_ratings["cost_other"] = str(ratings.get("cost_other") or "").strip()[:1000]
    clean_ratings["return_other"] = str(ratings.get("return_other") or "").strip()[:1000]
    clean_ratings["unhappy_detail"] = str(ratings.get("unhappy_detail") or "").strip()[:3000]
    clean_ratings["suggestions"] = str(ratings.get("suggestions") or "").strip()[:3000]
    if clean_ratings["e7"] == "6" and not clean_ratings["cost_other"]:
        raise ValueError("Vui lòng ghi ý kiến khác cho câu E7.")
    if clean_ratings["return_intent"] == "6" and not clean_ratings["return_other"]:
        raise ValueError("Vui lòng ghi ý kiến khác cho câu G2.")
    if raw.get("consent") is not True:
        raise ValueError("Vui lòng xác nhận đã đọc thông tin về việc sử dụng câu trả lời.")
    return {"profile": p, "ratings": clean_ratings}


def validate_outpatient_answers(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("profile"), dict) or not isinstance(raw.get("ratings"), dict):
        raise ValueError("Thiếu phần thông tin người trả lời hoặc phần đánh giá.")
    profile, ratings = raw["profile"], raw["ratings"]
    p = {
        "respondent": _choice(profile.get("respondent"), {"1", "2"}, "người trả lời"),
        "patient_name": str(profile.get("patient_name") or "").strip()[:200],
        "patient_code": str(profile.get("patient_code") or "").strip()[:100],
        "gender": _choice(profile.get("gender"), {"1", "2", "3"}, "giới tính"),
        "age": _number(profile.get("age"), "tuổi hoặc năm sinh", 0, 9999),
        "distance": _number(profile.get("distance"), "khoảng cách", 0, 9999),
        "bhyt": _choice(profile.get("bhyt"), {"1", "2"}, "BHYT"),
        "residence": _choice(profile.get("residence"), {"1", "2", "3"}, "nơi sinh sống"),
        "living_standard": _choice(profile.get("living_standard"), {"1", "2", "3"}, "mức sống gia đình"),
        "treatment_count": _number(profile.get("treatment_count"), "lần khám", 1, 9999),
        "phone": str(profile.get("phone") or "").strip()[:30],
    }
    if int(p["age"]) > 130 and not (1900 <= int(p["age"]) <= datetime.now().year):
        raise ValueError("Tuổi phải từ 0 đến 130, hoặc nhập năm sinh từ 1900 đến nay.")
    clean = {key: _choice(ratings.get(key), SCALE_VALUES, f"câu {key.upper()}") for key in OUTPATIENT_RATING_KEYS}
    clean["overall_percent"] = _number(ratings.get("overall_percent"), "đánh giá chung", 0, 9999)
    clean["e5_cost"] = _choice(ratings.get("e5_cost"), {"1", "2", "3", "4", "5", "6"}, "nhận xét chi phí")
    clean["cost_other"] = str(ratings.get("cost_other") or "").strip()[:1000]
    clean["return_intent"] = _choice(ratings.get("return_intent"), {"1", "2", "3", "4", "5", "6"}, "khả năng quay lại")
    clean["suggestions"] = str(ratings.get("suggestions") or "").strip()[:3000]
    clean["unhappy_detail"] = str(ratings.get("unhappy_detail") or "").strip()[:3000]
    clean["return_other"] = str(ratings.get("return_other") or "").strip()[:1000]
    if clean["e5_cost"] == "6" and not clean["cost_other"]:
        raise ValueError("Vui lòng ghi ý kiến khác về chi phí.")
    if clean["return_intent"] == "6" and not clean["return_other"]:
        raise ValueError("Vui lòng ghi ý kiến khác về khả năng quay lại.")
    return {"profile": p, "ratings": clean}


class Handler(SimpleHTTPRequestHandler):
    server_version = "InpatientSurvey/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if getattr(self.server, "uses_tls", False):
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        super().end_headers()

    def translate_path(self, path):
        parsed = urlparse(path)
        if parsed.path in ("/", "/mau-2", "/mau-2/", "/staff", "/staff/"):
            parsed_path = "/index.html" if parsed.path == "/" else "/outpatient.html" if parsed.path.startswith("/mau-2") else "/staff.html"
        else:
            parsed_path = parsed.path
        return super().translate_path(parsed_path)

    def _body_json(self):
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            raise ValueError("Chỉ chấp nhận JSON")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            raise ValueError("Kích thước dữ liệu không hợp lệ")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Dữ liệu không đúng định dạng")
        return payload

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        return bool(origin and urlparse(origin).netloc == self.headers.get("Host"))

    def _session(self):
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie.get("staff_session").value
        except (http.cookies.CookieError, AttributeError):
            return None
        with SESSION_LOCK:
            value = SESSIONS.get(token)
            if value and value[1] > time.time():
                return token, value[0]
            SESSIONS.pop(token, None)
        return None

    def _staff_required(self):
        session = self._session()
        if not session:
            self._json(401, {"error": "Đăng nhập lại để tiếp tục."})
            return None
        return session

    def _record(self, record_id):
        if not re.fullmatch(r"NTP-[A-F0-9]{12}", record_id):
            return None
        with db_connect() as connection:
            row = connection.execute("SELECT id, created_at, answers_json, state, reviewed_at, sent_at, survey_form FROM submissions WHERE id=?", (record_id,)).fetchone()
        return row

    def _staff_get(self, path, query):
        if path == "/api/staff/session":
            session = self._session()
            self._json(200, {"authenticated": bool(session), "username": session[1] if session else None})
            return True
        if path.startswith("/api/staff/"):
            session = self._staff_required()
            if not session:
                return True
            if path == "/api/staff/dashboard":
                with db_connect() as connection:
                    rows = connection.execute("SELECT created_at, answers_json, state, survey_form FROM submissions").fetchall()
                now = datetime.now().astimezone()
                today = now.date().isoformat()
                counts = {key: 0 for key in STATE_LABELS}
                scores = []
                daily = {}
                inpatient_wards = {}
                inpatient_total = 0
                outpatient_total = 0
                ward_labels = {ward["value"]: ward["label"] for ward in SCHEMA["wards"]}
                for created, blob, state, survey_form in rows:
                    counts[state] = counts.get(state, 0) + 1
                    day = created[:10]
                    daily[day] = daily.get(day, 0) + 1
                    try:
                        answers = json.loads(blob)
                        ratings = answers.get("ratings", {})
                        rating_values = []
                        for key in (OUTPATIENT_RATING_KEYS if survey_form == "2" else RATING_KEYS):
                            value = str(ratings.get(key, ""))
                            if value in {"1", "2", "3", "4", "5"}:
                                rating_values.append(int(value))
                        scores.extend(rating_values)
                        if survey_form == "2":
                            outpatient_total += 1
                        else:
                            inpatient_total += 1
                            profile = answers.get("profile", {})
                            ward_value = profile.get("ward", "")
                            ward_name = ward_labels.get(ward_value, ward_value or "Chưa chọn khoa")
                            ward = inpatient_wards.setdefault(ward_name, {"ward": ward_name, "count": 0, "scores": []})
                            ward["count"] += 1
                            ward["scores"].extend(rating_values)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                days = []
                for offset in range(6, -1, -1):
                    day = (now.date() - timedelta(days=offset)).isoformat()
                    days.append({"date": day, "count": daily.get(day, 0)})
                ward_report = []
                for ward in inpatient_wards.values():
                    ward_report.append({
                        "ward": ward["ward"],
                        "count": ward["count"],
                        "average_score": round(sum(ward["scores"]) / len(ward["scores"]), 2) if ward["scores"] else None,
                    })
                ward_report.sort(key=lambda item: (-item["count"], item["ward"]))
                self._json(200, {"total": len(rows), "today": daily.get(today, 0), "counts": counts, "average_score": round(sum(scores) / len(scores), 2) if scores else None, "daily": days, "inpatient": {"total": inpatient_total, "wards": ward_report}, "outpatient": {"total": outpatient_total}})
                return True
            if path == "/api/staff/submissions":
                state = query.get("state", ["pending"])[0]
                if state not in (*STATE_LABELS, "all"):
                    self._json(400, {"error": "Trạng thái không hợp lệ."}); return True
                search = query.get("q", [""])[0].strip()[:120]
                try: page = max(1, int(query.get("page", ["1"])[0]))
                except ValueError: page = 1
                page_size = 30
                with db_connect() as connection:
                    clauses, params = [], []
                    if state != "all": clauses.append("state=?"); params.append(state)
                    if search:
                        clauses.append("(id LIKE ? OR answers_json LIKE ?)")
                        wildcard = f"%{search}%"; params.extend([wildcard, wildcard])
                    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
                    total = connection.execute("SELECT COUNT(*) FROM submissions" + where, params).fetchone()[0]
                    offset = (page - 1) * page_size
                    rows = connection.execute("SELECT id, created_at, answers_json, state, survey_form FROM submissions" + where + " ORDER BY created_at DESC LIMIT ? OFFSET ?", [*params, page_size, offset]).fetchall()
                items = []
                for rid, created, blob, status, survey_form in rows:
                    profile = json.loads(blob).get("profile", {})
                    items.append({"id": rid, "created_at": created, "state": status, "state_label": STATE_LABELS.get(status, status), "survey_form": survey_form, "patient_name": profile.get("patient_name", ""), "respondent": profile.get("respondent", ""), "ward_label": profile.get("ward", "")})
                self._json(200, {"items": items, "total": total, "page": page, "page_size": page_size}); return True
            match = re.fullmatch(r"/api/staff/submissions/(NTP-[A-F0-9]{12})(?:/(export))?", path)
            if match:
                record_id, export = match.groups()
                row = self._record(record_id)
                if not row: self._json(404, {"error": "Không tìm thấy phiếu."}); return True
                rid, created, blob, status, reviewed_at, sent_at, survey_form = row
                answers = json.loads(blob)
                if export:
                    survey_type = query.get("survey_type", [""])[0]
                    if survey_type not in {"1", "2", "3", "4", "5", "6"}:
                        self._json(400, {"error": "Chọn kiểu khảo sát trước khi tải gói chuyển BYT."}); return True
                    payload = json.dumps({"id": rid, "created_at": created, "survey_form": survey_form, "survey_type": survey_type, "answers": answers}, ensure_ascii=False, indent=2).encode("utf-8")
                    self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Disposition", f'attachment; filename="{rid}.json"'); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload); return True
                self._json(200, {"item": {"id": rid, "created_at": created, "state": status, "state_label": STATE_LABELS.get(status, status), "survey_form": survey_form, "reviewed_at": reviewed_at, "sent_at": sent_at, "consent": True, "answers": answers}}); return True
            self._json(404, {"error": "Không tìm thấy đường dẫn."}); return True
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if self._staff_get(parsed.path, query): return
        if parsed.path == "/schema.json":
            payload = json.dumps(SCHEMA, ensure_ascii=False).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload); return
        if parsed.path == "/schema2.json":
            payload = json.dumps(OUTPATIENT_SCHEMA, ensure_ascii=False).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload); return
        if parsed.path == "/health":
            self._json(200, {"status": "ok"}); return
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/staff/"):
            if not self._origin_ok(): self.send_error(403, "Origin không hợp lệ"); return
            try: body = self._body_json()
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc: self._json(400, {"error": str(exc)}); return
            if path == "/api/staff/login":
                username = str(body.get("username", ""))[:64]
                failures = LOGIN_FAILURES.get(self.client_address[0], (0, 0))
                if failures[1] > time.time(): self._json(429, {"error": "Thử đăng nhập lại sau ít phút."}); return
                from staff_auth import verify
                if not verify(username, str(body.get("password", ""))):
                    count = failures[0] + 1; LOGIN_FAILURES[self.client_address[0]] = (count, time.time() + (300 if count >= 8 else 0))
                    self._json(401, {"error": "Tên đăng nhập hoặc mật khẩu không đúng."}); return
                LOGIN_FAILURES.pop(self.client_address[0], None)
                token = secrets.token_urlsafe(32)
                with SESSION_LOCK: SESSIONS[token] = (username, time.time() + SESSION_TTL)
                self._json(200, {"authenticated": True}, headers={"Set-Cookie": f"staff_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}" + ("; Secure" if getattr(self.server, "uses_tls", False) else "")})
                return
            if path == "/api/staff/logout":
                current = self._session()
                if current:
                    with SESSION_LOCK: SESSIONS.pop(current[0], None)
                self._json(200, {"authenticated": False}, headers={"Set-Cookie": "staff_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" + ("; Secure" if getattr(self.server, "uses_tls", False) else "")}); return
            session = self._staff_required()
            if not session: return
            match = re.fullmatch(r"/api/staff/submissions/(NTP-[A-F0-9]{12})/send-byt", path)
            if match:
                rid = match.group(1)
                row = self._record(rid)
                if not row: self._json(404, {"error": "Không tìm thấy phiếu."}); return
                current = row[3]
                if current not in {"approved", "reviewed", "failed"}:
                    self._json(409, {"error": "Phiếu cần được kiểm duyệt trước khi gửi Bộ Y tế."}); return
                with db_connect() as connection:
                    changed = connection.execute("UPDATE submissions SET state='syncing', byt_message=NULL WHERE id=? AND state=?", (rid, current)).rowcount
                if not changed:
                    self._json(409, {"error": "Phiếu đang được xử lý bởi một phiên khác."}); return
                try:
                    from byt_submit import BYTSubmissionError, submit
                    result = submit(rid, json.loads(row[2]), row[6])
                except BYTSubmissionError as exc:
                    message = str(exc)
                    with db_connect() as connection:
                        connection.execute("UPDATE submissions SET state='failed', byt_message=? WHERE id=?", (message, rid))
                    self._json(502, {"error": message, "state": "failed", "state_label": STATE_LABELS["failed"]}); return
                sent_at = datetime.now().astimezone().isoformat(timespec="seconds")
                with db_connect() as connection:
                    connection.execute("UPDATE submissions SET state='sent', sent_at=?, sent_by=?, byt_message=? WHERE id=?", (sent_at, session[1], result["message"], rid))
                self._json(200, {"state": "sent", "state_label": STATE_LABELS["sent"], "message": result["message"]}); return
            match = re.fullmatch(r"/api/staff/submissions/(NTP-[A-F0-9]{12})/edit", path)
            if match:
                rid = match.group(1)
                row = self._record(rid)
                if not row: self._json(404, {"error": "Không tìm thấy phiếu."}); return
                if row[3] in {"sent", "syncing"}:
                    self._json(409, {"error": "Không thể sửa phiếu đang gửi hoặc đã gửi Bộ Y tế."}); return
                supplied = body.get("answers")
                if not isinstance(supplied, dict):
                    self._json(400, {"error": "Dữ liệu chỉnh sửa không hợp lệ."}); return
                supplied = {**supplied, "consent": True}
                answers = validate_outpatient_answers(supplied) if row[6] == "2" else validate_answers(supplied)
                now = datetime.now().astimezone().isoformat(timespec="seconds")
                with db_connect() as connection:
                    connection.execute("UPDATE submissions SET answers_json=?, state='pending', reviewed_at=NULL, reviewed_by=NULL, byt_message=? WHERE id=?", (json.dumps(answers, ensure_ascii=False), "Phiếu đã được chỉnh sửa và cần kiểm duyệt lại.", rid))
                self._json(200, {"state": "pending", "state_label": STATE_LABELS["pending"]}); return
            match = re.fullmatch(r"/api/staff/submissions/(NTP-[A-F0-9]{12})/state", path)
            if match:
                rid = match.group(1); target = body.get("state")
                row = self._record(rid)
                if not row: self._json(404, {"error": "Không tìm thấy phiếu."}); return
                current = row[3]
                allowed = {"pending": "approved", "reviewed": "approved"}
                if allowed.get(current) != target: self._json(409, {"error": "Trạng thái phiếu đã thay đổi hoặc chuyển trạng thái không hợp lệ."}); return
                now = datetime.now().astimezone().isoformat(timespec="seconds")
                with db_connect() as connection:
                    connection.execute("UPDATE submissions SET state=?, reviewed_at=?, reviewed_by=? WHERE id=? AND state=?", (target, now, session[1], rid, current))
                self._json(200, {"state": target, "state_label": STATE_LABELS[target]}); return
            self._json(404, {"error": "Không tìm thấy đường dẫn."}); return
        if path not in {"/api/submissions", "/api/outpatient-submissions"}: self.send_error(404); return
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self.send_error(403, "Origin không khớp máy chủ khảo sát"); return
        try:
            raw = self._body_json()
            survey_form = "2" if path == "/api/outpatient-submissions" else "1"
            answers = validate_outpatient_answers(raw) if survey_form == "2" else validate_answers(raw)
            record_id = "NTP-" + secrets.token_hex(6).upper()
            created = datetime.now().astimezone().isoformat(timespec="seconds")
            with db_connect() as connection:
                connection.execute("INSERT INTO submissions (id, created_at, answers_json, state, survey_form) VALUES (?, ?, ?, 'pending', ?)", (record_id, created, json.dumps(answers, ensure_ascii=False), survey_form))
            self._json(201, {"id": record_id, "submitted": False, "message": "Phiếu đã được lưu và đang chờ quản trị viên kiểm duyệt."})
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc: self._json(400, {"error": str(exc)})
        except sqlite3.Error: self._json(500, {"error": "Không lưu được phiếu. Vui lòng báo nhân viên hỗ trợ."})

    def _json(self, status, payload, headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items(): self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        # Avoid logging URLs, form answers, or other request details.
        print(f"[{self.log_date_time_string()}] {self.address_string()} {self.command or 'request'}")


class SurveyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    parser = argparse.ArgumentParser(description="Chạy biểu mẫu nội trú trên mạng nội bộ.")
    parser.add_argument("--host", default="127.0.0.1", help="Mặc định chỉ máy này; dùng 0.0.0.0 để phục vụ máy khác qua Wi-Fi")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cert", type=Path, help="Chứng thư TLS, bắt buộc nếu --host không phải localhost")
    parser.add_argument("--key", type=Path, help="Khóa riêng TLS")
    args = parser.parse_args()
    try:
        is_loopback = ipaddress.ip_address(args.host).is_loopback or args.host == "localhost"
    except ValueError:
        is_loopback = args.host == "localhost"
    if not is_loopback and not (args.cert and args.key):
        parser.error("Chế độ truy cập từ điện thoại cần --cert và --key để dùng HTTPS.")
    if bool(args.cert) != bool(args.key):
        parser.error("Cần cung cấp đồng thời --cert và --key.")
    db_connect().close()
    server = SurveyServer((args.host, args.port), Handler)
    server.uses_tls = bool(args.cert and args.key)
    if server.uses_tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(args.cert), str(args.key))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        protocol = "https"
    else:
        protocol = "http"
    print(f"Khảo sát đang chạy tại {protocol}://{args.host}:{args.port}")
    print(f"Dữ liệu được lưu trong: {DB}")
    print("Phiếu gửi từ người bệnh được đồng bộ trực tiếp lên cổng Bộ Y tế khi đã cấu hình byt_credentials.json.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Đã dừng máy chủ.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
