#!/bin/bash
# 本地按 CI 的步骤打一个可安装的 fpk，用于装机验证。
# 用法：bash pack_local.sh <版本> [输出目录]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VER="${1:?用法: pack_local.sh <版本> [输出目录]}"
OUT="${2:-/tmp}"
cd "$ROOT"

# 1. manifest 版本
sed -i "s/^version=.*/version=${VER}/" manifest

# 2. app.tgz：ui/ + shim/ + VERSION
# 注意：飞牛只把 app.tgz 解到 @appcenter/<app>/，自定义目录必须放进来，
# 直接放在 fpk 根会被平台自己消费掉、不会落到应用目录。
rm -rf _pkg && mkdir -p _pkg/ui/images _pkg/shim
cp ICON.PNG     _pkg/ui/images/icon_64.png
cp ICON_256.PNG _pkg/ui/images/icon_256.png
cp packaging/ui/config _pkg/ui/config
cp shim/gateway_shim.py _pkg/shim/gateway_shim.py
printf '%s\n' "$(head -n1 VERSION | tr -d '[:space:]')" > _pkg/VERSION
python3 -c "import json;json.load(open('_pkg/ui/config'))"
python3 -c "import ast;ast.parse(open('_pkg/shim/gateway_shim.py').read())"
tar czf app.tgz -C _pkg ui VERSION shim
rm -rf _pkg

# 3. checksum
SUM=$(md5sum app.tgz | awk '{print $1}')
sed -i '/^checksum=/d' manifest
printf 'checksum=%s\n' "$SUM" >> manifest

# 4. 打包
NAME="dsh-fnos-${VER}-x86.fpk"
tar czf "${OUT}/${NAME}" manifest VERSION ICON.PNG ICON_256.PNG app.tgz cmd config wizard shim

echo "已生成 ${OUT}/${NAME}  $(stat -c%s "${OUT}/${NAME}") B"
echo "checksum=$SUM"
grep -E '^(version|checksum|desktop_)' manifest
tar tzf "${OUT}/${NAME}" | grep -E '^(app.tgz|wizard/|cmd/)' | head -20
