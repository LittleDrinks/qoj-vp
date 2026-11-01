# 0.3.0 管理员页面与手动样例

2026-11-01。0.3.0 本地与 Hydro VM 验证通过，生产源码、按需助手及常用 Firefox 已更新。

## 行为

- 导航栏 Jury 进入 Contests 列表，列表底部 Add new contest 建立本地比赛。点击比赛进入
  设置和资源管理；Team 返回选手界面。Home 只保留本队进度与提交列表。
- 准备阶段可改名称、时长；管理页设置 RankLand、开始/结束本地计时、归档或删除。
  删除需确认；运行中的比赛须先结束，未确认的源码操作须先核对。外站比赛和提交不删除，
  其他本地练习共用的提交事实、缓存资源不误删。
- 管理员按题添加样例：ZIP、同名 .in/.ans/.out 文件，或粘贴一组输入输出。
  文件完整配对、路径和大小校验后才发布缓存。替换需确认，原附件保持字节和下载身份不变。
  手动资源持久保存并优先保留，自动准备不会覆盖。
- 西安 D/E/F/G/I/J/K 的中文 H4 “样例输入／样例输出”被正确识别。新增七题共 11 组
  输入输出逐字节匹配真实题面；常用 VM 全 12 题缓存 ready，分块、整包和成员校验通过。
- 包含此前本地 0.2.1 的样例/附件拆分和赛后 `AC, TL` / Extra Test Failed 判定修正。

## 验证与交付

Python 全套 105 项通过，Node 全套 84 项通过（资源脚本内部断言不另加总）。
日志：`artifacts/resume-2026-11-01/python-admin-full.txt`、`artifacts/admin-0.3.0/node-tests.txt`。

| VM 回归 | Run | 检查 / 清理 | 结果 |
| --- | --- | --- | --- |
| 官方 DOMjudge 控件及提交交互 | `8549966dfa414f6dbdf316a3eb33fd50` | 28 / 5 | 全部通过 |
| 样例、附件与缓存下载 | `39e05c6cedc04689b336fff498eb65dc` | 15 / 4 | 全部通过 |
| 管理员建赛、配置、样例、结束、删除 | `ce01e81ced2e4f49a4628bbc29857540` | 15 / 4 | 全部通过 |
| 实际 Firefox 回执诊断 | `bdfb7fdf31074575a97aa0a2ae470bc5` | 8 / 3 | 全部通过 |

浏览器为 Hydro VM 的 Firefox ESR 140.16.0，geckodriver 0.37.1。测试使用独立账号形状
fixture、profile、native host 和账本；没有真实 QOJ 源码 POST 或官方 VP Start。
管理流程通过真实控件创建与修改比赛，粘贴样例、多文件上传和 ZIP 确认替换，逐字节验证
选手下载，保留原交互器，结束/删除测试比赛后重载验证没有复活。源码提交相关 302
来源绑定保持严格；503 直接响应以实际返回状态验收，不依赖旁路事件先于 Fetch 到达。
汇总及截图：`artifacts/admin-0.3.0/browser/`；管理测试已接入 `scripts/run_hydro_ci.py`。

原资源按钮连续导入后持续禁用的错误已通过实际浏览器复现并修复；成功和失败路径都释放
忙碌状态并重画按钮。后台删除等待已有同步与 ACK 完成，拒绝迟到刷新再次写原榜单；
相关 7 项并发回归通过，不通过重发源码测试。

生产目录在 `.../qoj-vp-mvp/2026-10-31/`，旧运行源码备份于
`backups/source-before-0.3.0-20261101-224432`。20 个扩展文件和 9 个 Python 模块校验一致；
助手 hello 返回 0.3.0 并退出，保护会话账本在部署前后保持不变。常用 Firefox 已重载，
Home 仍显示唯一 `3331061 / CORRECT`，缓存榜单仍明确标注其旧观察时间。

本地 XPI：445304 B，SHA-256 `a2d6eba36d86b60ea7b9c2c3389b4afe1722a71ef979b6337e5082a4cda8871a`。
wheel：42475 B，SHA-256 `57da0cd8a9ba25befa74f5297786dbfe87aeb62a6957a08a0708743ff5dc8f1a`。
XPI 的所有文件与 wheel 的 9 个 Python 模块均逐字节核对源码；CI 构建包按对应提交和
SHA256SUMS 识别。共享交付位置为 `E:\shared\qoj-vp-mvp-release\0.3.0`；
GitHub Actions 的具体 commit/run 决定云端验证，不将 VM 本地结果冒充云端运行。

已验证的真实西安数据：`artifacts/resume-diagnostics/xian-cache-after.json`；
解析诊断见 [西安样例标题](research/2026-11-01/xian-sample-labels.md)。
编辑器与共享目录诊断见 [VM 环境修复](research/2026-11-01/vm-editor-sharedfolders.md)，
编辑器最终操作由用户手动验证，不宣称执行了未运行的语义补全测试。

## 保留边界

Jury / Team 是同一本地扩展中的操作视图，不是多用户授权隔离。继续复用官方 DOMjudge
9.0.1 CSS 与模板结构，管理动作作本地适配，不宣称整页像素一致。

XPI 尚未取得 AMO 签名，重启 Firefox 后仍需临时载入；没有更改全局签名检查。
专用 Hydro CI runner 尚未注册，当前日常 VM 不作为 GitHub runner。
已经投递 RankLand 的 AC 如被 QOJ 重判会标记 needs-review，需在原榜单核对；
不会通过重复投递或抹掉旧回执假装同步成功。
