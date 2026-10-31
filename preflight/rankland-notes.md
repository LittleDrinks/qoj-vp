# RankLand Firefox ESR 前置测试

本目录的代码由主代理放入 VMware 虚拟机内执行；研究代理未操作 VM、Windows 焦点、Firefox 或真实用户存储。本地仅做 Python/JavaScript 语法与导入检查。**浏览器结论以主代理在 VM 中生成的结果文件和截图为准。**

## 文件与依赖

- `rankland_probe.py`：只接受已经创建的 Selenium Firefox driver，不安装或启动浏览器。
- Python 标准库与 Selenium；不需要 requests、Chrome、Playwright 或后台 Python HTTP 程序来连接真实站点。
- `rankland-fixtures/`：网络不可用时的静态 fixture。需要由主代理提供一个临时静态 HTTP server；这个 server 仅用于前置测试，不是产品架构要求。
- 必须使用独立测试 profile；建议路径包含 `qoj-vp-preflight`。函数会检查 Firefox 的 `moz:profile`，不满足标记时默认拒绝运行。若 Selenium 自动创建临时 profile，由主代理确认与用户 profile 隔离后可明确传 `allow_unmarked_profile=True`。

## 两阶段调用约定

第一阶段由主代理创建 driver 后调用：

```python
from rankland_probe import run_rankland_probe

result = run_rankland_probe(
    driver,
    "/path/to/persistent/preflight-results/rankland",
    fixture_url="http://<Firefox可达主机>:<独立端口>/",
)
```

默认先打开真实原站 `https://vp.xcpc.link/`，比赛为 `icpc2025nanjing`。只有真实页面加载失败、并且提供了 `fixture_url`，才切到离线 fixture；联网失败证据会单独保留，不会因 fixture 成功而改写为真实联网通过。

第一阶段成功状态为 `phase1_passed_restart_pending`，返回 `restart_manifest`。主代理随后：

1. 记录并正常执行 `driver.quit()`。
2. 使用**同一持久化的独立测试 profile** 重新启动 Firefox ESR，取得新的 driver；不能只刷新页面或重新开标签页。
3. 调用第二阶段：

```python
from rankland_probe import resume_rankland_probe

result2 = resume_rankland_probe(driver2, result["restart_manifest"])
```

第二阶段读取第一阶段 manifest，核对 `moz:processID` 已改变，再验证进度、manual、榜单本队行和本地投递 receipt。若缺少 PID、仍使用原 Firefox 进程、或 profile 未保留存储，会明确失败，不声称已经证明跨进程恢复。

函数不清理任何测试存档、不关闭主代理原有控制标签页，也不代替主代理退出 Firefox。第一阶段留下 run A 的暂停页面作为重启检查点；主代理可在全部证据保存后处理独立测试 profile。

## 第一阶段实际验证内容

1. 为每次调用生成唯一 `qoj-preflight-<nonce>-a/b` 两个 run 和唯一测试队名。
2. 使用原站现有参数 `from=120&play=1` 初始化两小时进度，避免实际等待两小时，也避免直接写 localStorage 冒充持久化。
3. 在同一比赛、同一规则、同一起始时间下，验证 run A/B 的真实存档 key 和本队信息分离。
4. 用原站真实“题目/结果/提交时间”表单记录一条 **synthetic 已判 AC**，核对原站保存的 manual 与实际渲染的本队行（解题数为 1）。这条记录不是 QOJ 真实提交，测试不会访问任何 QOJ/Codeforces 提交表单。
5. 使用同一 synthetic source ID 重试适配函数，凭本地 receipt 核对后跳过重复投递；确认另一 run 未被修改。
6. 关闭原 VP 标签页，打开准确 URL 的新标签页，确认两小时进度、原 manual 和本队行恢复。
7. 通过原站“暂停”按钮保存稳定检查点，导出重启 manifest。

所有站点存储操作都是只读 `getItem`/键查询。进度、暂停与手动判定的写入由原站现有初始化/表单/控件完成，没有 `localStorage.setItem` 注入，没有访问 Vue 私有状态。

