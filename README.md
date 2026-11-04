# QOJ Workbench

在 Firefox 中用 DOMjudge 风格的界面打 QOJ：提交代码、查看判定、下载样例和附件。

**[下载安装](https://github.com/LittleDrinks/qoj-vp/releases/latest)** · [反馈问题](https://github.com/LittleDrinks/qoj-vp/issues)

唯一支持和验收环境：**Hydro Contest OS 2026**。安装以 Release 为准。
开发中的下一版提供 `.deb` 安装包；安装后从应用菜单打开 **QOJ Workbench**，在 Firefox 确认添加扩展。

## 使用

1. 在 Firefox 登录 QOJ，进入比赛的 VP 确认页，点击 **准备比赛文件并打开工作台**。
2. 准备完成后，点击 QOJ 原站 **Start!**；工作台自动采用 QOJ 的开始时间。
3. 在 **Home** 提交和查看判定，在 **Problemset** 打开题面、下载样例或附件。
4. 比赛配置、手动添加样例、归档和删除放在 **Jury**。

助手只在需要时运行，不用手动开启后台服务。关闭页面后，比赛记录和已准备的文件仍保留。

## 开发

当前开发分支正在拆分 Judger、比赛账本与 Board；本地算榜改动尚未发布。正式安装以 Release 为准。

- [架构与构建](docs/ARCHITECTURE.md)
- [CI 与签名发布](docs/CI.md)
- [DOMjudge 来源和许可证](docs/UI_UPSTREAM.md)

目前支持 QOJ，暂不支持 Codeforces / Gym。项目采用 GPL-2.0-or-later；所复用依赖保留各自许可证。
