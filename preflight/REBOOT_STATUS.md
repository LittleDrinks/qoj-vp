# 重启后状态检测 — 2026-10-31

环境就绪，功能前置测试未因此宣布通过。本轮只检测重启状态，未恢复开发任务。

- WSL 工作目录、源码、断点与历史结果完整。
- VMware 目标 VM 运行，VMware Tools 正常；来宾认证、文件交换和程序执行成功。
- 来宾本地持久 profile 存在；SQLite quick_check=ok，已保存会话保留。
- 无遗留 preflight / native / geckodriver 测试进程，自有 native manifest 已清理。
- 来宾访问 RankLand 原站与 API 均为 HTTP 200。
- 来宾 Firefox ESR 140.16.0 以独立 headless profile 启动并执行 JavaScript 成功，QOJ 依赖导入成功；结束后 Firefox PID 已退出。
- E: 约 29 GiB 可用，来宾约 13.9 GiB 可用，WSL 约 445 GiB 可用。

初次宿主包装器在 55 秒上限超时；独立取回 guest 最终结果确认检查在约 56.9 秒后正常结束、所有检测通过，未重复启动测试。

证据：../artifacts/reboot-status/guest.json、summary.json。
功能问题与恢复步骤仍见 PAUSED.md。
