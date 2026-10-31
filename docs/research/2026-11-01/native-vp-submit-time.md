# 原生 VP 提交时间兼容与详情回填

2026-11-01。当前实现已能为部分只有相对显示时间的旧原生 VP 提交核实绝对时间；
无法核实的记录仍不进入当前练习进度或 RankLand 队列。没有从 `HH:MM:SS` 反推
QOJ 官方 VP 起点，也不创建、开始或结束官方 VP。

## 证据来源与实现

[history.py](../../../qojvp/history.py) 只接受详情页同一表格中唯一匹配的记录：SID、
owner、contest/problem 链接和 `Submit time` 列内带时区的 `time.uoj-time[datetime]`
必须同时成立。执行时间列、页脚时钟、其他记录时间、无时区值及歧义/错配均不能
提供提交时间。通过后记录 `timeSource=provider-absolute` 与原始带时区时间证据。

[application.py](../../../qojvp/application.py) 的生产 refresh 先保留当前已知事实，
再对 running 会话中缺时间的记录作受限历史探测：每次 refresh 至多三条，优先未尝试
和最早重试，失败负缓存 60 秒，成功事实持久复用。prepared 会话不触发此探测，
显式核对优先指定 SID；补时间不自动关联未知 intent，也不改变本地会话起点/窗口。

真实旧原生提交 `1511772` 已由生产 refresh 回填为 `2025-10-14T21:37:53+08:00`。
[native-time-backfill-proof.json](../../../artifacts/live-acceptance/native-time-backfill-proof.json)
核实时间来源为 provider-absolute、源码操作总数仍为 1、当前队列仍仅包含
`3331061 / synced`。旧记录有了绝对时间也不会被当成本次会话的新提交。

Python 完整 63 项测试通过；时间回填测试包含详情身份/时区边界、持久复用、负缓存、
公平轮转、prepared 不探测与指定 SID 优先。日志
[backend-final-tests.txt](../../../artifacts/backend-final-tests.txt)。

## 早期限制的更新

早期 [native-vp-relative-time-compatibility.json](../../../artifacts/research/2026-11-01/native-vp-relative-time-compatibility.json)
仅验证了“有本地已确认时间则保留；外部仅有相对时间时不入队”。它是旧受控 fixture
的观察，不应再解释为当前实现永远不能同步原生 VP 提交。当前增加了严格详情时间
核验这一路径；当详情不含可验证时间、身份不匹配或读取失败时，旧的保守边界仍成立。

真实验收没有额外源码 POST，不是官方原生 VP 全生命周期管理的证明；完整验收与
交付状态见 [MVP_RESULT](../../MVP_RESULT.md)。
