#!/usr/bin/env python3
"""Synchronize the current Cloudflare Quick Tunnel URL with EasiPage."""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SITE_NAME = os.environ.get("EASIPAGE_SITE_NAME", "khaosat-ntp")
TOKEN = os.environ.get("EASIPAGE_API_TOKEN", "")
STATE_FILE = Path("/var/lib/kshl-easipage-sync/upstream-url")
TUNNEL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def latest_tunnel_url() -> str | None:
    result = subprocess.run(
        ["journalctl", "-u", "kshl-cloudflared", "--no-pager", "-n", "500"],
        check=False,
        capture_output=True,
        text=True,
    )
    matches = TUNNEL_PATTERN.findall(result.stdout)
    return matches[-1] if matches else None


def update_easipage(upstream_url: str) -> None:
    request = urllib.request.Request(
        f"https://easipage.xyz/api/external-sites/{SITE_NAME}",
        data=json.dumps({"upstream_url": upstream_url}).encode(),
        method="PATCH",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "kshl-easipage-sync/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"EasiPage returned HTTP {response.status}")


def main() -> int:
    if not TOKEN:
        print("EASIPAGE_API_TOKEN is not configured.", file=sys.stderr)
        return 1
    current_url = latest_tunnel_url()
    if not current_url:
        print("No Cloudflare Quick Tunnel URL found yet.", file=sys.stderr)
        return 1
    previous_url = STATE_FILE.read_text().strip() if STATE_FILE.exists() else ""
    if current_url == previous_url:
        print("EasiPage upstream is current.")
        return 0
    try:
        update_easipage(current_url)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:500]
        print(f"EasiPage synchronization failed: HTTP {error.code}: {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, RuntimeError) as error:
        print(f"EasiPage synchronization failed: {error}", file=sys.stderr)
        return 1
    STATE_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE_FILE.write_text(current_url + "\n")
    os.chmod(STATE_FILE, 0o600)
    print("EasiPage upstream updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
