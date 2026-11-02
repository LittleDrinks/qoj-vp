# CI 与发布

普通推送使用 GitHub 托管的 Ubuntu 24.04 runner。真实 Firefox 回归另用专门的
Hydro Contest OS 虚拟机；当前用户正在使用的比赛 VM 不注册为 CI runner。

## 下载与安装

从 [GitHub Releases](https://github.com/LittleDrinks/qoj-vp/releases) 下载同一版本的
`qoj-vp-firefox-版本-signed.xpi`、`qoj-vp-mvp-source.tar.gz` 和 `INSTALL.md`。
仓库为私有，需要先登录有权限的 GitHub 账号。未签名包名称带 `-unsigned`，只用于开发。

在 Firefox 所在的 Linux 中按 `INSTALL.md` 安装/更新按需 Python 助手；然后打开
`about:addons` → 齿轮 → **从文件安装附加组件**，选择签名 XPI。
签名版重启后仍保留；升级使用同一扩展 ID，直接覆盖安装，不先卸载或删比赛数据。
已有临时版可先重启 Firefox 再安装签名版，助手账本保持原路径。
**XPI 不会自行安装 Python 助手**，两者需要使用同一版本。

安装时以 Release 中的 `-signed.xpi` 为准；未签名开发包不能作为长期安装版。

## 一次性配置 Mozilla 签名

采用 **unlisted**：由 Mozilla 签名，不公开上架 AMO 商店，签名包放在这个私有仓库的 Release。

1. 用自己的 Mozilla 开发者账号打开 [AMO API 凭据页](https://addons.mozilla.org/developers/addon/api/key/)，
   获取 JWT issuer 和 JWT secret。
2. 打开仓库 [Settings → Secrets and variables → Actions](https://github.com/LittleDrinks/qoj-vp/settings/secrets/actions)，
   添加 `AMO_JWT_ISSUER` 和 `AMO_JWT_SECRET` 两个 repository secrets。不要放到普通 Variables、源码或聊天里。
3. 打开 [Actions 工作流](https://github.com/LittleDrinks/qoj-vp/actions/workflows/ci.yml)，
   点击 **Run workflow**，选 `main`，将 `release_mode` 设为 `signed`。

凭据只传入 AMO 查询/签名步骤环境变量。测试通过后，固定版本的 web-ext 向 AMO 提交，下载签名包，
校验扩展内容与测试源码相同，上传安装说明/助手/源码/校验值，最后发布 GitHub Release。
签名流程会重新格式化 `manifest.json`，因此该文件比较严格解析后的 JSON 内容并拒绝重复字段；
其余代码和资源仍逐字节比较，下载的签名 ZIP 原样发布，不重新压缩或改写。
签名需要 Mozilla 账号且仍可能进入人工审核；CI 设置 20 分钟等待，超时不会发布不完整版本。
等待超时时先查看 AMO 该版本审核状态和工作流提示的开发者页面。重跑时先查询该版本：
已批准则下载原签名包并校验 AMO 的 SHA256，不重复上传；仍在审核或认证失败则停止。
只有版本不存在时才上传。下载的原始签名包保留为 `amo-output-提交号` artifact，
即使后续组包失败也可取回分析；组包仍逐文件核对源码，不能用恢复机制替换不同内容的同版本包。
[Mozilla 签名和审核说明](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/)。

0.3.3 起最低 Firefox 为 **140**，与已验证的 Hydro Firefox ESR 140.16 相容。
manifest 声明 QOJ 账号、题面/提交内容及比赛进度的必要数据传输；Firefox 安装时展示并征求同意。
原生助手也在声明范围内，不虚报“完全没有数据传输”。
[Mozilla 数据同意机制](https://extensionworkshop.com/documentation/develop/firefox-builtin-data-consent/)。
源代码、第三方来源、构建与受控验证说明见 [AMO_REVIEW.md](AMO_REVIEW.md)。

## 发布触发方式

| 触发 | 结果 |
| --- | --- |
| 普通 push / pull request | 测试、Mozilla lint、未签名 XPI / wheel / 完整源码 artifact |
| 手动 `release_mode=none` | 只运行 CI |
| 手动 `release_mode=draft-unsigned` | 创建带安装说明和全部包的开发草稿；不调用 AMO，不公开发布 |
| 手动 `release_mode=signed` | 测试 → AMO unlisted 签名 → GitHub Release 正式发布 |
| 推送 `v版本` tag | 自动走同一签名发布流程；需要先配置 AMO secrets |

版本同时存在于 `extension/manifest.json`、`pyproject.toml`、`qojvp/__init__.py`。
发布时三者必须相同，tag 必须为 `v` 加版本号，commit 必须已包含在默认分支。
手动发布自动选择 manifest 版本；已有 tag 不能移动，已正式发布的 Release 不能覆盖。
签名失败或凭据缺失不降级成未签名“正式版”。相同提交的开发草稿可用 signed 流程完成发布。

发布新版本示例（先完成三处版本更新、提交并推送）：

```sh
git tag v0.3.4
git push origin v0.3.4
```

也可以使用 `gh workflow run ci.yml -f release_mode=signed`，无需自己建 tag。
签名 job 串行执行，工作流不会自动取消正在进行的 AMO 上传。
普通 GitHub artifact 保留 30 天，发布 bundle artifact 保留 90 天；Release 资产长期保存。
自动更新暂未配置：私有 GitHub 下载地址无法直接交给 Firefox 更新器使用。先从 Release 手动
下载安装同 ID 新版，后续若选公开 HTTPS 更新源或 AMO 上架，再加入 `update_url`。
[Mozilla 更新说明](https://extensionworkshop.com/documentation/manage/updating-your-extension/)。

## 自动检查与本地打包

CI 递归检出固定的 `vendor/qoj-submitter`，Python 3.12 运行 `unittest`，Node 24 运行全部
`preflight/test_*.cjs` 和 `tests/test_*.cjs`，锁定 web-ext 版本运行 Mozilla lint，随后构建三个包。
源码包只导出 Git HEAD，包含固定 CLI submodule、`SOURCE_COMMIT` 和逐文件 `SOURCE_MANIFEST.json`；
工作区缓存、浏览器 profile、账号状态不会加入包里。源码包使用 tar.gz，提交源码供 AMO 审核。

```sh
git submodule update --init --recursive
python3 -m pip install . build
npm ci --ignore-scripts
npm run lint:firefox
python3 -m unittest discover -s tests -v
node --test preflight/test_*.cjs tests/test_*.cjs
python3 scripts/package_extension.py
python3 -m build --wheel
python3 scripts/package_source.py
cd dist
sha256sum *.xpi *.whl *.tar.gz > SHA256SUMS
sha256sum --check SHA256SUMS
```

`package_source.py` 导出 HEAD，不包含未提交修改。发布组包还校验版本、源码提交和扩展内容；
签名结构检查不等同于独立密码学验签，实际签名由 AMO 提供、Firefox 安装时验证。
CI 通过不代表已做本轮真实 QOJ 提交或签名安装验证。

## Hydro 专机

用户已有镜像：

```text
E:\VirtualBox VMs\hydro-contest-os-2026\ubuntu-24.04.5-icpc2026-amd64.iso
```

[官方镜像页](https://contest.hydro.ac/zh/contest-os/)说明其基于 Ubuntu 24.04.5，
提供 GNOME 和 CPython 3.12.3，并发布镜像校验文件。建议另建 `qoj-vp-ci` 虚拟机，
从该 ISO 安装、核对官方 SHA256，再创建专用非 root 用户运行 runner。参考配置为
4 vCPU、4 GiB 内存、40 GiB 动态磁盘；这是项目建议，不是镜像官方最低要求。

不复制日常 VM 的 Firefox profile、QOJ 登录或现有比赛数据。保留干净基础快照，
runner 的工作目录和测试输出放在该专机中。每个测试创建自己的 Firefox profile 和
Native Messaging 测试注册，退出后清理；测试数据使用本机 fixture。

一次性准备：

```sh
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev libcurl4-openssl-dev libssl-dev
/usr/bin/firefox-esr --version
```

现有来宾测试使用 `/usr/bin/firefox-esr`；先确认专机中这个路径存在。不要把 Ubuntu
默认 Snap Firefox 当作同一环境。测试脚本会记录实际 OS、Firefox 和 geckodriver 版本。
脚本不会仅凭 Ubuntu 版本就宣称镜像属于 Hydro。

在仓库 **Settings → Actions → Runners → New self-hosted runner** 中选 Linux x64，
按 GitHub 当场给出的下载、注册命令安装 runner，添加标签 `hydro-contest-os-2026`。
推荐在专机用一次性 `--ephemeral` runner：GitHub 在一个 job 完成后撤销注册，专机再恢复基础快照、注册下一次。
自动撤销注册不负责清理磁盘；镜像恢复需要单独编排。[GitHub 一次性 runner 说明](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)。
尚未做 VM 自动恢复编排时，也可手动启动专用 runner 做一轮验证，完成后停止 runner。
注册 token 短期有效，不写入仓库或镜像。[GitHub 注册说明](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners)。

注册并确认 runner online 后，设置仓库变量 `HYDRO_CI_ENABLED=true`，从默认分支手动运行
**Hydro Firefox regression**。工作流未启用时会明确报未配置，避免挂在无人处理的队列。
专机只接默认分支的手动任务，不接 pull request 自动任务。
label 路由方式遵循 [GitHub runner 选择规则](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)。

手动触发的 `check_rankland_online` 默认关闭。开启后，六套受控测试完成后会额外运行
`guest_rankland_readiness.py --mode verify`，访问当前线上 RankLand；因此该选项依赖
专机网络和站点可用性。没有打开该选项时不会把本地 fixture 测试描述成线上兼容验证。

## 真实浏览器回归范围

`scripts/run_hydro_ci.py` 默认顺序运行六套测试，线上 RankLand 检查需显式选择：

| 测试 | 检查内容 | 边界 |
| --- | --- | --- |
| DOMjudge visual parity | 官方 9.0.1 服务导出的页面快照、控件 CSS、提交弹窗操作 | 快照回放不是在线 DOMjudge；不宣称整页像素一致 |
| Home refresh | 官方 Home 两列、阻塞网络时连续 F5 恢复缓存题表和历史、失败与重试 | GET-only fixture；检查跨页面请求合并 |
| Resource cache | 样例/附件准备与下载、缓存复用 | 本地 QOJ fixture，不读用户登录 |
| Administration | 管理/选手视图分离、手动样例添加和选手下载、结束和删除本地比赛 | 独立 profile、账本和 GET-only fixture，不删除用户比赛 |
| Receipt diagnostics | Firefox 真实 HTTP 302/503/无 Location 行为、持久诊断 | POST 只发 localhost，不提交真实题目 |
| RankLand delayed sync | 原版榜单中的晚到判定、同题乱序、同秒不同提交、重判、手工记录保留、关页后赛后自动结算 | 固定原版脚本和本地合成数据；QOJ 为 GET-only fixture，不新开真实 VP |
| RankLand online（可选） | 原站加入测试队伍、单条合成判定、名次/得分/罚时与真实 DOM 比较、关页恢复 | 独立 profile/run 的合成比赛回放；QOJ 仍为 GET-only fixture，不使用真实账号 |

工作流下载固定 geckodriver 0.37.1 并校验发布资产的 SHA256；Python 浏览器依赖放进
checkout 的 `preflight/vendor_py`，不改系统 Python。截图、JSON 和测试日志作为
Actions artifact 保存 14 天。发生测试失败也保留证据，不上传 Firefox profile 和 SQLite。

Problemset 的 statement 直接打开 QOJ 原题面，不再运行已退役的自动 PDF 导出回归。

专机已准备好时，也可以直接运行：

```sh
/usr/bin/python3 scripts/run_hydro_ci.py --rankland-online
```

汇总中的 `ranklandOnlineRequested` 记录选项，`realRanklandTested` 仅在该测试进程实际
执行后变为 true；测试是否通过仍取决于对应 check 的状态。线上检查在调用生产
`rankland.snapshot` 前后独立读取原站队伍行；指标稳定时严格比较名次、得分、罚时，
仅对原站指标变化的窗口作有限重试。读取分数不修改原站 manual 数组。

QOJ 登录后 GET 不属于这些自动测试。CI 不在真实 QOJ 新开官方 VP 或提交源码，
也不将合成回放通过写成真实账号验收。Hydro workflow 是否实际通过，
以具体 run 的结果和产物为准。
