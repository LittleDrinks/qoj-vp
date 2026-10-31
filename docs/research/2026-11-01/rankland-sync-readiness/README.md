# RankLand 无队名入口的同步就绪调查

2026-11-01 重新只读 GET `https://vp.xcpc.link/`，HTML 仍引用
`/assets/index-ad07c00e.js`。实际下载 1,068,201 字节，SHA-256
`9121b4ca71c23a3edf48c5b3e858f7e5d62117a011837dc4ec3bc6c6b9b2916e`，
与已有 `preflight/rankland-fixtures/assets/index-ad07c00e.js` 完全相同，
因此没有重复保留另一份 bundle。

实际源码证据：

- `yd(query)` 约字符偏移 588327：`team` 默认空字符串；队名最多 80 字。
- `vp.view` 初始化约 1050250：从 URL 的 `team` 初始化 `ownName`，然后恢复已有本地存档。
- 渲染约 1052350：题目、结果、提交时间和“记录提交”这一整组控件受
  `p.value`（本队名称）条件控制；队名为空时只有“加入我的队伍”入口。
- `ye()` / `_e()` 约 1048120：原生队伍表单打开后，“加入”将输入队名放入原站内存、
  重算榜单并调用原站自身保存逻辑。无需外部改写 localStorage/Vue。
- 旧产品 `vp.rankland.ready` 要求题目下拉已经存在，未建立本队；
  旧 `guest_mvp.py` 的验收 URL 始终预置 `team=qoj-vp-mvp-...`，未覆盖普通无队名 URL。

源码确定存在覆盖缺口，但不据此声称已复现用户本人当时的标签页状态。
根代理观察该本地会话当时没有源码操作、已知提交或同步队列；原标签页随后已不存在。
因此验收采用独立 Firefox profile、GET-only QOJ fixture 和唯一 RankLand run。

运行真实窄回归：

```sh
python3 -B preflight/guest_rankland_readiness.py --mode reproduce
python3 -B preflight/guest_rankland_readiness.py --mode verify
```

第一条要求旧产品真实返回 `page_not_ready`、原站已加载但 `ownName` 为空且不存在题目下拉。
第二条验证真实原站队伍表单准备、GET 历史中的一个合成判定投递、重开后保留已有自定义队名和单一记录。
根代理已在实际 VMware Firefox 运行第一条，run
`ec5307b69085472b9fd1c130eed077f6`，结果 `reproduced`：页面完成加载且无原站错误、
唯一 version 2 存档正在约两小时处运行，manual 为零、ownName 为空，
原生“加入我的队伍”按钮一个、题目/结果下拉均不存在；旧产品返回原始
`page_not_ready`。原版首次使用提示此时也正显示。

候选修复只在同一存档身份且唯一原站标签页的 guard 通过时，使用原站已知 OK
关闭首次提示，再经“加入我的队伍”表单填入该本地会话已确认的 QOJ 账号并点击“加入”。
观察原站保存了队名、manual 未变、题目/结果下拉已出现后才继续同步。
已有任何非空原站队名均不改写；不直接写 localStorage/Vue。
只读就绪查询新增明确原因，加载失败与缺少队名不再共用无区别的诊断。
修后实际运行结果仍以根代理收取的 `--mode verify` VM 报告为准。

`preflight/rankland_readiness_probe.py` 提供可用于受影响页面的只读安全探针；
不返回账号、队名、完整 URL、任意网页文本或提交数组，不写存储、不点击、不打开标签页。
