# 当前工作状态

更新：2026-11-01（Asia/Shanghai）。本阶段实现和验收已完成：VMware Firefox 中的 QOJ
提交、题目资源、原版 RankLand 联动和 DOMjudge 9.0.1 参考回归。CF/Gym 不接入。
以下是当前状态；历史失败与旧 checkpoint 留在各自 artifacts 中，不作为当前结论。

## 已验证

- Python 完整测试 63 项通过：`artifacts/backend-final-tests.txt`。六个前端脚本由
  Node 测试运行器报告 28 项通过、0 失败：`artifacts/frontend-final-tests.txt`；
  各脚本内部断言计数不另加总为测试数量。
- Home 默认只显示 `inSession===true` 或带 `operationId` 的记录，账本不删历史。
  越窗本地操作时间显示“—”，保留绝对日期和核对入口；prepared 无当前操作时
  保持 No submissions。生产 renderer 五项回归先红后绿，末次真实 GUI 已核对为单条本次 AC，历史账本仍完整保留。
- 资源浏览器验收 run `1dc0a29b66334aaf819e8db48b3ae041`：12 项及 cleanup 全通过，
  证据 `artifacts/resources-browser/accepted/`。真实 UI 准备普通样例、extras-only
  interactor、unknown 资源；浏览器下载 ZIP 并逐字节核对。在线重载/选择后保留 UI
  上下文，再关闭 fixture，清单和缓存下载没有新增 QOJ 请求。整页离线启动未实现。
- 干净当前扩展与官方 DOMjudge 9.0.1 原始渲染快照回放 run
  `1d1e1f01316e4afd8f7681f78c95b6f2`：27 项及 5 项 cleanup 全通过，归档
  `artifacts/visual-parity/current/`。
  computed styles、visible fields、modal interactions 相等；navbar 原始 DOMRect
  仍有约 `1.5e-5 px` 浮点差异，16/20 组控件截图像素完全相同，导航字形仍有差异；整页像素一致未认证。
  基准 `preflight/visual-reference/rendered/` 来自真正 9.0.1 服务。
- Home 专门采集 run `ace102929829499a9875db8840f59b8b`：7 项及 cleanup 通过，
  状态为 `captured-not-parity-certified`。原版 Clarifications 在工作台适配为 Contest
  信息与操作，因此 Home 没有宣称 1:1；截图及独立复核见 `artifacts/home-parity/accepted/`。
- 真实原站 RankLand no-team 验收 run `50d8283d22ca474db464c803154be3e9`：
  6 项及 cleanup 全通过，证据 `artifacts/verified-reference-and-rankland/`。
  这是独立测试 run 的原站兼容证据，不替代下面真实 QOJ 提交的投递验收。
- 真实 QOJ 1051 / C（5115）仅发送过一次源码 POST：submission `3331061` 已 AC，
  源文件 SHA 匹配。首次回执曾为 UNKNOWN，已通过正常核对 UI 明确关联为
  `confirmed / CORRECT`；不得把此结果描述成真实自动回执全链路已重新测试。
- 原生 VP 旧提交可从严格核验的详情页补回绝对提交时间，不猜原生 VP 起点。
  真实 `1511772` 已由生产 refresh 回填 `2025-10-14T21:37:53+08:00`；源码操作仍为
  1 次，当前队列仍仅 `3331061 / synced`：
  `artifacts/live-acceptance/native-time-backfill-proof.json`。
- 回执诊断 run `d48017f4139f4c1aa62e5a32e86d7767` 的 8 项及 cleanup 通过：
  302 有 Location 确认回执，503 / 无 Location 的 302 不确认、不重发；安全诊断可恢复。
  证据 `artifacts/receipt-diagnostics/accepted/`；首次真实丢回执根因仍未证实。
- 上述真实提交的 RankLand outbox 已 `synced`。关闭原榜单 tab 9、重新打开为 tab 10
  后，exact URL/key 不变、C 的 manual AC 恰好一条、计时继续、本队得分 1 / 用时 77：
  `artifacts/live-acceptance/reopen-proof.json`、`real-rankland-sync-ledger.json`。
- PDF 隔离实引擎 5 项及 root URI 审计通过：`artifacts/pdf-isolation/accepted/`。
- 真实 C 题重新导出的 `Clone-Ranran.pdf` 为 165025 B，URI 0 / 敏感 URI 0；中文、
  公式、样例已渲染核对：`artifacts/live-acceptance/real-C-pdf-host-audit.json`、
  `real-C-pdf-text-checks.json`、`real-C-pdf-page1.png`。真实 `samples-C.zip` 为
  289 B，`1.in` / `1.ans` 内容精确匹配，原 H3 样例提取缺口已修复。
- 真实长春 4582 原生 Start 旁准备入口已完成 13/13、unknown 0；会话保持 prepared、
  `startAt=null`，原生表单提交次数 0，原 Start 仍启用。证据
  `artifacts/live-acceptance/live-reopened-and-resources.json`。
- 实际附件核验是 I / 22918：`attachments-I.zip` 4448 B，包含原样例与
  `triplet_testing_tool.py`。另用 GET 取得 3651 B 原包，所有原始成员字节均被缓存包
  保留。审计 `artifacts/live-acceptance/real-resource-artifact-audit.json` 全部 verified；
  不把旧 D / 22913 的网页工具 PDF 线索作为附件通过证据。
- XPI 已生成，22 个扩展文件逐字节等于当前源码；wheel 的 9 个 Python 模块均一致且
  含 LICENSE，标准 isolated build 成功。大小、SHA 见 `artifacts/extension-package-final.json`
  与 `artifacts/wheel-package-final.json`。

## 交付清单

产物位于 `dist/`；共享交付目录为 `E:\shared\qoj-vp-mvp-release`。
完整源码包、文件哈希、部署读回及本地 commit 由 `artifacts/release-final.json` 记录，
以该清单的最终状态为准。

## 当前部署与操作边界

- 当前 XPI SHA-256：`b4b8043403aa06efdd38552deb3b578dd2eaeaba3402f89e7d2150f3b762e0c6`。
  wheel SHA-256：`1772e0874062d8b44b06d9380f68a7adf256cb8f3301c09bf817b48607588001`。
  XPI 未签名，Firefox 临时加载在重启后仍需重新载入。
- 代码与证据：`/home/q2635/wsl-workspace/qoj-vp`。
  来宾项目：`/home/csj/.local/share/qoj-vp-mvp/2026-10-31`。
  来宾真实状态：`/home/csj/.local/share/qoj-vp`；QA 使用独立 host/profile/状态。
  交换目录：`E:\shared\qoj-vp-preflight-stage`。
- 后台操作 VM，不改变 Windows 焦点。不再向真实 QOJ 发送源码 POST，不创建官方
  VP，不点击原生 Start/Finish/register。已有 accepted submission 只允许 GET、核对、同步。
- 原生准备入口仅支持已确认的 `form#form-regvir` 结构，两个新增按钮是表单外的
  `type=button`；未知后续服务端确认页没有推断或实现。
- 来宾临时 QA debug 模块已移除并用 F5 清理上下文；本地四个一次性探针/收集器已删。
  唯一可选 GET timing 探针放在 `preflight/debug/`，不载入产品。
  不把真实 profile、凭据、Cookie、CSRF 值写入报告或发布包。

验收详情见 [MVP_RESULT.md](MVP_RESULT.md)，协议见 [MVP_CONTRACT.md](MVP_CONTRACT.md)。
工作区证据不包含账号凭据；实际最终交付状态以发布清单为准。
