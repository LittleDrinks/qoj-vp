# QOJ 题目资源准备、缓存与真实附件核验

更新：2026-11-01（Asia/Shanghai）。早期调研已转为本地缓存实现，并完成隔离浏览器
及真实 QOJ 资源核验。本文保留来源与结论的边界；发布状态见
[MVP_RESULT](../../MVP_RESULT.md)。未实现资源上传、公开托管或云服务。

## 已实现的流程

固定 `qoj-submitter` revision 为 `807ce1be13d67916b2716f8221a10a12731977fe`。
直接复用其 [download、organize 与 zip_bytes](../../../vendor/qoj-submitter/qoj_submitter/samples.py)，
包括 ZIP 路径/链接/重复项/解压大小检查，以及原始附件成员的保留规则；没有改子模块。
[application.py](../../../qojvp/application.py) 在其上补充身份核对、严格标记的题面样例
回退与资源分类，[resources.py](../../../qojvp/resources.py) 管理持久清单和文件缓存。

准备与提交、计时、判定和榜单独立。在 Home 资源弹窗，或已观测的 QOJ 原生 Start
表单旁点击独立准备按钮后，串行读取题目资源。准备不提交原生表单，不开始 QOJ 官方
VP，也不要求本地计时已开始；已有 ready 默认复用，明确刷新才重新联网。

| 清单事实 | Problemset 入口 |
| --- | --- |
| ready，成对普通样例且无其他文件 | samples |
| ready，含其他非空附件，包括样例与工具混合包 | 附件，单一下载入口保留所有成员 |
| unknown 或未准备 | 不显示可下载的 samples/附件；在准备弹窗中查看和重试 |
| 上次成功、本次刷新失败 | 保留旧包，单独标记本次未确认 |

实现只有 `ready / unknown`，没有 `verified-none`。单次 404、空 200、空 ZIP、权限或
网络异常都不能证明没有资源。资源类别也不能证明题型：工具文件或 `extras` 的存在
不等于已确认该题是交互题。显式交互提示会禁止本次 inline 样例回退；旧 inline 缓存
不会因此被冒充为交互附件或静默下载。

持久缓存按 QOJ origin、实际账号、比赛、题目隔离；清单包含资源类别、文件名、
准备时间、大小、整包与成员 SHA-256、样例对数和来源。前端不接收本地文件路径。

| 接口 | 行为 |
| --- | --- |
| `resource_manifest({sessionId})` | 纯离线读取当前 scope 已尝试过的题目；缺项仍是 unknown |
| `prepare_resource({sessionId,problemId,interactiveHint?})` | 认证原站 GET，复用 CLI 组织资源，成功写缓存；失败保留旧 good |
| `resource_chunk({sessionId,problemId,resourceId,offset,maxBytes?})` | 纯离线读取，返回 base64、偏移、EOF、整包及块哈希 |

整包上限 64 MiB，每块最多 256 KiB；浏览器校验身份、偏移单调性、大小、EOF、
每块与整包 SHA 后才生成 Blob 下载。题卡不再调用旧 `qoj_samples`，也不提供猜测的
QOJ 附件 href。旧 samples 单帧接口保留兼容，不代表新缓存下载仍受 512 KiB ZIP 限制。

## 已通过的浏览器与真实资源证据

隔离 Firefox 资源验收 run `1dc0a29b66334aaf819e8db48b3ae041` 的 12 项及 cleanup
全通过，归档于 [artifacts/resources-browser/accepted](../../../artifacts/resources-browser/accepted/)。
实际 UI 准备普通样例、extras-only 工具和 unknown，下载 ZIP 后逐字节核对；先在线
重载/选择比赛保留 UI 上下文，再关闭 fixture，manifest 与缓存下载没有新增 QOJ GET。
这证明文件可离线读取，**不证明整个工作台可以完全离线初始化**。

真实 QOJ 1051 / C / 5115 的 H3 样例标签提取缺口已修复。浏览器下载的
`samples-C.zip` 为 289 B，SHA-256 为
`38fe4d666be3dc94f7dd5289e31e72dd6c5b6c33b1dc2b949e521dfbb3dd827d`；
仅含 `samples-C/1.in` 与 `samples-C/1.ans`，内容均与预期精确匹配。

同题真实隔离导出的 `Clone-Ranran.pdf` 为 165025 B，SHA-256 为
`5f836b6b74cbd3572ce4f85ef9e555bcb278da9b701ef73926820afc46b85121`，
解析 URI 0、敏感 URI 0；中文、公式和样例已渲染核对。证据为
[PDF 审计](../../../artifacts/live-acceptance/real-C-pdf-host-audit.json)、
[文字检查](../../../artifacts/live-acceptance/real-C-pdf-text-checks.json)与
[首屏渲染](../../../artifacts/live-acceptance/real-C-pdf-page1.png)。

真实[长春比赛 4582](https://qoj.ac/contest/4582)原生 Start 表单旁的准备入口已完成
13/13 ready、unknown 0；新会话仍为 prepared、`startAt=null`，原生表单提交次数 0，
原 Start 保持启用，新增按钮在表单外。落盘证据见
[live-reopened-and-resources.json](../../../artifacts/live-acceptance/live-reopened-and-resources.json)。
这不证明未知后续服务端确认页接口，原生 Start 没有被点击。

附件原字节核验使用的是 **I / 22918**：

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `attachments-I.zip` | 4448 | `5b8ecc6f6d95dc3012eeb8ddd606c4b04b5b379004451c9934b0154a6a817387` |
| 独立 GET 的 `qoj-4582-I-original.zip` | 3651 | `5728eb852497a11d0a435cc5ecef34dfe7bc5643d2e10b459dafc6b12870ab13` |

原包含两对样例与 `triplet_testing_tool.py`；缓存包既保留标准化 `samples-I/`，也在
`attachment-extras/problem-I/` 下保留全部原始成员。独立原包逐成员比较全部字节一致，
不是只检查文件名。完整审计已归档为
[real-resource-artifact-audit.json](../../../artifacts/live-acceptance/real-resource-artifact-audit.json)，
状态全部 verified。
这些资源验证不增加 QOJ 源码提交或创建官方 VP。

## 早期调研记录的适用范围

早期只读内存 fixture 已确认：CLI 的下载层可保留 extras-only，原 CLI 落盘入口却会
拒绝空 samples；一次 404 返回空集并警告，空 200 可能得到 0 字节 attachment.bin，
空 ZIP 也不足以证明不存在。新缓存实现因此直接复用下载/组织函数并独立核验非空
资源，不把原 CLI `write_archives` 的限制当作新接口的附件能力。

此前通过网页工具读取的 [D / 22913 题面](https://qoj.ac/problem/22913)及其
[PDF 入口](https://qoj.ac/download.php?id=22913&type=statement)仅是公开线索：工具
解析可能来自缓存，当时没有本地 PDF 二进制、大小或 SHA，也没有主代理独立复核。
相关记录见[早期摘要](../../../artifacts/research/2026-11-01/ccpc-changchun-d-public-evidence.json)。
其中对交互题/对话样例的解释不能作为当前真实附件类型或 D 附件通过的证据；本次
经独立原包 GET 和字节核验的附件案例是 I / 22918。交互对话不能被自动拆成伪造的
普通输入/标准答案，这仍是资源回退的边界。

真实功能、当前源码核心视觉回归与诊断清理已通过，XPI/wheel 已生成；最终截图、
源码清单/source 包、交付复制与本地 commit 状态见验收记录。
