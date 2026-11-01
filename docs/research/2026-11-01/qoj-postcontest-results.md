# QOJ 赛后附加测试判定

2026-11-01 对用户指出的比赛 `1051`、题目 `5114`（B）进行了只读核对：

- `https://qoj.ac/submission/1511578`
- `https://qoj.ac/submission/1511566`
- `https://qoj.ac/contest/1051/submissions` 的本人记录

真实已登录 GET 的三个页面均返回 200。安全 DOM 保存在本地
`artifacts/resource-split/dual-verdict.json`，仅保留判定表格与 Details 结构，采集时已剥除
源码、测试输入输出、表单、脚本、CSRF 与 Cookie。该文件不进入源码包。
采集过滤器没有保留 `datetime` 属性，因此这份回放仅证明判定解析，不能用于验证绝对提交时间。

## 真实页面结构

两条提交在历史列表及详情页摘要中的 Result 都是同一个链接内的两个 span：

```html
<a href="/submission/1511578"><span>AC</span><span>, TL</span></a>
```

这里没有 `uoj-score` 或 `data-score`。不能要求数值分数存在，也不能将第一个 AC 当成
当前通过。`BeautifulSoup.get_text(' ', strip=True)` 得到的是 `AC , TL`，需要兼容分隔符两边空格。
普通提交仍可能使用 `a.uoj-score[data-score]`；同页的 `3331061` 是正常 `AC ✓`、100 分，未作修改。

两个 Details 卡片都先出现 **22 个 Accepted 测试结果**，随后在
`#details_details_accordion` 的最后一个测试卡片头部出现：

```html
<div class="card-header" data-toggle="collapse"
     data-target="#details_details_accordion_collapse_test_-1_Test">
  <div class="row">
    <div class="col-sm-2"><h4 class="card-title">Extra Test:</h4></div>
    <div class="col-sm-2">score: -3</div>
    <div class="col-sm-2">Extra Test Failed : Time Limit Exceeded on 4</div>
    <div class="col-sm-3"></div><div class="col-sm-3"></div>
  </div>
</div>
```

因此，本例的赛时 AC 与当前附加测试失败同时存在。`score: -3` 是测试卡片中的字段，
本项目不把它解释为提交总分。当前完整结果为 `TIMELIMIT`。

## 解析与同步规则

`qojvp/history.py` 接受严格的两项逗号结果：两项均能识别时采用第二项。`AC, TL` 映射为
`TIMELIMIT`，`AC, WA` 为 `WRONG-ANSWER`，`AC, Pending` 为 `JUDGING` 且 `pending=true`。
未知词、空项、更多项或其他分隔形式保持 `UNKNOWN`，不回退到旧 AC。
`TL` 与 `ML` 的缩写也见 [Universal Cup 官方提交规则](https://ucup.ac/zh/rule/2025-2026-season-rules/#submissions)。

详情解析识别完整的 `Extra Test Failed : <失败判定> on <测试编号>` 包装，只接受已知失败类型；
未识别的附加测试失败仍保存原文并保持 `UNKNOWN`。前面的 Accepted 测试和旧的 100 分不能
覆盖后面的失败或未确认状态。

每条记录用 `historyResult` 保存列表原文、数值分数和解析结果，`verdictSource` 标明
`history-result` 或 `submission-detail`。Application 仅对仍为 `UNKNOWN` 的数值非满分结果
继续细化；列表已经明确是 TL/WA 时，训练模式隐藏详情不会再把它降回未知。

修订按原 account/SID 更新同一条事实，本地进度使用当前判定。RankLand 队列沿用原
`queueId` 与来源 ID，未投递结果可更新为当前判定；已经投递的 AC 若变更，则保存旧回执，
标记 `rejudge` 与 `needs-review`，拒绝旧 revision 的 ACK。重复刷新不会新增提交或反复增加 revision。
RankLand 桥接对此返回需要核对，**没有自动删除或改写原站已录入记录的实现**，也不会把重判
追加成一条假提交。

## 回归证据

`tests/test_history.py` 包含由上述真实结构缩减的 `mixed_schema_history`、`extra_test_details`：

- 无数值分数的双 span 结果，以及 `TL`、`WA`、`Pending` 的对应状态；
- 早期 Accepted 后出现附加测试失败，传入旧 100 分也必须得到失败；
- 无法识别的附加测试失败不能恢复成 AC；
- 经真实 Application 入口、隔离 HTTP fixture 和 SQLite 队列验证修订、回执保留、去重、旧 ACK 拒绝，
  以及全部请求没有提交 POST；
- 列表已有明确失败而详情不可见时，判定不被覆盖。

红测试复现了旧详情解析器将该失败在旧 100 分条件下返回 `CORRECT`；修复后用完整安全 DOM
再次回放，两个 SID 的历史与详情均为 `TIMELIMIT`，`3331061` 仍为 `CORRECT`。
本地回放结果：`artifacts/resource-split/dual-verdict-parser-check.json`。

可重复执行：

```sh
PYTHONPATH=preflight/vendor_py python3 -m unittest tests.test_history tests.test_application -v
```

`preflight/vendor_py` 是当前工作区的依赖目录；GitHub CI 安装项目依赖后直接执行 unittest。
这些回归不启动正式 QOJ VP、不提交源码、不更改真实提交，也不写入用户的 RankLand 榜单。
