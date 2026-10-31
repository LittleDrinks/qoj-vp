# QOJ 赛前资源入口与缓存前端

2026-11-01。只支持已在当前主站实际观察到的表单，不推断未观察到的后续确认流程。

## 原站证据与边界

Root 在 VM 已登录的普通 Firefox 中，以只读 DOM/GET 方式取得 QOJ 4.5.48
`/contest/4582` 的以下结构：`form#form-regvir`，method 为 POST，action 为
`/contest/4582`；有隐藏的 `input[name=_token]`；原生开始按钮是
`button#button-submit-regvir[type=submit][name=submit-regvir]`，文案 `Start!`。
表单父元素为 `div.card-body`。其关联短脚本只处理提交锁按钮，没有观察到客户端确认弹窗。
未点击 Start、未提交该表单，故不能宣布已确认它之后的服务端确认页面或接口。

[官方更新日志](https://qoj.ac/blog/qingyu/blogs/631)记载曾增加 VP 注册确认列表，
但这不是当前 4.5.48 开始接口的完整契约。旧 UOJ 源码及 training 子站不替代主站证据。

`qoj-prepare-content.js` 仅在 HTTPS `qoj.ac/contest/<数字cid>` 顶层页面、且上述
确切表单结构成立时，给原生 form 添加一个**相邻元素**。两个新按钮均为
`type=button`；不改原生 form、action、token、Start 按钮或提交处理器。MutationObserver
仅让这个已知入口在 DOM 重新生成后恢复，未知表单不猜测、不注入。

## 资源专用消息

内容脚本只发送 `vp.resources.prepareContest` 和 `vp.resources.openContest`。
后台逐次检查 extension sender ID、顶层 frame、真实 tab URL、HTTPS origin、contest
路径与 cid。准备先通过现有 `qoj_contest` GET 读取当前认证账号和题表，再按同账号/cid
复用会话，prepared 优先；仅有 running 时复用它且保持原计时。没有可复用会话才建立
无 `startAt` 的 prepared 会话，默认时长 300 分钟。

准备 job 以账号/cid 合并，已有 ready 包默认复用；其余逐题调用 `prepare_resource`。
只发送计数进度，失败保持 unknown，旧 good 包由缓存模块保留。不调用原生 VP
注册、开始、结束，也不调用源码提交。这个 job 不是常驻 HTTP 服务。

“打开题目文件”再次验证当前账号/cid，仅打开匹配会话的
`ui.html?session=<UUID>&resources=1`。UI 完成正常初始化和会话选择后才打开资源弹窗，
不会调用 Start。Home 的准备资源弹窗仍是独立回退入口。

## 清单读取与下载

资源清单读取有真实 `resourceReading` 状态。开始读取即禁用准备、刷新和交互题勾选，
只有当前会话/序号的读取 finally 才解锁。只读验收接口暴露这个 flag。
这修复了首轮 VM run `373c61fb1e174765919c6f311dd4a2f3` 中：弹窗已显示、清单
Promise 仍未完成时，旧 tr 可被点击，随后整批 tr 被替换而产生 stale reference 的竞态。

题卡只按清单正向 ready 事实显示 samples 或附件；unknown 不显示下载按钮。
准备/重试集中在资源弹窗，ready 默认复用，只有明确刷新才重新读取 QOJ。
交互题勾选只来自用户或明确元数据，不能由 extras 推断；显式交互题不下载旧的
`inline-statement` 包。缓存下载只走 `resource_chunk`，没有猜测的 QOJ URL；每块
最多 256 KiB，WebCrypto 校验分块与整包 SHA-256、单调 offset、总大小/EOF/资源身份，
整包上限 64 MiB。任一不一致不生成下载文件。

## 窄验收与实际限制

```sh
node --check extension/ui.js
node --check extension/background.js
node --check extension/qoj-prepare-content.js
node preflight/test_ui_resources.cjs
node preflight/test_qoj_prepare_entry.cjs
node preflight/test_ui_history_notice.cjs
```

VM 内由 root 运行：

```sh
python3 preflight/guest_resource_cache.py --project /path/to/guest/project
```

可另传 `--configuration /path/to/rendered/configuration.json`。该脚本使用独立
临时扩展 ID/native host/profile/download 目录、GET-only fixture，真实 UI 准备普通
样例和 extras-only interactor、下载 ZIP 并核对原字节；在在线 reload/正常选择会话后
关闭 fixture，再验证离线清单/文件读取无新增 QOJ 请求。它不宣布整个工作台已能
完全离线初始化。弹窗先等待 `resourceReading=false` 和真实 Bootstrap shown 完成，
再 fresh query/单次 click；关闭复用 `VisualHarness.close_modal` 等待 backdrop 清理。
不 catch/reclick 来掩盖 stale。

账本保留全部历史；Home 默认只显示本次时间窗内提交与本地 operation，旧原生 VP
记录不再挤满默认表。越窗本地操作仍可核对，time 显示“—”并在提示中保留绝对日期。
大量未核实时间 warning 压缩为一条计数中文说明，其余读取缺口归并短提示；
“原站记录”提供当前比赛/账号的完整原生历史入口。

实际隔离 Firefox 资源 run `1dc0a29b66334aaf819e8db48b3ae041` 的 12 项及 cleanup
已通过，归档 `artifacts/resources-browser/accepted/`。认证普通 Firefox 中，长春 4582
原生 Start 旁入口也已完成 13/13 ready、unknown 0；会话 prepared、startAt null，
原表单 0 次提交、原 Start 仍启用。证据
[live-reopened-and-resources.json](../../../artifacts/live-acceptance/live-reopened-and-resources.json)。
真实附件核验为 I/22918，包含 `triplet_testing_tool.py` 和原样例，独立 GET 原包的每个
成员字节均保留；[完整资源审计](../../../artifacts/live-acceptance/real-resource-artifact-audit.json)
全部 verified。旧 D/22913 的工具 PDF 线索不作为此次附件通过证据。
