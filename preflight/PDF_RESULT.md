# Firefox PDF 补充验收

2026-10-31，来宾 Firefox ESR 140.16.0 / geckodriver 0.37.1。结果在 `artifacts/pdf-smoke/accepted/summary.json`，原始来宾归档和渲染预览保存在同目录。

`guest_pdf_audit.py` 只读提取了已安装 Firefox `browser/omni.ja` 的 `ext-tabs.js` 与 schema；实际实现先调用文件选择器，再调用 `browsingContext.print` 写出 PDF。

`guest_pdf_smoke.py` 在唯一临时 profile 和独立测试扩展中，调用真实 `browser.tabs.saveAsPDF`。唯一测试替身是来宾浏览器进程内的 `nsIFilePicker`：返回选定路径、取消或错误目标。Firefox 扩展 API、输出流与 PDF 引擎保持原实现。geckodriver 的 `--allow-system-access` 仅授权此无界面 QA 进程注册测试文件选择器，不改变用户 profile 或常规 Firefox 设置。

| 场景 | 实测结果 |
| --- | --- |
| 文件选择器确认有效目标 | `saved`，75,302 字节、有效 `%PDF-` 文件 |
| 文件选择器取消 | `canceled`，未创建目标文件 |
| 把已有目录作为文件目标 | `not_saved` |

PDF SHA-256：`95572c718ef5f2f8613c49a4086dcc610421b8612ce5d682e24b323bd08663ab`。Poppler 渲染后已检查中文、MathML 分式、样例输入输出；打印 CSS 隐藏的屏幕元素未出现。PDF 为一页 A4，生成器 Mozilla Firefox 140.16.0。数学字体的文本提取有替代字符，视觉渲染正常；不把文本提取等同于排版验证。

Firefox PID 12019 已退出。未注册或替换任何 Native Messaging host，未访问 QOJ 或提交源码。未启动可见窗口。

前两次启动因特权参数位置不正确而失败；第三次已保存 PDF 并验证取消，但“父目录不存在”不能作为写入失败条件，因为 Firefox 会创建目录。修正为已有目录后，最终三项全部通过，失败尝试记录也保留在 artifacts 中。

复现：在已部署来宾项目中运行 `/usr/bin/python3 -B preflight/guest_pdf_smoke.py`，依赖仍使用项目内 `preflight/vendor_py` 和 `preflight/tools/geckodriver`。检查 `results/pdf-smoke/summary.json` 的最终状态与进程退出记录；`running` 是中间状态，不能据旧结果重启任务。

此补测覆盖 Firefox PDF API 与引擎，不覆盖生产 `problem.pdf` 整条消息链、真实 QOJ 题面的数学公式/分页，或人工操作 OS 文件选择器。后者仍与真实账号验收一起保留。
