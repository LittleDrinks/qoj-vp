# QOJ VP MVP 验收记录

日期：2026-10-31。实现与所有实测文件保存在本工作目录；目标浏览器为 VMware Hydro Contest OS 内的 Firefox ESR 140.16.0。CF/Gym 未接入。

## 已交付实现

- DOMjudge 9.0.1 团队页结构与原始样式：Home/Submissions、Problemset、绿色 Submit 弹窗与明确确认；题号/语言自动推断可覆盖。
- 固定 qoj-submitter Git submodule，直接使用其 QojClient 和 samples 实现。原系统 submit 不改写。
- Firefox 原站内容脚本执行 HTTP，Native Messaging 按需 Python 助手处理协议/解析与 SQLite 账本；无需手动常驻服务。
- 实际观察 HTTP status/Location 确认提交编号，独立查询历史与详细判定；不把零分直接猜成 WA。
- Problemset 每题题面/PDF/Submit/samples 入口，HTML 可走 Firefox 保存 PDF；不完整样例与特殊附件保留。
- 每个 VP 固定 sessionId、开始锚点、账号和准确 RankLand URL；首次晚开会冻结实际进度，后续不更换存档槽。
- 原版 RankLand 表单同步、独立投递队列与回执；重复页面停止同步，重判或歧义保留待核对，不触发源码重提。

## 已实际验证

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 前置 Firefox/真实库/原站 RankLand 生命周期 | 22 项必要检查通过 | `artifacts/vm-preflight/round4/summary.json` |
| 正常受控提交、账号切换拒绝、并发开榜与重复页保护 | 30 项检查通过 | `artifacts/vm-mvp/safety-round1/summary.json` |
| 503 未知回执、关页不重发、用户显式核对关联，以及榜单/Firefox 重启恢复 | 29 项检查通过 | `artifacts/vm-mvp/unknown-final/summary.json` |
| 实际 Python helper 在 POST 已接收后被终止，恢复后不重复 POST；历史/判定/时钟/队列等 | 15 项集成测试通过 | `artifacts/backend-tests.txt` |
| 普通受控 UI 正常提交与官方 DOMjudge 页面参考 | 28 项必要检查及官方参考通过 | `artifacts/vm-mvp/round2/summary.json` |
| 真实模式助手安装、Firefox 往返和按需退出 | 通过，fixture=false；Firefox/助手均已退出 | `artifacts/installed-smoke/summary.json` |

所有源码 POST 都只发给来宾 loopback 受控评测 fixture，已校验实际 multipart 字段、选中文件 SHA-256 和一次 POST 数量。正常路径读取 webRequest 原始 302/Location；未知回执路径确认的是原始 503/无 Location，随后通过真实 UI 核对已存在的 provider ID，未伪造 302。

RankLand 使用真实公网原站，在独立测试 run 中经其可见控件记录合成 AC；没有直接写原站 localStorage 或 Vue 状态。两小时起点是时间锚点/原站参数初始化，不是声称真实等待两小时。测试覆盖关闭标签页、新 Firefox PID、同 profile 恢复、本队 AC 行、重复投递与同场多页保护。

官方 DOMjudge Team 演示实际登录并截图 Home、Problemset、Submit，未向演示站提交源码。实际版本为 10.0.0DEV/96199cbe3，与固定源码 9.0.1 不同，不能视为同版本像素回归。

## 仍需真实账号验收

真实模式最新 GET 已返回登录提示；此前隔离 profile 曾返回 403。没有导入 QOJ Cookie 或密码，没有向真实 QOJ 提交源码，因此真实登录账号的提交回执、详细判定和真实题面 PDF 排版仍需用户登录后验证。

原始 PDF 的发现、合成 PDF 下载和 Firefox WebDriver HTML 打印已通过；生产扩展的 saveAsPDF API 在目标 Firefox 存在，但 OS 保存对话框和真实题面数学公式/分页尚未做人工验收。

实际源码/内联 samples ZIP 目前各限 512 KiB。临时扩展重启后需重新载入；当前 XPI 未签名，尚未发布到 AMO。CLI 独立提交若只有未经核实的相对时间，不猜测所属 VP 时间，也不自动投递榜单。已同步结果的重判需要核对旧记录。

## VM 中使用

助手已注册到来宾用户 Firefox 的 Native Messaging。真实数据目录为 `/home/csj/.local/share/qoj-vp`，与 QA 状态隔离。

在 VM 普通 Firefox 打开 `about:debugging#/runtime/this-firefox`，临时载入：

```text
/home/csj/.local/share/qoj-vp-mvp/2026-10-31/extension/manifest.json
```

在同一个 Firefox 登录 QOJ，从工作台新建 VP 并选择对应 RankLand 比赛链接。最后的真实账号验收还需要一场允许测试的练习比赛、题号与源码，或用户手动完成一次提交再核对回执和判定。
