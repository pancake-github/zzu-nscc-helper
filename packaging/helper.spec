# PyInstaller公共运行库与组件业务代码分开，未选组件不会进入公共PYZ。
from pathlib import Path  # 路径以构建仓库为准。
from PyInstaller.utils.hooks import collect_all, copy_metadata  # 收集冻结运行所需依赖及许可证元数据。
root = Path(SPECPATH).parent  # 不引用开发者环境路径。
data, binaries, hidden = [], [], []  # 所有三个入口共享一致的第三方运行库。
for package in ('PyQt5', 'requests', 'urllib3', 'certifi', 'paramiko', 'cryptography', 'bcrypt', 'nacl', 'yaml', 'psutil', 'cffi'):  # 固定依赖白名单。
    found_data, found_bins, found_hidden = collect_all(package)  # 包括动态扩展和证书资源。
    data.extend(found_data)  # 不收集用户AppData或运行日志。
    binaries.extend(found_bins)  # 仅隔离构建环境的运行库。
    hidden.extend(found_hidden)  # 冻结侧无需用户安装Python。
for distribution in ('PyQt5', 'PyQt5-Qt5', 'paramiko', 'cryptography', 'requests', 'urllib3', 'certifi', 'PyYAML', 'psutil', 'bcrypt', 'PyNaCl'):  # 保留第三方元数据。
    data.extend(copy_metadata(distribution))  # 构建脚本另行整理许可证清单。
data.append((str(root / 'src/zzu_nscc_helper/data'), 'zzu_nscc_helper/data'))  # 只含固定平台预设及公开主机密钥。
a = Analysis([str(root / 'packaging/frozen_entry.py')], pathex=[str(root / 'src')], binaries=binaries, datas=data, hiddenimports=hidden + ['zzu_nscc_helper.gui', 'zzu_nscc_helper.worker', 'zzu_nscc_helper.installation'], excludes=['zzu_nscc_helper.keepalive', 'zzu_nscc_helper.transfer', 'zzu_nscc_helper.routing', 'zzu_nscc_helper.controller', 'zzu_nscc_helper.lifecycle', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore'], noarchive=False, optimize=1)  # 业务代码只放入选中组件包。
pyz = PYZ(a.pure)  # 三个EXE使用相同、可追溯的公共模块集合。
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='zzu-nscc-helper', console=False, debug=False, upx=False)  # 桌面无控制台。
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='zzu-nscc-worker', console=True, debug=False, upx=False)  # 私有JSON协议标准流。
maintenance = EXE(pyz, a.scripts, [], exclude_binaries=True, name='zzu-nscc-maintenance', console=True, debug=False, upx=False)  # 安装器隐藏调用维护入口。
bundle = COLLECT(gui, worker, maintenance, a.binaries, a.datas, strip=False, upx=False, name='zzu-nscc-helper')  # 同目录共享一套运行库。
