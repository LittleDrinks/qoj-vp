# QOJ / VP 工作台调研汇总

日期：2026-10-31。当前是调研与架构讨论，没有开始扩展产品开发，没有发送 QOJ / Codeforces 提交，也没有改动用户的 RankLand 存档。

## 已确定的产品方向

- Firefox 扩展打开完整工作标签页；Home / Submissions 与 Problemset 尽量复用 DOMjudge 上游界面和交互。
- Problemset 每题提供题面、独立 samples 和预选题目的 Submit 入口。
- 第一版 Scoreboard 打开或切回 vp.xcpc.link；DOMjudge 样式榜单后续再定。
- Python 助手按操作启动并结束，不要求手动维护常驻服务器。
- qoj-submitter 保持独立仓库，通过 submodule 固定版本并直接复用库代码；Codeforces / Gym 使用独立适配模块。
- CLI 帮助排版可以在现有 argparse 上使用 rich-argparse，保持已有命令兼容。

## VMware 已验证的控制方式

已连接当前运行的 `hydro contest os.vmx`，并通过 VMware Tools 完成认证后的来宾命令执行、只读诊断文件取回及来宾截图。无需依赖来宾桌面键盘输入；SSH 本次未连通。

实际环境：

| 项目 | 结果 |
| --- | --- |
| 宿主 VMware | Workstation 26.0.1 build-25688693 |
| 来宾 | Ubuntu 24.04.5 LTS，kernel 7.0.0-42-generic |
| 桌面 | Xorg + GNOME Shell / Mutter 46.2 |
| Python | 3.12.3 |
| Firefox | Debian 包 firefox-esr 140.16.0esr；桌面入口 Exec=firefox-esr |
| Firefox 配置目录线索 | ~/.mozilla/firefox-esr/ |
| 共享目录 | 宿主 E:\shared；来宾 vmhgfs-fuse 挂载在 /mnt/hgfs，配置共享名 shared |
| 比赛提交器 | /usr/local/bin/submit，官方 DOMjudge Python 客户端 |

用户提供的 vm-input 可以参考，但它默认指向另一台 Ubuntu，默认用户也不同；start/type/key 路径会启动 ydotoold，本次没有运行这些路径。调研使用 VMware Tools 直接执行诊断命令。

用户要求后台静默后，已停止前台激活、窗口大小调整、菜单输入及前台截图。后续工具调用应继续遵守这一要求。 后续一次 VMware Tools 后台截图返回成功，并检查到 Windows 前台窗口句柄保持不变。

## 黑屏排查与恢复

同一次故障期间，宿主 VMware 控制台近乎全黑，而 VMware Tools 抓取的来宾桌面正常；Xorg 和 GNOME 仍运行，所检查的来宾显示日志未发现对应崩溃。

| 检查 | 宿主画面区域黑色比例 | 来宾截图黑色比例 | 结论 |
| --- | ---: | ---: | --- |
| 黑屏基线 | 0.99888 | 0 | 宿主呈现失败，来宾仍在生成画面 |
| 临时设为 1920×1080 | 0.99867 | 0 | 降低分辨率未清除当前故障 |
| 挂起 / 恢复后 | 0 | 0 | 当前显示已恢复，登录会话保留 |

黑色统计是固定截图区域的抽样，不等于完整图像一致性测试。

第一次挂起返回通用 Unknown error；VMware 日志明确原因是保存状态空间不足，提示另需约 139 MB。当时 E: 实际可用约 5.6 GiB。用户清理空间后，第二次挂起和恢复均返回成功。没有为此删除用户文件。

宿主日志确认使用 Vulkan renderer 和 Vulkan presentation，用户偏好 `pref.remoteMKSHardwareAccel = TRUE`。这把问题范围缩小到宿主呈现通道，但尚不能确认具体驱动缺陷，也没有本机 VK_ERROR / DXGI device-removed 的证据。

可回退的后续候选方案：在 VMware 的“编辑 → 首选项 → 显示”中，取消“允许为所有虚拟机控制台启用硬件加速”，保留虚拟机自己的 3D 加速。Broadcom 员工说明了该开关与 Vulkan / DX12 presentation 的关系；是否需重开控制台应以实际后端日志和画面验证。此全局偏好本次尚未改动。

当前只能称为故障定位与显示恢复；反复切换窗口大小 / 分辨率的持久修复回归尚未完成。用户要求后台静默后不再为了验证而切换其窗口。

## submit 可以复用什么

来宾脚本与 DOMjudge 9.0.0 / 9.0.1 的 `submit/submit` 字节一致：20,652 字节，SHA-256 `9dddeea4a7647d17ac1eedb7b7c0459869da0c36f14fd6a1327f8273212c3b6a`。

