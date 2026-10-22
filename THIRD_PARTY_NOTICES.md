# 第三方组件与分发状态

本阶段仓库只纳入项目自身源码、测试和公开平台资源；没有重新分发Python、Qt、PyQt5、Paramiko、Clash、VPN客户端或其他第三方二进制库。

| 引用组件 | 用途 | 上游许可说明 |
| --- | --- | --- |
| Python | 程序运行时，后续打包 | https://docs.python.org/3/license.html |
| PyQt5 | 已有桌面界面 | https://riverbankcomputing.com/software/pyqt/ |
| Qt | 已有界面运行库 | https://www.qt.io/licensing/open-source-lgpl-obligations |
| Requests | CA资源与HTTP依赖 | https://github.com/psf/requests/blob/main/LICENSE |
| urllib3 | 固定目标HTTPS连接 | https://github.com/urllib3/urllib3/blob/main/LICENSE.txt |
| certifi | CA集合 | https://github.com/certifi/python-certifi/blob/master/LICENSE |
| Paramiko | SFTP传输 | https://github.com/paramiko/paramiko/blob/main/LICENSE |
| cryptography | SSH加密依赖 | https://github.com/pyca/cryptography/blob/main/LICENSE |
| PyNaCl | SSH公钥依赖 | https://github.com/pyca/pynacl/blob/main/LICENSE |
| bcrypt | SSH认证依赖 | https://github.com/pyca/bcrypt/blob/main/LICENSE |
| PyYAML | 后续读取Clash配置 | https://github.com/yaml/pyyaml/blob/main/LICENSE |
| psutil | 进程状态检查 | https://github.com/giampaolo/psutil/blob/master/LICENSE |

上述链接是来源索引，不替代二进制分发时的许可义务。打包阶段必须根据实际锁定版本附带完整许可证、版权声明、需要的源码获取说明及Qt相关材料；未完成该核对前不发布安装包。

公开SSH主机密钥仅用于核对本平台服务器身份，既不是用户私钥，也不提供平台登录权限。Edge清单中的`key`是维持扩展ID的公开RSA公钥，不包含签名私钥。
