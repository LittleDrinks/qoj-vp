# VP 体验改进调研

日期：2026-11-02。基线：当前 0.3.3 源码，VM 的上一轮验收仍为 0.3.2。
本轮只读检查代码与一手公开资料；没有打开用户的 VP、提交代码、写原站存储或修改产品实现。
用户已认为原生 submit / HTTP URL 兼容的收益不足，继续使用 Firefox 扩展与按需 Python 助手。
CF/Gym 不在本轮范围，RankLand 继续使用原站。

## 先明确状态归属，再增加体验功能

当前复杂度有一个具体来源：Home 的题目格来自本地提交，但解题总数、罚时和排名会改用 RankLand 快照。
`ui.js:402` 取 `snapshot.score`，下面各题却继续用本地 `progress`；如果本地已有两题 AC、
原榜只收到一题，同一行就可能出现两个绿格但总分为一。
`background.js` 的 `validRanklandScore` 校验身份、字段和观测时间，没有绑定本地提交 revision 或同步水位。
这是静态代码可推出的反例，本轮没有操作用户比赛复现。

建议让每类事实有一个所有者，其余模块读取它的派生结果：

| 职责 | 当前模块 | 应拥有的事实 |
| --- | --- | --- |
| QOJ 接入 | `transport.js`、`qoj-content.js`、`application.py`、`history.py` | 原站提交 ID、原提交时间与当前判定，以 QOJ 为准 |
| 本地练习记录 | `ledger.py`、`application.py` | 本次练习的身份、起止/规则、哪些原站提交属于本场，以及观察记录 |
| 工作台与协调 | `background.js`、`ui.js` | 从同一版本的本地会话快照展示题格、解题数、罚时和时钟；显示缓存可重建 |
| 榜单适配 | `scoreboard-sources.js`、`rankland-content.js` | 原榜映射、投递回执、比较排名及其观测时间，不反向决定本场成绩和时钟 |

数据主方向为“QOJ 事实 → 本地练习账本 → 本队显示 / 可选榜单投影”。
QOJ 官方 VP 的开始时间必须是明确读取并确认的原站事实，本地 Start 仍只创建本地练习。
远端名次是一次比较结果，应携带所对应的本地版本、榜单播放时间和观测时间；暂时不一致时显示过期或未知，
避免把当前题格与旧榜单总分拼成一行。界面只消费快照，读取失败保留已知数据。

减少状态所有者不等于删掉同步队列和回执。提交与原站点击都可能“已成功但响应丢失”；
持久化待办、提交指纹和幂等核对仍是必需的边界记录，不应该靠刷新页面猜测是否成功。

| 路线 | 能消除什么复杂度 | 仍需承担什么 |
| --- | --- | --- |
| A：继续打开 RankLand 原站，收窄适配器（近期建议） | 本队进度不再依赖原榜回传；原榜失败不影响提交/计时/本地成绩 | 没有已验证的公开程序化导入 API，原站表单、恢复、去重与重判核对仍无法完全省掉 |
| B：以后嵌入上游开源计分/渲染组件，只读历史比赛数据 | 可去掉向原站写 manual、再读取原站快照的往返；本地同一时钟驱动整个视图 | 需要接入上游组件、核实数据完整性/规则/封榜行为；UI 也不再是直接打开完整 RankLand VP 原站 |

