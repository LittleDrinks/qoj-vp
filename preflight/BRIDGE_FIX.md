# Firefox 请求桥接的前置测试修复

2026-10-31；VM 内 Firefox ESR 140.16.0、geckodriver 0.37.1。

最小复现入口是 `guest_extension_diagnostics.py --probe-injection`。这里的
`summary.status=passed` 仅表示诊断采集成功，握手是否成功必须读取
`browserDiagnostics.readyBefore/readyAfter`。

## 已复现的红 / 绿证据

| 安装路径 | 固定结果文件 | 静态内容脚本 | 文件注入 | 函数注入 / 消息 |
| --- | --- | --- | --- | --- |
| Selenium `install_addon` 的 base64 上传 | `../artifacts/vm-preflight/bridge-diag-3/summary.json` | NO_CONTENT_LISTENER | INJECTION_FRAME_ERROR，初始化标记不存在 | 函数执行及最小消息往返成功，sender/runtime/expected ID 一致 |
| 对同一持久 XPI 调用 classic 安装接口的 path 参数 | `../artifacts/vm-preflight/bridge-diag-4-path/summary.json` | CONTENT_READY | 成功 | 成功，readyAfter 仍为 CONTENT_READY |

第二轮只改变安装来源，仍是相同扩展 ID、0.1.2 文件、独立持久 profile、
原有权限和 sandbox。它排除了文件漏打包、host 权限缺失、sender.id
过滤错误这几个解释。可确认失败出在这套自动化临时上传安装路径；当前证据
不足以把更底层机制直接称为“文件提前删除”或某个 Firefox 图形缺陷。

测试控制器应使用：

```python
driver.execute("INSTALL_ADDON", {
    "path": str(persistent_xpi), "temporary": True,
})["value"]
```

临时扩展必须在 Firefox 重启后重新安装；用户 profile 与默认桌面 Firefox
不参与此试验。

## 修复后的代码

0.1.3 删除了用于定位的临时全局元数据、最小诊断 message listener 及全部
`DEBUG-bridge-3` 标记。保留只读资源哈希 / 权限 / ready 采集，以及显式开启
时才运行的 file/function 探针。探针检查每个 InjectionResult.error，不能只
凭 API Promise fulfilled 宣布文件执行成功；错误只返回分类，不返回页面文本、
源码、Cookie 或 CSRF。

Firefox 官方 API 说明：[scripting.executeScript](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/scripting/executeScript)。
安装接口说明：[Marionette addons](https://firefox-source-docs.mozilla.org/python/marionette_driver.html)。

完整 GET/native/QOJ fixtures 回归由主代理重新部署 0.1.3 后执行；此文不把
最小握手通过等同于真实 QOJ 提交、登录态或最终 MVP 已通过。

## 第二处实际失败：Firefox Xray 的 Headers iterator

完整流程在握手修复后仍失败。0.1.4 的单次只读 GET 进一步取得了精确证据：
`../artifacts/vm-preflight/bridge-diag-5-fetch/summary.json` 中响应已经是
HTTP 200 / basic、content-length 为 649；失败发生在 `headers` 阶段，
TypeError 为 `response.headers.entries() is not iterable`。它是响应转换失败，
不能继续称为网络不可达。

0.1.5 用明确允许列表逐项 `response.headers.get(name)` 替代 Headers 的
entries / for-of / forEach 迭代。允许字段仅为 content-type、content-length、
content-disposition、location、retry-after、date、last-modified，不读取
Cookie 或认证字段。单次 probeFetch 只返回阶段、状态及长度，正常请求仍返回
既有 HTTP envelope 给实际 QojClient。

红证据保留不覆盖；部署后先检查同一个 probeFetch 从 headers 错误变为
`stage=done`、status=200、bodyBytes=649，再运行完整 fixtures/native 回归。
此处先记录待验证的修复，不在尚无 VM 绿结果时声称通过。

0.1.5 的实际复查结果保存在
`../artifacts/vm-preflight/bridge-diag-6-fixed/summary.json`：headers 阶段已通过
（3 个允许字段），body-read 得到 649 字节，随后在 body-encode 再次抛错。
因此该轮尚未证明完整 GET 通过。0.1.6 进一步移除了编码中的
`String.fromCharCode(...bytes.subarray(...))`，改为逐索引读取 `bytes[i]`
构造普通字符串，再调用 btoa，不使用 typed-array iterator / spread。
待单次 probe 真正到达 done 后再跑完整流程。

0.1.6 的实际单次 GET 已绿：
`../artifacts/vm-preflight/bridge-diag-7-fixed-bytes/summary.json` 为 HTTP 200、
bodyBytes=649、encodedLength=868、stage=done。它确认索引编码修复了该请求的
转换失败；完整 preflight 与生产 MVP 浏览器验收仍需分别看主代理后续结果，
本记录不把单次 probe 当作完整验收。
