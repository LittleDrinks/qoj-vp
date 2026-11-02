# 原生 DOMjudge submit 与 URL 兼容边界

调研日期：2026-11-02。本文为方案调研，没有部署服务、修改产品代码、操作 VM 桌面、读取账号凭据，或发起 QOJ 提交。DOMjudge 细节固定在 9.0.1 的提交 `90bbb727906efb438ac2ec7512c09f17824cfc41`；Mozilla 文档于本日在线核对。

## 结论

**可以原样使用 VM 中的命令行 `submit`，办法是在现有 QOJ 逻辑前增加一个小型 DOMjudge HTTP API 兼容层。** 这个客户端只需要四类请求，不要求完整 DOMjudge 服务器。但它使用 HTTP，现有逐次启动的 Native Messaging 助手不能直接接受这些请求；使用期间必须有监听本机端口的进程。

**也可以提供 `/team`、`/team/problems`、`/jury/contests` 等真实 HTTP 路径。** 这与上述兼容层适合放在同一个服务中。页面移到 HTTP 后还要接回 Firefox 会话通道，不能只把 `ui.html` 改名：当前 UI 直接调用了扩展专属的 `browser.runtime` 和 `browser.storage`。

目前运行的产品是 Firefox 扩展加按任务启动的 Python 助手；完整 DOMjudge 之前用于外观和交互对照。现有产品没有 PHP/Twig 运行时。这个区别已经在 [UI_UPSTREAM.md](../../UI_UPSTREAM.md) 中说明，本次也核对了 [background.js](../../../extension/background.js) 的 `openWorkbench()`、`native()` 和 [ui.js](../../../extension/ui.js) 的扩展 API 调用。

如果新目标确实包括“原版终端 submit + 普通 HTTP 页面路径”，建议选择下文方案 B，并让 Firefox 自动管理服务启停。若目标只是页面导航更像 DOMjudge，方案 A 的改动更小。**未把新的常驻方式当成用户已经接受的决定，也未开始改造。**

## 三种经常混淆的“原生”

| 对象 | 实际是什么 | 接入 QOJ 的工作 |
| --- | --- | --- |
| 命令行 `submit A.cpp` | 独立 Python HTTP 客户端，询问题号/语言并上传源码 | 可保持客户端文件不变，在本地实现其四类 API 并转给现有 QOJ 提交流程 |
| 原网页的绿色 Submit 按钮及表单 | Twig 输出的 HTML/JS，提交到 Symfony 的 `/team/submit` | HTML/交互可以继续复用；不启动 PHP 后端时，需要适配表单端点及响应，不能宣称完整原生后端 |
| 完整 DOMjudge domserver | Symfony/PHP、数据库、队伍/比赛/题目/提交/评测实体及网页/API | 需同步这些实体，并增加转交 QOJ 与回填评测的桥接；安装原版服务器本身不会把判题改成 QOJ |

一手依据：[submit 客户端](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/submit/submit)、[Team SubmissionController](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/src/Controller/Team/SubmissionController.php)、[SubmitProblemType](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/src/Form/Type/SubmitProblemType.php)、[domserver 安装依赖](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/doc/manual/install-domserver.rst)。

## 原样命令行 submit 的准确协议

之前从 VM `/usr/local/bin/submit` 取得的研究副本仍在；本次复核 SHA-256 为：

```text
9dddeea4a7647d17ac1eedb7b7c0459869da0c36f14fd6a1327f8273212c3b6a
```

该文件与固定 9.0.1 的客户端一致，来源比对记录见 [10 月 31 日研究](../2026-10-31/domjudge-submit-reuse-research-2026-10-31.md)。本次同时重新在线读取固定上游源码，没有通过运行 `submit --help` 来探测，因为其帮助构造可能联网。

