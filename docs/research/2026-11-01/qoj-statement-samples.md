# QOJ 题面样例与 Competitive Companion

核查日期：2026-11-01。目标是兼容 QOJ 题面中可确认的普通输入输出样例，同时保留已有附件下载与交互器支持。

## 一手资料

CPH 是 VS Code 扩展；它的官方安装说明让用户另外安装 Competitive Companion 浏览器扩展，由浏览器提取题目后发送给 CPH。因此本次参考的是 Companion 的页面解析规则。[CPH README](https://github.com/agrawal-d/cph#quick-start)

Companion 维护者在 QOJ 支持讨论中提供了自定义规则：URL 正则 `https:\/\/qoj\.ac\/.*`，解析器 `UOJProblemParser`。这不是专门针对 QOJ 的完整格式保证；2026 年的另一个 QOJ 支持请求仍处于 open。[维护者回复](https://github.com/jmerle/competitive-companion/issues/405#issuecomment-1881654635)、[QOJ 支持请求](https://github.com/jmerle/competitive-companion/issues/783)

本次把源码核查固定在 `jmerle/competitive-companion` 的 `df90fabb52e8f566ea3382405e22d246af5d6a69`：

- UOJ 解析器在 `.uoj-content` 内选择 `pre:not(.sh_sourceCode)`，按出现顺序两两组成 input/output；不要求 `H4 输入 1` 等具体标签。[UOJProblemParser](https://github.com/jmerle/competitive-companion/blob/df90fabb52e8f566ea3382405e22d246af5d6a69/src/parsers/problem/UOJProblemParser.ts)
- Universal Cup 解析器另走题目附件 ZIP，根据文件编号整理 `.in`/`.ans`；没有附件链接时直接返回不含样例的题目。它不能证明 QOJ 的 HTML 题面没有样例。[UniversalCupProblemParser](https://github.com/jmerle/competitive-companion/blob/df90fabb52e8f566ea3382405e22d246af5d6a69/src/parsers/problem/UniversalCupProblemParser.ts)
- UOJ 路径默认开启样例空白规范化，逐行移除末尾空白并确保末尾换行。本项目继续保留已有的更小改动范围，不额外删除样例中的空格。[Test 数据模型](https://github.com/jmerle/competitive-companion/blob/df90fabb52e8f566ea3382405e22d246af5d6a69/src/models/Test.ts)

QOJ 站点维护者 Qingyu 的传题指南给出了三点与本问题直接相关的约定：

- 题面用 Markdown 自由编写，推荐样例放入 `<pre>`，题面最高标题用三级；没有规定所有题必须采用某一种样例小标题。
- 题面可以有多个语言版本，官方指南列举 `zh_cn`、`en`。
- `n_sample_tests` 默认是 0；下发 ZIP 可以通过配置不包含样例或样例输出。`download/` 的附加文件与配置指定的样例共同进入 `download.zip`。

因此，附件没有成功取得与题面没有样例是不同的状态。[2027 传题指南](https://training.qoj.ac/blog/qingyu/blog/4904?lang=default)、[2026 配置教程](https://qoj.ac/blog/qingyu/blog/1423?lang=en)

搜索结果中的 `docs.questoj.cn` 属于另一项目 Quest Online Judge，本次不把它作为 `qoj.ac` 的协议依据。

## 本项目采用的边界

保留固定版本 `vendor/qoj-submitter` 的附件下载、路径校验、组织与打包函数。附件可验证时优先保留原附件；交互器与其他附加文件仍显示为附件。只有在附件未确认且普通题面的样例区域能组成完整输入输出对时，才生成 `samples-<label>.zip`。

借鉴 Companion 对原始 `<pre>` 文本的提取与配对，但不复制其整个 `.uoj-content` 的泛选方式。需要限定单一可信题面、明确的样例区域及配对关系；题解代码、交互记录、无标签的其他代码块和不完整样例不应被猜成普通样例。当前字节约定是保留内容和空格，仅统一 CRLF/CR 为 LF，并补齐末尾换行。

## 实际页面与修复

VMware 已登录 Firefox 只读 GET `https://qoj.ac/contest/1051/problem/5113`，实际响应为 200，最终 URL 为 `/contest/1051/problem/5113/statement/zh_cn`。提取后的安全片段保存在 `artifacts/followup/qoj-a.json`，仅保留题面 article、所属 tab 和语言导航，没有登录表单、Cookie 或导航令牌。

该 A 题确实采用当前解析器已经支持的 `H3 样例`、`H4 输入 1/输出 1`、纯文本 PRE。直接运行旧解析器即可取得一对样例，因此本次没有宣称发现了 A 的新 HTML 格式问题，也没有放宽 PRE 的提取范围。样例按钮仍需要对应题目的已准备缓存；旧的 unknown 记录需重新执行资源准备。

真实样例章节被缩减为 `tests/fixtures/qoj-1051-a-samples.html`。按本项目既有末尾换行约定，输入 65 字节、SHA-256 `707961cefb6a97e0bc613828115d4336a58a352885b46026483890d38454c92e`；输出 20 字节、SHA-256 `6aa1db1e2ae35c7bf7321313636bfce971ab42b1620530ca7bbde2bc8371ca3c`。

为兼容默认题面为 PDF、另一个公开语言版本才有 HTML 样例的情况，资源准备增加有界语言回退：默认页面未能取得完整样例后，仅跟随该页面提供的同源、同比赛、同题 `/statement/<language>` 链接，优先 `zh_cn`、`zh`、`en`，最多额外请求三个页面。禁止 URL 猜测、外站或其他题目、带查询参数/片段的链接；最终重定向仍需属于同一题目。已有样例时不追加语言请求，交互题标记阻止整个题面回退。

`tests/test_sample_languages.py` 经真实 `prepare_resource` 调用验证。旧实现的语言回退场景先失败，新实现通过；另覆盖真实 A 字节、三次请求上限、无合法链接、交互题、跨题重定向和登录失效。语言回退的网络场景使用独立 HTTP fixture；真实 A 的在线缓存下载仍由 VMware 验收记录说明，不与 fixture 混称。