B 有公开复用基础：官方 [`standard-ranklist-utils` JS 文档](https://github.com/algoux/standard-ranklist-utils/blob/master/js/README.md)
提供 `filterSolutionsUntil`、`regenerateRanklistBySolutions`、`regenerateRowsByIncrementalSolutions` 和 `sortRows`，
可先验证按时间筛选、重建成绩与排序；同仓库也有 Python/Go 实现和跨语言 fixture。
官方 [`standard-ranklist-renderer-component`](https://github.com/algoux/standard-ranklist-renderer-component)
有框架组件、core 和 styles，本轮 README 声明支持 SRK 0.3.0 至 0.3.14。
这符合复用已有实现的偏好，不必重新写一套排名算法；选择该路线不等于已决定做 DOMjudge 样式全榜。

已核对 [utils LICENSE](https://github.com/algoux/standard-ranklist-utils/blob/master/LICENSE) 与
[renderer LICENSE](https://github.com/algoux/standard-ranklist-renderer-component/blob/master/LICENSE) 均为 MIT，复用须保留声明。
这不证明完整 RankLand VP 应用也采用相同许可；公开 bundle 不构成整站搬入插件的授权。
真正选 B 前应固定上游版本，用完整/缺失历史、CE、不罚错判定、封榜和重判 fixture 验证规则，
并确认所选比赛确实有足够历史数据。组件不会凭空补齐 Ucup 缺失的提交时间线。

无需真实 VP 的第一条架构验收：构造本地两题 AC、原榜一题 AC且暂停的快照，Home 应完整展示本地两题及一致罚时，
远端排名单独标为尚未对应当前进度；关闭原榜后本场仍可继续。此轮仅提出设计，不改产品实现。

### 模块边界与按需进程

这里不需要新增常驻服务。继续用同一仓库中的模块与现有 Native Messaging 接口收拢职责：

- `Application` 对外提供准备、开始、提交、刷新判定、结束、读取练习快照等操作。
  `Ledger` 保存本场身份、规则、提交事实与待核对操作；本队计分由一个可独立测试的模块计算。
  页面不分别拼接多个来源的总分、题格与罚时。
- QOJ 适配器继续复用 QOJ CLI。当前 `BrowserSession` 将 HTTP 请求交给已登录的 Firefox，
  Python 收到响应后解析；这段消息往返是共用 Python 和浏览器会话所需的传输，不应被当作第二套比赛状态。
  Cookie 仍由 Firefox 管理，不再建立 Python 登录状态同步。
- `background.js` 负责浏览器生命周期、请求合并、通知页面和唤起助手。界面先显示上次快照，
  后台更新成功后用同一个版本替换；网络失败不会清空题表，重复 F5 不等于重复抓取整场。
- RankLand 模块接收需要投影的判定，保存投递回执，并提供可比较的排名观察。
  UI 不需要了解原站 DOM、manual 数组或恢复 URL 的内部格式。

时钟以保存的开始时间、截止时间和赛制为依据；无须让 Python 每秒运行来维持它。
Firefox 开着时由扩展定时唤起短任务；浏览器完全关闭时不承诺后台继续抓取，重开后补查未完成记录。
因此“关闭后恢复同一场”与“浏览器关闭期间仍实时同步外站”是不同的产品能力。

实施顺序建议是：先统一本队快照与计分，再收拢到点后的判定收尾，随后做可迁移的比赛存档。
是否替换 RankLand 原站展示单独决定；前三步本身就能减少用户面对的同步故障。

## 建议优先解决的问题

先让一场 VP 能顺畅准备、可信地计时和计分、完整收尾、随时恢复，再增加复盘能力。
以下是设计建议和源码检查发现，不是新功能已完成，也不是这些边界已在真实 VP 中复现。

| 顺序 | 改进 | 选手能得到什么 | 大致成本与边界 |
| --- | --- | --- | --- |
| 1 | 赛前一次准备完整 | 开赛前看到账号、时长、样例/附件、榜单来源是否就绪；一次下载比赛文件 | 中；只读检查和缓存聚合，不替用户启动 QOJ 官方 VP |
| 2 | 本队成绩与榜单时间可信 | 没有 RankLand 也能看到自己的解题数/罚时；知道原榜是否与当前 VP 同时刻 | 中；规则必须明确，排名需要可靠同场数据 |
| 3 | 到点后完成收尾 | 最后一分钟交的代码还能得到判定；清楚哪些记录尚未同步 | 中；RankLand 原站结束后无法直接用原表单补录是实际约束 |
| 4 | 可导出、迁移、恢复的 VP 存档 | 重装浏览器、迁移 VM 后仍能找到同一场记录 | 中；需覆盖助手账本与原站存档的关联，不能只备份 URL |
| 5 | 简洁的赛后复盘 | 看首次 AC、错误尝试、空档、补题入口，以及赛后判定变化 | 小到中；先做已有事实可支持的统计，后续再记录判定观察历史 |
| 6 | 让 Clarifications 真正有用 | 在原有右列读到题目更正和通知，不用乱翻讨论区 | 中；只同步可验证的原始公告，讨论与题解要区分 |

## 1. 赛前准备集中到一次完成

现状：Jury 已能建赛、准备资源、手动添加样例；Problemset 的样例与附件已分开；
QOJ 原生 VP 确认页旁也有资源准备入口。题号/语言推断已实现，不能再作为新增能力宣传。
当前 `loadSetupContest` 读取账号/题表，时长输入默认 300 分钟；`startSession` 主要执行一次确认，
未把资源状态、榜单来源、赛制/时长、登录账号集中成开赛前的最终概览。
现有按题下载也没有“本场全部文件”的选手入口。
证据：[ui.html](../../../extension/ui.html)、[ui.js](../../../extension/ui.js) 的
`loadSetupContest`、`prepareSession`、`startSession`、`renderResourceModal`，以及
[qoj-prepare-content.js](../../../extension/qoj-prepare-content.js)。

建议：管理员准备时形成一页简短状态，资源分为“已缓存/原站暂不可取/需手动补充”，
提供整场 ZIP，按题目录保留 samples 与 attachments。选手开始后只保留比赛需要的界面。
明确当前启动的是本地练习；从 QOJ 原生确认页进入时保留原站确认流程，后续可研究读取已确认的
官方开始时间，但不能通过点击本地 Start 假装创建了官方 VP。
DOMjudge 官方也把选文件、自动推断、核对后确认作为提交路径，不需要为此再造 CLI。
[固定 DOMjudge 9.0.1 team manual](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/doc/manual/team.rst)。

验收：一场 12 题 fixture 有普通题、无可确认样例题、交互题、一个失效下载；准备页如实列出，
已缓存资源可断网下载整场包，缺失项可手动补充；重复准备和取消开始均不产生官方 Start/源码 POST。

## 2. 可信的本队成绩与同一时刻的榜单

现状：自动匹配 RankLand 已实现，题目/顺序/时长等均会核对；匹配不到时回到实际发现的 QOJ 原榜链接。
本队栏在没有 RankLand 快照时能从本地记录显示解题数和各题尝试，但总罚时与排名都显示“—”。
`validRanklandScore` 检查快照身份、字段和观测时间，却没有比较 `elapsedMs` 与本地 VP 的进度；
快照中虽携带 `running`，当前显示路径未据此解释原榜暂停。原站运行中的存档还允许倍速。
证据：[scoreboard-sources.js](../../../extension/scoreboard-sources.js)、
[background.js](../../../extension/background.js) 的 `validRanklandScore` / `readRanklandScore`，
[ui.js](../../../extension/ui.js) 的 `renderSummary` / `renderScoreboardSource`。

建议分两步：

- 先补本队本地罚时，明确来源为本次提交与确认的计分规则，排名继续依赖可靠原榜。
  没有 RankLand 的 Ucup 也能正常完成个人 VP。不要把整个世界排名也推算出来。
- 同时检查原榜的计时、暂停和倍速；不一致时使用轻量状态说明“榜单停在 1:20，本场已进行 1:35”，
  提供恢复到本场进度的明确入口，不能把暂停或快进后的榜单称作当前实时排名。
  QOJ 原榜未被证明能按本次本地时间回放，应标为原赛参考榜；赛时打开可能暴露最终结果，
  可默认保留本队进度，让用户明确选择查看参考榜。不要假设 Ucup 一定有可用 SRK 数据。

规则必须来自具体比赛或用户确认。第 5 季 Ucup 的 Rated 规则规定默认五小时、第四小时封榜、
首次 AC 时间按整分钟向下取整、此前错误罚 20 分钟但 CE 除外；Extra 可能另用赛制。
DOMjudge 也允许管理员改变 CE 计分，故不能把某一默认规则硬编码成所有 QOJ 比赛规则。
[Ucup 官方规则](https://ucup.ac/rule/online-stage/)、[DOMjudge team manual](https://www.domjudge.org/docs/manual/9.0/team.html)。
DOMjudge 封榜时本队仍更新而名次显示未知，可作为界面语义参考；
此处不要求重新实现 RankLand 的历史榜单或封榜算法。

验收：本地 10 分钟 WA、11 分钟 CE、30 分钟 AC，在明确 20 分钟罚时/CE 不罚的 fixture 中得到 50；
未解决题的错误不加总罚时。另用暂停、2 倍速、关页恢复的榜单 fixture，验证状态不会误报同步。
Ucup 无匹配时不报“配置失败”，不显示伪造排名，也不自动打开包含最终信息的原榜。

## 3. 比赛到点与结果结算分开

现状：本地结束时间已冻结，时间窗外的提交不计入进度；未确认提交不会自动重发。
但扩展每分钟后台任务只遍历尚未到截止时间的 `running` 会话。可见页面仍有待判轮询逻辑，
因此不能笼统称“比赛结束后完全不会刷新”；真正要补的是关闭页面后的收尾和明确的完成状态。
RankLand 的记录函数要求正在运行且未结束，现有同步也在暂停时拒绝投递。
首次在本地结束后打开榜单时，`prepare_rankland` 只把起点放在最后一秒，并不能保证多条队列均能在结束前补入。
证据：[background.js](../../../extension/background.js) 的 `vp-refresh`、
[rankland-content.js](../../../extension/rankland-content.js) 的 `deliver`、
[application.py](../../../qojvp/application.py) 的 `prepare_rankland`。
原站约束来自 [RankLand 公开 bundle](https://vp.xcpc.link/assets/index-ad07c00e.js) 的 `Me()`，见末尾证据版本。

建议：到点禁止新的比赛提交，但保留“判定收尾”状态，后台有界补查已发出的提交，
最后显示“本地成绩已确认 / 原榜仍有 N 条待核对”。关闭工作台再打开也继续收尾。
对于已经结束或需要重判的原榜，要提供清楚的待核对入口；不能反复重试原站已经不接受的表单，
也不能为了补榜偷偷修改本场起点或清空原站存档。
原站赛后补录能力应单独验证；在找到可靠兼容路径前，保证本地结果完整更优先。
ICPC CCS 规范把比赛结束与 finalized 分开，并要求存在未判提交时不能宣称最终结果；
这里只借鉴其语义，不把本插件视作申请 ICPC 认证的赛场系统。
[CCS Finalizing the Contest](https://ccs-specs.icpc.io/2026-01/ccs_system_requirements#finalizing-the-contest)。

验收：4:59:58 提交，5:00:05 才返回 AC；在截止前后关闭页面、重启扩展，确认一次提交仍被计入，
不出现第二次 POST，未同步项不会被错误标为已完成，最终记录保留原提交时间而非判完时间。

## 4. 能迁移的比赛存档

现状：本地会话、提交账本、同步队列、完整 RankLand URL 与同一 run 的恢复均已实现；
显示缓存也解决了慢助手时的空白。但没有面向用户的完整存档导出/导入界面。
RankLand 当前存档在该 origin 的 localStorage 中；准确 URL 不等于它的 manual 记录本身。
原站“导出 SRK/Ghost/XLSX”等是榜单输出，不含完整恢复所需的会话与来源关联。
证据：[MVP_CONTRACT.md](../../MVP_CONTRACT.md)、
[RankLand 生命周期调研](../2026-10-31/rankland-vp-lifecycle-research-2026-10-31.md)，
本轮已重新核对公开 bundle hash 与保存/恢复函数。

建议：在 Jury 增加导出这场练习、导入存档；保存会话、QOJ 已确认记录、资源清单、原榜身份和回执关联，
以及版本化、只读取得的原榜 VP 存档。缺少原站存档时如实说明能恢复哪些内容。
导入先预览，重名不覆盖旧 run；不携带登录 Cookie，正在运行的原榜不直接写其私有存储。
这是跨 VM/浏览器迁移能力，与现在同一机器上关闭标签后恢复不同。

验收：在独立 Firefox profile A 做 fixture VP、导出后在空 profile B 导入；
开始时间、题目、提交 ID/判定、资源字节与原榜 run 都相同。重复导入无重复记录，
损坏/未知版本导入不能覆盖已有比赛。

## 5. 赛后复盘先使用可证明的事实

现状：已保留提交时间、题号、判定和最终记录；QOJ 重判会更新结果，并将已经投递过的 RankLand
项目标为 needs-review。`submissions` 表保存当前记录和 revision，没有完整的历史观察表；
队列里的 `previousVerdict` 也不是所有判定变化的完整时间线。
证据：[ledger.py](../../../qojvp/ledger.py) 的表结构、`save_submission` / `_queue`，
[history.py](../../../qojvp/history.py) 的重判结果提取。

建议：结束后提供精简的复盘页，按题显示首次提交/首次 AC、错误尝试、未解决题和原题入口，
允许记一句失误原因。后续新增追加式判定观察历史，把“本次观察时为 AC，后续重判为 TL”表达清楚。
过去没有记录过的历史判定不能补造，也不能把两次提交之间的空档冒充实际思考时间。
已同步到 RankLand 的重判继续要求核对，避免又生成一次同题提交来伪装修正。
Ucup 官方也描述了可能发生重判/材料更新的情形，复盘应保留来源与观察时点。
[Ucup Special Issues](https://ucup.ac/rule/online-stage/#special-issues)。

验收：fixture 先返回 AC，之后返回 AC, TL；赛后当前成绩按 TL，观察历史保留变化与时间，
不改动原提交时间，不再自动追加一条 RankLand 提交。没有历史观察的旧数据标为未知。

## 6. Clarifications 保留布局并逐步加入内容

现状：Home 已恢复 DOMjudge 两列，右侧 Clarifications 仍为占位和 QOJ 原站入口。
DOMjudge 官方把题目澄清作为右侧信息；Ucup 规则说明题目修改/额外例子会作为 clarification 放在
比赛 index 页。QOJ 的普通 Discussions 同时可能含赛后题解，不能直接等同于原始比赛公告。
证据：[ui.html](../../../extension/ui.html) 的 `team-clarifications`、
[scoreboards.py](../../../qojvp/scoreboards.py) 的导航提取、
[DOMjudge manual](https://www.domjudge.org/docs/manual/9.0/team.html#clarifications)、
[Ucup Clarifications](https://ucup.ac/rule/online-stage/#clarifications)。

建议：先只读同步可信公告，按题号、原时间显示，带未读标记；界面仍留在现有右列。
能够验证原始赛时相对时间时才考虑按 VP 时间回放；无法验证时间的公告明确为静态更正。
题解入口赛后再出现。当前不需要实现给原比赛裁判发消息的功能。

验收：fixture 包含一条题面更正、一条赛后题解、一个无时间的讨论；正常比赛页只展示明确公告，
不把讨论冒充裁判回复，不在赛时提前展开题解，重开仍记住已读状态。

## 本轮来源与限制

- 2026-11-02 对 `https://vp.xcpc.link/` 及其实际引用 bundle 做 GET；未执行应用脚本或建立 VP。
  当前资源仍为 `index-ad07c00e.js`，1,068,201 字节，SHA-256
  `9121b4ca71c23a3edf48c5b3e858f7e5d62117a011837dc4ec3bc6c6b9b2916e`。
  保存函数约字符偏移 1045329，恢复约 1045790，原站记录提交约 1048440，
  `snapshotAt`/封榜约 592037。偏移属于此固定 bundle，不能当稳定 API。
- 原站恢复会在 `running=true` 时补算关闭期间的时间并乘以 speed；存档含 elapsed、savedAt、
  running、speed、ownName、manual。因此关页恢复已具备上游支持；需改善的是多系统时间语义和可迁移性。
- [SRK 官方规范](https://github.com/algoux/standard-ranklist/blob/master/specs/ranklist.md)
  提供比赛、题目、提交等结构；这说明复用数据格式可行，但不证明任何一场 Ucup 都有可抓取的完整事件。
- 本轮打开具体 QOJ 比赛公开 URL 被重定向登录，未为调研读取用户凭据。关于其本地接入的结论来自
  当前项目代码与已保存契约；没有声称本次确认了所有原站页面/API。
- 在线 `manual/9.0` 目前标为 9.0.2DEV；精确的既有 UI 参照仍以固定 9.0.1 提交为准。
- 未执行真实 VP/提交/恢复测试。上述验收场景均可先用 fixture、隔离 profile 与受控时钟完成。
