# 0.3.3 签名发布验证

2026-11-02。发布提交 `4a325e97e9d4b78344a5c0d93ab6f4adadf85219`。

- [正式 Release](https://github.com/LittleDrinks/qoj-vp/releases/tag/v0.3.3)
- [成功的 CD](https://github.com/LittleDrinks/qoj-vp/actions/runs/41394832840)：Python 142、Node 148 项通过，Mozilla lint 无错误。
- Mozilla unlisted 签名；无需公开上架 AMO。私有仓库下载需 GitHub 登录。
- 文件已经下载并核对全部 `SHA256SUMS`，复制到 Windows `E:\shared\qoj-vp-mvp-release\0.3.3-signed` 后再次读取校验。
- XPI：`qoj-vp-firefox-0.3.3-signed.xpi`
- SHA256：`d0c3902e4583add456e753a0f18edf3060bc2e7323b547b77c892b750ae92780`

## 实际 Firefox 检查

Hydro 虚拟机的 Firefox ESR 140.16.0，独立临时系统账户、独立 profile，无用户 Cookie、原生助手注册或比赛账本。
Firefox 在 headless 模式下运行，未改变常用 profile 的设置或扩展。

1. 保持 `xpinstall.signatures.required=true`。
2. 对同一签名包故意修改 `ui.js`，正式安装被 Firefox 以 `ERROR_CORRUPT_FILE` 拒绝。
3. 原始签名包以 `temporary=false` 安装，ID 为 `qoj-vp@littledrinks.local`，版本 0.3.3，处于启用状态。
4. Firefox AddonManager 返回 `signedState=2`，与其 `SIGNEDSTATE_SIGNED` 常量相等。
5. 退出并用同一 profile 重启 Firefox；版本、签名状态和启用状态保持，仍不是临时扩展。

这次验证覆盖签名、永久安装与浏览器重启保留，不是新一次真实 QOJ 提交验收；未启动真实 VP 或发送题目源码。
常用 Firefox 与原生助手仍是此前部署的 0.3.2。升级步骤见 [CI.md](CI.md)，需同时更新按需助手。

本地证据：`artifacts/cd-firefox-signed-install.json`、`artifacts/cd-signed-delivery-summary.json`。
首次测试工具参数错误，随后使用 `nobody` 的测试又因启动超时失败；最终改用拥有完整目录的隔离临时账户完成检查。
这些前两次失败不属于 XPI 安装失败，最终成功证据以完整第三轮为准。

## 发布链路修复

AMO 首次签名已成功，但组包器原先逐字节比较 `manifest.json`，把签名流程产生的 JSON 排版变化误判为内容变化。
取回实际产物后确认：只改变 manifest 的空白排版；JSON 字段与其余文件均相同。

现在签名后的 manifest 按严格 JSON 内容比较、拒绝重复字段；其他文件仍逐字节比较。
修改权限、版本、扩展 ID 或脚本都会拒绝发布。发布原始签名 ZIP，不重新压缩或改写。

重跑 CD 会先只读查询相同 AMO 版本：已批准就下载原包并核对 AMO SHA256，仍在审核则停止，
不存在才上传。原始 AMO 产物在组包之前保存为 Actions artifact，方便后续失败恢复。
正式发布的版本/tag 保持不可覆盖；下一次产品修改应更新三个版本号后发布新版本。
