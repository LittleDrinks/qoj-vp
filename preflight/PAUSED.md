# 暂停断点 — 2026-10-31

历史断点：用户暂停以便处理电脑。2026-10-31 重启状态检测通过后，用户已明确授权“开工”，暂停解除。后续按 docs/ARCHITECTURE.md 实施。

## 已实际验证

- 来宾 Firefox ESR 140.16.0 headless 在专用持久 profile 中运行，不操作 Windows 前台。
- MV3 扩展与按需 Python Native Messaging 往返；成功任务的助手 PID 已退出。
- 直接 import 固定 qoj-submitter 807ce1be13d67916b2716f8221a10a12731977fe，无重写其题表 / 表单 / samples 解析。
- 两小时起点的本机会话可在关页、关闭并以新 PID 重启 Firefox 后恢复。
- 合成题面 PDF 下载、HTML 经 WebDriver print_page 导出 PDF 成功。后者不能当作产品扩展导出 API 已验证。
- 实际联网的原版 RankLand 加载成功，from=120 两小时初始化、独立 run A/B 分离成功。

## 尚未完成

- QOJ 的四项 fixture 集成均在浏览器请求桥接失败；没有真实 QOJ 提交或判定同步。
- RankLand 实际记录、去重、关页及跨 Firefox 重启恢复：首轮被首次使用提示遮挡；已有点击原站 OK 的修复，尚未实跑修复版。
- DOMjudge 提交 / problemset 前端模板参考已开始固定源码下载；产品界面未实现，也没有实际 DOMjudge 页面视觉回归。
- CF/Gym 不在范围内。

## 最后一次诊断

结果：artifacts/vm-preflight/extension-diagnostics-1/summary.json 和 extension-diagnostics-2/summary.json。

- guest 首轮 XPI 实物已取回，http-content.js 与 workspace 一致，排除缺文件 / 旧脚本。
- Firefox runtime.getURL 读取资源成功，SHA 与磁盘相同；host 权限已授予，目标 tab 为正确的 loopback origin。
- ready 消息在默认与显式注入后均为 NO_CONTENT_LISTENER。
- file / function 的 scripting.executeScript 调用返回成功；function 明确看到正确 pageOrigin 和 extension runtime。file 的结果为 null，仍需检查 InjectionResult.error 等细节，不能据此断定监听器执行成功。
- invalid-FD 日志与脚本错误的因果关系未确认；未关闭 sandbox。
- 还未测试持久 path 安装与 Selenium base64 安装的差分，也未应用运行时 fallback。

当前默认诊断 summary.status=passed 只表示 diagnosticCollectionOnly 采集成功，不代表请求桥已通过。

## 关机前清理状态

最后诊断已于 2026-10-31T09:23:12Z 结束。Firefox PID 3709 已消失，临时 HTTP server 停止，自有 Native Messaging manifest 已移除。测试 profile、SQLite、源码与结果均保留。没有要求关停用户原本的桌面 Firefox 或 VMware。

并行代理已中断；不要继续其任务，除非用户恢复工作。

## 路径和运行方式

- 权威工作目录：/home/q2635/wsl-workspace/qoj-vp。
- Windows 交换目录：E:\shared\qoj-vp-preflight-stage，仅交换副本。
- guest 根目录：/home/csj/.local/share/qoj-vp-preflight/2026-10-31。
- VMX：E:\VirtualBox VMs\hydro-contest-os-2026\hydro contest os.vmx。
- vmrun：D:\Program Files\VMware\VMware Workstation\vmrun.exe。
- guest 执行：/bin/sh <guest-root>/job-extension-diagnostics.sh [--probe-injection]；完整流程用 job-preflight.sh。
- VM 工具传内联脚本会损坏嵌套引号；使用持久文件 copyFileFromHostToGuest + runProgramInGuest。不要前台激活窗口。
- 不保存或打印来宾密码、QOJ Cookie、CSRF。凭据仅来自对话授权，重新开机后需要在内存中构造传输环境。

## 恢复后的下一步

1. 先读本文件、SCOPE.md、最新 extension diagnostics，以及代理已落盘的文件；不要重做已通过项。
2. 最小化内容脚本 / 消息握手失败，检查执行结果 error 和 listener 条件，再决定单变量差分。仍用 VM 内 Firefox。
3. 修复后重跑完整 preflight，核对嵌套 RankLand 结果，不只看外层 step.status。
4. 真实 QOJ 登录态、提交回执与判定、真实题面 PDF 排版未验证，报告必须单独列明，不能让 fixture 结果替代。

完整首轮证据：artifacts/vm-preflight/round1/results/。
首轮 17 项必要检查通过，5 项失败；后续仅完成诊断采集，没有宣布完整前置测试通过。
