# Hydro VM 内 submit 的来源、能力与复用边界

调研日期：2026-10-31。范围：静态读取主代理从虚拟机取回的实际脚本，并与 DOMjudge 官方仓库、LittleDrinks/qoj-submitter 固定提交进行对照。没有执行 `submit`（包括 `--help`）、登录、提交代码或读取任何凭据文件。没有更改虚拟机、现有命令或用户仓库。

## 可直接用于决策的结论

1. VM 中 `/usr/local/bin/submit` 是 **DOMjudge 官方提交客户端的原样文件**，与上游 **9.0.0、9.0.1** 的 `submit/submit` 字节一致。它可以成为 CLI 操作习惯的固定参考，但不能据此认定 VM 内部署了完整 DOMjudge 9.0.1。
2. 值得复用的是文件选择与检查、文件名推断题号/语言、入口点推断、提交前摘要与确认等交互规则。DOMjudge 的网络协议和认证不能直接用于 QOJ/CF。
3. **实际脚本没有 `--json` 选项，也不是 Native Messaging 助手。** `print_if_json` 只是尝试打印 API 错误响应中的 JSON。它没有稳定消息封装、原生消息长度帧、提交结果轮询或 VP 生命周期管理。
4. 应保持系统 `submit` 原状；新项目使用 qoj-submitter 子模块的可导入实现，并借用 DOMjudge 的交互规则。现有 `qoj` / `qoj-submit` 的命名已明确避免覆盖系统 `submit`。

## 实物与精确来源

实际 guest 路径：`/usr/local/bin/submit`。

主代理取回的只读研究副本：[实际 submit 文件](/mnt/c/Users/q2635/AppData/Local/Temp/qoj-vm-research-20261031-submit)。

| 标识 | 实际值 |
| --- | --- |
| 文件字节数 | 20,652 |
| SHA-256 | `9dddeea4a7647d17ac1eedb7b7c0459869da0c36f14fd6a1327f8273212c3b6a` |
| Git blob SHA-1 | `446d9c38d33aad1fe97b3b68beae15554e13eafa` |
| 精确匹配的上游 tag | `9.0.0`、`9.0.1` |
| 精确匹配的历史提交 | `f4cd8ab1f6bae99ec393ff3feeca361aff679707`，2025-03-16，Minor submit client cleanup |
| 9.0.1 tag 对应提交 | `90bbb727906efb438ac2ec7512c09f17824cfc41` |

本次实际下载了 9.0.0、9.0.1、8.3.1、8.3.2 与两个历史提交的目标文件，分别计算 Git blob；前两者及 `f4cd8ab` 精确匹配，8.3.x 不匹配。不是仅凭注释或文件名判断来源。

