# 郑州超算助手 · ZZU NSCC Helper

使用郑州超算时，VPN 空闲断开、隔天网页会话失效、Clash 分流配置冲突，以及文件传输和校验繁琐，都会打断日常工作。**郑州超算助手**将连接维护、Clash 分流和 SFTP 上传下载整合到一个中文 Windows 桌面应用中，让这些重复操作更容易管理。

**非官方项目，仅适用于本项目说明的郑州超算平台 SSL VPN 接入环境，不适用于其他超算中心。** 使用前需要自己的有效平台账号，并先安装、登录平台 VPN。

## 从这些常见问题出发

- **电脑还开着，VPN 却断了。** 根据当前平台客服反馈，没有数据传输约 15 分钟会断开；仅保持浏览器打开，不一定有持续的有效流量。
- **VPN 有流量，网页却提示会话失效。** VPN 连接与网页登录态需要分别维护，单独保住 VPN 流量不能代表网页会话也已更新。
- **同时使用 Clash 和超算 VPN，分流难配置。** 系统代理、TUN、DNS 各有作用，本机端口和 VPN 网卡也可能不同，直接照搬他人的配置容易出错。
- **上传下载后，还要核对文件是否完整。** 批量文件、同名保护和校验结果需要清楚记录，避免把“传完了”直接当成“已校验”。

## 我们如何解决

| 您需要解决的问题 | 助手提供的方式 |
| --- | --- |
| VPN 因长时间没有流量而断开 | 独立 HTTPS 通道首次成功后，每 **13 分钟**进行一次真实内网传输，检查 TLS、响应和 VPN 路由。 |
| 网页长期没有业务交互 | 使用当前浏览器登录态，在随机助手专用目录完成 **1 KiB 上传 → 完整读回校验 → 删除 → 确认不存在**；首次手动开始执行一轮。新候选将完整成功后的周期由24小时改为 **5 小时**，观察对门户页面会话的实际效果。 |
| Clash 与超算 VPN 的分流配置 | 检测实际端口、控制器和 VPN 网卡，针对本平台生成精确规则，提供改动预览、备份和回滚。 |
| 超算文件上传下载与核验 | 中文 SFTP 界面支持文件和目录传输、同名保护、进度和回执；上传后完整读回并核对 SHA-256。 |

可只安装保活、分流或 SFTP，也可以任意组合；安装后无需自行配置 Python。正常运行时驻留托盘，任务由您手动开始和停止。网页暂时失败会退避重试，明确登录失效时提醒处理，VPN 通道仍可独立运行。详细行为见[维护策略](docs/WEB_SESSION.md)与[组件安装说明](docs/INSTALLATION.md)。

## 已经测试，并持续更新

已发布的 beta.4 通过自动回归、在线与离线共 **14 种组件安装组合**、公开下载资产 SHA-256 核验，并在实际超算平台完成安装版的 **上传、读回校验、删除和清理确认**；VPN 的约 13 分钟间隔传输也已实际验证。新候选 beta.5 的验证单独记录，结果与限制公开保存在[阶段验收记录](docs/STAGES.md)。

项目会结合实际使用反馈持续修复和更新。目前仍为**测试版**：实际使用中已观察到 VPN 正常、命令行仍可用，但 E-File 和计算服务外层页面会话失效。beta.5 将文件交互缩短到5小时进行验证，**文件校验成功不等于门户登录已续期**；模拟时钟也不代替真实跨周期观察。各模块的实机覆盖范围以验收记录为准，不承诺绕过平台的强制登录期限。

## 请确保您使用的是最新发布版本

