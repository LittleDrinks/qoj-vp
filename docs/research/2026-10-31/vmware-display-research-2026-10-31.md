# VMware 宿主控制台黑屏：只读研究

日期：2026-10-31。该子任务仅检查已有截图、日志和一手资料；没有操作桌面、切换 VM 状态、修改配置、安装或更新软件。

## 当前结论

本次最强证据是：**来宾画面可读取且能随分辨率调整，而宿主 VMware 控制台持续接近纯黑**。故优先验证宿主呈现路径，不能直接认定为 GNOME/Xorg 死锁，也不能仅凭使用 Vulkan 就断言某个 Vulkan 驱动缺陷已经确诊。

优先试验项是 Workstation 全局偏好中的 `Edit > Preferences > Display > Graphics > Allow hardware acceleration for all virtual machine consoles`。关闭它针对的是宿主控制台呈现；与 VM 硬件设置中的来宾 3D 加速是不同层次，可以先保留来宾 3D，再单独对照呈现偏好。

**是否立即生效尚未得到权威保证。** 有 26H1 用户报告需关闭并重新打开 GUI Console；应以实际后端日志和宿主画面恢复为准，不能仅凭 preferences.ini 变为 FALSE 判定修复。

## 本机证据

以下配置和日志由本子任务重新读取。来宾系统、进程和版本信息来自主代理已取得的诊断文件；没有再次连接来宾。

| 证据 | 观察 |
| --- | --- |
| `/mnt/e/VirtualBox VMs/hydro-contest-os-2026/hydro contest os.vmx:3` | `virtualHW.version = "22"` |
| 同文件第 4 行 | `mks.enable3d = "TRUE"` |
| 同文件第 52、62 行 | graphicsMemoryKB 为 8388608，vramSize 为 268435456；这些数值本身不足以证明显存耗尽 |
| `/mnt/c/Users/q2635/AppData/Roaming/VMware/preferences.ini:41` | `pref.remoteMKSHardwareAccel = "TRUE"` |
| 当前 `vmware.log:298` | 本次 VM 启动读取了同一个 TRUE 偏好 |
| 当前 `vmware.log:2640`、`:2642` | 使用 Vulkan presentation；启动了 VK presentation backend |
| 当前日志检索 | 未找到 VK_ERROR、DXGI_ERROR_DEVICE_REMOVED 或明确 device-lost 日志 |
| 主代理的来宾诊断 | Ubuntu 24.04.5、内核 7.0.0-42、Xorg、GNOME Shell 46.2；调整 xrandr 到 1920×1080 成功 |

日志是运行中可追加的文件，上述行号指本子任务读取时的当前日志，而非永久固定工件。

### 截图对照

本子任务独立计算已有 PNG 的画面区域统计：取横向 5%–95%、纵向 15%–93%，缩至 240×160，RGB 最大通道小于 8 计为黑色。

| 截图 | 分辨率 | 取样区域黑色比例 | 文件时间 UTC |
| --- | --- | --- | --- |
| `qoj-vmware-host-probe-20261031.png` | 3840×2100 | 0.998880 | 07:14:51 |
| `qoj-vmware-guest-auth-20261031.png` | 3838×1920 | 0.000000 | 07:10:13 |
| `qoj-vmware-host-1080p-20261031.png` | 3840×2100 | 0.998880 | 07:21:29 |
| `qoj-vmware-guest-1080p-20261031.png` | 1920×1080 | 0.000000 | 07:20:09 |

这些文件位于 `/mnt/c/Users/q2635/AppData/Local/Temp/`，属于同一排查阶段，**不是同帧同步采集**。后者来宾截图尺寸确实变为 1920×1080，因此比单张可能陈旧的截图更能支持“来宾仍处理显示操作”。主代理还取得了用户当时看到的黑屏截图。

降低分辨率没有让宿主窗口恢复，已削弱“只因为当前分辨率过大”的解释。它不排除分辨率切换曾触发宿主状态失效。

## 三个不同开关

| 层次 | 代表配置 | 作用与当前判断 |
| --- | --- | --- |
| 来宾 3D 能力 | `mks.enable3d` | 来宾能否使用虚拟 GPU 的 3D 功能；当前已启用，先保持不变以避免同时改变多个变量 |
| 宿主渲染后端 | `mks.enableVulkanRenderer`、`mks.enableDX12Renderer` | 负责宿主侧执行图形渲染；不能将其名称与 presentation 混用 |
| 宿主呈现后端 | `mks.enableVulkanPresentation`、`mks.enableDX12Presentation`，及全局控制台硬件加速偏好 | 负责将渲染图像呈现进 VMware 的宿主窗口；当前日志明确为 VK presentation，优先在此层做对照 |

