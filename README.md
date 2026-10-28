# 郑州超算助手 · ZZU NSCC Helper

**已发布首个公开测试版 `v0.5.0-beta.1`。** [下载页面与已知限制](https://github.com/pancake-github/zzu-nscc-helper/releases/tag/v0.5.0-beta.1) · [在线安装器](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.1/zzu-nscc-helper-online-0.5.0-beta.1-x64.exe) · [完整离线安装包](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.1/zzu-nscc-helper-offline-0.5.0-beta.1-x64.exe)。本版为预发布测试版，实测范围见[安装说明](docs/INSTALLATION.md)。

**E-File 显示“仅查看”、无法绑定？** 已提供 [Edge 连接组件 0.4.1 修复包](https://github.com/pancake-github/zzu-nscc-helper/releases/tag/edge-v0.4.1)，兼容平台添加的 `;jsessionid=…` 会话地址。适用于上述主程序，无需重装主程序；旧安装器仍内含 0.4.0 组件，安装或重装后请按[组件更新说明](docs/INSTALLATION.md#edge-连接组件-041-修复)更新。

**仅适用于本项目说明的郑州超算平台 SSL VPN 接入环境。非官方项目，不适用于其他超算中心。**

郑州超算平台专用 Windows 助手：SSL VPN 保活、Clash Verge Rev 自适应分流及 SFTP 上传下载。支持按需安装、配置备份回滚和文件校验。

关键词：郑州超算、国家超级计算郑州中心、SSL VPN、VPN保活、Clash Verge Rev、Mihomo、SFTP、Windows。

## 当前实际状态

当前为 **0.5.0-beta.1 公开测试版**。统一中文界面、独立后台进程、真实保活入口、SFTP上传下载界面，以及Clash检测、预览、事务应用和回滚均已接入。尚未完成的实机项目在下文和发布说明中保留，不标为稳定版。

**本批安装器已在本机 Windows 11 完成安装、升级、组件迁移和卸载入口核查；额外干净 Windows 11 虚拟机验收按维护者要求跳过，未记为通过。** Windows 云构建已通过在线、离线各七种组件组合及添加组件、保留本机资料、坏载荷拒绝检查。发布沿用已实测构建 `39913823258` 的同一批字节，源码与标签固定到 `06e75f9f463fec896838aec8f3bac8d0aa34ca16`；后续文档提交不替换安装包。`baseline/`保留历史来源，源码统一入口为`launcher.py`。

三组件源码融合和第三阶段离线/本机模拟服务回归已完成，覆盖独立组件、Clash端口及管道、自适应VPN身份、配置冲突、失败恢复、SFTP主机密钥变化和取消清理。正式联网、安装及升级结果以[阶段验收记录](docs/STAGES.md)为准。

本批安装包已完成一次专用标签页真实保活运行 1456.547 秒（约 24.3 分钟），在约第 0、13 分钟各成功一次 HTTPS 交互，HTTP 200、TLS 校验通过、异常路由采样为 0、工作进程已清理；测试因专用标签页导航而停止。按维护者接受的超过 15 分钟标准通过本轮保活检查，无需重跑 45 分钟，也不改写为完整 45 分钟通过。Clash 修正后的实际应用/回滚、专用标签恢复与失败终止、真实 SFTP 仍待独立实测；维护者已接受这些限制并授权先发布测试版，详细边界见[开发与验收阶段](docs/STAGES.md)。

## 适用条件

- 用户拥有自己的有效郑州超算账号，已安装并登录平台SSL VPN。
- 首版目标：Windows 11 x64、Microsoft Edge、Clash Verge Rev 2.5.8。
- 平台固定服务地址与身份见[平台说明](docs/PLATFORM.md)，其他环境不自动套用。
- 保活不代表网页SSO登录永不过期；不自动登录VPN，不读取浏览器密码或Cookie。

## 下载与按需安装

安装后无需自行安装 Python。选择[在线安装器](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.1/zzu-nscc-helper-online-0.5.0-beta.1-x64.exe)按需下载，或使用[完整离线安装包](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.1/zzu-nscc-helper-offline-0.5.0-beta.1-x64.exe)。请对照 [SHA256SUMS.txt](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.1/SHA256SUMS.txt) 校验文件。安装器尚无 Authenticode 数字签名，Windows 可能显示发布者未知提示。

| 可选组件 | 对应功能 | Edge扩展 |
| --- | --- | --- |
| 仅VPN保活 | 标签绑定、真实HTTPS交互、托盘和故障停止 | 首次手动加载一次 |
| 仅Clash分流 | 环境检测、改动预览、应用、备份和回滚 | 不需要 |
| 仅SFTP传输 | 中文上传下载、进度、校验、回执 | 不需要 |
| 全部安装 | 三项功能 | 仅保活使用 |
| 自定义 | 任意非空组合 | 按选项决定 |

在线安装器只下载公共运行库和已选组件；离线安装包保留同样的组件选择。每个下载资产都要通过SHA-256校验。Release 中的 `core.zip` 等四个载荷由在线安装器使用，通常无需手动下载。[最新 Edge 连接组件 0.4.1](https://github.com/pancake-github/zzu-nscc-helper/releases/download/edge-v0.4.1/zzu-nscc-helper-edge-0.4.1.zip)亦单独提供；保活首次使用仍需手动加载一次，步骤见[安装说明](docs/INSTALLATION.md)。

## 现有源码与检查

- `baseline/keepalive/`：已存在的0.4保活实现和离线测试；本机生成的通信清单、EXE、日志及截图不入库。
- `baseline/transfer/`：公开化后的上传下载核心和原有离线测试。请求必须包含用户实际填写的`username`，没有固定开发者账号。
- `src/zzu_nscc_helper/`：统一GUI、共享平台资源、保活、分流和传输的活跃实现。
- `worker_entry.py`：后台任务入口；密码只走本次匿名管道，不进入命令行或环境变量。
- `scripts/audit_public_tree.py`：精确文件白名单，并检查工作目录、Git暂存区、可达提交历史、平台公钥和来源哈希。

项目整理期间不要求安装或升级现有Python依赖。`observed-dependencies.json`只记录基线实际使用过的版本，**不是经过干净环境验证的构建锁文件**。

已有兼容开发环境中可从仓库根目录运行离线检查：

```powershell
python -m unittest discover -s tests -v # 离线验证融合实现；本机通信测试需先编译Native Host。
node tests/test_extension_fusion.cjs # 使用模拟Edge API验证融合扩展，不操作用户标签。
python scripts/audit_public_tree.py # 上传前检查实际文件、暂存内容和可达历史。
```

源码入口、组件选择和本机数据位置见[源码使用说明](docs/SOURCE_USAGE.md)。完整功能设计、接口边界与验收顺序见[融合架构](docs/ARCHITECTURE.md)。

## 数据与许可

不发布个人账号、密码、订阅、令牌、原始配置备份、原始日志、传输回执或研究文件。仅包含本平台经过指纹校验的公开SSH主机密钥。参见[数据边界](docs/PRIVACY.md)。

项目采用[GPL-3.0-only](LICENSE)。第三方组件许可见[第三方说明](THIRD_PARTY_NOTICES.md)。
