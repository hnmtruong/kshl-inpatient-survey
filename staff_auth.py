#!/usr/bin/env python3
"""Password storage and account administration for the staff review page."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent
USERS_FILE = ROOT / "data" / "staff_users.json"
ITERATIONS = 600_000


def load_users():
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def verify(username: str, password: str) -> bool:
    users = load_users()
    record = users.get(username)
    if not isinstance(record, dict):
        # Keep the work factor similar for unknown usernames.
        hashlib.pbkdf2_hmac("sha256", password.encode(), b"invalid-user-salt", ITERATIONS)
        return False
    try:
        salt = bytes.fromhex(record["salt"])
        expected = bytes.fromhex(record["hash"])
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(record["iterations"]))
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def save_users(users):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = USERS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(users, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(USERS_FILE)
    os.chmod(USERS_FILE, 0o600)


def add_user(username: str):
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", username):
        raise ValueError("Tên đăng nhập cần 3–64 ký tự: chữ, số, dấu chấm, gạch dưới hoặc gạch ngang.")
    password = getpass.getpass("Mật khẩu nhân viên (ít nhất 5 ký tự): ")
    confirm = getpass.getpass("Nhập lại mật khẩu: ")
    if len(password) < 5:
        raise ValueError("Mật khẩu cần ít nhất 5 ký tự.")
    if not hmac.compare_digest(password, confirm):
        raise ValueError("Hai lần nhập mật khẩu không trùng nhau.")
    salt = secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    users = load_users()
    users[username] = {"salt": salt.hex(), "hash": digest.hex(), "iterations": ITERATIONS}
    save_users(users)


def main():
    parser = argparse.ArgumentParser(description="Quản lý tài khoản trang review khảo sát.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    add = subparsers.add_parser("add", help="Thêm hoặc đặt lại tài khoản")
    add.add_argument("username")
    remove = subparsers.add_parser("remove", help="Xóa tài khoản")
    remove.add_argument("username")
    subparsers.add_parser("list", help="Liệt kê tên tài khoản")
    args = parser.parse_args()
    if args.action == "add":
        try:
            add_user(args.username)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"Đã lưu tài khoản {args.username}.")
    elif args.action == "remove":
        users = load_users()
        if args.username not in users:
            parser.error("Không tìm thấy tài khoản.")
        del users[args.username]
        save_users(users)
        print(f"Đã xóa tài khoản {args.username}.")
    else:
        for username in sorted(load_users()):
            print(username)


if __name__ == "__main__":
    main()
