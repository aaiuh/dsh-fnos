# dsh-fnos · DeepSeek Harness 飞牛原生包

把 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（命令行 `dsh`）打包成飞牛 fnOS 能装的应用。**默认跟随 npm latest 自动升级**，你不用管版本。

## 装法

在飞牛应用中心上传 `dsh-fnos-<版本>-x86.fpk`，或者把本仓库加进集合源后用 FnDepot 安装。

安装向导只有四个可填项：

| 项 | 默认 | 说明 |
|---|---|---|
| 监听端口 | `3080` | DSH Web 的端口 |
| 监听地址 | 留空 | 留空自动取主网卡 IPv4；dsh 不接受 `0.0.0.0` |
| npm 源 | `registry.npmmirror.com` | 安装和升级时拉 dsh 本体用的源 |
| **自动跟随最新版** | 开 | 见下节 |

装完访问 `http://设备IP:3080`，首次进入在设置里填 DeepSeek API Key。

> **首次访问要带启动 token。** dsh web 默认开启浏览器鉴权，直接开端口只会返回 `401 dsh web authentication required`。第一次请从应用「日志」里复制 `首次访问链接（含启动 token）` 那一行（也可读 `/vol1/@appshare/dsh-fnos/entry-url.txt`），打开后浏览器会写入 30 天有效的 HttpOnly cookie，之后就能直接访问端口。每次重启都会生成新 token，旧链接随即失效。

## dsh 版本：永远跟随 npm latest

**装的时候不选版本，装的就是 npm 上标记 `latest` 的最新版。** 装完之后也一直跟：

```
应用启动 → 后台查一次 npm dist-tags.latest
              │
              ├─ 一样      → 什么都不做
              ├─ 有新版    → npm 装新版（约 900 MB）→ 经应用中心重启一次
              └─ 装新版失败 → 自动装回原版本，不会停在半坏状态
```

几条实现上的约束，省得你踩：

- **24 小时内只查一次**（时间戳落 `/var/apps/dsh-fnos/var/last-auto-update`），避免每次重启都去拉 900 MB。
- **升级在后台跑**，不阻塞启动。所以启动瞬间看到的还是旧版，升级完它会自己重启一次。
- **失败必然回退**到升级前的版本，日志在 `/var/apps/dsh-fnos/var/auto-update.log`。

### 想关掉自动升级

应用「设置」里把「自动跟随最新版」关掉即可。关掉后 **dsh 本体就固定在当前版本**，不再自动升级；要换版本只能按下一节手动装。这跟 fpk 层无关——装新版 fpk 照样能升。

### 想试比 latest 更新的预发布

**本包只跟 `latest`，不提供 `next` 切换。** 上游 `latest` 滞后于 `next` 是常态，但把「跟哪个」做成选项，就又回到每次都要人做决定的老路上——和这个包的设计目标相反。

真要用 `next`：先关掉「自动跟随最新版」（否则下次启动会被拉回 latest），然后以 root 装并**把属主改回来**：

```bash
sudo env PATH=/var/apps/nodejs_v24/target/bin:/usr/local/bin:/usr/bin:/bin \
  HOME=/vol1/@appshare/dsh-fnos \
  NPM_CONFIG_PREFIX=/vol1/@appshare/dsh-fnos/.npm-global \
  NPM_CONFIG_CACHE=/vol1/@appshare/dsh-fnos/.npm-cache \
  npm install -g @deepseek-ai/dsh@next --registry https://registry.npmmirror.com

# 必须做，否则 dsh 以应用身份跑起来读不到 root 装的包，应用起不来
sudo chown -R dsh-fnos:dsh-fnos /vol1/@appshare/dsh-fnos/.npm-global
```

最后在应用中心重启一次。`.installed-version` 会由下次安装或升级时刷新。

## 两层升级，别搅混

这个包有两层东西可以升级，来源不同：

| 层 | 里面是什么 | 怎么升级 |
|---|---|---|
| **fpk 层** | manifest、`cmd/` 脚本、向导、网关适配层 | CI 每 6 小时跟随上游出包；装新版 fpk 覆盖 |
| **dsh 本体层** | `@deepseek-ai/dsh`，约 900 MB | 应用内自动跟随 latest，**不用重装 fpk** |

dsh 本体升级完全走不到重装流程；只有适配层脚本本身变了才需要装新 fpk。

## 为什么不把运行时打进包

`@deepseek-ai/dsh` 装完约 **900 MB / 200 个顶层依赖 / 330 个 `@deepseek-ai` 子包**。塞进 fpk 会让包变成几百兆，而且每次上游发版都要重传。

所以这个包走另一条路：

```
fpk 本体 ≈ 45 KB        只有 manifest、cmd 脚本、wizard、图标
       ↓ 安装时
复用系统 nodejs_v24     Node v24，不打 Node
       ↓ npm install -g
dsh 落到 @appshare/dsh-fnos/.npm-global     约 900 MB
```

代价是安装要联网、要等几分钟；换来的是包小、CI 秒出、升级只换脚本或只换 npm 包。

## 自动跟随上游（CI 层）

`.github/workflows/build.yml` 每 6 小时查一次 `npm view @deepseek-ai/dsh version`：

```
上游版本变了  →  重新打包  →  发 Release  →  登记 fnpack.json  →  提交
```

版本号规则：上游 `0.2.2-rc.1` 映射成 fpk 版本 `0.2.2-N`。fnOS 的 version 字段只认数字，所以主版本取上游的数字部分，后面跟打包修订号；同主版本下每次重打修订号加一。

构建期有两道校验，宁可构建失败也不让新旧实现混进包里：

- `build/render_wizard.py` —— 幂等清理向导里遗留的版本下拉，取 npm latest 写入 `VERSION` 作安装兜底
- `build/verify_wizard.py` —— 断言向导里没有版本下拉、有自动跟随开关且默认开启

## 数据在哪

```
/vol1/@appshare/dsh-fnos/            会话、配置、API Key、.npm-global
/vol1/@appshare/dsh-fnos/.installed-version   当前装的 dsh 版本
/var/apps/dsh-fnos/var/info.log      启停日志
/var/apps/dsh-fnos/var/dsh.log       dsh 自己的输出
/var/apps/dsh-fnos/var/auto-update.log  自动升级记录（含回退）
```

升级（不论哪一层）都不动数据目录。卸载默认也保留，除非在应用中心勾了「删除应用数据」。

## 已知限制

- **只打 x86**：上游 npm 包本身跨架构，但系统里的 `nodejs_v24` 是 x86 版；arm 设备需要等对应的运行时应用。
- **安装和升级都要网络**：一次约 900 MB。npm 源填国内镜像快得多。
- **上游 `latest` 滞后于 `next`**：`latest` 是上游标记的稳定发布，不一定是最新提交。本包跟 `latest`，不跟 `next`。
- **自动升级会重启一次**：升级完成的瞬间界面短暂不可用，几十秒后自动恢复。
- **`dsh` 目前全是预发布**：上游还没发正式版，所以跟的也是 rc。

## 许可

打包脚本与配置：MIT。
dsh 本体：MIT（DeepSeek AI）。本仓库不再分发 dsh 代码，只分发打包脚本与元数据。
图标：取自上游品牌素材。
