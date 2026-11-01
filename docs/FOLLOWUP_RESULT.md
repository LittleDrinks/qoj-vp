# 0.2.0 后续修复记录

更新：2026-11-01（Asia/Shanghai）。目标仍为 Hydro Contest OS VMware 中的 Firefox ESR。
本轮处理真实使用反馈：Home 的排名/罚时缺失、右上角比赛控件与原版不同、statement
等待不结束、重启后的临时扩展消失，以及普通样例准备的语言回退。

主要改动已完成 VM 与自动化验证并推送 GitHub。本文只记录 0.2.0；
[MVP_RESULT.md](MVP_RESULT.md) 中的 0.1.0 测试计数、包哈希、PDF 验收均为历史证据。
CF/Gym、自制完整榜单、整页离线初始化不在本轮完成范围。

## 当前行为

- Home 从原版 RankLand 的本队行读取主排名、得分和罚时；工作台可见时每 10 秒刷新。
  原站暂不可读时保留同一比赛/run 的缓存与原观察时间，未知字段保持“—”。
  改榜单设置或切换会话后不复用另一身份的快照；延迟返回也不能覆盖新会话。
- 右上角复用 DOMjudge 9.0.1 的奖杯下拉菜单，New contest 移到 Home，空状态入口仍保留。
  下拉支持普通点击、Escape、方向键与 Enter；完整比赛名保留在提示和可访问名称中。
- statement 是新标签中的普通 QOJ 原题面链接。自动 PDF 导出及其等待链路已移除；
  保留上游 `file-pdf` 图标以维持原控件外观，链接的题面可以是 HTML。
- 样例准备优先使用已确认的附件；普通题缺少样例时，最多跟随三个同题公开语言链接。
  不猜 URL，不把 404 视为“确定没有”，不把交互记录打包成普通样例。
- Python 助手继续按需运行；未新增真实 QOJ 源码提交或官方 VP。已有 submission
  `3331061` 只作为判定和榜单读取证据，不重发代码。

## 本轮已验证

