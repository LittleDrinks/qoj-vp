# QOJ / RankLand 榜单来源与自动选择

2026-11-01，匹配模块实现于 2026-11-02。联网调研仅用公开 GET、当前原站 JavaScript 与本仓库代码检查；没有开启 QOJ VP、提交源码、修改用户浏览器数据或发送站点消息。

## 可以落地的结论

- 榜单来源应是比赛的独立配置，而不能把“未填写 RankLand URL”当成整场练习没有榜单。RankLand 有对应数据时使用原站 VP；没有时提供 QOJ 原生榜单入口。
- **QOJ 原生比赛/VP 排名与工作台本地计时不是同一件事。** QOJ 官方手册明确赛后 upsolve 不改变原生榜单。工作台 `start_session` 只保存本地开始时间，没有注册 QOJ VP。因此不能从原生历史榜找到同名账号，就把该行当成本次本地练习的排名。[官方手册](https://qoj.ac/blog/ucupannouncements/blog/701)
- 本地练习的提交、用时、通过题目继续由已有持久账本显示。外部榜没有本次参与记录时，名次保持未知，并清楚标注打开的是原生榜/历史榜；不伪造一个与本次时钟不相符的名次。
- 不宜用比赛标题中的 `Universal Cup` 一刀切分流。当前 RankLand 440 条公开比赛中有四场 Ucup 半决赛/总决赛，但没有 Dolgoprudny；部分 Ucup 分站又与 ICPC/CCPC 同题。这次查询只说明目录当前覆盖，不能推广为整个系列永久不支持。[公开目录](https://rl.algoux.cn/api/v2/public/contests)

## RankLand：已验证可用的自动匹配接口

2026-11-01 在 WSL 实际 GET：

| 接口 | 结果与用途 |
| --- | --- |
| `https://rl.algoux.cn/api/v2/public/contests` | HTTP 200；`{success:true,code:0,data:{contests:[…]}}`，440 条，无分页字段。元数据含 `uk/name/title/duration/srkFileID/redirectUK`。 |
| `https://rl.algoux.cn/api/v2/public/contests/icpc2022xi_an` | HTTP 200；12 题的 `alias=A…L`，`link=https://qoj.ac/problem/5113…5124`，与西安 2022 的题目一一对应。 |
| `https://rl.algoux.cn/api/v2/public/contests/ccpc2026changchun` | HTTP 200；13 题的 link 含 `/contest/4582/problem/22910…22922`，同时给出 CCPC26 计分配置。 |
| `https://rl.algoux.cn/api/v2/public/contests/icpc2022xian` | HTTP 404；不能从年份和城市拼接猜测 UK。 |

对应一手页面：[目录](https://rl.algoux.cn/api/v2/public/contests)、[西安详情](https://rl.algoux.cn/api/v2/public/contests/icpc2022xi_an)、[长春详情](https://rl.algoux.cn/api/v2/public/contests/ccpc2026changchun)。匿名 GET 没有使用 cookie，目录响应带 `Access-Control-Allow-Origin: *`。

公开副本保存于忽略目录 `artifacts/scoreboard-source-research/`，包括本次 catalog、两场详情。它们是调研证据，不作为持续更新的生产数据库。

当前 [原站 bundle](https://vp.xcpc.link/assets/index-ad07c00e.js) 仍是 1,068,201 bytes、SHA-256 `9121b4ca71c23a3edf48c5b3e858f7e5d62117a011837dc4ec3bc6c6b9b2916e`，与仓库隔离浏览器 fixture 相同。其 `listAllRanklists()` 调用公开目录，过滤没有 `srkFileID` 的记录；`getRanklistInfo()` 通过 UK 取详情，使用该记录的 SRK 文件。没有必要使用旧站 `/rank/search`。

建议实现以下约束：

1. 读取 QOJ 题表后异步取得 RankLand 目录。用规范化的完整标题、别名标题、年份/地点缩小候选；只比较元数据，不下载全部 SRK。
2. 对少数候选取详情，核对**完整题目集合、题号顺序、比赛时长和规则支持**。若每个 `problems[].link` 都能解析出对应 QOJ problem ID，且 alias 顺序完全相同，这是比相似标题更强的依据。
3. 只有一个经过完整验证的候选时自动保存。多个候选、缺少题目链接、题目重排、部分重合或同名热身赛均不自动绑定。Jury 中可保留候选和人工选择；队员入口保持简单。
4. 自动选择沿用现有 `rankland_url()` 生成本地 session 专属 `run`，并保存完整恢复 URL。不得覆盖用户已有配置/正在进行的原站 run，不按新 tab ID 重建存档。
5. 目录请求失败与“没有匹配比赛”分开记录；缓存已验证映射，让断网不清掉原有榜单。使用公开 GET 和 `credentials: omit`，无需转发 QOJ 身份。

独立模块 `extension/scoreboard-sources.js` 已实现其中的目录筛选和唯一强匹配。生产接线、已有配置保留及浏览器中实际 CORS/权限与恢复行为由集成验收单独检查。

### 模块接口与验证

`VpScoreboardSources.resolve(contest, durationMs)` 接受已验证 QOJ 题表：

```js
{
  id: "1051",
  name: "The 2022 ICPC Asia Xi'an Regional Contest", // title 也支持
  titles: [], // 可选别名标题
  scoreboardUrl: "https://qoj.ac/results/QOJ1051?mode=pc2", // 原站已发现链接
  problems: [{id: "5113", label: "A"}, /* 完整题表 */]
}
```

返回 `{source,state,reason,url,ranklandUrl,qojUrl,candidates,candidateCount,checkedCandidates,checkedAt,contestKey?}`。

- `source`: `rankland` 或 `qoj`；`state`: `matched` / `unmatched` / `unverified` / `ambiguous` / `unavailable`。
- 只有一个完整验证候选且其他候选均已明确不匹配时才返回 `matched`。缺链接/畸形详情、另一个候选超时、多个完整匹配均不能自动选定。
- 标题只是候选过滤。若标题不带年份，可用目录 `startAt` 排除其他年份的同城比赛；证明一致仍要求全部题号、题序和时长。
- 默认最多 6 个详情；候选超额返回 `CANDIDATE_LIMIT` / `unverified`，不把没查完说成没有榜。
- 仅返回 `https://vp.xcpc.link/?contest=<UK>`。不建标签、不启动回放、不填写 run、不存会话配置。native 的现有配置流程负责稳定 run。
- `qojUrl` 使用传入的原站同比赛 `scoreboardUrl`（限定同源的 `/results/QOJ<cid>`、`/contest/<cid>/standings` 或比赛首页）。缺少实际榜入口则回到该比赛首页，**不会猜造 `/standings`**。
- `VpScoreboardSources.create({fetchImpl,clock,timeoutMs,cacheTtlMs,maxCandidates})` 可注入测试依赖。默认超时 5 秒、内存缓存 5 分钟；目录和详情请求合并 in-flight；全部 GET、omit credentials、拒绝重定向，失败结果不带服务端任意文本。缓存过期后失败返回 availability 状态，调用者应保留已有已确认配置。

定向命令 `node --test preflight/test_scoreboard_sources.cjs`：18 项通过。真实公开 GET smoke（`artifacts/scoreboard-source-research/resolver-live.json`）验证：西安 1051 → `icpc2022xi_an`、长春 4582 → `ccpc2026changchun`、Dolgoprudny 4569 无标题候选 → QOJ。这不是浏览器接线或线上 VP 排名验收。

## QOJ：已确认与尚待登录态验证的部分

[公开比赛列表](https://qoj.ac/contests) 当前将 “The 5th Universal Cup. Extra Stage 1: Dolgoprudny” 链接到 `/contest/4569`，同一行 “Petrozavodsk Summer 2026. Day 3. MIPT Contest” 指向同一比赛的 `?v=1`。这说明匹配时需要保留别名标题，不能把副标题当成另一场比赛。

本次匿名直接请求 QOJ 返回 HTTP 403；web 读取比赛链接会转至登录页。因此没有凭匿名结果断言当前 `4569` 的榜单可见性、原生 VP 状态、账号行或完整数据接口。`/contest/{cid}/standings` 在 QOJ 系列站点确有公开实例，但生产应优先读取当前比赛导航栏实际给出的链接，而不是仅靠路径猜测。[同系原生榜实例](https://training.qoj.ac/contest/1850/standings)

主代理随后在现有已登录 guest Firefox 只读检查 `4569` 导航，看到的是 **External Standings(PC^2)**，实际 href 为 `/results/QOJ4569?mode=pc2`，并没有 `/standings` 导航。Virtual Contest 侧栏表示该原生参与已结束。研究代理再次匿名 GET 这个确切结果 URL 仍为 403，不能代替登录态读取；工作台此次本地新建计时也不能把已结束的原生参与排名当作自己当前排名。

QOJ 官方更新日志说明：比赛管理员可选择榜单展示正式选手、虚拟选手和不同 Ghost；Battle of Giants / External Scoreboard 会自动刷新。这进一步说明页面可能有不同榜单，单凭“同一 contestId + 同名账号”不足以确定行的语义。[QOJ 更新日志](https://qoj.ac/blog/qingyu/blog/631)

需要在现有已登录 Firefox 中只读提取：

- `GET /contest/4569` 的导航链接（Standings / External Standings / Battle of Giants）、Virtual Contest 状态、规则/罚时、页面 server time。
- 导航实际给出的榜单页面：表头、数据容器/加载脚本地址、LittleDrinks 行及其参与类型标记、页面上的筛选控件名。不要抓取或保存登录 token、cookie、密码、源码。
- 若想把原站本队行显示回工作台，需要可验证的原生参与开始时间/身份，并与本地会话对应；缺少这个证据只提供原站入口，不导入名次。

现有 QOJ CLI 固定子模块提供登录、题表、提交表单、提交协议，没有 standings API。应新增独立只读适配模块；无需改写其提交协议，也无需把 QOJ 榜转成自制 RankLand 数据。

## 无需新开官方 VP 的回归

- 使用当前登录会话只读检查已发生提交和可见榜；绝不通过“开 VP 后马上交题”构造验收。
- 用上述匿名公开 RankLand 元数据做真实接口烟测；题目匹配的确定性测试使用脱敏 fixture。
- 覆盖西安完整匹配、长春完整匹配、Ucup 无匹配、同题不同顺序、同年热身赛、两个完整候选、API 超时、人工设置优先等分支。
- QOJ 采用已读页面结构制作合成 fixture，分别覆盖原生 VP、历史榜、账号缺席/被过滤、登录失效。不可因为 fixture 排名解析通过就声称已验证线上 VP 排名。
- 继续使用现有原站 bundle + 合成 SRK 的隔离 Firefox 回归检查打开、关闭和恢复 RankLand；无需写入真实比赛或重交代码。