客户端默认 `api_version = ''`，将请求拼为 `<baseurl>/api/<endpoint>`。其 `--url` 应传网站根路径，不带 `/team` 或 `/api`；`--url` 优先于 `SUBMITBASEURL`。[固定源码：URL 配置与拼接](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/submit/submit#L28-L34)、[do_api_request](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/submit/submit#L189-L232)、[选项处理](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/submit/submit#L435-L485)。

| 请求 | 兼容层必须提供的内容 |
| --- | --- |
| `GET /api/contests` | JSON 数组；字符串 `id`、`shortname`、`name`；建议同时提供 `allow_submit`。只有一个比赛时客户端可自动选择；多个时需 `-c` 指定 ID 或 shortname |
| `GET /api/contests/{cid}/languages` | JSON 数组；字符串 `id`、`name`，非空 `extensions` 数组，以及 `entry_point_required` 布尔值 |
| `GET /api/contests/{cid}/problems` | JSON 数组；字符串 `id`、`label`、`name`。文件 basename 及 `-p` 可匹配 ID 或 label，忽略大小写 |
| `POST /api/contests/{cid}/submissions` | `multipart/form-data`；普通字段 `problem`、`language`，可选 `entry_point`；文件字段名是重复的 `code[]` |

读取列表和推断逻辑见 [read_contests/read_languages/read_problems](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/submit/submit#L82-L186)、[动态帮助所需 name](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/submit/submit#L252-L289)、[题目与语言推断](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/submit/submit#L547-L583)。提交协议也与服务端 [API SubmissionController](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/src/Controller/API/SubmissionController.php) 相符。

成功响应须为 2xx JSON 对象，至少有字符串 `id` 和 Python `datetime.fromisoformat()` 能解析的 `time`。客户端随即打印接收回执，以及固定格式的 `<baseurl>/team/submission/{id}` 结果链接。因此，若希望完整保留原客户端体验，还应提供这条详情路由；CLI 本身不会轮询最终判定。[固定源码：上传与回执](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/submit/submit#L356-L379)。

实施时的项目约束如下，属于针对现有系统的设计建议：

- `cid` 映射到本地练习会话，不能直接等同于 QOJ 比赛号：同一 QOJ 比赛可能对应多次本地练习。可采用本地会话 ID，加一个用户可读的 shortname。
- `problem` 与 `language` 映射到该会话当前可用的 QOJ 选项。多个 C++ 版本有相同扩展名时，列表顺序影响自动选择，必须沿用现有默认值并允许 `-l` 精确指定。
- 原客户端允许多文件，但现有 QOJ 路径只接受一个源码文件。兼容层应明确拒绝多文件请求，不能悄悄取第一个文件。
- 复用 `Application.submit()`、账号核对、会话状态和持久化操作记录，不再实现第二条直接发 QOJ POST 的路径。原客户端没有 operationId，因此 HTTP 适配器需创建操作记录，并利用现有指纹与未确认记录拦截重复发送。
- 只有 QOJ 已确认回执才返回上述成功结构；超时/回执未知时保留记录并报告未知，不能生成一个假 QOJ submission ID。后续判定、RankLand 同步仍走现有独立任务。
- 客户端认证按其官方机制使用 `.netrc`/HTTP 认证；若本地服务使用此机制，应配置本地专用凭证，不是把 QOJ 登录口令放进去。此次没有读取或生成任何凭据。

当前提交语义可在 [application.py 的 submit](../../../qojvp/application.py) 和 [UI_UPSTREAM.md 的提交状态约定](../../UI_UPSTREAM.md) 核对。原客户端 `.netrc` 说明位于 [固定源码帮助](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/submit/submit#L302-L304)。

## 原网页路由和表单的准确范围

以下是固定 9.0.1 源码中的路由，不是根据截图猜的名称：

| 页面/资源 | DOMjudge 路径 | 一手定义 |
| --- | --- | --- |
| Team Home | `/team` | [Team MiscController](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/src/Controller/Team/MiscController.php) |
| Problemset | `/team/problems` | [Team ProblemController](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/src/Controller/Team/ProblemController.php) |
| Submit 表单/单题预选 | `/team/submit`、`/team/submit/{problem}` | [Team SubmissionController](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/src/Controller/Team/SubmissionController.php) |
| 提交详情 | `/team/submission/{submitId}` | 同上；原版参数为数字 |
| Scoreboard | `/team/scoreboard` | [Team ScoreboardController](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/src/Controller/Team/ScoreboardController.php) |
| 题面 | `/team/problems/{probId}/statement` | Team ProblemController |
| 样例 | `/team/{probId}/samples.zip` | Team ProblemController |
| 附件 | `/team/{probId}/attachment/{attachmentId}` | Team ProblemController |
| Jury 比赛列表/新增 | `/jury/contests`、`/jury/contests/add` | [Jury ContestController](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/src/Controller/Jury/ContestController.php) |
| Jury 编辑比赛 | `/jury/contests/{contestId}/edit` | 同上；原版参数为数字 |

原页面的表单与 CLI API 不是同一个协议。已有脱敏 [submit-page.html](../../../preflight/visual-reference/rendered/submit-page.html) 明确显示 `POST /team/submit`，字段为 `submit_problem[code]`、`submit_problem[problem]`、`submit_problem[language]`、`submit_problem[entry_point]`、`submit_problem[_token]`。原服务器的控制器读取当前 User/Team/Contest，经 Symfony 表单校验后调用 `SubmissionService.submitSolution()`，成功重定向 Team Home；XHR 则获得模态框模板。

因此可以让兼容层接受这些名称并渲染现有适配页面，从而复用原 URL/表单行为；这仍是协议兼容。若要原控制器、Twig、数据库驱动的 Home/Clarification/Jury 全部不改地运行，则是完整 domserver 方案。DOMjudge 官方安装文档明确要求 PHP、Web 服务和 MySQL/MariaDB；该部署还需要额外的 QOJ 转交/判定桥接，不是换几条 URL 就完成。[9.0.1 安装文档](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/doc/manual/install-domserver.rst)。

项目已经决定题面用 QOJ 超链接、榜单优先打开原站。保留 `/statement` 或 `/scoreboard` 路由时可以做清晰的跳转，不必因此重新实现 PDF 或整套榜单。当前本地会话 UUID 与原版 Jury 数字 ID 也须显式映射，不能只改可见 URL 后丢失选择状态。

## Firefox 的 URL 与进程边界

1. `browser.runtime.getURL()` 生成扩展包资源的完整 `moz-extension://…` URL，不会建立 HTTP 服务器，也不会验证文件存在。可打包 `team/index.html`、`team/problems.html` 等真实入口文件；不能靠这个 API 获得 `http://localhost/team`。[Mozilla runtime.getURL](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/runtime/getURL)。
2. `history.pushState()` 只能设置同源 URL，而且浏览器以后可能重新加载那个 URL。由此可推断：仅把地址栏改成扩展包中不存在的 `/team/problems` 并不是可靠路由，必须验证直接打开、刷新、浏览器恢复都能找到实际资源。[Mozilla pushState](https://developer.mozilla.org/en-US/docs/Web/API/History/pushState)。
3. `protocol_handlers` 支持指定的标准协议或 `web+`/`ext+` 开头的自定义协议；可以把 `ext+qojvp:` 映射到扩展页。它是启动入口，不是承载网页的 HTTP 协议，也不会让 Python requests 获得 DOMjudge API。该机制不能注册任意裸 `domjudge:` 或接管 `http:`。[Mozilla protocol_handlers](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/protocol_handlers)。
4. Native Messaging 的 `connectNative()` 可启动助手，并在端口断开或连接页关闭时结束它；一次 `sendNativeMessage()` 则在回复后结束。因此服务可以由 Firefox 管理，但“使用期间存在的 HTTP 服务”和“每个任务回复后立刻退出的助手”是两种生命周期。现有代码使用后者的语义：每个任务单独 connect，完成即 disconnect。[Mozilla Native messaging](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging)、[本地 background.js](../../../extension/background.js)。
5. 把现有扩展 UI 放到普通 HTTP origin 后，不能直接保留所有 `browser.*` 调用。需要让受限的 content script 将明确的操作转给扩展后台，或把页面动作交给本地服务，再由 Native Messaging 请求 Firefox 的 QOJ 通道。两者都要有明确的消息边界。[Mozilla content scripts](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Content_scripts)。

## 两种可实施选择

| 比较项 | A：保留扩展页面，补齐导航入口 | B：Firefox 管理的本机兼容服务 |
| --- | --- | --- |
| 地址 | `moz-extension://…/team/index.html` 等真实包内入口；可配自定义启动深链 | `http://127.0.0.1:<port>/team`、`/team/problems`、`/jury/contests` |
| 原样终端 submit | 无法直接连 Native Messaging；继续现有 qoj CLI，或另加明确命名的启动器 | 原 `/usr/local/bin/submit` 不改，使用 `--url`/`SUBMITBASEURL` 指向兼容层 |
| 原网页 Submit | 继续现有 DOMjudge 模板/样式适配及 QOJ 消息接口 | 可实现原 URL 和表单契约，后端转给现有 QOJ 逻辑；不等于运行完整原版 PHP 控制器 |
| 进程生命周期 | 保持每个 Python 任务完成即退出 | 使用工作台期间保持本机监听；Firefox 负责启动、断开后关闭，用户无需守终端或 `&` |
| 数据与账号 | 沿用现有本地记录及 Firefox 登录态 | 同样复用；额外处理 HTTP 请求与浏览器通道的关联、认证、并发和断线 |
| 工作量 | 小，主要是入口文件和路由状态；不满足 CLI 原样 HTTP 兼容 | 中等；四类 API 较小，但页面 origin、生命周期和未知回执处理需要集成测试 |

### B 的具体拆分建议（尚未实现）

```text
原版 submit ── HTTP /api/contests/… ──┐
                                    ├─ 本机适配服务 ─ 现有 Application/ledger
浏览器页面 ── /team、/jury/contests ──┘                        │
                                                   Native Messaging
                                                            │
                                                   Firefox 的 QOJ 会话
                                                            │
                                                          qoj.ac
```

- 适配服务只监听回环地址；会话选择、语言与题目映射、单文件限制、HTTP 认证及页面请求校验都在这一层完成。QOJ 的账号检查、实际提交、未确认结果和判定同步仍委托既有模块。
- 扩展先建立服务连接，再打开 HTTP 页面；用户关闭全部工作台后，在没有进行中操作时断开。浏览器关闭/异常退出由 Native Messaging 的进程管理和持久化记录兜底，不做自行脱离的后台进程。
- 初版明确要求 Firefox 已运行且助手可用。浏览器完全关闭时，原客户端直接访问无人监听的端口不会自动唤起 Firefox；若要这一点，需另做启动器或操作系统级激活。不能把原客户端没实现的启动能力写成已经具备。
- 可先只做四类 API 与提交详情 URL，保留扩展页面；通过原版 CLI 的离线回归后再迁移整个页面 origin。这样能分别验收“确实复用了原 CLI”和“页面 URL 一致”。
- 不推荐为了上述路径单独引入 PHP+数据库。只有用户明确希望原版 DOMjudge 服务端页面/管理系统也直接运行时，才进入完整 domserver 加 QOJ 桥接的方案。

## 不占用真实 VP 的验证方法

这些是建议的下一步测试，**本次没有运行该适配层，也未声称兼容已通过**：

1. 在隔离测试目录启动只连 fixture 的 HTTP 兼容服务，原样执行固定 SHA-256 的 `submit` 子进程。记录上述三个 GET 和一个 POST 的实际路径、multipart 字段、文件字节、比赛/语言推断和成功输出；网络出口禁止真实 QOJ。
2. 模拟缺少比赛、多个活动比赛、未知语言、多文件、401、POST 后连接中断，以及收到 QOJ 回执后延迟判定。断线后重复命令必须先核对旧操作，不能发第二次源码。
3. 在 VM Firefox 打开 `/team`、`/team/problems`、`/team/submission/{id}`、`/jury/contests`，验证直接访问、刷新、前进后退和重启恢复。与官方 9.0.1 的相同页面截图及交互对照。
4. 验证工作台打开时端口存在、正常关闭后退出、Firefox 崩溃后不遗留脱离进程；保持进行中请求的未知状态可恢复。
5. 真实 QOJ 部分继续使用只读历史/现有会话验证判定和账号。只有后续明确需要真实提交验收时再另行安排，不以新开 VP 即刻交题测试。

## 推荐与需要决定的边界

用户新提到的“原生 submit + URL”若指终端客户端和普通网页地址，**推荐 B：Firefox 自动启停的轻量兼容服务，保持系统 submit 原样，复用现有 QOJ 代码**。这能复用真正的客户端，同时不要求用户手动管理常驻进程。

唯一需要用户确认的产品取舍是：是否接受“Firefox 工作台使用期间有一个自动管理的本地服务”，而不仅是当前“单次任务结束就退出的助手”。若不接受，则采用 A，并明确保留扩展 URL、原版 CLI HTTP 兼容暂不实现。完整 DOMjudge 服务端不是这两项功能的必要条件。

版本注意：`https://www.domjudge.org/docs/manual/9.0/` 本次在线访问显示了 9.0.2DEV 标识，因此本文的精确协议与路由均引用固定 9.0.1 提交，而非把该可变文档页面当作 9.0.1 的不可变证据。
