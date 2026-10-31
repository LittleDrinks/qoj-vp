# 真实提交已接受、浏览器回执未确认的只读诊断

根代理实际观察：旧赛 1051、C/5115 的唯一一次源码发送形成原站提交
`3331061`，原站历史显示相同账号、题目、C++20、537 字节、时间
`2026-11-01 02:20:57`，并已 AC。源码 SHA-256 为
`5937bfc79630eec8e5ede77eed553ca3bd0c2b2155bc8082726cd15b9bb68979`。
本地操作 `f6a64310-8b40-4643-b486-89db1fbde3f9` 此时仍为 unknown、SID 为空。
这证明不得重新发送源码；后续恢复采用 GET 和现有明确核对关联流程，保留账本。

## 当前源码的边界

- `extension/transport.js` 为每次显式 POST 生成随机 nonce，只在任务进行期间保留。
  `onBeforeSendHeaders` 同时要求 nonce 命中、请求 URL 逐字相同、方法 POST、
  `item.tabId === details.tabId`。任何一项不符都不绑定 requestId，也不会留下已关联响应诊断。
- opaque manual redirect 返回后最多再等约一秒；没有观察到实际 3xx 和 Location
  就抛 `UNCONFIRMED_REDIRECT`。不能依据“最近一条同题提交”伪造回执。
- `onHeadersReceived` 以 requestId 查已关联请求，当前会覆盖先前 observed；
  若存在后续响应，这里尚未限定原始请求 URL。正常 manual redirect 应停于首跳，
  是否发生过多阶段响应需要真实事件证据，不能只凭静态代码判断此次根因。
- `extension/qoj-content.js` 使用隔离 content script 中的标准 fetch/FormData/Blob；
  没有调用页面可修改的 wrappedJSObject.fetch，没有必要先扩大页面代码权限或改 CSP。
- `qojvp/application.py` 将 CLI UnknownSubmission 归为 unknown 时不持久化底层异常；
  本地账本中的 generic unknown 文案本身不能区分断连、超时、漏观察或不符合提交 ID 格式的响应。

## 待证伪的原因与最小探针

1. **标签页元数据不一致**：若 Firefox 将该 context 的 fetch 记为 tabId=-1 或其它 ID，
   带同样 nonce 的同源只读 GET 应表现为 nonce、URL、方法关联正确但 tab 比较失败。
2. **观察器/nonce 未到达**：若 header 被移除或过滤器未触发，同样 GET 将没有 nonce 命中事件；
   不应通过放松标签页校验修复这一种情况。
3. **首跳回执被覆盖或晚到**：若事件序列含同一 requestId 的多次响应，需保留原始 URL 的首次结果；
   若已有初始 302 诊断但内容返回仍 unknown，应继续核对 opaque envelope 和 Location 格式。
4. **内容 fetch 未完成或连接中断**：若没有正常 opaque/HTTP 响应，需检查超时/断连路径；
   不应把“原站已接受”自动等同于浏览器已取得安全提交回执。

安全输出只保留 expectedTabId、observed tabId、frameId/parentFrameId、resource type、
nonce 存在/匹配布尔、URL 相同布尔、origin/path、requestId、HTTP status 和 Location origin/path。
不输出 nonce 原值、Cookie、Authorization、CSRF、请求体、响应 HTML 或未知 query。

Mozilla 官方文档说明 MV3 content fetch 在页面 context；webRequest 的 tabId=-1
表示请求未关联标签页。这些说明不能证明实际这次采用了哪一种元数据，必须以 VM 观察为准：

- <https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Content_scripts#xhr_and_fetch>
- <https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/webRequest/onBeforeSendHeaders>

## 最小验证层次

1. 先记录真实、只读 GET 事件，确定上面哪一条预测成立；本阶段产品源码不变。
2. 对实际 transport 模块做浏览器 API 事件回放，使用观察到的元数据形态：正确 nonce、
   URL、方法、上下文才关联；错误 nonce、其它正数 tab、其它 URL/origin、已结束 nonce
   均不能形成成功回执。测试不执行网络请求，也不使用真实源码。
3. 真实隔离 Firefox 仅向 loopback synthetic judge 发送受控测试 POST，验证原始 302/Location
   可确认为一个 SID，503/无 Location 仍保持 unknown，且一次操作只发送一次。
   与真实 QOJ 的后续交互严格只读及明确关联现有 `3331061`，不再真实提交。

根代理后续实际只读证据已排除：当前 tabId 不匹配、nonce/URL 不匹配、表单 action 的
query/hash 问题。保留监听三秒的一次 GET 中，before 为 9ms、Fetch 返回为 307ms、
headers 为 308ms；仅晚一毫秒，**不能证明原 POST 因一秒等待不足失败**。
原 POST 当时没有相应阶段记录，根因目前仍未确认。

