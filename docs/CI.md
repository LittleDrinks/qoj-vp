# CI 与发布

普通推送使用 GitHub 托管的 Ubuntu 24.04 runner。真实 Firefox 回归另用专门的
Hydro Contest OS 虚拟机；当前用户正在使用的比赛 VM 不注册为 CI runner。
这份配置不等于已创建或注册专机，第一次 GitHub Actions 运行结果才是云端验收证据。

## 自动检查与产物

`.github/workflows/ci.yml` 在 push、pull request 和手动触发时执行：

1. 递归检出固定的 `vendor/qoj-submitter` submodule。
2. Python 3.12 运行 `unittest`；Node 24 运行全部 `preflight/test_*.cjs` 和 `tests/test_*.cjs`。
3. 构建 Firefox XPI、Python wheel、包含固定 CLI submodule 内容的完整源码 tar.gz。
4. 上传包、`SHA256SUMS` 和测试日志。源码包只导出 Git 提交，带 `SOURCE_COMMIT`
   和逐文件 `SOURCE_MANIFEST.json`；工作区缓存、浏览器 profile、账户状态不在包里。

构建的 XPI 未经 Mozilla 签名。GitHub 打包不改变 Firefox 的签名和临时扩展规则，
也不会直接更新用户的虚拟机。测试通过只覆盖受控测试，不能当成实际 QOJ 提交的证据。

推送 `v*` tag 时，同一工作流测试成功后创建带三个包和校验文件的 **draft release**。
草稿由仓库所有者检查后发布；普通 commit 不创建 Release。不配置 PyPI、AMO 或其他
外部发布凭据，默认只使用 GitHub 内置 `GITHUB_TOKEN`。

本地对应命令：

```sh
git submodule update --init --recursive
python3 -m pip install . build
python3 -m unittest discover -s tests -v
node --test preflight/test_*.cjs tests/test_*.cjs
python3 scripts/package_extension.py
python3 -m build --wheel
python3 scripts/package_source.py
cd dist
sha256sum *.xpi *.whl *.tar.gz > SHA256SUMS
sha256sum --check SHA256SUMS
```

`package_source.py` 导出 HEAD 的文件，不包含尚未提交的修改；修改应先进入准备发布的提交。
wheel 只包含按需 Python helper，部署时还需要完整源码包中的固定 QOJ CLI 和安装脚本。

## 长期安装与签名

`about:debugging` 的临时安装在 Firefox 重启后结束，这是开发加载方式的行为，
不是 GitHub artifact 下载失败。[Mozilla 临时安装说明](https://extensionworkshop.com/documentation/develop/temporary-installation-in-firefox/)。

长期分发可以使用 AMO 的 **unlisted** 签名：扩展不进入公开商店列表，签名后的 XPI
仍可自行分发和普通安装。CI 后续可在测试通过后调用 `web-ext sign`，把签名产物加入
Release；这一步需要所有者的 AMO 账号及签名凭据，当前没有上传或配置。
ESR 的 `xpinstall.signatures.required=false` 是 Mozilla 支持的开发选项，但会放宽整个
profile 的签名检查，不能把它描述成已获得签名。[Mozilla 签名与分发说明](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/)。

自动更新还需稳定的 HTTPS `update_url` 与版本清单，或选择 AMO 上架分发。
私有 GitHub Release 的资产需要仓库访问权限，不能直接假设 Firefox 更新器能读取；
签名前先使用手动下载安装，确定分发地址后再加入更新清单。
[Mozilla 更新说明](https://extensionworkshop.com/documentation/manage/updating-your-extension/)。

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

手动触发的 `check_rankland_online` 默认关闭。开启后，三套受控测试完成后会额外运行
`guest_rankland_readiness.py --mode verify`，访问当前线上 RankLand；因此该选项依赖
专机网络和站点可用性。没有打开该选项时不会把本地 fixture 测试描述成线上兼容验证。

## 真实浏览器回归范围

`scripts/run_hydro_ci.py` 默认顺序运行现有三套测试，第四项需显式选择：

| 测试 | 检查内容 | 边界 |
| --- | --- | --- |
| DOMjudge visual parity | 官方 9.0.1 服务导出的页面快照、控件 CSS、提交弹窗操作 | 快照回放不是在线 DOMjudge；不宣称整页像素一致 |
| Resource cache | 样例/附件准备与下载、缓存复用 | 本地 QOJ fixture，不读用户登录 |
| Receipt diagnostics | Firefox 真实 HTTP 302/503/无 Location 行为、持久诊断 | POST 只发 localhost，不提交真实题目 |
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
