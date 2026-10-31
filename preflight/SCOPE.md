# 前置实测与 MVP 范围

2026-10-31，依据用户最新要求；覆盖此前报告中关于 CF/Gym 的计划。

## 当前工作：前置测试，属于调研

所有浏览器实测在 VMware Hydro Contest OS 的 Firefox ESR 中运行。本机不安装 Firefox。使用独立测试 profile 和本地测试状态；保持 Windows 当前窗口焦点，不切到 VMware 前台。

需要取得实际运行证据：

1. Firefox MV3 扩展与按需 Python Native Messaging 助手往返，任务后助手退出。
2. 实际导入固定版本的 qoj-submitter；通过 Firefox 执行 HTTP，再由现有 Python 客户端解析题表、表单和单题 samples。
3. 会话保存到来宾本地目录；以两小时量级的时间锚点验证关闭页面、关闭 Firefox、重开后的恢复。
4. 在独立 RankLand 测试会话中验证准确恢复 URL、进度保存及原站记录提交入口。用户已有存档不参与试验。

受控 HTTP fixture 与真实 QOJ / RankLand 联网结果分别记录。没有真实账户、登录态或网络访问证据的项目不得写成通过。前置阶段不向 QOJ 发送源码提交。

## MVP 必须具备

- DOMjudge 风格提交页，使用现有 QOJ CLI 的可导入实现完成 QOJ 提交，确认提交编号并持续同步真实判定。
- Problemset 仿 DOMjudge 页面，每题提供题面 PDF、提交和独立 samples 下载。
- Scoreboard 打开或切回原版 RankLand，至少保证比赛实时进度可查看，打了两小时后关页重开能恢复同一会话。
- RankLand 自动同步判定先实测可行性；可行则纳入，不能通过直接写存储来假称实时同步已经完成。
- 会话、提交事实、查询、榜单同步和页面生命周期分别管理。按需助手无须手动启动常驻服务。

原生 DOMjudge submit 的网络接口不能直接用于 QOJ；其交互与文件推断作为参考。若提供同名用法的 QOJ submit 入口，应明确由适配模块调用 QOJ CLI，不覆盖比赛系统自带 /usr/local/bin/submit。

题面 PDF 要验证实际来源：QOJ 已提供 PDF 时使用原件；只有 HTML 时需要单独验证导出方案，不把任意附件当成题面 PDF。

CF / Gym 暂不接入。DOMjudge 样式的完整榜单后续再讨论。

## 固定源码

qoj-submitter: 807ce1be13d67916b2716f8221a10a12731977fe。

当前目录是隔离测试原型，不是已交付的 MVP。
