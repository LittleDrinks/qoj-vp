# QOJ 赛后提交与真实验证选赛

2026-10-31；本轮只读公网资料及本仓库调用路径。未操作 VM / 本机浏览器，未注册、开始或取消任何官方 VP，未提交源码，未修改产品代码。用户 CF 历史由主代理核对，本子任务不重复读取账号历史。

## 已收敛的一个候选

选择 **The 2022 ICPC Asia Xi'an Regional Contest**。三个平台的关系由一手链接闭环确认，不靠比赛名称猜配：

| 平台 | 定位 | 直接证据 |
| --- | --- | --- |
| Codeforces | Gym **104077**，Finished | [官方比赛页](https://codeforces.com/gym/104077)列出 A Bridge、B Cells Coloring |
| QOJ | contest **1051** | [官方 Problem 5113](https://qoj.ac/problem/5113) 的比赛归属链接指向 `/contest/1051`；[Xi'an 分类](https://qoj.ac/category/87)列出 2022 场，12 题 |
| RankLand | unique key **icpc2022xi_an**，五小时 | [当前公开比赛 API](https://rl.algoux.cn/api/v2/public/contests/icpc2022xi_an) 的 refLinks 直接包含 CF Gym 104077，problems 给出题号、名称和 QOJ 链接 |

建议优先复用用户已在 CF 完成的 A 或 B：

| 题号 | 名称 | QOJ problem ID | 本项目现有的比赛提交页路径 |
| --- | --- | --- | --- |
| A | Bridge | **5113** | `https://qoj.ac/contest/1051/problem/5113` |
| B | Cells Coloring | **5114** | `https://qoj.ac/contest/1051/problem/5114` |

工作台比赛 ID 填 `1051`；RankLand 比赛链接为
`https://vp.xcpc.link/?contest=icpc2022xi_an&rule=ICPC`，由扩展生成独立 run 并保存完整恢复 URL。

RankLand API 还明确给出全套 A–L 到 QOJ 5113–5124 的链接映射。[文件 API](https://rl.algoux.cn/api/v2/public/files/94031158458802176)给出的 SRK 是
`https://cdn.algoux.cn/rankland/file/94031158458802176/icpc2022xi_an.srk.json`，
SHA-256 `4c8d68ca13a964b0d9558058455d139ac411fc7e84d39e2eca6a702530f7c40d`。
本轮直接对这两个 API 做了无认证 GET，均为 200；未打开 VP 应用创建回放。

## 赛后提交与官方 VP 的区别

QOJ 上的 **Training Mode 个人设置不是赛后练习开关**。管理员官方更新日志
[2025-05-15 段](https://qoj.ac/blog/qingyu/blogs/631)说明它会在 virtual contests
隐藏失败测试点和详细判定反馈，以模拟 World Finals 环境。不能通过开启这个设置
来声称已避开官方 VP。

官方 [Manual of the Contest System](https://qoj.ac/blog/ucupannouncements/blog/701?lang=default)
把 Upsolving 和 Virtual Contests 分开说明：已有参赛窗口结束后仍可继续解题，
这些提交不影响原比赛榜单；另有显式的 virtual contest 入口用于新建虚拟参赛。
管理员 [更新日志 2023-08-28 段](https://qoj.ac/blog/qingyu/blogs/631)也说明修正了
Time Window 结束后的提交被计入比赛的问题，并允许在比赛提交记录中查看赛后提交。

因此，本项目“QOJ 赛后提交 + 本地计时 + RankLand 独立回放”的架构能够解耦。
本仓库 `qojvp/application.py` 的 create_session/start_session 分支只写本地账本，
在构造 HTTP transport 之前返回；现有 QojClient.submit 只提交题目表单，不含
注册 / 开始官方 VP 的调用。这证明扩展的本地“开始”本身不会发官方 VP 注册请求，
不等同于已经确认当前账号在特定 QOJ 比赛中的提交权限。

## 实际提交前仍需主代理只读确认

1. LittleDrinks 在 QOJ 1051 当前没有进行中的官方 VP；不要因 CF 做过就推断 QOJ 参赛状态，也不要点击任何 Start / Register Virtual Contest 控件。
2. 已登录普通 Firefox 的 `/contest/1051` 和 A / B 页可直接显示正常赛后提交表单及语言选项。公开未登录比赛首页会跳登录；单凭公开题面或 Submit 按钮不能证明账号具有该赛提交权限。
3. 使用该已签发的赛后题目表单提交。若站点要求先开始官方 VP 才能提交，立即停止该路径；不要为了测试去开始一次 VP，也不要自行猜 `v=0` 参数具有练习权限语义。

未找到当前 QOJ 部署的官方公开源码仓库，也未找到足以独立证明“一账号一比赛可否重复 VP”完整规则的当前官方页面。官方手册只明确开始后的窗口不能更改；不能把这条扩大解释成已查明所有重复参赛规则。本次直接遵守用户“不创建任何 QOJ 官方 VP”的限制。
