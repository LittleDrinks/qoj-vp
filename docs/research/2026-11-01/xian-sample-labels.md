# 西安 2022 七题样例准备失败

QOJ contest 1051 的资源诊断显示：A、B、C、H、L 已有的缓存包能完整分块读取，整包与
每块 SHA 校验通过。D、E、F、G、I、J、K 的最近准备结果为 SAMPLES_UNAVAILABLE，
没有生成缓存包。错误发生在题面样例提取，不是已准备 ZIP 的下载权限。

通过当前 Firefox 登录态只读请求了这些题的默认页与页面明确提供的语言链接。
七题均有中文 HTML 题面，结构为激活 tab 中的 `article.uoj-article.top-buffer-md`：

```html
<h3>样例</h3>
<h4>样例输入 1</h4><pre>...</pre>
<h4>样例输出 1</h4><pre>...</pre>
```

旧规则只识别 `输入 1 / 输出 1`，遗漏了前面的“样例”二字。
修复只增加这两个已验证的 H4 标签形式；仍要求样例节、紧邻的纯文本 PRE、唯一编号和完整配对，
不抓解释代码、非激活 tab 或未知嵌套控件。

| 题目 | QOJ pid | 完整样例组 |
| --- | --- | --- |
| D | 5116 | 1 |
| E | 5117 | 1 |
| F | 5118 | 3 |
| G | 5119 | 1 |
| I | 5121 | 2 |
| J | 5122 | 2 |
| K | 5123 | 1 |

七题共 11 组的解析结果逐字节匹配现场 PRE 文本（沿用已有换行规范）。先增加测试复现
解析空结果以及 prepare_resource 返回 unknown，再修正生产规则，提取与资源生成测试转绿。
语言回退的六项原有测试也通过。没有真实 QOJ 源码 POST、官方 VP Start/Finish。

本地证据：`artifacts/resume-diagnostics/xian-cache-probe.json`、`xian-structure.json`、
`xian-parser-red.txt`、`xian-parser-green.txt`、`xian-language-green.txt`、
`xian-parser-real-replay.json`。页面采集只保留公开题面和语言链接，不保存请求凭据。
修复后在常用 Firefox 登录态重新准备了这七题，12 题均为 ready；逐题读取全部缓存分块，
整包及成员校验全部通过，结果见 `artifacts/resume-diagnostics/xian-cache-after.json`。
手动添加样例是独立的管理员能力，不替代这次解析错误的修复。
