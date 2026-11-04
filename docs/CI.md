# CI 与发布

唯一运行和验收目标：**Hydro Contest OS 2026**。普通 Ubuntu runner 用于构建和逻辑测试，不表示支持其他桌面环境。

## 当前流程

- `ci.yml`：GitHub 托管 Ubuntu 24.04，运行 Python / Node 测试、Mozilla lint，打包并按需签名。
- `hydro-ci.yml`：手动触发，使用 `hydro-contest-os-2026` 标签的自托管 runner。配置 `HYDRO_CI_ENABLED=true` 后才启用。
- 浏览器测试使用独立 profile、账本和本地题目数据，保存 JSON、截图和日志。不得新开真实 QOJ VP 或提交源码。
- 当前工作流尚未把 Hydro 虚拟机迁到 GitHub 托管 runner；下面是迁移方案，不是已通过的验收结果。

## GitHub 托管 Hydro：建议方案

```text
GitHub Actions Ubuntu runner
  → 从 GHCR 拉取固定摘要的 Hydro 磁盘镜像
  → QEMU/KVM 启动一次性 Hydro 虚拟机
  → 安装包、Firefox、Native Messaging、升级与重启回归
  → 上传报告，销毁虚拟机及写入层
```

GHCR 负责存储 Docker/OCI 镜像；可把压缩的 qcow2 磁盘作为镜像中的文件分发。
运行仍由 Actions 上的 QEMU 完成。将 Hydro 用户空间做成 Docker 容器，不能替代完整系统的安装和重启验收。
[GHCR 官方说明](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)。

先做小规模可行性测试，再把它设为发布门槛：

1. 从官方 Hydro ISO 创建干净测试镜像，核对校验值；记录镜像、Firefox、系统包版本。不要上传日常 VM、个人账号或比赛记录。
2. 实测 GitHub runner 上 `/dev/kvm` 能否启动 guest，以及可用磁盘、镜像下载时间和启动时间。
3. 跑一条安装 → 浏览器连接 → 创建本地测试记录 → Firefox/系统重启 → 记录恢复链路。
4. 连续通过后接入现有浏览器回归。基础镜像独立构建和更新，产品代码与安装包每次注入，不每次重新安装系统。

GitHub 明确将嵌套虚拟化视为实验性能力，不保证稳定性、性能和兼容性。
若实测不稳定，用具备 KVM 的独立云主机运行一次性 Hydro guest，由 Actions 调度；同样不依赖个人电脑。
[官方支持边界](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners#runner-images)。

公开仓库的标准 Linux runner 当前免费，配置为 4 核 / 16 GB 内存 / 14 GB SSD。
这份 Hydro ISO 本身约 7.1 GiB，不能假定下载 ISO、展开系统盘和运行测试能同时容纳；应预构建压缩磁盘并测量峰值占用。
GHCR 当前单层限 10 GB、上传超时 10 分钟，镜像布局需适配这两个限制。
[Runner 资源](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories) ·
[GHCR 限制](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#troubleshooting)。

容器镜像存储和带宽目前免费，政策可能调整。GitHub 的 custom runner image 是另一套较大 runner 功能，
需要组织/企业配置并单独计费，不是将个人 ISO 上传 GHCR 后直接作为 `runs-on` 使用。
[GHCR 计费](https://docs.github.com/en/billing/concepts/product-billing/github-packages#free-use-of-github-packages) ·
[Custom images](https://docs.github.com/en/actions/how-tos/manage-runners/larger-runners/use-custom-images)。

## 签名与发布

安装方式以对应 [Release](https://github.com/LittleDrinks/qoj-vp/releases/latest) 为准。
下一版计划提供 `.deb`、签名 XPI 和 `SHA256SUMS`；不再把过程记录或 `INSTALL.md` 放入下载区。
`.deb` 自动安装依赖、注册助手并提供桌面入口；用户只需在 Firefox 确认添加扩展。
助手按需退出，升级保留比赛数据。完整对应源码随包提供，开发产物保留在 Actions artifact。

签名使用 Mozilla **unlisted**。仓库 Actions secrets 为 `AMO_JWT_ISSUER`、`AMO_JWT_SECRET`。
运行 `ci.yml` 的 `release_mode=signed`，或推送 `v版本` tag。
版本需同时更新 `extension/manifest.json`、`pyproject.toml`、`qojvp/__init__.py`，提交必须在默认分支。

签名结果必须与测试源码逐文件一致；manifest 只允许 JSON 格式变化。
签名失败不发布未签名替代品，已发布版本及 tag 不覆盖。AMO 超时后先查询现有版本，避免重复上传。
构建与数据声明见 [Mozilla 审核说明](AMO_REVIEW.md)。

## 验收边界

- 逻辑测试：适配器、时间、重判、缓存、持久化和打包。
- Hydro 浏览器：官方 DOMjudge 参考页面、提交弹窗、资源下载、Jury、刷新恢复及真实助手连接。
- 新 Board：本地 SRK 渲染、延迟判定重算、重判和关页恢复；与可选原站导出分开验收。
- 安装包：干净安装、旧版升级、自定义目录保留、签名安装、Firefox 与 guest 重启。
- 真实 QOJ/RankLand 网络兼容另行记录；合成数据通过不等于真实比赛通过。

每次报告写明镜像摘要、产品提交、测试包哈希和实际执行项。失败保留证据，不上传浏览器 profile、账本或凭据。
