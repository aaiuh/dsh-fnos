#!/usr/bin/env python3
"""按 npm 上的实际发布情况，渲染安装/设置向导里的「dsh 版本」下拉。

上游的 dist-tags 不一定会跟着发版走：最新发到 0.2.1-rc.4 时 latest 可能仍停在
0.2.1-rc.2。所以这里把最近若干版本连同它所属的 tag 一起列出来，让装的人自己选，
而不是由包去猜「该跟哪个」。

用法：
    python3 build/render_wizard.py [--registry URL] [--keep N] [--json]

产物：wizard/install、wizard/config（都含 dsh_version 下拉）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request

PKG = "@deepseek-ai/dsh"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIZARD_DIR = os.path.join(ROOT, "wizard")
KEEP = 5


def fetch_meta(registry: str) -> dict:
    url = registry.rstrip("/") + "/" + PKG.replace("/", "%2F")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def npm_view(args: list[str], registry: str) -> str:
    """URL 取不到时退回 npm CLI（走 .npmrc 里的代理/镜像设置）。"""
    try:
        out = subprocess.run(
            ["npm", "view", PKG, *args, "--registry", registry],
            capture_output=True, text=True, timeout=60,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def semver_key(v: str):
    """把 0.2.1-rc.4 这类版本排成可比较的键：数字段 + 预发布段。"""
    import re

    m = re.fullmatch(r"(\d+(?:\.\d+)*)(?:-(.+))?", (v or "").strip())
    if not m:
        return ((0,), (0,))
    nums = tuple(int(x) for x in m.group(1).split("."))
    pre = m.group(2) or ""
    if not pre:
        return (nums, (1, ()))
    parts = []
    for token in pre.split("."):
        parts.append((0, int(token), "") if token.isdigit() else (0, -1, token))
    return (nums, (0, tuple(parts)))


def collect(registry: str, keep: int) -> tuple[list[dict], dict[str, str]]:
    meta = fetch_meta(registry)
    tags = meta.get("dist-tags") or {}
    times = meta.get("time") or {}
    versions = [v for v in (meta.get("versions") or {}) if v != "created"]

    if not versions:
        raise RuntimeError("npm 上没有拿到任何版本")

    latest = tags.get("latest") or ""
    if not latest:
        latest = npm_view(["version"], registry)

    # 展示顺序：latest 优先，其次 next，其余按版本号倒序，最后截断
    ordered: list[str] = []
    for tag in ("latest", "next"):
        v = tags.get(tag)
        if v and v not in ordered:
            ordered.append(v)
    for v in sorted(versions, key=semver_key, reverse=True):
        if v not in ordered:
            ordered.append(v)
    ordered = ordered[:keep]

    tag_of = {}
    for tag, v in tags.items():
        tag_of.setdefault(v, []).append(tag)

    opts = []
    for v in ordered:
        marks = [t for t in tag_of.get(v, []) if t in ("latest", "next")]
        when = (times.get(v) or "")[:10]
        bits = []
        if "latest" in marks:
            bits.append("latest")
        if "next" in marks:
            bits.append("next")
        label = v
        if bits or when:
            label += "（" + " · ".join(bits + ([when] if when else [])) + "）"
        opts.append({"label": label, "value": v})

    return opts, {"latest": latest, "next": tags.get("next") or ""}


def version_field(options: list[dict], default: str) -> dict:
    return {
        "type": "select",
        "field": "dsh_version",
        "label": "dsh 版本",
        "initValue": default,
        "options": options,
        "helpText": (
            "装哪个版本的 dsh 本体。latest 是上游标记的稳定发布，"
            "next 是更新的预发布；两者不一定相同，这里按实际发布列出。"
            "装完也能在应用设置里改，改完会自动换版本并重启。"
        ),
    }


def render(path: str, options: list[dict], default: str) -> None:
    with open(path, encoding="utf-8") as fh:
        steps = json.load(fh)

    for step in steps:
        items = step.get("items") or []
        for i, item in enumerate(items):
            if item.get("field") == "dsh_version":
                items[i] = version_field(options, default)
                break
        else:
            # 没有就插在第一位，装的时候第一眼看到
            items.insert(0, version_field(options, default))

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(steps, fh, ensure_ascii=False, indent=4)
        fh.write("\n")
    print(f"[wizard] 已更新 {os.path.relpath(path, ROOT)}：{len(options)} 个版本选项，默认 {default}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="https://registry.npmmirror.com")
    ap.add_argument("--keep", type=int, default=KEEP)
    ap.add_argument("--default", default="", help="默认选中的版本；留空则取 latest")
    ap.add_argument("--write-version", action="store_true", help="同时把默认版本写进 VERSION")
    ap.add_argument("--json", action="store_true", help="只打印结果，不写文件")
    args = ap.parse_args()

    try:
        options, tags = collect(args.registry, args.keep)
    except Exception as exc:  # 网络不通时不要打断构建
        print(f"[wizard] WARN 取不到 npm 版本列表（{exc}），保留现有 wizard 不变", file=sys.stderr)
        return 0

    known = {o["value"] for o in options}
    default = args.default or tags.get("latest") or options[0]["value"]
    if default not in known:
        # --default 指向的版本（例如手动 dispatch 指定的）不在最近列表里，补进去
        options.insert(0, {"label": default, "value": default})

    if args.json:
        print(json.dumps({"options": options, "tags": tags, "default": default},
                         ensure_ascii=False, indent=2))
        return 0

    for name in ("install", "config"):
        path = os.path.join(WIZARD_DIR, name)
        if os.path.exists(path):
            render(path, options, default)
        else:
            print(f"[wizard] 跳过（不存在）{path}", file=sys.stderr)

    if args.write_version:
        with open(os.path.join(ROOT, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write(default + "\n")
        print(f"[wizard] VERSION 兜底值写为 {default}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
