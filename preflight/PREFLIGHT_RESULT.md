# VMware Firefox 前置实测结果 — 2026-10-31

必要检查 22 项全部通过。完成时间：2026-10-31T11:13:53.923706+00:00。

- 固定实际 QojClient / samples 库经 Firefox 原站内容脚本读取受控题表、表单与每题 samples，A/B 两类附件均通过。
- Native Messaging 任务往返、任务进程退出、本机 SQLite 会话关页及跨 Firefox 新 PID 恢复通过。
- 原版 RankLand 真实公网模式：两小时起点、独立 run、原站表单记录合成 AC、本队行、去重、关闭标签页与 Firefox 重启恢复通过。
- 合成 PDF 原件读取与 HTML WebDriver 打印通过；不能替代生产扩展 saveAsPDF 交互或真实 QOJ 题面排版验收。
- 来宾 Firefox、临时 HTTP server 和自有 native manifest 均清理，保留持久测试数据。

真实 QOJ 独立观察：未认证的隔离 headless Firefox GET 返回 HTTP 403。没有真实 QOJ 源码 POST，没有证明真实账户提交/判定已经通过。

修复依据见 BRIDGE_FIX.md：临时上传安装与持久 path 安装的差异，以及 Firefox Xray 下 Headers iterator / TypedArray spread 的内容脚本兼容问题。最终单次诊断完整返回 200 / 649 bytes / stage=done 后，才跑本次完整回归。

证据：../artifacts/vm-preflight/round4/summary.json。历史失败及最小差分保留在 artifacts/vm-preflight 的 round1/2/3 与 bridge-diag-* 子目录。

生产 MVP UI、POST 回执、自动同步等是后续独立验收项，不由本结果替代。