适合复用或作为回归基准的是文件检查、题号 / 语言 / 入口点推断、提交确认和回执交互。它使用 DOMjudge 的接口，不能直接用于 QOJ / CF；没有 `--json`、判定轮询或 VP 生命周期，顶层还有参数解析与执行逻辑，不能直接 import 为助手库。

系统自带 submit 保留。Native helper 应直接调用 qoj-submitter 的客户端与样例模块，并将数据、进度输出和 Native Messaging 协议分开。QOJ 个人提交列表与判定采集仍需补齐。

## RankLand 的保存机制更正

本次实际下载当前 bundle `index-ad07c00e.js`。进度在 localStorage 的 `RanklandVP2:...` 键中；sessionStorage 的 `RanklandVP:presenceSession` 只是在线人数标识。之前交接将两者混淆，不能继续沿用那个结论。

恢复依赖比赛及 run、规则、起始时间等配置。当前未发现统一的历史会话列表；默认 run=default，重置会覆盖当前槽。关闭标签页不是暂停，恢复时会根据 savedAt、running 和倍速补算时间。

用户旧记录的真实存储尚未读取，不能声称已经丢失或已经恢复。检查旧记录前应先备份目标 origin 的相关存档，避免用不匹配的页面初始化状态覆盖旧值。

当前 manual 只有题号、时间和判定，没有原 OJ submission ID；页面初始化才读取存档。直接改 localStorage 不能保证实时榜单更新，还可能被原页面自动保存覆盖。原站表单 / 消息桥接仍待实际验证。

## 解耦生命周期建议

| 模块 | 管理的事实 / 接口 |
| --- | --- |
| 会话与提交账本 | 稳定 sessionId、比赛 / 账号 / 题号映射、原站开始时间、完整恢复 URL、提交回执和同步队列 |
| 平台适配 | QOJ / CF 的题表、样例、提交、历史与判定；返回原始事实 |
| RankLand 兼容 | 恢复原站视图、消费已确认提交、核对同步结果；失败不阻塞 OJ 提交 |
| 扩展控制与视图 | 用户操作、页面状态、按需助手连接、浏览器请求通道；不把 tabId 当会话身份 |

建议由按需 native helper 管理本机用户目录中的 SQLite 账本，扩展保留缓存和视图入口。每次操作持久化后退出；时钟使用时间锚点补算，不靠常驻 Python 计时。数据库放来宾本地用户目录，研究材料和安装包通过共享目录交换。

VP 核心状态可用 `draft → prepared → starting → running → finished → archived`；标签页开关、网络状态、查询覆盖与榜单同步状态分别保存。RankLand 回放暂停不代表 QOJ / CF 的原站 VP 暂停。

提交以 `platform + account + submissionId` 标识。关闭页面时未取得回执的提交标为 unknown，先查原站，不自动重复 POST。CLI 独立提交可以在恢复时通过原站历史分页补查汇入，CLI 无需依赖扩展正在运行。

RankLand 同步使用独立的待处理队列，保留去重、重判、读回核对和歧义状态。原站没有 source ID，不能凭空保证 exactly-once；同步失败不会撤销真实提交，也不应导致再次提交源码。

## 建议下一轮先验证的内容

1. 在实际 Firefox ESR 中完成一次按需 Native Messaging 往返，并确认任务结束后助手退出。
2. 验证浏览器请求通道与 QojClient 的可替换 session，保持当前浏览器登录体验。
3. 建立最小持久会话目录和完整恢复入口，验证关闭页面 / Firefox 后恢复。
4. 接题表、单题 samples、提交回执和判定补查，再独立接 CF / Gym。
5. 在指定练习会话上验证 RankLand 真实记录入口；首版榜单继续使用原站。

以上是实施建议，尚未开始产品实现。

## 分项报告

- [rankland-vp-lifecycle-research-2026-10-31.md](rankland-vp-lifecycle-research-2026-10-31.md)
- [qoj-vp-lifecycle-architecture-2026-10-31.md](qoj-vp-lifecycle-architecture-2026-10-31.md)
- [domjudge-submit-reuse-research-2026-10-31.md](domjudge-submit-reuse-research-2026-10-31.md)
- [vmware-display-research-2026-10-31.md](vmware-display-research-2026-10-31.md)

显示证据：[故障时宿主](display-before-host.png)、[故障时来宾](display-before-guest.png)、[恢复后宿主](display-after-host.png)、[恢复后来宾](display-after-guest.png)。
