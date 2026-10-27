#!/usr/bin/env python3
"""把一次构建的结果登记进 fnpack.json（幂等）。

用法：
    python3 build/publish.py <fpk版本> <fpk路径> <上游dsh版本> [changelog]

fpk 版本形如 0.2.1-1（上游 0.2.1 的第一版打包）；上游版本形如 0.2.1-rc.2。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import sys

REPO = "aaiuh/dsh-fnos"
APPNAME = "dsh-fnos"
DISPLAY = "DeepSeek Harness"
CATEGORIES = ["AI赋能"]
SERVICE_PORT = "3080"
OS_MIN = "1.1.3100"


def sha256_of(path: str) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def read_manifest(path: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        meta[k.strip()] = v.strip()
    return meta


def main() -> int:
    if len(sys.argv) < 4:
        print("用法: publish.py <fpk版本> <fpk路径> <上游版本> [changelog]", file=sys.stderr)
        return 2
    ver, fpk, upstream = sys.argv[1], sys.argv[2], sys.argv[3]
    changelog = sys.argv[4] if len(sys.argv) > 4 else ""

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    idx_path = os.path.join(root, "fnpack.json")
    manifest = read_manifest(os.path.join(root, "manifest"))

    sha, size = sha256_of(fpk)
    url = f"https://github.com/{REPO}/releases/download/v{ver}/{os.path.basename(fpk)}"

    doc = {"schema_version": "2", "source_info": {}, "apps": {}}
    if os.path.exists(idx_path):
        try:
            doc = json.load(open(idx_path, encoding="utf-8"))
        except Exception:
            pass
    doc.setdefault("schema_version", "2")
    doc["source_info"] = {
        "name": "aaiuh飞牛应用源",
        "author": "aaiuh",
        "homepage": "https://github.com/aaiuh/fnos-apps",
        "description": "飞牛 fnOS 原生应用集合。免费开源，跟随各应用上游更新。",
    }
    apps = doc.setdefault("apps", {})
    app = apps.setdefault(APPNAME, {})
    app.update({
        "display_name": manifest.get("display_name") or DISPLAY,
        "desc": manifest.get("desc", ""),
        "platform": [manifest.get("platform") or "x86"],
        "categories": CATEGORIES,
        "icon_url": f"https://raw.githubusercontent.com/{REPO}/main/ICON_256.PNG",
        "preview_urls": [],
        "readme_url": f"https://raw.githubusercontent.com/{REPO}/main/README.md",
        "bug_report_url": f"https://github.com/{REPO}/issues",
        "maintainer": manifest.get("maintainer") or "DeepSeek AI",
        "maintainer_url": manifest.get("maintainer_url") or "https://github.com/deepseek-ai/deepseek-harness",
        "distributor": "aaiuh",
        "distributor_url": f"https://github.com/{REPO}",
        "run_as": "package",
        "install_type": "",
        "is_docker": False,
        "service_port": manifest.get("service_port") or SERVICE_PORT,
    })

    releases = app.setdefault("releases", {})
    if not changelog:
        changelog = f"跟随上游 dsh {upstream}。"
    else:
        changelog = f"{changelog}\n\n上游 dsh {upstream}。"
    releases[ver] = {
        "changelog": changelog.strip()[:4000],
        "updated_at": _dt.date.today().isoformat(),
        "os_min_version": manifest.get("os_min_version") or OS_MIN,
        "packages": {
            "x86": {"download_url": url, "sha256": sha, "size": size}
        },
    }
    app["releases"] = dict(sorted(releases.items(), key=lambda kv: _verkey(kv[0])))

    with open(idx_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"[publish] fnpack.json 已登记 {APPNAME} {ver}  {size:,} B  {sha[:16]}…")
    return 0


def _verkey(v: str):
    import re

    v = (v or "").strip().lstrip("vV")
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", v)
    if not m:
        return ((0,), 0, (0, ""))
    nums = tuple(int(x) for x in m.group(1).split("."))
    tail = m.group(2) or ""
    if not tail:
        return (nums, 0, (0, ""))
    rev = re.fullmatch(r"-(\d+)", tail)
    if rev:
        return (nums, 1, (int(rev.group(1)), ""))
    return (nums, -1, (0, tail))


if __name__ == "__main__":
    sys.exit(main())
