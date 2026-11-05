# 项目导航

- 产品入口、模块职责与验证流程：先读 `README.md` 的“开发与验证”。
- 修改算榜或回放：`src/firefox/board/`；比赛状态与提交事实：`src/qojvp/application.py`、`ledger.py`。
- 修改外部 RankLand 同步：`src/firefox/rankland-*.js`；它是可选导出路径，与本地 Scoreboard 分开验证。
- 查运行环境或 CI 失败：`.github/workflows/`、`.github/actions/hydro-runtime/`、`infra/hydro/`。
- 浏览器 fixture、原站快照和断言：`tests/browser/`。查调用先限定源码目录；大型 JSON、压缩资源按字段读取。
