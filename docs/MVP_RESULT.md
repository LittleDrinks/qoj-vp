# QOJ MVP 验收记录

> 本文是 **0.1.0 / daddc97** 的历史验收记录。2026-11-01 的 0.2.0 后续修复正在进行：
> statement 已改为普通 QOJ 原题面链接，自动 PDF 导出已移除；榜单增加名次/罚时/得分
> 只读回填，导航改为官方奖杯菜单。下文 PDF 功能、测试数量、包哈希与“当前”描述仅指
> 当时版本，不作为本轮完成证明。最新状态见 [ACTIVE_WORK.md](ACTIVE_WORK.md)，
> CI 与长期签名安装计划见 [CI.md](CI.md)。

更新：2026-11-01。目标环境为 VMware Hydro Contest OS 内的 Firefox ESR。
核心实现、当前源码浏览器回归及真实附件/PDF/提交榜单恢复已通过，XPI/wheel 已生成。
源码包、部署读回与本地 commit 见最终发布清单。CF/Gym 未接入。

## 当前实现

- 复用 DOMjudge 9.0.1 原始样式与团队页骨架：Problemset、提交弹窗、提交历史；
  Home 将原版 Clarifications 区适配为 Contest 信息和操作，不声明整页 1:1。
  文件名/扩展名推断题号和语言，提交前明确核对。
- 直接使用固定 `vendor/qoj-submitter` 子模块的 QojClient 与资源下载/组织函数；
  Firefox 原站会话执行 HTTP，Python Native Messaging 助手按任务运行并退出。
- SQLite 保存会话、提交事实、未知回执和 RankLand 投递状态。未知提交不自动重发；
  原站未核实的相对时间不算作本次练习进度或榜单时间。
- Home 默认表只显示本次时间窗内提交或本地 operation，完整历史仍在账本与原站入口。
  越窗本地操作不隐藏，时间显示“—”并保留绝对日期提示，不显示旧提交的巨大负时。
- 原生 VP 历史的绝对时间可从同一详情表严格匹配 SID、owner、contest/problem 和
  带时区 Submit time 后回填；成功持久复用，失败缓存 60 秒，每次 refresh 至多探测
  3 条并公平轮转。prepared 不探测，显式核对优先指定 SID；不猜 VP 起点、不自动关联 intent。
- 资源准备生成每题缓存清单与 ZIP。题卡只为 ready 缓存显示 samples 或附件，
  404/权限/网络问题保留 unknown；失败不覆盖旧 good 包。分块及整包 SHA 校验后下载。
- QOJ 已观测的原生 Start 表单旁提供独立准备/打开入口；不改写或提交原表单。
  Home 的资源弹窗保留为回退入口。
- Scoreboard 使用原版 RankLand。完整恢复 URL、独立 run、原站表单同步与投递回执
  持久保存；同场多页、重判及歧义保留核对状态。
- 原始 PDF 优先，HTML 使用隔离题面打印与 Firefox 保存 PDF。保存、取消和失败状态
  明确区分，导出仍需检查真实题面的链接和排版。

## 已验证结果

| 验证 | 当前结论 | 证据 |
| --- | --- | --- |
| Python 完整后端测试 | 63 项通过 | `artifacts/backend-final-tests.txt` |
| 六个前端脚本 | Node 运行器报告 28 项通过、0 失败；不另加内部断言数 | `artifacts/frontend-final-tests.txt` |
| 资源真实浏览器 UI、准备、缓存 ZIP 下载、离线文件读取 | run `1dc0a29b66334aaf819e8db48b3ae041`，12 项及 cleanup 全通过 | `artifacts/resources-browser/accepted/` |
| 当前源码与官方 9.0.1 原始渲染快照/资产在同一 VM Firefox 回放 | run `1d1e1f01316e4afd8f7681f78c95b6f2`，27 项及 5 项 cleanup 全通过 | `artifacts/visual-parity/current/`；来源 `preflight/visual-reference/rendered/` |
| Home 专门采集 | run `ace102929829499a9875db8840f59b8b`，7 项及 cleanup 通过；`captured-not-parity-certified` | `artifacts/home-parity/accepted/`；不作为 Home 1:1 证明 |
| 原站 RankLand 无本队时建立队伍、记录及恢复 | run `50d8283d22ca474db464c803154be3e9`，6 项及 cleanup 全通过 | `artifacts/verified-reference-and-rankland/` |
| 真实 QOJ 单次训练提交 | 1051 / C / 5115，submission `3331061` 已 AC，源 SHA 匹配，正常核对 UI 明确关联 `confirmed / CORRECT` | `artifacts/live-acceptance/reconciled-source-ledger.json` |
| 真实判定投递与原站榜单重开 | outbox `synced`；tab 9→10，同 exact URL/key，C 的 manual AC 恰一条，计时继续，本队 score 1 / time 77 | `artifacts/live-acceptance/reopen-proof.json`、`real-rankland-sync-ledger.json`、`live-reopened-and-resources.json` |
| 真实旧原生 VP 时间回填 | `1511772` 经生产 refresh 回填 `2025-10-14T21:37:53+08:00`；源码操作仍 1 次，当前队列仅 `3331061 / synced` | `artifacts/live-acceptance/native-time-backfill-proof.json` |
| 回执诊断与持久恢复 | run `d48017f4139f4c1aa62e5a32e86d7767`，8 项及 cleanup 通过；302 有 Location 确认，503 / 无 Location 的 302 不确认、不重发，安全诊断恢复无重放 | `artifacts/receipt-diagnostics/accepted/` |
| PDF 真实引擎与隔离、取消、失败、歧义拒绝、URI 审计 | 5 项及 root URI 审计通过 | `artifacts/pdf-isolation/accepted/` |
| 真实 C 题样例与 PDF | 样例 ZIP 289 B，1.in/1.ans 精确匹配；PDF 165025 B、URI 0 / 敏感 URI 0，中文/公式/样例已渲染核对 | `artifacts/live-acceptance/real-resource-artifact-audit.json`、`real-C-pdf-host-audit.json`、`real-C-pdf-text-checks.json`、`real-C-pdf-page1.png` |
| 真实长春 4582 赛前准备入口 | 13/13 ready、unknown 0；prepared 会话 startAt null，原表单 0 次提交，原 Start 仍启用 | `artifacts/live-acceptance/live-reopened-and-resources.json` |
| 真实 I / 22918 附件 | 缓存 ZIP 4448 B，保留原样例与 triplet_testing_tool.py；3651 B 独立 GET 原包的每个成员字节均一致 | `artifacts/live-acceptance/real-resource-artifact-audit.json`，全部 verified |

