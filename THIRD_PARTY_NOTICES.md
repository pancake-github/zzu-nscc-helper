# 第三方组件与分发状态

源码仓库包含本项目源码、测试、平台公开资源和构建流程。GitHub Actions开始生成候选安装包，候选包包含冻结的Python、PyQt5、Qt及实际使用的第三方运行库；候选构建不代表正式Release或实机验收已通过。Clash和VPN客户端由使用者自行安装，本项目不打包它们。

候选安装目录的`licenses/`保留构建环境发行包附带的完整许可证与版权文件，`build-info.json`列出实际版本，`corresponding-sources.json`提供固定版本源代码归档地址及哈希。Python 3.12.4源码哈希已经实际完整读取核验；Qt 5.15.2源码哈希来自官方发布的SHA-256文件。第三方Python包的源码位置与哈希来自PyPI相同版本发行元数据，构建依赖本身另以官方轮子哈希锁定。

| 引用组件 | 用途 | 上游许可说明 |
| --- | --- | --- |
| Python | 冻结程序运行时 | https://docs.python.org/3/license.html |
| PyQt5 | 中文桌面界面，使用GPL分发方案 | https://riverbankcomputing.com/software/pyqt/ |
| Qt | 界面和本机通信运行库 | https://www.qt.io/licensing/open-source-lgpl-obligations |
| Requests | CA资源与HTTP依赖 | https://github.com/psf/requests/blob/main/LICENSE |
| urllib3 | 固定目标HTTPS连接 | https://github.com/urllib3/urllib3/blob/main/LICENSE.txt |
| certifi | CA集合 | https://github.com/certifi/python-certifi/blob/master/LICENSE |
| Paramiko | SFTP传输 | https://github.com/paramiko/paramiko/blob/main/LICENSE |
| cryptography | SSH加密依赖 | https://github.com/pyca/cryptography/blob/main/LICENSE |
| PyNaCl | SSH公钥依赖 | https://github.com/pyca/pynacl/blob/main/LICENSE |
| bcrypt | SSH认证依赖 | https://github.com/pyca/bcrypt/blob/main/LICENSE |
| PyYAML | 安全读取Clash配置 | https://github.com/yaml/pyyaml/blob/main/LICENSE |
| psutil | 进程状态检查 | https://github.com/giampaolo/psutil/blob/master/LICENSE |

上述链接是上游许可索引，不替代候选包内实际版本的完整许可文件。正式Release前仍须核对实际产物的许可证、版权声明、对应源码获取说明及Qt材料；候选测试通过不能代替这项核对。项目自身完整源码和构建脚本以GPL-3.0-only公开，源码与二进制之间的对应关系以构建提交及产物哈希记录。

公开SSH主机密钥仅用于核对本平台服务器身份，既不是用户私钥，也不提供平台登录权限。Edge清单中的`key`是维持扩展ID的公开RSA公钥，不包含签名私钥。
