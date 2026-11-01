# QOJ workbench

Firefox 扩展，提供复用 DOMjudge 9.0.1 的提交页和 Problemset，直接使用 QOJ CLI
准备样例/附件、提交和同步判定；榜单使用原版 RankLand。目标为 VMware 内 Firefox，
CF/Gym 暂不接入。

当前版本为 0.3.0：新增独立的 Jury 比赛管理页，选手 Home 保留进度与提交；
管理员可配置、结束、归档和删除本地比赛，以及上传或粘贴手动样例。
修复西安 2022 七题中文样例标题的识别；真实 VM 中 12 题缓存与文件校验均通过。
该版本还包含样例/附件分开下载及 QOJ 赛后重判修正。Python 105 项、Node 84 项及
VM 四套回归通过，常用 Firefox 已更新。回归与部署记录见
[0.3.0 验收记录](docs/ADMIN_0.3.0.md)。

此前已交付的 0.2.0 回填 RankLand 名次/得分/罚时，恢复官方奖杯比赛菜单，statement 直接打开
QOJ 原题面。该版本的 VM Firefox 视觉回归通过；当时真实工作台显示原榜单的 470 / 1 / 77。
西安 A 的真实 samples 下载、关闭榜单后的缓存和重开恢复均已验证；功能提交
`d5817bb` 的 GitHub CI 已通过 69 项 Python、62 项 Node 测试。
私有仓库：[LittleDrinks/qoj-vp](https://github.com/LittleDrinks/qoj-vp)。
该版本证据与限制见 [0.2.0 修复记录](docs/FOLLOWUP_RESULT.md)，当前工作状态见
[ACTIVE_WORK](docs/ACTIVE_WORK.md)；[0.1.0 验收记录](docs/MVP_RESULT.md)仅作历史记录。

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

导航栏 **Jury → Contests → Add new contest** 用于读取 QOJ 比赛与当前账号、保存练习。
点击管理列表中的比赛可修改准备阶段的名称、时长和 RankLand 链接，以及管理题目资源。
**Team** 返回选手界面；奖杯菜单只切换已有比赛。管理与选手页面共用本地扩展，
这是操作界面的分离，不是多用户权限系统。

管理员的 **Start now** 仅开始本地计时，不创建 QOJ 官方 VP。**Finish now** 截止本次
本地练习；结束、归档或未开始的比赛可确认删除。删除只移除本地比赛记录与其同步队列，
不删除 QOJ / RankLand 原站记录，也保留同账号同比赛共享的题目资源。
仍有未确认源码提交时会拒绝删除，先从选手 Home 核对原站提交。

在比赛管理的“题目资源与样例”中准备文件，或使用 QOJ 原生 Start 表单旁的“准备题目文件”。
准备不会触发原站 Start。Problemset 只为已确认缓存显示 samples、附件两个独立入口；
未知状态可在管理员资源弹窗中重试，不用一次 404 判断不存在。
下载仅读取本地缓存并校验分块与整包 SHA，不再跳转猜测附件地址。

管理员可按题“添加样例”：上传一个 ZIP、选择同名的 `.in` 与 `.ans` / `.out` 文件，
或粘贴一组输入输出。已有样例需要勾选替换确认；附件保留不变。手动样例会在后续自动
准备中保留，保存后选手直接在 Problemset 下载。总计限 8 MiB，单个样例文件限 4 MiB。

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

- [本轮状态](docs/ACTIVE_WORK.md)、[0.3.0 验收记录](docs/ADMIN_0.3.0.md)、[0.2.1 本地修复记录](docs/REPAIR_0.2.1.md)、[0.2.0 历史修复记录](docs/FOLLOWUP_RESULT.md)与[0.1.0 历史验收](docs/MVP_RESULT.md)
- [GitHub CI、产物与 Hydro 专机方案](docs/CI.md)
- [接口契约](docs/MVP_CONTRACT.md)与[Python 状态/接口](qojvp/README.md)
- [DOMjudge 来源与许可证](docs/UI_UPSTREAM.md)
- [QOJ 赛前入口与资源边界](docs/research/2026-11-01/qoj-preparation-entry.md)
- [资源缓存实现与真实附件证据](docs/research/2026-11-01/resources-preparation.md)

首次 [GitHub CI](https://github.com/LittleDrinks/qoj-vp/actions/runs/41261493139) 在 `c265ddb`
通过 69 项 Python、62 项 Node 测试并打包；该结果不覆盖此后尚未推送的修改。
Hydro Firefox 工作流需另行注册专用
runner 后手动启用，专机尚未部署。UI 使用官方 9.0.1 控件与模板结构，增加本地比赛管理，
不声明整页像素一致。此前唯一真实提交经显式核对恢复，首次丢回执根因仍未知，不重复发送源码。
