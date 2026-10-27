# dsh-fnos · DeepSeek Harness 飞牛原生包

把 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（命令行 `dsh`）打包成飞牛 fnOS 能装的应用，由 GitHub Actions 跟随上游 npm 版本自动构建。

## 装法

在飞牛应用中心上传 `dsh-fnos-<版本>-x86.fpk`，或者把本仓库加进集合源后用 FnDepot 安装。

安装向导里可以改三样东西：

| 项 | 默认 | 说明 |
|---|---|---|
| 监听端口 | `3080` | DSH Web 的端口 |
| 监听地址 | 留空 | 留空自动取主网卡 IPv4；dsh 不接受 `0.0.0.0` |
| npm 源 | `registry.npmmirror.com` | 安装时拉 dsh 本体用的源 |

装完访问 `http://设备IP:3080`，首次进入在设置里填 DeepSeek API Key。

## 为什么不把运行时打进包

`@deepseek-ai/dsh` 装完是 **836 MB / 194 个顶层包 / 306 个 `@deepseek-ai` 子包**。塞进 fpk 会让包变成两百多兆，而且每次上游发版都要重传。

所以这个包走另一条路：

```
fpk 本体 ≈ 20 KB        只有 manifest、cmd 脚本、wizard、图标
       ↓ 安装时
复用系统 nodejs_v24     Node v24.22.1，不打 Node
       ↓ npm install -g
dsh 落到 @appshare/dsh-fnos/.npm-global     约 900 MB
```

代价是安装要联网、要等几分钟；换来的是包小、CI 秒出、升级只换脚本。

## 自动跟随上游

`.github/workflows/build.yml` 每 6 小时查一次 `npm view @deepseek-ai/dsh version`：

```
上游版本变了  →  重新打包  →  发 Release  →  登记 fnpack.json  →  提交
```

版本号规则：上游 `0.2.1-rc.2` 映射成 fpk 版本 `0.2.1-1`。fnOS 的 version 字段只认数字，所以主版本取上游的数字部分，后面跟打包修订号；同主版本下每次重打修订号加一。

## 数据在哪

```
/vol1/@appshare/dsh-fnos/            会话、配置、API Key、.npm-global
/var/apps/dsh-fnos/var/info.log      启停日志
/var/apps/dsh-fnos/var/dsh.log       dsh 自己的输出
```

升级不动数据目录。卸载默认也保留，除非在应用中心勾了「删除应用数据」。

## 已知限制

- **只打 x86**：上游 npm 包本身跨架构，但系统里的 `nodejs_v24` 是 x86 版；arm 设备需要等对应的运行时应用。
- **安装需要网络**：装的时候要从 npm 拉 900 MB，没网装不上。
- **`dsh` 目前全是预发布**：上游 npm 的 latest 是 `0.2.1-rc.2`，正式版还没出，所以这个包跟的也是 rc。

## 许可

打包脚本与配置：MIT。
dsh 本体：MIT（DeepSeek AI）。本仓库不再分发 dsh 代码，只分发打包脚本与元数据。
图标：取自上游品牌素材。
