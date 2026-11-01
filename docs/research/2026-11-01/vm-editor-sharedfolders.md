# Hydro 来宾 C++ 补全与 HGFS 复制修复

2026-11-01 在运行中的 Hydro Contest OS / csj 用户环境排查。全程通过 VMware 来宾操作，
未激活 Windows 窗口；用户随后手动确认环境正常。此记录独立于 QOJ 插件版本验收。

## C++ 扩展

Code 1.114.0 已安装 ms-vscode.cpptools 1.33.4。`~/.vscode/extensions` 是指向系统
`/opt/vscode/` 预装目录的符号链接，属主为 root。扩展日志明确报告激活失败：
对 `bin/cpptools-srv2` 执行 chmod 时 EPERM；该文件原模式为 0644，其余服务程序已有执行位。
实际修复仅给该预装程序补齐执行位至 0755，没有递归 chmod/chown 用户目录或共享文件。

GCC 14 本来已安装：`/usr/bin/g++-14`，登录 shell 的 g++ 由 `~/.local/bin/g++` 提供。
vmrun 的最小 PATH 找不到裸 g++ 不代表缺少编译器，因此没有重新安装 GCC 或改用户编译参数。

为准备独立显示环境的语义补全检查，安装了 xvfb/xauth，APT 同时更新了相依的 X server
组件；未重启桌面。随后用户手动确认补全正常，未再执行该探针。不能把准备好的测试脚本
当成已经通过的自动化补全证据。

## 共享文件夹复制

原 `/mnt/hgfs` 由 `mnt-hgfs.mount` 挂载，选项只有 `default_permissions,allow_other`。
新建共享文件显示为 root:root。普通 csj 用户能写内容，但 chmod 返回 EPERM。
同一份 618 B 模板的对照检查：普通缓冲复制成功，Python copy2 和 VS Code 自带 Electron
的 `fs.copyFileSync` 失败；后者准确复现截图中的 copyfile EPERM。

先在单独挂载点验证 `uid=1000,gid=1000`，Electron 复制成功、文件属主为 csj。
确认没有用户进程打开共享路径后，新增：

```ini
# /etc/systemd/system/mnt-hgfs.mount.d/10-csj-ownership.conf
[Mount]
Options=default_permissions,allow_other,uid=1000,gid=1000
```

重新加载 systemd 并正常重启该 mount，测试挂载已卸载。原 mount unit 的备份位于来宾项目
`results/environment-repair/mnt-hgfs.mount.before`。这是来宾显示的 UID/GID 映射，没有修改
Windows 文件 ACL。配置随开机挂载生效。

修复后同样的 Electron 默认复制及 Python copy2 均通过、字节相等。强制跨文件系统克隆
仍会返回正常的 EXDEV；VS Code 默认复制已经可以工作。用户原本要复制的模板也已通过
Electron COPYFILE_EXCL 复制到 `shared/workplace/CP/contests/CSP-S 2026/template.cpp`，
没有覆盖既有文件，SHA-256 与源文件一致。

本地证据：`artifacts/resume-diagnostics/environment-before.json`、`environment-after.json`、
`permission-repair-stage1.json`、`permission-repair-stage2.json`、`template-copy.json`。
回退共享映射只需移除本次 drop-in、daemon-reload，再在没有共享文件写入时重启 mount。