| 验证 | 结果与边界 | 证据 |
| --- | --- | --- |
| GitHub 首次 CI | `c265ddbd1cca739f0f699c5a795a2bf5917220f0`：69 项 Python、62 项 Node 通过；不覆盖之后的未推送修改 | [run 41261493139](https://github.com/LittleDrinks/qoj-vp/actions/runs/41261493139) |
| CI 产物独立读回 | 三包校验通过；源码清单 289 文件、XPI 20 文件、固定子模块与提交一致，未夹带本地状态 | `artifacts/ci-validation/github-c265ddb/artifact-readback.json` |
| VMware 官方样式回归 | run `846e8c204cf94d6abb0b755b22786280`：28 项及 5 项 cleanup 通过；包含真实 Bootstrap 下拉键盘操作 | `artifacts/followup/followup-visual-summary.json` |
| 控件样式 | 20 组控件 computed styles 相等；参考为官方 9.0.1 服务导出的 HTML/资产回放，不是整页像素 1:1 认证 | 同一视觉 run；参考 `preflight/visual-reference/rendered/` |
| 已登录工作台原站数据回填 | RPC 和工作台状态均为 live，名次 470、得分 1、罚时 77；数字属于该次观察，不保证后续名次不变 | `artifacts/followup/final-live.json` |
| 西安 A / 5113 真实 UI 下载 | 正常点击 samples 后落盘 `/home/csj/samples-A.zip`，282 B；整包及输入 65 B、输出 20 B 的 SHA 均与真实题面匹配，`matchesRealStatement=true` | `artifacts/followup/file-readback.json`、`followup-a-download.png`、`followup-problemset.png`；[题面样例研究](research/2026-11-01/qoj-statement-samples.md) |
| VM 扩展文件读回 | 来宾 20 个生产扩展文件与工作区逐文件哈希一致；已退役 PDF 两文件不存在 | `artifacts/followup/file-readback.json` |
| 既有真实提交未重发 | operationCount 仍为 1，原 operation `f6a64310-8b40-4643-b486-89db1fbde3f9` 为 confirmed；队列 `3331061` 为 synced | 同一 `file-readback.json` 的 `protectedSession` |
| 临时扩展恢复 | 本轮已在用户 VM 中重新加载工作台；原比赛账本仍保留 | 当前 VM 工作台；安装方式仍是临时安装 |

上述 A 题实际下载 ZIP 的 SHA-256 与缓存相同，为
`c2a2a7b941dc1aa3382d0a7d7b072c1009e183eef8d0fccfe59a37a48c314fa3`。
输入与输出的独立 SHA、真实页面结构及语言回退边界记录在题面样例研究中。
`live-results.json` 中较早的榜单读取为 unavailable；后续 RPC 与 UI 双重 live
回填证据以 `final-live.json` 为准。

## 追加验证与发布识别

功能修正提交 `d5817bbf6f8cdff827a372bd952a021b616ccf63` 的
[CI run 41264182943](https://github.com/LittleDrinks/qoj-vp/actions/runs/41264182943)
已通过 69 项 Python、62 项 Node 测试。此后文档提交的包和 CI 结果以对应 Actions run
的 commit 为准；源码包包含 `SOURCE_COMMIT` 和逐文件 `SOURCE_MANIFEST.json`。
XPI/wheel/源码三包的 `SHA256SUMS` 使用相对文件名，可在解压后的 artifact 根目录检查。
交付包存放在 `E:\shared\qoj-vp-mvp-release\0.2.0`，该目录的交付清单固定实际提交和包哈希。

本轮独立原站 RankLand run `03bf13e9d5f240529d235476fb3cbb04` 的 7 项与 4 项
cleanup 全部通过，包含真实 DOM 与生产快照严格对照、关页恢复和判定去重。
之前 run `e650309d092b49f698724bea81d9e16a` 失败在 QA 错误地等待原站永久暂停：
带已到期 `at` 参数的原站定时器会恢复播放。修正测试为 DOM 前后读数夹住生产读取，
只在前后指标相同时严格比较；不暂停或改写原站，不跳过断言。
完整证据归档在 `artifacts/followup/regression/`，汇总在
`artifacts/followup/followup-rankland-summary.json`；失败原件为 `rankland-red.json`。

真实用户会话也已正常关页重开：`closed-cache.json` 记录 RPC/UI 为 cached、原因
`TAB_CLOSED`，保留 470 / 1 / 77 和原 `observedAt`；`followup-closed-cache.png`
显示“上次同步于”。正常点击打开榜单后，`reopened-live.json` 的 RPC/UI 均恢复 live，
完整 URL、存档 key、队名和 manual 数组不变，仍只有 C 的一条 AC。上述文件均在
`artifacts/followup/`。statement 正常点击后直接打开中文 A 题，见同目录
`followup-statement-link.png`。

来宾 20 个生产扩展文件已逐文件读回，与已测试源码一致，退休 PDF 文件已删除。
最终包的来源提交和校验结果记录于交付清单；不把早期 `c265ddb` 三包冒充最终版本。

## 安装与 CI 限制

私有仓库为 [LittleDrinks/qoj-vp](https://github.com/LittleDrinks/qoj-vp)。自动测试、打包和
Hydro 手动工作流已配置；可选线上 RankLand 检查也已接入。专用 Hydro VM runner
尚未注册，不能宣称专机已上线；日常比赛 VM 没有被注册为 CI runner。

XPI 仍未获得 AMO 签名，当前通过 `about:debugging` 临时加载，因此 Firefox 重启后
仍需重新载入。重装入口不等于持久安装修复。没有更改 Firefox 签名检查偏好，也未上传
AMO 或配置签名凭据；长期安装采用 unlisted 签名的计划和要求见 [CI.md](CI.md)。

Home 的 Contest 操作区仍属于功能适配，不声明整页与官方 1:1。旧真实提交首次丢回执
的根因仍未证实，本轮没有重新发送源码来掩盖这一限制。
