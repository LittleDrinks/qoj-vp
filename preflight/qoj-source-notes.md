# QOJ 第一阶段前置测试：真实库、HTTP fixture、题面与判定边界

范围：MVP 仅 QOJ；这里是合成 HTTP fixture 与源码调查，未发送真实提交、注册 VP 或验证真实 QOJ 登录态。工作目录已统一迁移至 `/home/q2635/wsl-workspace/qoj-vp/preflight`。

## 固定来源与直接复用

`LittleDrinks/qoj-submitter` 固定为 `807ce1be13d67916b2716f8221a10a12731977fe`。主代理使用的真实源在 `vendor/qoj-submitter/`；`fixtures/upstream/` 是本次读取的同 commit 参考副本及各文件 SHA-256 记录，不是另一份实现。

- [client.py](https://github.com/LittleDrinks/qoj-submitter/blob/807ce1be13d67916b2716f8221a10a12731977fe/qoj_submitter/client.py)：`QojClient`、题表解析、提交表单解析、提交回执；本次没有修改。
- [samples.py](https://github.com/LittleDrinks/qoj-submitter/blob/807ce1be13d67916b2716f8221a10a12731977fe/qoj_submitter/samples.py)：附件 ZIP 读取、路径校验、自然排序、`.in/.ans` 配对、特殊附件保留。
- [tests/test_client.py](https://github.com/LittleDrinks/qoj-submitter/blob/807ce1be13d67916b2716f8221a10a12731977fe/tests/test_client.py)：fixture 题号和表单格式的依据，包含静态和 JS 字符串生成的语言选项。
- [tests/test_samples.py](https://github.com/LittleDrinks/qoj-submitter/blob/807ce1be13d67916b2716f8221a10a12731977fe/tests/test_samples.py)：缺答案、工具附件、404、HTML 错误及不安全 ZIP 路径的依据。

真实 `client.py` SHA-256 为 `59462626522eb6a511b6ccfbaf7e93ee1adb422d0dc6ace9bf6946edc75d0211`。本次自检比较了主代理 vendor 中的文件与该值，并导入真实 pycurl。

## 依赖

上游 `pyproject.toml` 声明 Python >=3.10，运行依赖：

```text
requests>=2.31,<3
beautifulsoup4>=4.12,<5
pycurl>=7.45,<8
```

构建依赖为 setuptools>=68。主代理已准备真实依赖于 `vendor_py/`。`client.py` 在导入时会导入 `curl_adapter.py`，后者立即导入 pycurl；即使传入浏览器请求 session、避免默认 CurlAdapter，导入依赖仍需满足，不可用占位 pycurl 掩盖它。

## 已验证的 parser 契约

1. `QojClient` 的 base 只接受 `https://qoj.ac` 或 `https://contest.ucup.ac`，不允许 localhost、端口或附加路径。`get()` 还要求最终逻辑 `Response.url` 与 base 同源。
2. 因此本地 fixture 只改真实 HTTP 目的地，传回 Python 的逻辑 URL 仍是 QOJ URL；原库的 origin 校验保持启用。fixture 不返回重定向，测试 transport 遇到重定向会拒绝。
3. 题表取自 `table tr` 的直属 `td`：第一格为合法标签，第二格中的链接 path 匹配 `/contest/3387/problem/<数字ID>`。
4. 表单必须有 `form#form-answer`、有值的 `input[name=_token]`、`select[name=answer_answer_language]`。动态分支还支持 `form-group-answer_answer` 配合 `source_code_form_group(..., JSON字符串语言片段, ...)`。
5. form action 必须落在同源的 `/contest/<cid>/problem/<pid>` 路径之下。返回的表单仅供只读分析；本次不调用 `client.submit()`。

## FixtureServer 接口

```python
from fixture_server import FixtureServer

with FixtureServer(host="127.0.0.1", port=0) as fixture:
    origin = fixture.origin
    # 把 origin 交给 browser transport 的 fixtureOrigin。
    # actual HTTP -> origin；logical Response.url -> https://qoj.ac/...
    records = fixture.requests
    assert fixture.rejected_post_count == 0

assert not fixture.running
```

导入不会监听端口。`start()`/`shutdown()`、`close()` 与 context manager 都可用；`shutdown()` 后 `.origin` 不再可取，测试应在上下文中保存必要结果。请求记录仅包含 method/path、白名单 query 字段、HTTP status 和 POST 拒绝事实，不保存 Cookie、Authorization 或正文。每次请求关闭连接，测试退出后关闭 HTTP server 及服务线程。

| GET 路径 | 内容 |
| --- | --- |
| `/healthz`、`/fixture-metadata` | 合成 fixture 标识、固定源码 commit、题目/语言元数据 |
| `/` | `QojClient.status()` 可识别的虚构账号 FixtureUser |
| `/contest/3387` | A=15419、B=15420，标题为 QOJ PRE-FLIGHT FIXTURE |
| `/contest/3387/problem/15419` | 静态语言 select、dummy CSRF、合成题面与明确标记的 PDF 链接 |
| `/contest/3387/problem/15420` | 动态语言 JSON 片段、dummy CSRF、故意 HTML-only 的题面 |
| `/download.php?type=problem&id=15419&contest_id=3387` | 两组完整 `.in/.ans` 的真实 ZIP |
| 同路径 id=15420 | 两个输入、仅一个答案，以及合成 `run.sh`、`judge.cpp`；不执行附件 |
| 上述下载路径加 `case=missing/html/unsafe` | 404、HTTP 200 HTML 错误、不安全路径 ZIP，供负向验证 |
| `/fixture-statements/A.pdf` | 761 字节、1 页 A4 的有效合成 PDF；不能据此推断真实 QOJ 有 PDF |
| `/contest/3387/submissions?submitter=FixtureUser&page=1` | 合成历史列表；page=2 为空 |
| `/submission/1000001`…`1000004` | 合成 AC、先 AC 后 WA、待判、CE 详情。上游库没有相应 parser，这些只是后续候选样本 |

**所有 POST 返回 405 并记录拒绝，绝不转发到 QOJ。** 表单中的提交按钮也被禁用。PUT/PATCH/DELETE 同样拒绝。

## 确定的预期结果

`fixtures/expected.json` 保存静态预期和资产 SHA。原库经真实本地 HTTP 解析后的端到端结果在 `fixtures/client-http-selfcheck.json`：

```text
contest.id = 3387
contest.name = QOJ PRE-FLIGHT FIXTURE
problems = A:15419/New Gomoku, B:15420/Abstract Portal
languages(A) = languages(B) = [C++20, Python3]
form.action(A) = https://qoj.ac/contest/3387/problem/15419/statement/zh_cn
form.action(B) = https://qoj.ac/contest/3387/problem/15420/statement/zh_cn
samples = A/1.in, A/1.ans, A/2.in, A/2.ans, B/1.in, B/1.ans, B/2.in
missing B/2.ans is preserved as missing, never invented
extras = all 5 original B attachment entries
warnings = [B: 2 inputs, 1 paired answers; extra or incomplete attachment]
HTTP = 9 GET, 0 POST
fixture context exits and its thread stops
```

上面的 samples 路径在实际返回值中均带 `samples-` 前缀，例如 `samples-A/1.in`。当前库 `zip_bytes()` 的 ZIP 时间戳未固定，因此跨次运行比较输出时应检查条目与内容，不应要求重新打包后的整份 ZIP 字节 hash 恒定。

另一个隔离的 server 自检 `fixtures/server-selfcheck.json` 专门向本地 fixture 发送了一次无意义负向 POST，确认 HTTP 405、计数为 1；这与原库 GET-only 自检中的 0 POST 是两个独立测试实例。

`pdfinfo fixtures/statement-A.pdf` 确认 1 页 A4、PDF 1.4、无加密/JS；`pdftotext` 能读出合成标识。这只验证 PDF 资产与 HTTP 传输，不验证真实 QOJ HTML 的 PDF 排版或 Firefox 打印流程。

## 题面 PDF 策略

### 真实来源只能从页面发现

固定的 qoj-submitter 只下载题目附件，没有题面 PDF 获取功能。附件入口是 `/download.php?type=problem&id=<pid>&contest_id=<cid>`，不能假设其内容含 PDF；`samples.py` 会把普通 `.in/.ans` 以外文件作为 extras 保留。

`vp-helper` 的 `QOJ.prepare()` 会从比赛页寻找标题含 Statements/题面的 download.php 链接；没有时再找逐题的 `.pdf` 链接、iframe 或 object。它在找不到 PDF 时会报错，这是其流程选择，**不是 QOJ 承诺每场都有 PDF**。本项目应分开题表、样例、题面和 VP 准备；PDF 缺失不应阻断其他能力。[当前参考实现](https://github.com/thedyingkai/vp-helper/blob/main/vp_helper/qoj.py)

候选发现流程：从已登录页面取得真实 href/src/data，再检查返回的 MIME 与 PDF 内容；不拼猜一个固定 PDF URL。无登录访问 `https://qoj.ac/contest/3387` 本次被带到登录页，未取得该场真实附件或题面。

### HTML-only 的正常后备流程

Firefox 可打开原生题面并使用“打印 → 保存为 PDF”。扩展的 `browser.tabs.saveAsPDF(pageSettings)` 保存当前页面，会弹出系统保存对话框；返回 saved/replaced/canceled 等状态。它不是静默写入任意路径的下载接口。[Mozilla API](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/tabs/saveAsPDF)；[Firefox 打印说明](https://support.mozilla.org/en-US/kb/how-print-web-pages-firefox)

Mozilla 兼容数据记载桌面 Firefox 很早已支持该 API，但具体 ESR 环境仍要实跑确认 API 存在、对话框行为和页面资源完整性。API 不接收 tabId，因此不能把它当成后台静默导出任意题面标签页的功能。[兼容数据](https://github.com/mdn/browser-compat-data/blob/main/webextensions/api/tabs.json)

打印前要验证字体、图片、数学公式已完成渲染；页面加载完成不保证异步公式已经排版。HTML 导出应与原生 PDF 下载明确区分。合成 HTML fixture 仅含简易 MathML 和 print CSS，不能代表真实 QOJ 的 MathJax、中文字体、分页和图片均已通过视觉验收。

## 本人历史与判定查询的实际缺口

固定 qoj-submitter 的 `QojClient` 有 status/login/contest/form/submit，没有本人提交历史列表、判定轮询或详情判定 parser。提交成功目前仅确认 302 Location 指向 `/submission/<sid>`；没有 Location 时保留 UnknownSubmission，不自动重发 POST。

可调查的既有实现是 `vp-helper` 的 `QOJ.submissions()` 与 `detail_verdict()`：

- 列表候选：`https://qoj.ac/contest/<cid>/submissions?submitter=<handle>&page=N`，按 submission ID 去重，并验证实际 submitter 与题目映射。
- 详情候选：`https://qoj.ac/submission/<sid>?locale=en`。
- 列表数值 0 不能区分 WA/CE/RE；实现会读取详情的最新 Details 区域，并寻找测试点判定，避免前面的 AC 覆盖后面的失败。
- `status_details_` 等标记提示仍在判题；详情暂不可读要表示未确认并退避重查，不能凭 0 分伪造 WA。
- 参考实现将历史读取依赖于已确认 VP 开始时间。本项目若要独立“本人历史”，应将读取事实与 VP 时间过滤拆开，不直接照搬整个 VP 流程。[参考源](https://github.com/thedyingkai/vp-helper/blob/main/vp_helper/qoj.py)

这些路径和选择器是从现有开源客户端观察到的候选，不是已发现的 QOJ 稳定公开 API 文档。本次未在真实账号页面上重新联调，因此不得称历史/判定兼容已实现。

## 本次边界

已完成：固定源码、真实依赖导入、未改动原库的本地 HTTP 解析、正/负 ZIP 资产、POST 拒绝、服务器退出、有效合成 PDF 检查。

未由本子任务执行：VMware/Windows GUI、VM 中 Firefox 测试、真实 QOJ 登录/提交、真实题面下载、HTML→PDF 的浏览器打印与视觉验收。主代理会在 VM 前置测试中分别记录这些结果，不能用这里的宿主自检代替。
