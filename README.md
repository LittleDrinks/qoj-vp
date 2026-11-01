# QOJ workbench

Firefox 扩展，提供复用 DOMjudge 9.0.1 的提交页和 Problemset，直接使用 QOJ CLI
准备样例/附件、提交和同步判定；榜单使用原版 RankLand。目标为 VMware 内 Firefox，
CF/Gym 暂不接入。

当前为 0.2.0 后续修复阶段：回填 RankLand 名次/得分/罚时，恢复官方样式的比赛菜单，
statement 改为直接打开 QOJ 原题面。虚拟机回归、部署和首次 GitHub Actions 运行正在
完成；不能用 0.1.0 的测试数量或包哈希代替这一版的验证结果。
私有仓库：[LittleDrinks/qoj-vp](https://github.com/LittleDrinks/qoj-vp)。
当前状态见 [ACTIVE_WORK](docs/ACTIVE_WORK.md)，此前实测见 [0.1.0 验收记录](docs/MVP_RESULT.md)。

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
重载同一扩展后可重新打开工作台，助手保存的比赛账本仍保留。长期安装计划使用 AMO
unlisted 签名，目前尚未配置签名凭据；CI 产物仍为未签名 XPI，不修改浏览器全局签名设置。
详见 [安装与签名说明](docs/CI.md#长期安装与签名)。

QOJ 登录与安全验证在同一个 Firefox 的原站页面完成。助手按任务启动并退出，无需
手动常驻服务，不导入 Cookie、不保存密码，也不改系统原有 `submit`。状态默认保存于
`~/.local/share/qoj-vp/`，与隔离 QA 目录分开。

## 使用

通过 Home 的 **New contest** 读取 QOJ 比赛与账号，保存练习及可选 RankLand 链接。
导航栏使用 DOMjudge 9.0.1 的奖杯下拉菜单切换已保存的比赛。
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
工作台可见时每 10 秒从唯一匹配的原站页面只读获取本队名次、得分和罚时。页面未打开
或未就绪时显示上次快照及其更新时间；从未取得的数据保持“—”，不自行推算排名。
旧原生 VP 的相对时间只在详情页能核实带时区的绝对提交时间时回填；无法核实的记录
不进入本次进度/榜单，不猜 VP 起点或自动关联未知提交。

Problemset 的 **statement** 在新标签打开对应 QOJ 原题面，不再自动生成 PDF。
整个工作台完全离线初始化尚未实现；此前验证的是保留在线加载的比赛上下文后离线
读取清单/文件。

## 验证与文档

- [本轮状态](docs/ACTIVE_WORK.md)与[此前验收记录](docs/MVP_RESULT.md)
- [GitHub CI、产物与 Hydro 专机方案](docs/CI.md)
- [接口契约](docs/MVP_CONTRACT.md)与[Python 状态/接口](qojvp/README.md)
- [DOMjudge 来源与许可证](docs/UI_UPSTREAM.md)
- [QOJ 赛前入口与资源边界](docs/research/2026-11-01/qoj-preparation-entry.md)
- [资源缓存实现与真实附件证据](docs/research/2026-11-01/resources-preparation.md)

GitHub 托管 CI 运行 Python/Node 回归并打包；Hydro Firefox 工作流需另行注册专用
runner 后手动启用，专机尚未部署。Home 的 Contest 信息区保留功能适配，不声明整页
与官方 1:1。此前唯一真实提交经显式核对恢复，首次丢回执根因仍未知，不重复发送源码。
