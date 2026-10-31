# QOJ VP workbench

已实现 DOMjudge 风格 Home/Submissions、Problemset、QOJ 提交与判定账本、每题 samples/PDF 入口，以及原版 RankLand 进度恢复和表单同步。正在 VMware Firefox 验收；真实 QOJ 账号提交尚未通过验证。

2026-10-31 重启后状态检测已通过，用户已授权开工。实施约定见 [docs/MVP_CONTRACT.md](docs/MVP_CONTRACT.md)；此前断点记录见 [preflight/PAUSED.md](preflight/PAUSED.md)。

- 最新范围：[preflight/SCOPE.md](preflight/SCOPE.md)
- 前期调研：[docs/research/2026-10-31/README.md](docs/research/2026-10-31/README.md)

CF/Gym 暂不接入。前置测试必须在 VMware Firefox ESR 中实跑，后台运行，不改变 Windows 焦点。所有后续代码、报告和测试证据放在此工作目录。

## Linux Firefox 安装

在 Firefox 所在系统安装助手。本次目标为 VMware Hydro Contest OS。

```sh
git submodule update --init
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python scripts/install_native.py
python3 scripts/package_extension.py
```

开发测试：打开 `about:debugging#/runtime/this-firefox`，选择“临时载入附加组件”，打开 `extension/manifest.json`。当前 XPI 尚未签名，正式分发需另行签名。Firefox 重启后重新载入临时扩展，可恢复同一 VP。

QOJ 登录与安全验证在同一 Firefox 的原站页面完成。助手不导入 Cookie、不记录密码，也不需要手动启动后台服务器；系统 `/usr/local/bin/submit` 保持原状。记录默认保存在 `~/.local/share/qoj-vp/vp.sqlite3`。

## 使用与验证

“新建 VP”读取 QOJ 比赛，填写本次名称和从 RankLand 复制的比赛链接，然后开始计时或填写已有开始时间。本地时钟不代替 QOJ 原站虚拟参赛。

选择源文件后核对自动推断的题号/语言，确认框列出文件、账号、比赛、题目与语言。取得原站编号后更新判定；结果不明时先核对历史，不自动重发源码。源码与内联 samples ZIP 当前上限均为 512 KiB。

Scoreboard 恢复已保存的同一 RankLand 会话。只保留一个同场榜单页面；原站多个页面会覆盖彼此进度。同步通过原站表单完成，不写其 localStorage 或 Vue 私有状态；重判与歧义需要核对。

有原始 PDF 时打开原件；HTML 使用 Firefox 保存 PDF 流程并由用户选择保存位置。samples 按题下载，保留不完整答案提示和特殊附件。

- [前置实测结果](preflight/PREFLIGHT_RESULT.md)：22 项必要检查通过。
- [Python 接口与持久状态](qojvp/README.md)
- [DOMjudge 上游来源和许可证](docs/UI_UPSTREAM.md)
- [当前实施断点](docs/ACTIVE_WORK.md)

真实 QOJ 在早期隔离测试中返回 403，安装真实模式后的最新只读探测已到登录提示；真实账号提交仍未验收。受控 fixture 的成功不代替该结论。官方 DOMjudge 运行演示为 10.0.0DEV，与固定 9.0.1 源码不同，已保存实际页面作外观/交互参考，不能视为同版像素回归。
