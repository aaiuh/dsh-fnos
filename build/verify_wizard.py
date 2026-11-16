#!/usr/bin/env python3
"""构建期校验：向导里不准再有版本下拉，只准有「自动跟随最新版」开关。

版本策略是「永远 npm latest」，所以任何残留的 dsh_version 字段都意味着
有新旧的实现混进了包里——那种包装上去行为不可预测，必须在发布前挡掉。
"""
from __future__ import annotations

import json
import os
import sys
from typing import NoReturn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIZARD = ["wizard/install", "wizard/config", "wizard/uninstall"]


def fail(msg: str) -> NoReturn:
    print(f"[verify-wizard] FAIL {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    for name in WIZARD:
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            fail(f"{name} 不存在")
        try:
            steps = json.load(open(path, encoding="utf-8"))
        except Exception as exc:
            fail(f"{name} 不是合法 JSON：{exc}")

        if not isinstance(steps, list) or not steps:
            fail(f"{name} 必须是非空数组")

        for step in steps:
            items = step.get("items")
            if not isinstance(items, list):
                fail(f"{name} 里每个 step 必须有 items 数组")
            for item in items:
                if not isinstance(item, dict):
                    fail(f"{name} 的 items 里有非对象成员")
                if item.get("field") == "dsh_version":
                    fail(f"{name} 里还有 dsh_version 字段，版本应恒为 npm latest")

    # 安装与设置向导都要能控制自动跟随
    for name in ("wizard/install", "wizard/config"):
        items = json.load(open(os.path.join(ROOT, name), encoding="utf-8"))[0]["items"]
        fields = {i.get("field") for i in items if isinstance(i, dict)}
        if "dsh_auto_update" not in fields:
            fail(f"{name} 缺少 dsh_auto_update 开关")
        switch = next(i for i in items if i.get("field") == "dsh_auto_update")
        if switch.get("type") != "switch":
            fail(f"{name} 的 dsh_auto_update 必须是 switch 类型")
        if str(switch.get("initValue")) != "true":
            fail(f"{name} 的 dsh_auto_update 默认值应为 true（默认跟随最新版）")

    print("[verify-wizard] OK 三个向导结构正确，版本恒为 npm latest，自动跟随默认开启")
    return 0


if __name__ == "__main__":
    sys.exit(main())