固定源码：[9.0.1 对应不可变提交中的 submit](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/submit/submit)。官方 blob 对象：[446d9c38](https://api.github.com/repos/DOMjudge/domjudge/git/blobs/446d9c38d33aad1fe97b3b68beae15554e13eafa)。

脚本文件没有精确发行版字符串；`--version` 只有 DOMjudge 的通用说明。因此只能确认该文件与这些上游版本一致，不能用它单独区分 9.0.0 与 9.0.1，也不能认定完整 GUI/服务器的版本。

## 实际具备的能力

下表行号基于实际文件，也与固定的 9.0.1 源码对应。

| 能力 | 实际实现 | 如何用于本项目 |
| --- | --- | --- |
| 从文件名推断题号 | 以第一个文件去掉最后扩展名的 basename 作为题号，再匹配服务器返回的 problem ID 或 label，不区分大小写（约 535–586 行） | 沿用交互；平台适配模块提供真实 label→ID 对照，CF 的 A1/A2 等题号保留字符串 |
| 从扩展名推断语言 | 用 API 返回的语言 ID/扩展名集合匹配，不硬编码一套全局编译器 ID；多个候选时取服务器列表中第一个匹配者（113–152、555–575 行附近） | 借用规则，但 QOJ/CF 的具体编译器选项必须来自各自表单；不要把 cpp 固定等同于跨站同一编译器 |
| 多文件 | 多个文件一起提交，题号和语言依据第一个文件；重复路径会忽略（约 499–539 行） | 可作为 DOMjudge 行为参考；QOJ/CF 是否支持多文件要按站点能力决定，不能只因 UI 支持就发送 |
| Java/Kotlin/Python 入口点 | Java 用 basename，Kotlin 经字符处理后加 Kt，Python 3 使用完整文件名；仅在服务器要求 entry point 时应用（235–249、588–600 行附近） | 可借其独立推断函数与行为案例；QOJ/CF 的入口点字段能力仍由平台决定 |
| 提交前文件检查 | stat、可读性、空文件、最近修改时间；mtime 超过 5 分钟警告；可选 python-magic 检测二进制（约 507–534 行） | 适合复用为文件检查结果，UI 负责显示；mtime/文件大小用浏览器 File 元数据也能取得 |
| 提交前确认 | 展示文件、比赛、题目、语言、入口点、URL，收集 y/n；-y 跳过（46–50、607–628 行附近） | 保留确认内容；浏览器用提交弹窗，助手不调用 input() |
| 提交回执 | POST 成功后要求 JSON 包含字符串 id，展示服务器 time 和 submission URL（356–379 行） | 复用“先确认回执，再显示已提交”的语义；QOJ 则从已验证 Location URL 提取 ID |
| 比赛/语言/题目帮助 | get_epilog() 动态列出当前 API 的比赛、题目和语言（252–323 行） | 可作为交互参考；不建议复制其 --help 前置联网行为 |
| 打印 | -P/--print 经 DOMjudge printing/team 接口提交打印任务（326–353 行） | 用户当前需求不包含打印，首版无需接入 |

源码没有显式的源码大小上限检查、VP 开始/暂停/结束、历史目录、提交判定轮询、QOJ HTML 解析、CF 表单提交、RankLand 同步或样例下载模块。不能从“比赛时使用的 submit”推导出它具备这些能力。

## DOMjudge 专有协议与认证

`do_api_request()`（189–232 行）请求形如：

```text
GET  <baseurl>/api/contests
GET  <baseurl>/api/contests/<cid>/languages
GET  <baseurl>/api/contests/<cid>/problems
POST <baseurl>/api/contests/<cid>/submissions
```

提交字段是 DOMjudge 的 problem、language、可选 entry_point，以及 code[] 文件列表。它消费的是 DOMjudge/CCS 风格 JSON，而 QOJ 现有实现读取 HTML 表单、CSRF token，并发送 answer_answer_* 字段；两者的传输和数据契约不同。

baseurl 的优先级为 `--url` → `SUBMITBASEURL` → 文件顶部默认值；此 VM 文件的默认值为空。比赛为 `--contest` → `SUBMITCONTEST` → 自动选择唯一活动比赛。认证说明指向 `~/.netrc`，代码依赖 requests 的相应默认行为；本次没有访问 netrc 或任何 Cookie/配置内容。

它不会继承 Firefox 登录态，也没有浏览器会话连接。不能通过只改 baseurl 就获得 QOJ 或 CF 支持。

官方说明：[工作站配置与 submit 客户端](https://www.domjudge.org/docs/manual/main/install-workstation.html)、[团队使用说明](https://www.domjudge.org/docs/manual/main/team.html)。

## 不能直接作为 Python 库或原生助手使用的原因

- 399 行附近开始在模块顶层构造 parser；422 行直接 parse_args()，随后读比赛数据、检查文件，最后调用 do_api_submit()。没有 `if __name__ == '__main__'` 隔离，直接 import 会执行 CLI 流程。
- 多数函数依赖全局 args、my_contest、my_language、filenames 等变量；错误路径直接 exit()，确认使用 input()。
- 所有 argparse 选项已通过 AST 静态遍历核对：version/help/contest/print/problem/language/entry_point/verbose/quiet/assume-yes/url/filename，**没有 --json**。
- print_if_json()（73–79 行）只处理 API 错误文本。普通摘要、警告和回执是人类文本；debug 还记录原始响应。它不能充当助手的 stdout 消息协议。
- requests.get/post 没有 timeout 参数。原样用作按需助手，会存在网络请求长时间不结束的路径，不符合“任务结束就退出”的使用目标。
- --help 会在构造动态 epilog 前尝试读取已配置服务器的比赛、语言和题目。因此即便只是执行帮助，也不等于严格离线读取；本次没有执行它。

Native Messaging 应另设很小的入口，只处理结构化请求/响应；人类帮助文字、进度和日志与其 stdout 帧分开。应调用可导入的数据逻辑，而不是解析这个 submit 的终端输出。

## 与 qoj-submitter 的复用关系

本次核对的 qoj-submitter 固定提交为 `807ce1be13d67916b2716f8221a10a12731977fe`（2026-10-28）。

一手代码：

- [QojClient 与表单解析](https://github.com/LittleDrinks/qoj-submitter/blob/807ce1be13d67916b2716f8221a10a12731977fe/qoj_submitter/client.py)
- [样例模块](https://github.com/LittleDrinks/qoj-submitter/blob/807ce1be13d67916b2716f8221a10a12731977fe/qoj_submitter/samples.py)
- [CLI 选择与入口](https://github.com/LittleDrinks/qoj-submitter/blob/807ce1be13d67916b2716f8221a10a12731977fe/qoj_submitter/cli.py)
- [包与命令定义](https://github.com/LittleDrinks/qoj-submitter/blob/807ce1be13d67916b2716f8221a10a12731977fe/pyproject.toml)
- [现有命名与样例说明](https://github.com/LittleDrinks/qoj-submitter/blob/807ce1be13d67916b2716f8221a10a12731977fe/README.md)

适合直接作为 submodule 的主要原因是它已经把 QojClient、表单解析和 samples 分成可导入的模块，CLI 使用这些实现；无需为了 DOMjudge 交互把这套网络协议重写到官方 submit 中。

具体建议：

1. 继续保留 `qoj`、`qoj-submit` 和比赛系统原有 `submit`，不覆盖后者。新项目通过包依赖安装 submodule，再直接 import qoj_submitter。
2. 复用现有 QojClient.contest/form/submit；语言选择已有 cli.choose_language，可按实际调用需要提取成共享逻辑，避免再写一份不同默认值的算法。
3. 原样客户端提交返回的是**确认过的 submission URL**，不是完整的 receipt 对象；助手可以据此解析已验证的 submission ID，再返回结构化回执。UnknownSubmission 表示网络后结果未确认，必须保留这个状态，不能让同步队列自动重复 POST。
4. 单题 samples 可复用现有 download(client, contest) 的整理规则：该函数按 contest['problems'] 遍历，调用时可以给出只含目标题目的题表视图，或在后续抽出单题入口。zip_bytes(files) 已能在内存里生成压缩包。保留 samples-A/1.in、1.ans 和特殊附件单独处理的既有行为。
5. samples.download() 第 91 行仍直接 print 进度；进入原生助手时需要隔离 stdout，或改为可选进度回调。不能把它的打印内容混进 Native Messaging 帧。
6. QojClient 的 session 参数给浏览器请求通道留下了接入点，但它仍使用 requests 风格 Response、headers 等接口，并设置 User-Agent。浏览器通道要满足真实使用到的契约、处理浏览器不能任意更改的头；“可以传 session”不是已经实现浏览器兼容的证明。本次没有做该桥接实测。
7. 当前 QojClient.status() 是登录状态查询；没有完整的本人提交历史与判定查询方法。新的判定采集、VP 时间线和 RankLand 同步，需要作为独立能力补齐，不能说 qoj CLI 已覆盖全流程。

CF/Gym 应有单独的平台适配模块。可以参考 vp-helper 的网页表单和官方 API 组合方式，但不应把 DOMjudge 的 language ID、problem ID 或提交字段套到 CF 上。

## 与 VP 生命周期的接口建议

以下为设计建议，未实现：

- 提交模块只接受明确的平台/账号/比赛/题目/语言/文件，返回已确认回执或结果未确认状态；不负责创建 VP、操作榜单页或记录排名。
- 判定采集模块按 platform + account + submissionId 更新提交事实，保留原始时间、原始判定与归一化判定。
- VP 会话模块维护会话 ID、原 OJ 计时锚点、准确 RankLand 恢复 URL 与题目映射；标签页开关不改变会话身份。
- RankLand 同步模块消费提交事实，维护待同步队列和去重关联；榜单失败不阻塞 QOJ/CF 提交。
- Python 进程只在任务期间存在。闭页/断线后未获得提交回执时，保留结果未确认状态，恢复时先查询原 OJ，再决定如何继续；不因助手进程退出就重发提交。

这些接口不要求先实现自己的 DOMjudge 样式 board；首版仍可只打开原站榜单。

## 来源与许可

实际脚本头部声明 GNU GPL；固定 9.0.1 的 [README](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/README.md#copyright--licensing) 明确为 GPL version 2 or later，[COPYING](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/COPYING) 为 GPL v2 正文。

qoj-submitter 固定提交的 [LICENSE](https://github.com/LittleDrinks/qoj-submitter/blob/807ce1be13d67916b2716f8221a10a12731977fe/LICENSE) 则采用 public-domain / Unlicense 文本。两份来源的许可不同，实际复制代码时应分别记录，不应把原项目许可等同于新引入代码的许可。

如果实际拷贝或修改这份代码，应保留上游来源、不可变提交、许可证与变更记录，并按相应许可安排分发；不能仅因它随比赛镜像安装，就当成无来源约束的代码。前端模板和样式还需要独立记录所选版本与第三方资源许可。本报告没有替用户决定最终项目许可证。

## 验证限制

- 已验证实际脚本的字节哈希、上游 blob、多个 tag 的精确一致性，以及静态全部选项、函数和请求调用。
- 只读了脚本自身与公开上游源码；没有读取凭据、运行 submit 或发送真实提交。
- 没有验证这个 VM 是否配置了可达的 DOMjudge 服务器，也没有把帮助中动态联网的结果当成已知能力。
- Native Messaging、浏览器请求通道、QOJ 判定采集与 CF/Gym 提交兼容均未在本子任务实现或联调。
