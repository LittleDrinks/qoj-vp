# RankLand VP 生命周期与同步调研

调研时间：2026-10-31，UTC 06:58。范围为只读源码/文档检查；没有启动 VP、修改站点存储、提交代码或操作用户已有会话。

## 结论

1. **当前版本的 VP 进度保存在 localStorage，而非 sessionStorage。** 先前交接将 `RanklandVP:presenceSession` 当成 VP 进度，判断不准确；它只用于在线人数统计。不能据此推断用户旧版数据的实际状态。
2. 当前页面能恢复指定存档，但没有发现“我的 VP 历史”列表。关闭标签后“找不到”，可能是找不到准确入口、恢复配置不一致、换了浏览器配置/域名、数据被清理或旧值失效；尚未检查用户实际存储，不能确认其中哪一种。
3. 自动同步 QOJ 判定可以做成独立适配模块，但当前站点没有发现公开的提交导入接口。**直接改 localStorage 不能保证正在运行的页面更新，而且会被自动保存覆盖。** 需要利用原站“记录提交”的真实入口，或与上游协商结构化桥接；内部状态改写只能作为明确标注版本的兼容方案。
4. 可以先实现自己的 VP 会话目录、准确恢复链接、提交账本和同步队列，同时继续使用原站榜单。无需为了生命周期管理提前实现 DOMjudge 样式榜单。

## 一手证据与版本

