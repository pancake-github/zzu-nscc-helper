# 郑州超算助手 · ZZU NSCC Helper

**开发验收中：尚未发布安装包。** 正在构建可按需安装的在线、离线版本；正式下载入口在安装和真实平台验收完成后提供。当前构建与安装边界见[安装说明](docs/INSTALLATION.md)。

**仅适用于本项目说明的郑州超算平台 SSL VPN 接入环境。非官方项目，不适用于其他超算中心。**

郑州超算平台专用 Windows 助手：SSL VPN 保活、Clash Verge Rev 自适应分流及 SFTP 上传下载。支持按需安装、配置备份回滚和文件校验。

关键词：郑州超算、国家超级计算郑州中心、SSL VPN、VPN保活、Clash Verge Rev、Mihomo、SFTP、Windows。

## 当前实际状态

当前版本为 **0.5.0.dev1，三组件源码融合开发版**。统一中文界面、独立后台进程、真实保活入口、SFTP上传下载界面，以及Clash检测、预览、事务应用和回滚均已接入。

**安装器、干净环境构建及融合版真实联网验收尚未完成；当前没有可下载的一键安装包。** `baseline/`保留历史来源，实际统一入口为`launcher.py`。版本号不会提前标为`v0.5.0-beta.1`。

三组件源码融合和第三阶段离线/本机模拟服务回归已完成，覆盖独立组件、Clash端口及管道、自适应VPN身份、配置冲突、失败恢复、SFTP主机密钥变化和取消清理。正式联网、安装及升级结果以[阶段验收记录](docs/STAGES.md)为准。

已有保活基线在一次Windows实测中完成45分钟、4次HTTPS交互，每次读回2735字节；这一结果不代表尚未构建的安装包已经验收。详细边界见[开发与验收阶段](docs/STAGES.md)。

## 适用条件

- 用户拥有自己的有效郑州超算账号，已安装并登录平台SSL VPN。
- 首版目标：Windows 11 x64、Microsoft Edge、Clash Verge Rev 2.5.8。
- 平台固定服务地址与身份见[平台说明](docs/PLATFORM.md)，其他环境不自动套用。
- 保活不代表网页SSO登录永不过期；不自动登录VPN，不读取浏览器密码或Cookie。

## 按需安装设计

| 可选组件 | 对应功能 | Edge扩展 |
| --- | --- | --- |
| 仅VPN保活 | 标签绑定、真实HTTPS交互、托盘和故障停止 | 首次手动加载一次 |
| 仅Clash分流 | 环境检测、改动预览、应用、备份和回滚 | 不需要 |
| 仅SFTP传输 | 中文上传下载、进度、校验、回执 | 不需要 |
| 全部安装 | 三项功能 | 仅保活使用 |
| 自定义 | 任意非空组合 | 按选项决定 |

在线安装器只下载公共运行库和已选组件；离线安装包保留同样的组件选择。每个下载资产都要通过SHA-256校验。安装器和下载入口将在后续阶段实际验证后发布。

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