## 诊断补强，非原故障根因修复

`extension/transport.js` 现为每次授权 POST 记录独立 diagnosticId 和安全阶段，
严格 nonce/tab/url/method 绑定与原来十次 100ms 的等待均保留。阶段包括 created、
tabSelected、contentReady、messageDispatched、beforeObserved/beforeRejected/beforeBound、
headersObserved、opaqueReturned、receiptMissing、最终 receiptReturned/httpReturned/failed。

仅保存 path、标签页数字与匹配布尔、状态、Location path/同源布尔、固定错误码和时间。
不保存 nonce、请求/响应 headers、body、CSRF、query、异常原文或账号。
diagnosticId 另行产生，绝不复用 nonce。

`browser.storage.local` 的 `http-post-diagnostics-v1` 保留最近 30 次、每次最多 16 个阶段；
只恢复安全诊断，绝不恢复待发送请求、nonce 绑定或任何自动重试。
`VpTransport.diagnostics()` 返回 postAttempts 和 persistence 状态；写入失败不改变请求或回执行为。
没有 finalCode 的恢复记录仅表示阶段记录未结束，不能自动断言已发送或未发送。
transport 无法观察后续 Python 的 UnknownSubmission 分类，所以真实 503/200 等表示为
`HTTP_RESPONSE` 加真实状态，不能将其冒充原生层已确认的错误原因。

`node --test preflight/test_transport_receipts.cjs` 当前 19 项通过，无浏览器/网络。
将同一测试指向 `git show HEAD:extension/transport.js` 的独立只读快照时，原有 12 项仍通过、
新增 7 项诊断测试失败，验证旧版确实缺少阶段/持久化诊断；产品文件未为此回退。
新增检查覆盖敏感字段排除、被拒标签页匹配的诊断、503 原始状态、存储失败不影响回执、
event page 恢复不恢复 nonce/不发请求、异常原文排除及存储有界。
这些结果证明诊断补强的行为，**不证明原真实丢回执根因已复现或修复**。

`python3 -B preflight/guest_transport_diagnostics.py` 提供窄真实 Firefox 回归，
自建 QA 扩展逐字节加载这两个生产脚本，仅授予 loopback 权限、不使用 native host。
三个无源码的合成 multipart POST 分别返回 302、503、302 无 Location，核对真实观察阶段、
敏感值不落日志、扩展 QA 页刷新后的存储恢复及 POST 仍只有三次。
脚本最终在 VM 中执行通过，见下述独立归档；本机 AST/`--help` 不是浏览器验收的替代。

实际 VM 两轮结果已用于修正 QA 本身：首轮在 tabs.create 尚未完成导航时触发严格
origin 检查，fixture 仅 GET、零 POST；现已等待精确 URL、complete 和真实 ready 握手。
第二轮 `352ed1dbfab54404825989a4ee9f4775` 的 fixture 已依次收到三次 POST：
15419/302、15420/503、15421/302。按脚本逐项 await/验证的控制流，前两项已经通过；
失败来自第三项无 Location 的 302，Firefox 将其作为 opaque redirect，产品按设计拒绝确认。
这不是已复现真实 QOJ 丢回执原因的证据。

QA 现允许第三项在**真实观察到 status302 且 Location 缺失**时保持
`UNCONFIRMED_REDIRECT`；直接非 opaque 302 也不得声称成功回执。仍断言只发三次。
所有失败路径先保存每项 outcome/currentCase、安全阶段、标签页就绪/context 和 fixture 计数，
再执行断言与清理；异常只保留固定 code。

最终 run `d48017f4139f4c1aa62e5a32e86d7767` 的 8 项及 cleanup 全通过，归档
[artifacts/receipt-diagnostics/accepted](../../../artifacts/receipt-diagnostics/accepted/)。
真实 Firefox 对有 Location 的 302 确认回执，503 / 无 Location 的 opaque 302 不确认；
fixture 恰好三次合成、无源码 POST，安全诊断持久化，刷新扩展上下文后恢复三条诊断
但不重放请求。第三项修正的是 QA 对 opaque 无 Location 302 的预期，不是产品根因。
真实 QOJ `3331061` 已经正常显式核对关联，首次丢回执的根因仍未证实，后续没有真实
源码 POST 重测自动回执。

`preflight/debug/qa_receipt_timing_probe.js` 是可选临时 self module，固定 GET-only，
监听保留数秒，先缓存 safe headers 元数据、最终按 nonce-bound requestId 归并。
不作为产品运行时资源加载；现有三秒实测已足以排除当前 GET 的等待不足，无须为该脚本额外访问原站。
来宾临时 QA debug 模块已删除并 F5 清过上下文；本地四个一次性探针/收集器也已删除。
