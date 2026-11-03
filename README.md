# QOJ workbench

Firefox 扩展，提供复用 DOMjudge 9.0.1 的提交页和 Problemset，直接使用 QOJ CLI
准备样例/附件、提交和同步判定；榜单自动匹配原版 RankLand，未匹配时使用 QOJ 原榜。目标为 VMware 内 Firefox，
CF/Gym 暂不接入。

当前版本为 0.3.5：在 QOJ 的 VP 确认页准备比赛文件，点击原站 **Start!** 后工作台自动开始，
按 QOJ 的服务器时间恢复计时。操作和验证见 [原生 VP 联动](docs/QOJ_NATIVE_VP_0.3.5.md)。
选手页一键同步原版 RankLand、延迟判定及赛后补判见 [同步修复记录](docs/RANKLAND_SYNC_0.3.4.md)。
Firefox CD 已配置 AMO unlisted 签名并发布到 GitHub Release，详见 [发布与安装](docs/CI.md)。
0.3.2 已修复刷新空白与加载动效，使用浏览器显示缓存先恢复页面，助手核验后启用提交。
验证记录见 [0.3.2 启动修复](docs/STARTUP_0.3.2.md)；上一轮见 [0.3.1 修复记录](docs/FOLLOWUP_0.3.1.md)。

0.3.0 新增独立的 Jury 比赛管理页，选手 Home 保留进度与提交；
管理员可配置、结束、归档和删除本地比赛，以及上传或粘贴手动样例。
修复西安 2022 七题中文样例标题的识别；真实 VM 中 12 题缓存与文件校验均通过。
该版本还包含样例/附件分开下载及 QOJ 赛后重判修正。Python 105 项、Node 84 项及
VM 四套回归通过。该版本的回归与部署记录见
[0.3.0 验收记录](docs/ADMIN_0.3.0.md)。

此前已交付的 0.2.0 回填 RankLand 名次/得分/罚时，恢复官方奖杯比赛菜单，statement 直接打开
QOJ 原题面。该版本的 VM Firefox 视觉回归通过；当时真实工作台显示原榜单的 470 / 1 / 77。
西安 A 的真实 samples 下载、关闭榜单后的缓存和重开恢复均已验证；功能提交
`d5817bb` 的 GitHub CI 已通过 69 项 Python、62 项 Node 测试。
仓库：[LittleDrinks/qoj-vp](https://github.com/LittleDrinks/qoj-vp)。
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

Firefox 要求 140+。正常安装从 [GitHub Releases](https://github.com/LittleDrinks/qoj-vp/releases)
下载带 `-signed.xpi` 的包，在 `about:addons` → 齿轮 → 从文件安装附加组件。
上面的 Python 助手仍需安装；升级下载同版本完整源码，重新运行助手安装，再覆盖安装 XPI。
保持扩展 ID 和原数据目录不变，不需要先卸载或删除比赛。

开发时打开 `about:debugging#/runtime/this-firefox`，临时载入 `extension/manifest.json`。
未签名开发包文件名带 `-unsigned`，临时安装在 Firefox 重启后结束。
本仓库已配置签名；自行 fork 时的一次性配置步骤见 [安装与签名说明](docs/CI.md#一次性配置-mozilla-签名)。

QOJ 登录与安全验证在同一个 Firefox 的原站页面完成。助手按任务启动并退出，无需
手动常驻服务，不导入 Cookie、不保存密码，也不改系统原有 `submit`。状态默认保存于
`~/.local/share/qoj-vp/`，与隔离 QA 目录分开。

## 使用

在 QOJ 比赛点击 VP，进入 `/contest/<cid>/virtual/register` 确认页。
**准备比赛文件并打开工作台** 会自动绑定当前账号和比赛，调用已安装的按需助手准备样例/附件。
准备不会启动计时。回到该确认页点击原站 **Start!**，QOJ 确认成功后工作台自动进入 Home 并开始计时。
也可以直接点击原站 Start，插件会利用该确认页保存的规则创建对应比赛；资源可之后在 Jury 准备。
页面请求延迟或临时失败时保留开始意图，恢复后采用 QOJ 的原始起点，不从重试时刻重新开始。

导航栏 **Jury → Contests → Add new contest** 用于读取 QOJ 比赛与当前账号、保存练习。
点击管理列表中的比赛可修改准备阶段的名称、时长和 RankLand 链接，以及管理题目资源。
**Team** 返回选手界面；奖杯菜单只切换已有比赛。管理与选手页面共用本地扩展，
这是操作界面的分离，不是多用户权限系统。

从 Jury 手工新建的比赛仍可用 **Start now** 仅开始本地计时；已绑定原生 VP 的比赛显示
**前往 QOJ 开始**，避免同时启动两个时钟。**Finish now** 截止本次
本地练习；结束、归档或未开始的比赛可确认删除。删除只移除本地比赛记录与其同步队列，
不删除 QOJ / RankLand 原站记录，也保留同账号同比赛共享的题目资源。
仍有未确认源码提交时会拒绝删除，先从选手 Home 核对原站提交。

在比赛管理的“题目资源与样例”中准备文件，或使用 QOJ VP 确认页的准备入口。
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

**Scoreboard** 打开已保存的同一 RankLand 会话。选手 Submissions 的 **同步到 RankLand**
会先读取最新 QOJ 判定；Firefox 开着时，待判自动补齐，比赛结束后仍继续结算。
计分使用核实的 QOJ 接收时间；同题较早待判会暂缓后续结果，其他题正常同步。
适配器在原回放页面退出后受控更新其存档，再由原版页面重算；有记录变化时榜单会短暂重载。
重复同步不重复计数，已导入的重判结果可替换或撤回，原站手工记录保留。
同一场榜单只保留一个可写页面；手工冲突或上游格式变化会停止导入并保留记录以便核对。
工作台可见时每 10 秒从唯一匹配的原站页面只读获取本队名次、得分和罚时。页面未打开
或未就绪时显示上次快照及其更新时间；从未取得的数据保持“—”，不自行推算排名。
旧原生 VP 的相对时间只在详情页能核实带时区的绝对提交时间时回填；无法核实的记录
不进入本次进度/榜单，不猜 VP 起点或自动关联未知提交。

Problemset 的 **statement** 在新标签打开对应 QOJ 原题面，不再自动生成 PDF。
已保存比赛可在重新打开页面时从本地恢复题表、提交历史和缓存资源。
首次读取比赛、获取最新判定及访问原站榜单仍需网络。

## 验证与文档

- [本轮状态](docs/ACTIVE_WORK.md)、[0.3.1 修复记录](docs/FOLLOWUP_0.3.1.md)、[0.3.0 验收记录](docs/ADMIN_0.3.0.md)、[0.2.1 本地修复记录](docs/REPAIR_0.2.1.md)、[0.2.0 历史修复记录](docs/FOLLOWUP_RESULT.md)与[0.1.0 历史验收](docs/MVP_RESULT.md)
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