- 页面：[vp.xcpc.link](https://vp.xcpc.link/)。本次 HTML 引用 `/assets/index-ad07c00e.js`。
- 主要证据：[当前公开 JavaScript bundle](https://vp.xcpc.link/assets/index-ad07c00e.js)。本地只读副本为 `/tmp/rankland-vp-current-bundle.js`。
- 字节数：1,068,201。
- SHA-256：`9121b4ca71c23a3edf48c5b3e858f7e5d62117a011837dc4ec3bc6c6b9b2916e`。
- 未发现 source map，也未在页面链接中发现该 VP 应用的公开源码仓库。下述偏移量是 Python 解码后字符串的 **Unicode 字符偏移**，不是 UTF-8 字节偏移；函数名来自这份压缩包，随发版可能变化。
- 浏览器存储语义：[MDN localStorage](https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage)、[MDN sessionStorage](https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage)、[MDN storage event](https://developer.mozilla.org/en-US/docs/Web/API/Window/storage_event)。localStorage 按 origin 保存；普通窗口关闭不会像 sessionStorage 那样结束其生命周期，隐私模式、清理数据和浏览器策略仍会影响保存。

## 当前真实保存与恢复机制

证据：bundle 中 `vp.view` 的 `setup`，约字符偏移 `1043740–1051200`。

### 存档标识

存档键由以下信息组合：

```text
RanklandVP2:<contest>:<run>:<rule>:<revealCount>:<revealRatio>:<scheduledAt-or-null>:<startMinutes>
```

- `contest` 来自查询参数 `contest`；是 RankLand unique key。
- `run` 来自查询参数 `run`，省略时为 `default`。
- `rule` 支持 `auto`、`ICPC`、`CCPC26`。
- 另外包括揭题阈值、预约时间和起始分钟数；这些值改变会改变存档槽。
- speed、队名和单位保存在值内，未包含在键内。

对应位置：`U`/`D` 定义约 `1044050`；存档键 `z` 约 `1045320`；参数解析 `yd` 约 `588327`。

### 存档值

保存函数 `xe` 写入 version 2 的对象，包含：

| 字段 | 含义 |
| --- | --- |
| `version` | 固定为 2 |
| `elapsed` | 已回放比赛时间，毫秒 |
| `savedAt` | 保存时的真实时间戳 |
| `running` | 是否继续计时 |
| `speed` | 1、2、5、10、30、60 倍 |
| `ownName` / `ownOrganization` | 本队信息 |
| `manual` | 手动记录的提交数组 |

当前 `manual` 元素只包含 `problemIndex`、`timeMs`、`result`，**没有原 OJ、submission ID、账号、重判版本或同步 ID**。恢复时校验题号范围、时间范围、判定枚举和数组长度（上限 10,000）；不是任意 JSON 都能当成恢复状态。

证据：`xe`/`de`，约 `1045500–1046850`。

### 保存时机与关闭页面的含义

- 暂停/继续、倍速切换、修改队伍信息、记录提交、重新开始时保存。
- 计时器每 250ms 更新；运行时约每 5 秒持久化一次。
- `pagehide`、`visibilitychange`、页面卸载及离开相关路由时保存。
- 恢复函数 `de` 在比赛加载后读取一次存档；如果保存时 `running=true`，会补上 `(现在-savedAt)*speed`，并限制在比赛结束时刻以内。

**因此，关闭标签页不等于暂停比赛。** 比赛是否继续由保存的 `running` 决定，恢复过程可以通过时间戳补算，不需要标签页一直计时。

证据：`Te`、`Fe`、`nt`、`et`、`de`，约 `1045820–1051200`。

### “重新开始”与历史目录

`oe` 将时间归零，清空 manual、本队名称等，再写回当前存档槽。当前没有发现历史 VP 列表、session archive UI、存档 JSON 导入入口。

选赛页 `setup.view` 的 `te` 使用 `Lw()` 构造新入口。`Lw()` 当前写出 contest/rule/speed/from/feed/play，以及可选 at/team/organization/count/ratio，**不生成新的 run**。因此默认入口使用同配置的 `run=default` 存档；不能声称 UI 每次新建 VP 都生成 UUID。

证据：`Lw` 约 `589350–589775`；选赛页 `te` 约 `623500–624700`；重置 `oe` 约 `1048100`。

**可行但尚未实测的兼容方向**：扩展创建自己的 session ID，并在 RankLand URL 上指定独立 `run`，同时保存完整 URL。当前读取代码支持此参数，其格式允许字母、数字、点、下划线和连字符。但需验证真实浏览器回归，且注意原站选赛页重新生成 URL 时不会保留这个 run。

### 存档失败后的覆盖风险

静态代码显示：`de()` 恢复校验失败后会显示错误并暂停，但之后仍执行 `xe()` 保存当前初始化状态。因此在查看未知旧存档前，应先只读备份目标键和值；不要先把旧记录写回当前页面试运气。这是代码路径推断，**本次没有拿用户数据复现**。

## 为什么当前没有 QOJ 自动同步

### 原站现有流程

原站提示在原 OJ 做题后手动记录结果。运行中的页面使用 `Me()`：

1. 要求比赛正在运行、有本队名称、未结束，提交时间合法。
2. 读取题目、判定和时间选择。
3. 向内存中的 `g.value` 追加一个 manual 元素。
4. 调用 `Be()`，通过 `snapshotAt(elapsed, manual, ownName, ownOrganization)` 重新产生当前榜单。
5. 调用 `xe()` 保存。

题目当前已 AC/FB 时该入口忽略后续记录。判定枚举是 AC、WA、TLE、MLE、RTE、CE、PE、OLE、IDLE、NOUT、RJ、UKE；没有普通的 pending 项。时间输入支持时、分；默认“当前时间”保留内部毫秒精度。

证据：`gk`/`yk` 约 `590240–590430`；`Me` 约 `1048500–1049500`；表单渲染约 `1052300–1055000`；`snapshotAt` 约 `592037–593200`。

### 榜单仍由现有 SRK 实现产生

`xk()` 验证 SRK 0.3.x ICPC 榜单；`snapshotAt()` 将当前 manual 提交合并为 `__vp_self__` 的题目事件，再按回放时刻筛选并交给原榜单处理逻辑。原始历史队伍的封榜处理和本队显示也在这里完成。

`vk()` 会根据所选规则修改配置，当前还将 penalty 设置为 20 分钟。自动同步不能自行假设所有原 OJ/比赛的规则天然一致，需把“原 OJ 判定事实”和“RankLand 回放计分配置”分开。

证据：`vk` 约 `589775–590256`；`xk`/`snapshotAt` 约 `590744–593200`。

### 为什么直接写 localStorage 不够

- 当前恢复读取发生在初始化加载阶段；未发现该 VP 模块监听 `storage` 或对外提交 `message` 事件。
- Vue 页面正在使用自己的内存数组；外部修改存储不会自动调用 `Be()`。
- 运行页面约 5 秒保存一次，可能把外部写入的新值覆盖为旧内存状态。
- 直接写入后 reload 也要处理旧页面离开时的 `pagehide` 保存，不能把“写入成功”当成“导入成功”。
- 原站没有 submission ID 的空间，重复同步、重判和删除需要扩展自己的账本和对应关系。

以上是当前 bundle 范围内的结论，不等价于证明服务端永远不存在其他未公开接口。

### 兼容入口的选择

| 路径 | 价值 | 当前限制 |
| --- | --- | --- |
| 使用原站现有记录提交表单 | 自动触发原有计算与保存，保持兼容意图 | 依赖 DOM；只能在运行时记录；历史时间输入精度、重复与重判需要处理；本次未实测 |
| 与原站约定结构化导入/消息接口 | 可明确 submission ID、幂等与更新语义，维护成本较可控 | 本次未发现现成公开入口；需要后续与上游协商，本次未联系任何人 |
| 页内 Vue 内部状态桥接 | 可能精确更新数组并调用现有逻辑 | 强依赖内部实现与 bundle 版本，不作为稳定公开接口承诺 |
| 页面不运行时导入版本化存档，再通过准确 URL 打开 | 可以恢复/迁移已有数据 | 必须先备份、校验版本；不能支持运行中写入后假定自动刷新 |

## 导出功能并非 VP 存档导出

当前榜单菜单有 SRK JSON、Gym ghost、VJ replay 和 XLSX 等导出，使用的是正在展示的 ranklist。它们不包含完整 VP 生命周期所需的 run、savedAt、running、speed 和完整来源关联，因此不能直接当成“继续这次 VP”的备份文件。

证据：StyledRanklist 内 `We`/`Ye`/`st`/`ze`，约 `1014750–1015400`；导出菜单约 `1022300`。本次没有触发下载。

## 在线人数接口与会话存档的区别

`Vse()` 只在 sessionStorage 存在线人数 session ID；`jse()` 约每 30 秒向 `/api/vp-presence` 发送 sessionId 和 contestId。请求体没有 elapsed、manual 或队伍信息，不能据此恢复提交记录。

证据：常量 `Ak`/`bk` 约 `601119`；`Vse`/`jse` 约 `1041800–1042650`。

## 建议的解耦生命周期模型（设计建议，未实现）

### 持久会话与页面分离

扩展保存一份版本化的 `VpSession`，包含 session ID、OJ 站点与比赛 ID、RankLand contest key、完整恢复 URL、题目对应关系、原 OJ 已确认开始时间、回放配置以及状态。会话不以 tabId 作为身份；标签页只是一种可以重新打开的视图。

初始状态建议为 `draft → prepared → running → finished → archived`。界面开/关、网络在线/离线、同步正常/待补偿属于独立维度。原 OJ 的 VP 计时和 RankLand 回放时钟分别保存；暂停榜单回放不会暂停原 OJ 比赛。

### 提交事实与同步副本分离

提交模块产出按 `platform + account + submissionId` 标识的记录，保留源时间戳、题目、语言、原始判定、归一化判定及更新时间。提交成功与判定完成分别记录。未知或待判不伪造为 WA，也不因为超时自动重复 POST。

RankLand 同步模块消费已确认记录，产生独立的 outbox 状态（待同步、已确认、失败待重试、跳过及原因），维护 source ID 到目标副本的关联。重开榜单后补发缺失副本；故障不会阻止 QOJ 提交继续。

### 时钟无需后台持续运行

保存确认过的开始时间或 anchor timestamp；页面恢复时补算 elapsed。需要查询判定时才唤起按需助手。Firefox 关闭期间不宣称仍在轮询；重开后从原 OJ 拉取并按 ID 去重补齐，再补偿同步。

### 阶段与验收建议

1. 先做会话目录、完整 URL 恢复、存档只读检查与备份导出；榜单仍跳原站。
2. 独立验证 QOJ/CF 提交账本与关闭后补查；与 VP 视图解耦。
3. 在合成/指定练习 VP 上验证原站记录桥接，重点覆盖重复、重判、跨题号映射、关闭标签后补偿、运行与暂停时钟、异常存档保护。
4. 最后再讨论 DOMjudge 样式榜单；沿用同一会话和提交事实，不另起一套状态。

## 本次验证限制

- 当前公开 HTML 与 JavaScript bundle 已实际下载并核验 hash；以上正向机制均有对应函数路径。
- 没有查看、导出或修改用户真实浏览器存储，因此用户那次丢失记录的具体原因仍未确认，也没有宣称已恢复。
- 没有新建 VP 或触发在线人数 POST，没有发送 QOJ/CF 提交。
- ego-browser 的本机启动路径失效；OpenCLI 当前返回 Browser Bridge 未连接。没有为此安装/修复浏览器环境。
- 按 [opencli-autofix 技能](/home/q2635/.agents/skills/opencli-autofix/SKILL.md) 的明确要求，`BROWSER_CONNECT` 对应 “STOP. Do not modify code.”，因此未进入 adapter 修复。调研继续采用一手 bundle 静态检查；这没有阻止上述源码结论，但运行中 UI 桥接仍待实测。