安装、升级或遇到问题时，请先查看 [GitHub Releases](https://github.com/pancake-github/zzu-nscc-helper/releases)，核对**主程序与配套 Edge 扩展**版本。旧安装包或旧扩展可能缺少最新修复；仓库源码已更新也不等于本机已经升级。

当前发布：**`v0.5.0-beta.4`（界面 `0.5.0b4`），内置扩展 `0.5.2`**。

正在验证的新候选：**`v0.5.0-beta.5`（界面 `0.5.0b5`），配套扩展 `0.5.3`**。下方下载入口在新版本完成发布前仍指向 beta.4。

**[在线安装器](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.4/zzu-nscc-helper-online-0.5.0-beta.4-x64.exe)** · **[完整离线安装包](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.4/zzu-nscc-helper-offline-0.5.0-beta.4-x64.exe)** · [本版发布说明](https://github.com/pancake-github/zzu-nscc-helper/releases/tag/v0.5.0-beta.4)

两种安装器均已包含配套扩展，无需另装补丁。旧版用户从托盘退出助手后覆盖升级；Edge 首次使用需手动加载安装目录中的扩展，升级后重新加载一次并核对版本。支持带会话参数的 E-File、计算服务和命令行页面，具体步骤见[安装说明](docs/INSTALLATION.md)。

关键词：郑州超算、国家超级计算郑州中心、SSL VPN、VPN保活、Clash Verge Rev、Mihomo、SFTP、Windows。

## 双通道维护策略

新候选的VPN独立HTTPS仍在成功后等待13分钟；网页使用当前浏览器登录态和所选集群，在个人主目录的随机助手专用目录中完成1KiB文件上传、完整读回SHA-256、删除及不存在确认，成功后等待5小时。两轮之间不定期请求网页接口，不新增门户续期请求。短暂故障按30秒、60秒、随后180秒退避，先恢复原事务；不会重复上传或清理其他文件。关闭全部关联网页或登录失效时暂停网页维护，VPN继续。详见[网页维护与隐私边界](docs/WEB_SESSION.md)。

## 当前实际状态

当前整合版本为 **0.5.0-beta.4**（界面 **0.5.0b4**），内置扩展 **0.5.2**；基础连接协议保持 **0.4.0**，新网页功能另行核对能力字段。统一中文界面、独立后台进程、真实保活入口、SFTP上传下载界面，以及Clash检测、预览、事务应用和回滚均已接入。尚未完成的实机项目在下文和发布说明中保留，不标为稳定版。

beta.4 [构建41989829586](https://github.com/pancake-github/zzu-nscc-helper/actions/runs/41989829586)已通过回归、隐私与安装包审核，以及在线、离线共14种组件组合和覆盖旧扩展检查。源码及本机安装版均已完成真实文件上传、读回校验、删除与不存在确认，VPN独立完成约13分钟间隔的两次请求。24小时调度通过模拟时钟验证，真实跨日尚未验证；[发布后复核41991506941](https://github.com/pancake-github/zzu-nscc-helper/actions/runs/41991506941)已通过全部公开资产匿名回读和真实在线下载安装；本机0.5.0b4已使用同一哈希的离线包升级，详见[阶段记录](docs/STAGES.md)。

历史 beta.3 [构建 41971147570](https://github.com/pancake-github/zzu-nscc-helper/actions/runs/41971147570)通过在线、离线共 14 种组件组合及升级保护检查。本轮源码在真实平台连续运行超过 15 分钟，VPN 和两个业务页均完成第 0、13 分钟两轮交互；网页认证响应验证及页面状态更新成功。该记录不等于隔天持续运行或所有模块均已实测，最新安装与分发结果见[阶段记录](docs/STAGES.md)。

历史 beta.3 [公开下载与在线安装复核](https://github.com/pancake-github/zzu-nscc-helper/actions/runs/41972872261)已通过：公开资产匿名回读、哈希和包内审核，以及在线安装器真实下载三组件、安装、自检、GUI启动和卸载。所有保活安装均确认为扩展0.5.0。

此前 **v0.5.0-beta.1** 已在本机 Windows 11 完成安装、升级、组件迁移和卸载入口核查；额外干净 Windows 11 虚拟机验收按维护者要求跳过，未记为通过。该历史版本来自构建 `39913823258`、源码 `06e75f9f463fec896838aec8f3bac8d0aa34ca16`。**beta.2 使用新构建与独立校验和**，新增实际安装扩展版本、脚本哈希及覆盖旧扩展检查；本轮结果以对应 Release 和 `installer-matrix.json` 为准。`baseline/`保留历史来源，源码统一入口为`launcher.py`。

三组件源码融合和第三阶段离线/本机模拟服务回归已完成，覆盖独立组件、Clash端口及管道、自适应VPN身份、配置冲突、失败恢复、SFTP主机密钥变化和取消清理。正式联网、安装及升级结果以[阶段验收记录](docs/STAGES.md)为准。

beta.2 已完成两种安装器共 14 种组件组合检查，以及安装后扩展版本、文件哈希和合成旧扩展覆盖检查。[发布后验证](https://github.com/pancake-github/zzu-nscc-helper/actions/runs/40656439857)还完成全部公开资产匿名回读，并实际使用在线安装器从 GitHub 下载、安装三组件、自检、启动和卸载，确认内置扩展为 0.4.1。

历史 beta.1 安装包已完成一次专用标签页真实保活运行 1456.547 秒（约 24.3 分钟），在约第 0、13 分钟各成功一次 HTTPS 交互，HTTP 200、TLS 校验通过、异常路由采样为 0、工作进程已清理；测试因专用标签页导航而停止。按维护者接受的超过 15 分钟标准通过本轮保活检查，无需重跑 45 分钟，也不改写为完整 45 分钟通过。Clash 修正后的实际应用/回滚、专用标签恢复与失败终止、真实 SFTP 仍待独立实测；维护者已接受这些限制并授权先发布测试版，详细边界见[开发与验收阶段](docs/STAGES.md)。

## 适用条件

- 用户拥有自己的有效郑州超算账号，已安装并登录平台SSL VPN。
- 首版目标：Windows 11 x64、Microsoft Edge、Clash Verge Rev 2.5.8。
- 平台固定服务地址与身份见[平台说明](docs/PLATFORM.md)，其他环境不自动套用。
- 保活不代表网页SSO登录永不过期；不自动登录VPN，不读取浏览器密码或Cookie。

## 下载与按需安装

安装后无需自行安装 Python。选择[在线安装器](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.4/zzu-nscc-helper-online-0.5.0-beta.4-x64.exe)按需下载，或使用[完整离线安装包](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.4/zzu-nscc-helper-offline-0.5.0-beta.4-x64.exe)。请对照 [SHA256SUMS.txt](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.4/SHA256SUMS.txt) 校验文件。安装器尚无 Authenticode 数字签名，Windows 可能显示发布者未知提示。

| 可选组件 | 对应功能 | Edge扩展 |
| --- | --- | --- |
| 仅VPN保活 | VPN与网页双通道、标签绑定、托盘和故障提示 | 首次手动加载一次 |
| 仅Clash分流 | 环境检测、改动预览、应用、备份和回滚 | 不需要 |
| 仅SFTP传输 | 中文上传下载、进度、校验、回执 | 不需要 |
| 全部安装 | 三项功能 | 仅保活使用 |
| 自定义 | 任意非空组合 | 按选项决定 |

在线安装器只下载公共运行库和已选组件；离线安装包保留同样的组件选择。每个下载资产都要通过SHA-256校验。Release 中的 `core.zip` 等四个载荷由在线安装器使用，通常无需手动下载。新版安装器已包含 0.5.2 扩展，无需再下载补丁。[独立扩展包](https://github.com/pancake-github/zzu-nscc-helper/releases/download/v0.5.0-beta.4/zzu-nscc-helper-edge-0.5.0-beta.4.zip)仅供需要单独部署扩展的用户；保活首次使用仍需手动加载一次，步骤见[安装说明](docs/INSTALLATION.md)。

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
node tests/test_web_session.cjs # 验证真实接口契约、失败、取消和响应脱敏，不访问平台。
python scripts/audit_public_tree.py # 上传前检查实际文件、暂存内容和可达历史。
```

源码入口、组件选择和本机数据位置见[源码使用说明](docs/SOURCE_USAGE.md)。完整功能设计、接口边界与验收顺序见[融合架构](docs/ARCHITECTURE.md)。

## 数据与许可

不发布个人账号、密码、订阅、令牌、原始配置备份、原始日志、传输回执或研究文件。仅包含本平台经过指纹校验的公开SSH主机密钥。参见[数据边界](docs/PRIVACY.md)。

项目采用[GPL-3.0-only](LICENSE)。第三方组件许可见[第三方说明](THIRD_PARTY_NOTICES.md)。
