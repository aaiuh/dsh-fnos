#!/bin/bash
# 本地按 CI 的步骤打一个可安装的 fpk，用于装机验证。
# 用法：bash pack_local.sh <版本> [输出目录]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VER="${1:?用法: pack_local.sh <版本> [输出目录]}"
OUT="${2:-/vol1/@appshare/Hermes/.hermes/cache/scratch}"
cd "$ROOT"

# 1. manifest 版本
sed -i "s/^version=.*/version=${VER}/" manifest

# 2. app.tgz：ui/ + VERSION
rm -rf _pkg && mkdir -p _pkg/ui/images
cp ICON.PNG     _pkg/ui/images/icon_64.png
cp ICON_256.PNG _pkg/ui/images/icon_256.png
cp packaging/ui/config _pkg/ui/config
printf '%s\n' "$(head -n1 VERSION | tr -d '[:space:]')" > _pkg/VERSION
python3 -c "import json;json.load(open('_pkg/ui/config'))"
tar czf app.tgz -C _pkg ui VERSION
rm -rf _pkg

# 3. checksum
SUM=$(md5sum app.tgz | awk '{print $1}')
sed -i '/^checksum=/d' manifest
printf 'checksum=%s\n' "$SUM" >> manifest

# 4. 打包
NAME="dsh-fnos-${VER}-x86.fpk"
tar czf "${OUT}/${NAME}" manifest VERSION ICON.PNG ICON_256.PNG app.tgz cmd config wizard

echo "已生成 ${OUT}/${NAME}  $(stat -c%s "${OUT}/${NAME}") B"
echo "checksum=$SUM"
grep -E '^(version|checksum|desktop_)' manifest
tar tzf "${OUT}/${NAME}" | grep -E '^(app.tgz|wizard/|cmd/)' | head -20