Broadcom 员工 Shibdas Bandyopadhyay 明确解释 renderer backend 与 presentation backend 是两个 GPU 使用环节，并举出 Vulkan renderer 可以配不同 presentation 的日志。参见 [2026-07-08 员工回复](https://community.broadcom.com/vmware-cloud-foundation/question/linux-guest-goes-permanently-black-after-a-host-uac-prompt-lock-unlock-dx12-present-backend-device-removed-partial-recovery-workstation-26h1)。

## 一手资料与适用范围

### 全局呈现偏好的优先级

Broadcom 员工 James Lin 在 2026-03-03 的回复确认：25H2u1 将 Vulkan/DX12 presentation 与全局控制台硬件加速复选框关联；取消勾选会覆盖这两项 presentation 配置，勾选后才尊重 VMX 中的相关设置。2026-04-23 他补充关闭后还会禁用其他有已知问题的呈现模式，并可能有性能代价。**这支持优先验证呈现偏好，不证明本机黑屏已经由该项确诊。** [一手说明](https://community.broadcom.com/vmware-cloud-foundation/discussion/vmware-25h2)

### 偏好何时生效

26H1 的相关讨论中，一位用户在 2026-05-19 报告：先暂停/关闭来宾，取消全局复选框，再关闭并重开 GUI Console 才生效。同帖还出现升级后遗留 `pref.remoteMKSHardwareAccel = "TRUE"` 的用户发现。该帖主要症状是切换标签后变成缩略图，**与本机持续黑屏并不完全相同**；重开 GUI 是值得验证的步骤，不能当成所有版本的官方硬性要求。[26H1 用户实测及员工跟进](https://community.broadcom.com/vmware-cloud-foundation/discussion/workstation-26h1-tabbing-changes-fullscreen-to-thumbnail)

### 挂起/恢复的意义与限制

另一帖子报告 DX12 presentation 在宿主安全桌面切换后持续黑屏，作者发现挂起/恢复可以清除失效状态。但本机当前使用 VK presentation，日志也没有其关键 DEVICE_REMOVED 证据。因此，挂起/恢复只能作为**保留来宾内存的恢复试验**，不是对那个具体缺陷的确诊，也不构成长期修复证明。该操作仍会暂停来宾执行并可能影响网络计时。见上述 [安全桌面切换讨论](https://community.broadcom.com/vmware-cloud-foundation/question/linux-guest-goes-permanently-black-after-a-host-uac-prompt-lock-unlock-dx12-present-backend-device-removed-partial-recovery-workstation-26h1)。

### 不宜先强制 DX11

Broadcom 员工在 2026-04-21 说明：仅禁用 Vulkan renderer 会转到 DX12 renderer；要落到 DX11 还需另一项禁用配置。他建议先找出实际问题，而不是先切 DX11。本机应先做 presentation 层单变量对照，避免把 renderer、presentation、guest 3D 一起改掉。[员工答复](https://community.broadcom.com/vmware-cloud-foundation/question/how-do-i-force-vmware-to-use-dx11)

### 不匹配的旧知识库

搜索发现的 Broadcom legacy KB 52557，适用描述是较早虚拟硬件版本、非 3D Linux VM、分辨率变大及 guest dmesg command-buffer error。本机硬件版本 22、3D 启用、来宾截图正常且已有降低分辨率失败的对照，不能把该旧显存建议当成本机结论。[旧 KB](https://knowledge.broadcom.com/external/article?legacyId=52557)

## 建议的最小、可回退验证顺序

1. 保留当前 VMX、全局复选框旧值和两路画面基线。不要清理现有日志。
2. 仅取消全局控制台硬件加速复选框，保持 VM 的 `mks.enable3d` 和 renderer 设置不变。先观察当前窗口和新增后端日志。
3. 若当前窗口没有立即恢复，不据此认定偏好无效；验证关闭并重开 GUI Console 是否刷新后端。关闭界面时必须明确选保留 VM 状态的路径，不能把退出 GUI 自动当成来宾关机或保存成功。
4. 若当前失效状态仍在，再由主代理决定是否做一次挂起/恢复，恢复后重新测量宿主与来宾画面。恢复成功只证明清除了当前状态，还要验证原来的窗口大小/分辨率触发条件。
5. 恢复后做少量单变量回归：固定宿主窗口时改变来宾模式；固定来宾模式时切换宿主窗口/全屏；每次记录具体后端、实际来宾模式和两路截图。页面可见并非足够，还要有一次可见内容变化确认画面不是陈旧帧。
6. 只有呈现路径对照仍失败时，再安排 renderer 或驱动的独立对照。每次只改一个层次，并保留还原值。

生效与修复的验收应包含：宿主窗口能显示当前来宾画面；可观察到内容更新；对应日志/配置反映预期后端；原触发条件短期回归不再复现。不能仅用“命令返回 0”“截图文件生成”或“重开后暂时亮了”宣称长期解决。

## 尚未验证

- 未在子任务中切换偏好或重开 GUI，无法承诺此版本的实时生效行为。
- 未进行挂起/恢复或来宾重启。
- 未确认当前究竟是哪一个 GPU/驱动或 VMware 代码路径造成呈现失效；存在虚拟显示适配器并不等于已证明它们参与故障。
- 官方 26H1u1 release-notes URL 本次访问返回 403；不使用第三方更新日志据此宣称该具体问题在本版本已修复。
- 没有修改 Windows 的 UAC、Hyper-V、显卡驱动、注册表或系统显示设置。

## 追加：仅新建 GUI 窗口与偏好热重载

主代理追加的问题是：能否用 `vmware.exe -n <vmx>` 在 VM 继续运行时重开显示，以及该全局偏好是否支持文件热重载。

### `-n` 的已知语义

VMware 编写的用户手册将 `-n` 定义为新建 Workstation 窗口，另将 `-x`、`-X` 定义为开机/开机并全屏。Broadcom 社区的旧版工作人员答复也明确建议用 `-n` 强制新窗口，而非默认复用窗口。[原厂人员答复](https://community.broadcom.com/vmware-cloud-foundation/communities/community-home/digestviewer/viewthread?CommunityKey=fb707ac3-9412-4fad-b7af-018f5da56d9f&GroupId=7171&MessageKey=88d2b780-3318-434b-8e74-467d902ebae7)；[VMware 编写的 17 用户手册镜像，命令行章节](https://internet-lab.ru/sites/internet-lab.ru/files/2024-09/workstation-pro-17-user-guide.pdf)。这部分资料不是 26H1u1 的特定生命周期承诺。

因此，不加 `-x`、`-X` 的 `-n <vmx>` 可以作为**新建 GUI/连接窗口的候选试验**；不能把它称为已验证的 renderer 或 presentation 重启命令。未找到一手资料证明在 26H1u1 中，它能把同一已打开且运行中的 VM 复制成第二个独立 console，而不只是转交已有实例、移动视图或遇到独占检查。不能据命令退出码宣称后端已经重建。

### 当前安装包中的界面证据

只读查看当前安装包 `D:\Program Files\VMware\VMware Workstation\messages\zh_CN\vmware.vmsg`：

- 第 5519 行，`msg.vmui.menu.edit.prefs` 明确将首选项快捷键标为 `Ctrl+P`。
- 第 4820 行，`msg.vmappsdkWin32.display.remoteMKSHDAccelEnabled` 是全局控制台硬件加速复选框，带 `R` 助记键。
- 第 5548 行保留“新建窗口”菜单文本。
- 第 3544 行保留配置文件独占失败、可能被另一个 VMware 进程使用的提示。这只是程序支持该错误的静态证据，不表示本机已经发生该错误。

### 文件热重载没有确认

本次未找到 Broadcom 文档、员工回复或当前安装包文本明确说明：外部修改 `preferences.ini` 中的 `pref.remoteMKSHardwareAccel` 会被正在运行的 GUI 和既有 VMX 自动热重载。

已确认的资料是员工描述 GUI 复选框的配置优先级，以及用户报告关闭重开 GUI 后生效。因此应优先使用正式偏好入口；如果只写文件，需要将“文件值已变”和“运行中后端已变”分别验证，不能将二者等同。即使新 GUI 读到新值，也仍需检查既有 VMX 的当前呈现后端。