核心提交组件的 DOMjudge computed styles、visible fields 与 modal interactions 均相等。
20 组控件截图中 16 组逐像素相同；导航栏文字/图标仍有差异，原始 DOMRect 宽度
相差约 `1.5e-5 px`。独立结果见 `artifacts/visual-parity/current/pixel-diff.json` 与
`review.md`；整页像素完全一致未认证。参考是实际官方 9.0.1 服务渲染 HTML/资产的离线回放，
不是手写替身，也不是在 VM 中运行的 DOMjudge 后端。早期 10.0.0DEV 演示仅为旧参考。
Home 的 Clarifications→Contest 属于功能适配；七项采集检查证明可见结构/截图已记录，
没有认证 Home 与原版整页一致。

资源验收证明的是：先在线重载/选择比赛、保留真实 UI 上下文，再关闭 fixture，
清单和缓存文件读取无新增 QOJ 请求。**整个工作台完全离线初始化未实现。**

真实 QOJ 仅发生一次上述源码 POST。接收回执最初为 UNKNOWN，后来经用户可见的
正常核对流程关联原站 ID；不能据此声称最新版自动回执又做过一次真实提交测试。
首次真实丢回执的根因仍未证实；隔离诊断验收的通过不等于复现或修复了该次根因。
后续只做 GET、核对与原站榜单同步，不重发源码，不新建官方 VP。

上述六个前端脚本为 `preflight/test_ui_resources.cjs`、
`preflight/test_qoj_prepare_entry.cjs`、`preflight/test_ui_history_notice.cjs`、
`preflight/test_transport_receipts.cjs`、`preflight/test_ui_submissions.cjs`、
`tests/test_qoj_response_limits.cjs`；28 是 Node 运行器的实际汇总，不拼接各脚本内部断言数。
新增五项生产 renderer 回归先复现巨大负时/旧记录混入，再验证当前 AC、unknown 核对、
越窗 own operation、sending/rejected 与 prepared 空表；不修改账本事实或全局时间格式。

真实附件通过证据来自长春 I / 22918，不是旧 D / 22913 的网页工具 PDF 解析。
C 的 H3 标签样例提取缺口已修复，并通过真实下载与新增后端测试核验。

## 构建与交付

| 产物 | 已核验结果 | SHA-256 |
| --- | --- | --- |
| `qoj-vp-firefox-0.1.0.xpi` | 440472 B；22 文件逐字节等于当前扩展源码；未签名 | `b4b8043403aa06efdd38552deb3b578dd2eaeaba3402f89e7d2150f3b762e0c6` |
| `qoj_vp_workbench-0.1.0-py3-none-any.whl` | 35806 B；9 个 Python 模块一致，含 LICENSE | `1772e0874062d8b44b06d9380f68a7adf256cb8f3301c09bf817b48607588001` |

证据为 `artifacts/extension-package-final.json`、`artifacts/wheel-package-final.json`。
普通 isolated wheel build 已成功，日志 `artifacts/wheel-build-final.txt`；构建要求
`setuptools>=77` 与现有 SPDX license / license-files 配置匹配，依据
[Setuptools 官方迁移说明](https://setuptools.pypa.io/en/stable/userguide/license_migration.html)。

来宾临时 QA debug 模块已删除并 F5 清过上下文；本地四个一次性探针/收集器已删除。
唯一保留的可选 GET-only timing 探针位于 `preflight/debug/`，不作为产品脚本载入。

完整源码包、共享目录/VM 部署读回和本地 commit 由 `artifacts/release-final.json`
记录。共享目录为 `E:\shared\qoj-vp-mvp-release`，实际交付状态以该清单为准。

## 使用与限制

在 Firefox 所在系统安装助手，登录使用同一个 Firefox 的 QOJ 原站会话。当前 VM
产品路径为 `/home/csj/.local/share/qoj-vp-mvp/2026-10-31/extension/manifest.json`，
可通过 `about:debugging#/runtime/this-firefox` 临时载入。真实数据与 QA 状态隔离。

源码上限 512 KiB；缓存资源整包上限 64 MiB，每块最多 256 KiB。当前 XPI 未签名，
临时扩展重启后需重新载入。当前产物哈希见上表；不要把较早 release 的哈希当作
本次最终产物，共享目录/VM 的复制仍以最后交付清单为准。
