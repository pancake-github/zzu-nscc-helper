"""准备当前用户的 Edge 本机通信组件，不需要管理员权限。"""  # 只操作本软件专用键。
import json  # 校验内置组件清单。
from pathlib import Path  # 限定绝对路径。
from ..paths import data_root  # 私有注册清单不进入源码。
import winreg  # 注册当前用户 Native Messaging 主机。

def prepare(root):  # 由主软件启动时统一调用。
    root = Path(root).resolve()  # 获取固定项目目录。
    manifest = data_root() / 'native-host.json'  # 本软件通信清单。
    try:  # 文件缺失或注册失败都返回可见状态。
        host = root / 'native_host.exe'  # 已编译组件。
        eid = (root / 'extension-id.txt').read_text(encoding='ascii').strip()  # 固定扩展标识。
        if not host.is_file():  # 校验路径与来源。
            return False, '内置连接组件不完整，请联系修复。'  # 不注册未知程序。
        keyname = r'Software\Microsoft\Edge\NativeMessagingHosts\cn.zzdx.vpn_tabs'  # 精确应用私有键。
        try:  # 已有注册只允许指向本项目。
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, keyname) as key:  # 仅读取专用键。
                current = winreg.QueryValueEx(key, '')[0]  # 获取清单位置。
                if Path(current).resolve() != manifest:  # 不覆盖其他安装。
                    return False, '发现另一份助手的连接组件，请先处理旧安装。'  # 报告冲突。
                data = json.loads(manifest.read_text(encoding='utf-8'))  # 已注册也必须核对实际组件文件。
                if data.get('path') != str(host) or data.get('allowed_origins') != ['chrome-extension://' + eid + '/']:  # 不把旧组件误报就绪。
                    return False, '已注册组件与当前安装不一致，请通过安装器迁移。'  # 不覆盖另一份程序的清单。
        except FileNotFoundError:  # 首次运行可准备组件。
            manifest.parent.mkdir(parents=True, exist_ok=True)  # 私有清单位于当前用户数据目录。
            manifest.write_text(json.dumps({'name': 'cn.zzdx.vpn_tabs', 'description': '郑州超算助手连接组件', 'path': str(host), 'type': 'stdio', 'allowed_origins': ['chrome-extension://' + eid + '/']}, ensure_ascii=False), encoding='utf-8')  # 不含凭据，仅记录本机组件位置。
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, keyname) as key:  # 不修改 Edge 策略或权限。
                winreg.SetValueEx(key, '', 0, winreg.REG_SZ, str(manifest))  # 仅指向本应用清单。
        return True, '本机连接组件已准备；等待 Edge 扩展连接。'  # 不误报扩展已加载。
    except (OSError, ValueError, TypeError):  # 配置损坏或无权限。
        return False, '本机连接组件准备失败，请查看使用说明。'  # 不输出系统敏感细节。
