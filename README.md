# QOJ workbench

Firefox 扩展，提供复用 DOMjudge 9.0.1 的提交页和 Problemset，直接使用 QOJ CLI
准备样例/附件、提交和同步判定；榜单使用原版 RankLand。目标为 VMware 内 Firefox，
CF/Gym 暂不接入。

真实 QOJ 单次训练提交已 AC，经正常核对 UI 关联后同步到原版 RankLand，关页重开仍
保留进度。C 题样例/PDF、长春赛前准备入口及 I 题附件原字节核验已通过。资源浏览器
与官方 9.0.1 当前源码参考回归已通过；发布包和交付清单见 `dist/` 与
`artifacts/release-final.json`。Home 的 Contest 信息区是功能适配，不能声称整页 1:1。
当前准确状态见 [ACTIVE_WORK](docs/ACTIVE_WORK.md) 与 [验收记录](docs/MVP_RESULT.md)。

## 安装

在 Firefox 所在的 Linux 系统安装按需 Python 助手：

```sh
git submodule update --init
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python scripts/install_native.py
python3 scripts/package_extension.py
```

源码压缩包已包含固定子模块内容，可跳过第一条命令。

开发时打开 `about:debugging#/runtime/this-firefox`，临时载入
`extension/manifest.json`。当前 XPI 未签名；Firefox 重启后需重新载入临时扩展。
当前 XPI 与 wheel 已打包核验；共享目录/VM 的最终复制状态见验收记录。

QOJ 登录与安全验证在同一个 Firefox 的原站页面完成。助手按任务启动并退出，无需
手动常驻服务，不导入 Cookie、不保存密码，也不改系统原有 `submit`。状态默认保存于
`~/.local/share/qoj-vp/`，与隔离 QA 目录分开。

## 使用

通过 **New contest** 读取 QOJ 比赛与账号，保存练习及可选 RankLand 链接。
工作台 **Start** 仅开始本地计时，不创建 QOJ 官方 VP。

在 Home 选择“准备资源”，或在支持的 QOJ 原生 Start 表单旁点击“准备题目文件”。
已有缓存默认复用，明确刷新才重新读取；准备不会触发原站 Start。Problemset 只为已
确认缓存显示 samples 或附件；未知状态在准备弹窗中重试，不用一次 404 判断不存在。
下载仅读取本地缓存并校验分块与整包 SHA，不再跳转猜测附件地址。

选择源文件后核对题号、语言和账号，再确认提交。结果未知时先核对原站记录，不
自动重发源码。源码限 512 KiB；资源整包限 64 MiB，按最多 256 KiB 分块读取。
Home 默认只显示本次时间窗内提交与本地操作；完整历史保留在账本和“原站记录”。
越窗本地操作仍可核对，时间显示“—”，绝对时间保留在提示中。

**Scoreboard** 打开已保存的同一 RankLand 会话，通过原站控件同步判定，不直接写
其 localStorage 或 Vue 私有状态。同一场榜单只保留一个可写页面；重判和歧义需要核对。
旧原生 VP 的相对时间只在详情页能核实带时区的绝对提交时间时回填；无法核实的记录
不进入本次进度/榜单，不猜 VP 起点或自动关联未知提交。

题面有原始 PDF 时打开原件；HTML 使用隔离题面与 Firefox 保存 PDF。整个工作台
完全离线初始化尚未实现；已验证的是保留在线加载的比赛上下文后离线读取清单/文件。

## 验证与文档

- [验收记录与限制](docs/MVP_RESULT.md)
- [接口契约](docs/MVP_CONTRACT.md)与[Python 状态/接口](qojvp/README.md)
- [DOMjudge 来源与许可证](docs/UI_UPSTREAM.md)
- [QOJ 赛前入口与资源边界](docs/research/2026-11-01/qoj-preparation-entry.md)
- [资源缓存实现与真实附件证据](docs/research/2026-11-01/resources-preparation.md)

Python 完整 63 项、Node 运行器报告的 28 项测试已通过。官方 9.0.1 实际渲染快照
在同一 Firefox 中的提交组件样式、字段和交互比较通过；Home 已单独采集，未认证为
整页一致，整页像素完全相等也未评估。真实首次提交经显式核对恢复，丢回执根因仍未知。
最终证据、产物哈希及交付状态以验收记录为准。
