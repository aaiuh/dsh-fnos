#!/usr/bin/env python3
"""把「dsh 版本」收敛成一条线：永远跟随 npm 上的 latest。

以前的实现会在向导里渲染一个最近 5 个版本的下拉让人自己选。实际用下来没意义：
上游发版很勤（rc.1 → rc.3 只隔 9 天），下拉里的版本很快过期，而「选版本」这个动作
对使用者没有价值——要的就是最新版。

现在版本只由两处决定：
  * 安装时：cmd/install_callback 解析 npm 的 dist-tags.latest
  * 之后：cmd/main 启动时后台检查 latest，有新版自动升级（设置里可关）

本脚本因此退化为「校验 + 兜底」：
  1. 取 npm latest（取不到不影响构建）
  2. --write-version 时写入 VERSION，作为 npm 不可达时的安装兜底
  3. 幂等清理向导里遗留的 dsh_version 下拉，确保 dsh_auto_update 开关在

用法：
    python3 build/render_wizard.py [--registry URL] [--write-version] [--json]
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

AUTO_FIELD = {
    "type": "switch",
    "field": "dsh_auto_update",
    "label": "自动跟随最新版",
    "initValue": "true",
    "helpText": (
        "开启后，应用启动时会在后台检查 npm 上的 latest；"
        "有新版本自动安装并重启一次（不额外占端口，重启期间界面短暂不可用）。"
        "关掉就固定当前版本，需要手动在应用中心覆盖安装新版 fpk 才会升级。"
    ),
}


def fetch_latest(registry: str) -> str:
    """取 latest：先直连 registry，再退回 npm CLI；都失败返回空串。"""
    url = registry.rstrip("/") + "/" + PKG.replace("/", "%2F")
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            meta = json.load(r)
        latest = ((meta.get("dist-tags") or {}).get("latest") or "").strip()
        if latest:
            return latest
    except Exception:
        pass

    try:
        out = subprocess.run(
            ["npm", "view", PKG, "dist-tags.latest", "--registry", registry],
            capture_output=True, text=True, timeout=60,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def normalize(path: str) -> list[str]:
    """删掉遗留的 dsh_version 下拉，补上 dsh_auto_update 开关。返回改动说明。"""
    changes: list[str] = []
    with open(path, encoding="utf-8") as fh:
        steps = json.load(fh)

    for step in steps:
        items = step.get("items") or []

        kept = [i for i in items if i.get("field") != "dsh_version"]
        if len(kept) != len(items):
            changes.append("移除 dsh_version 下拉")

        if not any(i.get("field") == "dsh_auto_update" for i in kept):
            kept.append(AUTO_FIELD)
            changes.append("补上 dsh_auto_update 开关")

        step["items"] = kept

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(steps, fh, ensure_ascii=False, indent=4)
        fh.write("\n")
    return changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="https://registry.npmmirror.com")
    ap.add_argument("--keep", type=int, default=0, help="已废弃，保留只为兼容旧调用")
    ap.add_argument("--default", default="", help="已废弃：版本恒为 npm latest")
    ap.add_argument("--write-version", action="store_true", help="把 latest 写进 VERSION 兜底")
    ap.add_argument("--json", action="store_true", help="只打印结果，不写文件")
    args = ap.parse_args()

    latest = fetch_latest(args.registry)
    if not latest:
        print("[wizard] WARN 取不到 npm latest，向导保持现状（安装时还会再试一次）",
              file=sys.stderr)

    if args.json:
        print(json.dumps({"latest": latest, "registry": args.registry},
                         ensure_ascii=False, indent=2))
        return 0

    for name in ("install", "config"):
        path = os.path.join(WIZARD_DIR, name)
        if not os.path.exists(path):
            print(f"[wizard] 跳过（不存在）{path}", file=sys.stderr)
            continue
        changes = normalize(path)
        print(f"[wizard] {name}：" + ("、".join(changes) if changes else "已是最新结构"))

    if args.write_version and latest:
        with open(os.path.join(ROOT, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write(latest + "\n")
        print(f"[wizard] VERSION 兜底值写为 {latest}")

    print(f"[wizard] dsh 目标版本：npm latest = {latest or '（未取到）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