全新 profile 会出现“现可自定义榜单的显示样式！”引导弹窗。harness 在表单操作前点击该弹窗内原有的 `OK` 按钮，等待原站自己保存已读标记并关闭弹层；同时处理榜单先渲染、引导后挂载的 race。不会移除遮挡 DOM 或直接修改已读存储。只有明确的 click-intercepted（目标未收到点击）才重试目标点击，不因提交回执暂缺就再次点击“记录提交”。结果中的 `ui_events` 保留真实引导确认操作。

## 去重证据的准确范围

`deliver_synthetic_result()` 是测试用的表单适配函数，不是产品自动同步功能，也不是原站稳定接口。它检查原始目标记录并把本次投递的观测保存到 `rankland-delivery-receipts.json`。

- 有本地 receipt 且目标记录、本队行仍匹配时，跳过重复点击。
- 目标已经存在同题/同时间/同结果、但没有本地来源 receipt 时，返回 ambiguous，不盲目再追加。
- 原站 manual 没有 source submission ID；这些检查不能赋予它 exactly-once 语义。
- 不覆盖通用 WA 重复、重判修正、多写入者并发或桥接版本变化；这些仍是后续产品设计与回归范围。
- 当前网页的过往提交时间输入只有时/分，fixture 使用恰好 120 分钟的 synthetic 时间；不假称已验证毫秒级导入。

## 离线 fixture 服务约定

使用一个独立 HTTP 端口，把静态 docroot 直接设置为本目录的 `rankland-fixtures/`，使页面从 origin 根路径 `/` 打开。例如主代理可以使用 Python 的静态文件服务器，或现有测试 server 的独立站点。

不要把这个应用挂到 `/rankland-fixtures/` 子路径：当前上游 router 仅配置 `/`，worker 和字体也使用 `/assets/` 路径。

fixture 包括：

- 原站未修改的 `index-ad07c00e.js`、`index-99fb3111.css`、rank-time worker 和字体。
- `fixture-network.js` 在应用启动前改写 XHR/fetch 的网络响应，让公开比赛信息、SRK 文件信息和 SRK 文件来自本地 JSON；禁止非 GET XHR，并在测试环境截获仅用于在线人数的 presence 请求。
- `feed.srk.json`：最小合成 SRK 0.3.9 ICPC 五小时比赛，两个题目、两个虚构历史队伍。它不是 QOJ/ICPC 实赛数据。
- `upstream-assets.json`：上游来源、字节数和 SHA-256。
- `live-reference.json` 与 `reference-srk.json`：本次确实通过公开 GET 取得的真实比赛参考数据，保留来源；**fixture 使用的是另一个合成 feed**，不会把这些真实队伍冒充测试队伍。

主 bundle SHA-256：

```text
9121b4ca71c23a3edf48c5b3e858f7e5d62117a011837dc4ec3bc6c6b9b2916e
```

真实联网数据来源：

- [比赛信息](https://rl.algoux.cn/api/v2/public/contests/icpc2025nanjing)
- [文件信息](https://rl.algoux.cn/api/v2/public/files/94031839248867328)
- [SRK CDN](https://cdn.algoux.cn/rankland/file/94031839248867328/icpc2025nanjing.srk.json)
- [原站当前应用代码](https://vp.xcpc.link/assets/index-ad07c00e.js)

## 结果文件

- `rankland-phase1-result.json`：各项检查、真实联网尝试及 live/fixture 模式。
- `rankland-restart-manifest.json`：准确恢复 URL、测试 run/队名、暂停检查点和第一阶段 Firefox PID。
- `rankland-phase2-result.json`：PID 改变、同 profile 存储恢复与 receipt 去重检查。
- `rankland-*.json` / `rankland-*.png`：初始两小时、表单投递、新标签页恢复、重启检查点、Firefox 重启后的实际状态和截图。

失败返回 `status=failed`，附错误和 traceback；不能只依据 Python 进程退出码判断前置测试通过。最终验收需要同时检查 phase1 的成功且待重启状态、phase2 的 `passed` 以及 mode。`synthetic_feed_upstream_renderer` 证明的是上游代码在 ESR 的行为，不证明 VMware 到公网 API/CDN 的网络可达性。

