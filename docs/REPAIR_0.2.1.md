# 0.2.1 修复与验证记录

更新：2026-11-01（Asia/Shanghai）。**0.2.1 已通过本地与 VM 回归，生产源码、按需助手及常用 Firefox 界面均已更新**。
源码包以其中的 `SOURCE_COMMIT` 和 `SOURCE_MANIFEST.json` 标识提交；CI 状态以对应提交的 Actions run 为准。本页只记录产品改动与验证，不包含虚拟机编辑器或共享目录的环境修复。

## 行为变化

Problemset 和资源准备弹窗分别显示 **samples** 与 **附件**。有哪一类已确认资源，就提供哪一个按钮；
两类同时存在时提供两个独立 ZIP。samples 包只包含完整的输入/输出配对，附件包保留原始目录与工具文件。
如果原始附件本身包含工具依赖的输入/输出文件，这些文件仍保留在附件中，不擅自删除。

原 schema 1 合并缓存可在本地离线迁移为两个下载项，无需重新访问 QOJ。迁移先验证原包和成员的
路径、大小与哈希，再原子发布下载清单；旧顶层资源 ID 保留兼容。刷新失败时保留已验证的旧包，
不把未知或一次 404 显示为“确定没有”。固定的 qoj-submitter 子模块提交未改变。
接口细节与真实长春附件证据见[资源准备记录](research/2026-11-01/resources-preparation.md)。

**New contest** 从 Home 操作区移到奖杯比赛菜单底部，使用分隔线与切换比赛项区分；点击后先关闭菜单，
再打开现有建赛对话框。无比赛时的欢迎入口保留。官方 DOMjudge 9.0.1 的管理员从 Jury → Contests
页面的 Add new contest 创建比赛；本扩展的菜单位置是按用户需求作的适配，不是官方菜单的逐字复刻。
按钮与菜单继续使用已固定的上游资产，不声明 Home 整页像素一致。

QOJ 同时展示赛时结果与赛后结果时，以当前结果为准：`AC, TL` 映射 TIMELIMIT，`AC, WA`
映射 WRONG-ANSWER，`AC, Pending` 保持 JUDGING。详情页早期 Accepted 后出现
`Extra Test Failed : Time Limit Exceeded on 4` 时，不再误判为 AC；未知失败保持 UNKNOWN。
列表原始结果保存在 `historyResult`，`verdictSource` 标明最终结果来自列表或详情。
真实页面结构与回归见[赛后判定记录](research/2026-11-01/qoj-postcontest-results.md)。

重判更新原提交事实和原队列项。尚未投递的结果可采用新判定；**已经同步到 RankLand 的 AC 不会被自动删除或改写**，
旧回执保留，队列标记 rejudge / needs-review，需要人工核对。重复刷新不会追加一条假提交。

## 验证状态

| 检查 | 当前结果 | 证据或边界 |
| --- | --- | --- |
| 本地 Python 全套 | 86 项通过 | `artifacts/resume-2026-11-01/python-tests.txt` |
| 本地 Node 全套 | 64 项通过 | `artifacts/resume-2026-11-01/node-tests.txt` |
| 视觉测试交互断言 | 已修正并离线核验 | 要求 extension/reference × generic/per-problem 原四条，以及 new-contest-setup 一条，五条唯一、完整且全部成功；15 种缺失、失败或重复扰动均被拒绝。`artifacts/resume-2026-11-01/visual-harness-check.json` |
| 恢复后的 VM 视觉回归 | run `1f226038d30b44a4ada273f7b7281236`：28 项及 5 项 cleanup 通过 | `artifacts/resume-diagnostics/resume-visual-summary.json`；computed styles、可见字段与五条弹窗交互条件均通过，不等于整页像素认证 |
| 当前候选的 VM 资源回归 | run `cc6114f3e6de4bb2ac9515ace5aa750c`：15 项及 4 项 cleanup 通过 | `artifacts/resume-diagnostics/resume-resource-summary.json`；使用真实 UI 与隔离 QOJ fixture，包含双下载及旧缓存离线迁移 |
| 当前候选的 VM 回执回归 | run `a24994c0eea2402681d993056b7dff3d`：8 项及 3 项 cleanup 通过 | `artifacts/resume-diagnostics/resume-receipt-summary.json`；仅向本地 fixture 发送三次无源码的合成 POST，验证 302、503、缺失 Location 与诊断恢复，不向真实 QOJ 提交 |
| VM 回归总入口 | visual、resources、receipts 全部通过 | `artifacts/resume-diagnostics/resume-vm-summary.json` |
| 生产源码与按需助手更新 | 20 个扩展文件、9 个 Python 模块校验通过；native hello 为 0.2.1，助手已退出 | `artifacts/resume-diagnostics/candidate-deployed.json`；保护会话账本未变、真实源码 POST 增量为 0；保留更新前源码备份 |
| 常用 Firefox 界面加载 | 已重新临时加载已校验的生产 extension/manifest.json | `artifacts/resume-diagnostics/resume-menu.png` 显示菜单建赛入口；`resume-problemset-split.png` 显示真实长春 I 的 samples 与附件双按钮；原西安会话仍显示唯一的 #3331061 和缓存排名 |
| 构建与 GitHub CI | XPI 与标准隔离 wheel 构建通过；GitHub 自动测试和产物按提交记录 | `artifacts/resume-diagnostics/wheel-build.log`；签名状态仍为 unsigned，旧 0.2.0 CI 不能代替本版本运行 |

本地可重复执行：

```sh
PYTHONPATH=preflight/vendor_py python3 -m unittest discover -s tests -v
node --test preflight/test_*.cjs tests/test_*.cjs
```

`preflight/vendor_py` 是当前工作区已有依赖目录；GitHub CI 安装项目依赖后直接执行 unittest。

## 保留限制

- XPI 仍未签名；当前安装方式为 Firefox 临时加载，重启后需重载。AMO unlisted 签名与专用
  Hydro runner 尚未配置，没有调整浏览器全局签名检查；见 [CI.md](CI.md)。
- RankLand 已投递记录的重判仍需要人工核对；未实现自动撤回或改写原站记录。
- 首次真实提交丢回执的根因仍未知，本轮隔离回执测试不能替代再次真实提交的端到端证明。
- 0.2.0 的 RankLand 关页恢复、真实样例下载与部署证据保留在 [FOLLOWUP_RESULT.md](FOLLOWUP_RESULT.md)，
  此处不把它们描述为当前版本已重新完成的验证。
