"""安装器维护入口：只维护本产品清单及当前用户的Edge连接注册。"""  # 无平台网络或认证操作。
import argparse  # 固定维护动作。
import ctypes  # 枚举进程实际载入的DLL位置。
from ctypes import wintypes  # 六十四位进程的模块句柄宽度。
import hashlib  # 防止迁移或卸载覆盖后续修改。
import importlib  # 仅验证已安装的固定组件。
import json  # 安装清单和私有迁移记录。
import os  # 原子替换维护文件。
from pathlib import Path  # 所有程序路径来自实际安装目录。
import sys  # 冻结程序的实际位置。
import uuid  # Windows签名校验动作的固定GUID。
import winreg  # 仅操作当前用户本产品的注册键。
from .components import COMPONENTS, normalize_selection  # 安装器与运行时使用相同选择契约。
from .instance import InstanceGuard  # 安装和升级不得抢占运行中的助手。
from .paths import data_root  # 私有迁移备份不进入安装包。

KEY = r'Software\Microsoft\Edge\NativeMessagingHosts\cn.zzdx.vpn_tabs'  # 精确私有主机键。
ORIGIN = 'chrome-extension://oheagkgeajcaljpakdklopdbfmchnifd/'  # 仅允许本产品固定扩展。
KNOWN_DESCRIPTIONS = ('SSL VPN assistant local tab bridge', '郑州超算助手连接组件')  # 只迁移已识别的旧版本。

def atomic_json(path, value):  # 同目录完整写入后发布，避免半份JSON。
    path.parent.mkdir(parents=True, exist_ok=True)  # 只在确定的数据根目录创建。
    temporary = path.with_name(path.name + '.new')  # 本软件专用中间文件。
    if temporary.exists():  # 不覆盖可能来自上次中断的未知内容。
        raise ValueError('MAINTENANCE_CONFLICT')  # 留给检查点处理。
    owned = False  # 排他创建失败时不得清理别人的文件。
    try:  # 失败也只清理本次实际创建的中间文件。
        with temporary.open('x', encoding='utf-8') as stream:  # 排他创建。
            owned = True  # 只有本次实际创建后才取得清理权。
            json.dump(value, stream, ensure_ascii=False, indent=2)  # 不含认证信息。
            stream.flush()  # 先送入操作系统。
            os.fsync(stream.fileno())  # 先完成写入再替换。
        os.replace(temporary, path)  # 原子发布。
    finally:  # 不递归清理任何用户目录。
        if owned:  # 不删除并发创建的其他文件。
            temporary.unlink(missing_ok=True)  # 只清理本次专用文件。

def idle():  # 只测试互斥是否空闲，不退出用户进程。
    guards = [InstanceGuard(), InstanceGuard(prefix='ZZDXVPNKeepalive-')]  # 与统一版及旧版使用同一身份规则。
    try:  # 检测后立即释放自身句柄。
        return all(guard.primary for guard in guards)  # 任一助手运行都拒绝安装或卸载。
    finally:  # 不留下安装锁。
        for guard in guards:  # 只关闭本进程持有的引用。
            guard.close()  # 原进程的锁不受影响。

def registration():  # 返回当前值，未注册与访问失败明确区分。
    try:  # 仅不存在时返回空值。
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:  # 不读取浏览器密码或其他扩展。
            value, kind = winreg.QueryValueEx(key, '')  # 只读默认清单路径。
            if kind != winreg.REG_SZ or not isinstance(value, str):  # 不猜测其他值类型。
                raise ValueError('NATIVE_REGISTRATION_CONFLICT')  # 修改前停止。
            return value  # 路径仅保存在本机私有备份。
    except FileNotFoundError:  # 本产品没有注册。
        return None  # 不视为错误。

def write_registration(value):  # 只设置或删除本产品自己的默认值。
    if value is None:  # 恢复原本未注册的状态。
        try:  # 删除键前确认不存在其他值或子键。
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:  # 仅当前用户。
                children, values, _ = winreg.QueryInfoKey(key)  # 不误删其他内容。
                if children or values > 1:  # 后续人工配置需要保留。
                    raise ValueError('NATIVE_REGISTRATION_CONFLICT')  # 不扩大删除范围。
                if values:  # 本软件只写过一个默认值。
                    winreg.DeleteValue(key, '')  # 不触碰其他浏览器设置。
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY)  # 只删除空的私有键。
        except FileNotFoundError:  # 已经恢复为空。
            pass  # 不重复报错。
    else:  # 正常安装或恢复旧注册。
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as key:  # 不申请管理员权限。
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, value)  # 不修改Edge策略。

def configure(root, selected):  # 安装文件就绪后才发布组件清单和连接信息。
    selected = normalize_selection(selected)  # 至少一个已知组件。
    for component in selected:  # 未实际安装的组件不能写进清单。
        relative = {'keepalive': 'keepalive/tab_app.py', 'routing': 'routing.py', 'sftp': 'transfer/nscc_download.py'}[component]  # 固定业务入口。
        if not (root / 'modules/zzu_nscc_helper' / relative).is_file():  # 不靠界面隐藏冒充按需安装。
            raise ValueError('COMPONENT_PAYLOAD_MISSING')  # 写入清单前停止。
    manifest = data_root() / 'native-host.json'  # 与正常GUI的注册位置一致。
    backup = data_root() / 'native-migration.json'  # 永远留在本机。
    previous = registration() if 'keepalive' in selected else None  # 不安装保活时不读取或改动浏览器注册。
    if 'keepalive' in selected:  # 只有保活组件需要连接器。
        host = root / 'modules/zzu_nscc_helper/keepalive/native_host.exe'  # 选中组件实际内置程序。
        if not host.is_file():  # 源码目录不能冒充安装包。
            raise ValueError('NATIVE_PAYLOAD_MISSING')  # 不写入失效注册。
        if previous and Path(previous).resolve() != manifest.resolve():  # 只迁移已识别的旧助手。
            old = json.loads(Path(previous).read_text(encoding='utf-8-sig'))  # 路径和正文不打印。
            if old.get('name') != 'cn.zzdx.vpn_tabs' or old.get('description') not in KNOWN_DESCRIPTIONS or old.get('allowed_origins') != [ORIGIN] or Path(old.get('path', '')).name != 'native_host.exe':  # 不接管其他注册。
                raise ValueError('NATIVE_REGISTRATION_CONFLICT')  # 原样保留。
        if backup.exists():  # 升级必须保留第一次迁移记录。
            saved = json.loads(backup.read_text(encoding='utf-8'))  # 仅校验身份。
            if saved.get('schema') != 1 or previous not in (str(manifest), saved.get('previous_registration')):  # 允许上次未完成迁移安全重入，拒绝其他安装接管。
                raise ValueError('NATIVE_MIGRATION_CONFLICT')  # 不覆盖备份。
        else:  # 首次安装先保存原注册及本产品旧清单。
            atomic_json(backup, {'schema': 1, 'previous_registration': previous, 'previous_manifest': manifest.read_text(encoding='utf-8') if manifest.exists() else None})  # 不复制其他个人配置。
        old_bytes = manifest.read_bytes() if manifest.exists() else None  # 失败恢复只针对本产品清单。
        try:  # 连接信息必须完整提交。
            atomic_json(manifest, {'name': 'cn.zzdx.vpn_tabs', 'description': KNOWN_DESCRIPTIONS[1], 'path': str(host), 'type': 'stdio', 'allowed_origins': [ORIGIN]})  # 不含账号或Cookie。
            write_registration(str(manifest))  # 仅当前用户注册。
            atomic_json(root / 'components.json', {'schema': 1, 'components': list(selected)})  # 连接注册和安装清单一并提交。
        except Exception:  # 不留下半迁移状态。
            if old_bytes is None:  # 原本没有本产品清单。
                manifest.unlink(missing_ok=True)  # 不删除其他旧助手文件。
            else:  # 恢复原有本产品文件。
                manifest.write_bytes(old_bytes)  # 异常会让维护动作整体失败。
            write_registration(previous)  # 保留原浏览器连接目标。
            raise  # 不报告成功。
    else:  # 非保活安装不涉及浏览器注册。
        atomic_json(root / 'components.json', {'schema': 1, 'components': list(selected)})  # GUI和工作进程共用固定清单。
    return {'ok': True, 'components': list(selected), 'native_registered': 'keepalive' in selected}  # 不回传私有迁移路径。

def unregister(root):  # 卸载只撤销仍属于当前安装的注册。
    backup = data_root() / 'native-migration.json'  # 私有原注册记录。
    manifest = data_root() / 'native-host.json'  # 本产品清单。
    if not backup.exists():  # 非保活安装无需操作。
        return {'ok': True, 'native_changed': False}  # 不触碰其他安装。
    if registration() != str(manifest):  # 后续被其他软件接管。
        return {'ok': False, 'error': 'NATIVE_REGISTRATION_CONFLICT'}  # 保留现场和备份。
    current = json.loads(manifest.read_text(encoding='utf-8'))  # 只核对本产品指向。
    if current.get('path') != str(root / 'modules/zzu_nscc_helper/keepalive/native_host.exe'):  # 不撤销另一安装的连接器。
        return {'ok': False, 'error': 'NATIVE_MIGRATION_CONFLICT'}  # 不覆盖新状态。
    saved = json.loads(backup.read_text(encoding='utf-8'))  # 恢复第一次安装前的状态。
    if saved.get('schema') != 1:  # 损坏备份不能猜测。
        raise ValueError('NATIVE_MIGRATION_CONFLICT')  # 保留备份供核对。
    write_registration(saved['previous_registration'])  # 恢复旧助手或原本未注册状态。
    if saved['previous_manifest'] is None:  # 本产品清单最初不存在。
        manifest.unlink()  # 只清理自己的连接清单。
    else:  # 保留升级前本产品的实际清单。
        manifest.write_text(saved['previous_manifest'], encoding='utf-8')  # 不写到其他软件目录。
    backup.unlink()  # 成功恢复后才移除本次迁移记录。
    return {'ok': True, 'native_changed': True}  # 用户日志与规则备份继续保留。

def trusted_signature_offline(path):  # 仅用本机证书缓存核验已注入DLL，不修改信任库或联网。
    class FileInfo(ctypes.Structure):  # WINTRUST_FILE_INFO的原生布局。
        _fields_ = [('size', wintypes.DWORD), ('path', wintypes.LPCWSTR), ('handle', wintypes.HANDLE), ('subject', ctypes.c_void_p)]  # 文件对象不加载执行。
    class TrustData(ctypes.Structure):  # WINTRUST_DATA的文件联合成员用等宽指针表示。
        _fields_ = [('size', wintypes.DWORD), ('policy', ctypes.c_void_p), ('sip', ctypes.c_void_p), ('ui', wintypes.DWORD), ('revocation', wintypes.DWORD), ('choice', wintypes.DWORD), ('file', ctypes.POINTER(FileInfo)), ('action', wintypes.DWORD), ('state', wintypes.HANDLE), ('url', wintypes.LPWSTR), ('flags', wintypes.DWORD), ('context', wintypes.DWORD), ('signature', ctypes.c_void_p)]  # 对齐由ctypes按Windows ABI处理。
    item = FileInfo(ctypes.sizeof(FileInfo), str(path), None, None)  # 仅核验已观测到的实际文件。
    data = TrustData()  # 所有保留字段初始化为零。
    data.size, data.ui, data.choice, data.action = ctypes.sizeof(TrustData), 2, 1, 1  # 无界面、文件对象、建立后必须释放校验状态。
    data.file, data.flags = ctypes.pointer(item), 0x1000 | 0x80 | 0x2000  # 仅缓存撤销检查、除根外证书链检查、拒绝MD2/MD4。
    action = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID('00aac56b-cd44-11d0-8cc2-00c04fc295ee').bytes_le)  # WINTRUST_ACTION_GENERIC_VERIFY_V2。
    verify = ctypes.WinDLL('wintrust', use_last_error=True).WinVerifyTrust  # 系统签名接口，不启动PowerShell。
    verify.argtypes, verify.restype = [wintypes.HWND, ctypes.c_void_p, ctypes.POINTER(TrustData)], wintypes.LONG  # LONG为有符号错误码，仅零表示成功。
    try:  # 无论校验结果如何都释放系统状态。
        return verify(wintypes.HWND(-1), ctypes.byref(action), ctypes.byref(data)) == 0  # 缓存不足或未知签名不放行。
    finally:  # Windows要求每次VERIFY对应CLOSE。
        data.action = 2  # WTD_STATEACTION_CLOSE。
        verify(wintypes.HWND(-1), ctypes.byref(action), ctypes.byref(data))  # 不修改被测DLL。

def classify_external_library(path, packaged_names):  # 区分借用运行库与系统中其他软件的已签名注入。
    name = path.name.lower()  # Windows文件名忽略大小写。
    if name in packaged_names or name.endswith('.pyd') or name.startswith(('python', 'qt5', 'qt6', 'pyside', 'pyqt', 'vcruntime', 'msvcp')):  # 即使有签名也不允许借用外部Python、Qt或同名打包库。
        return 'borrowed_runtime'  # 仍是自检失败。
    return 'signed_external' if trusted_signature_offline(path) else 'untrusted_external'  # 不因声卡或辅助软件注入误报Python依赖，也不盲目信任未知DLL。

def self_test(root):  # 无平台流量的冻结程序检查。
    from .gui import installed_components, MainWindow  # 使用实际安装清单和主界面。
    from PyQt5.QtWidgets import QApplication  # 在本进程离线创建控件。
    from PyQt5.QtCore import QProcess  # 核对后台未启动。
    selected = installed_components()  # 缺失清单不能默认为全部。
    expected = {'keepalive': '.keepalive.tab_app', 'routing': '.routing', 'sftp': '.transfer.nscc_upload'}  # 只导入固定模块。
    for component in selected:  # 真正验证模块能够导入。
        importlib.import_module(expected[component], 'zzu_nscc_helper')  # 不认证、不请求平台。
    app = QApplication.instance() or QApplication([])  # CI使用offscreen平台。
    window = MainWindow(selected, preview=True)  # 不注册连接器或检测生产环境。
    try:  # 即使观测失败也关闭本次GUI和日志句柄。
        tasks = [task for task in (window.detector, window.routing.task if window.routing else None, window.transfer.task if window.transfer else None) if task]  # 只检查真实存在的控制器。
        no_workers = all(task.process is None or task.process.state() == QProcess.NotRunning for task in tasks) and (not window.keepalive or window.keepalive.worker is None)  # 尚未启动的控制器没有QProcess，不能当作自检异常。
        tab_count = window.tabs.count()  # 真实构造的页面数量。
    finally:  # 异常也不能留下Windows文件句柄或托盘。
        window.cleanup()  # 主界面关闭自身定时器和托盘。
        window.exiting = True  # 不收起到托盘。
        window.close()  # 不进入事件循环。
        app.processEvents()  # 处理删除事件。
    windows = Path(os.environ['WINDIR']).resolve()  # Windows系统库允许来自系统目录。
    external = []  # 不回显外部路径。
    for module in tuple(sys.modules.values()):  # 检查实际加载的Python模块来源。
        location = getattr(module, '__file__', None)  # 内建模块没有文件。
        if location and Path(location).is_absolute():  # 相对虚拟路径不代表本机Python环境。
            path = Path(location).resolve()  # 解析实际来源。
            if not path.is_relative_to(root) and not path.is_relative_to(windows):  # 不能借用原Python环境。
                external.append(getattr(module, '__name__', 'unknown'))  # 只返回模块名。
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)  # 查询本进程实际载入的原生运行库。
    kernel.GetCurrentProcess.restype = wintypes.HANDLE  # 不截断伪句柄。
    kernel.K32EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]  # 正确的Win32接口。
    kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]  # 模块路径只在内存核对。
    handles, needed = (wintypes.HMODULE * 2048)(), wintypes.DWORD()  # 有界模块缓冲。
    if not kernel.K32EnumProcessModules(kernel.GetCurrentProcess(), handles, ctypes.sizeof(handles), ctypes.byref(needed)) or needed.value > ctypes.sizeof(handles):  # 枚举失败不能宣称无外部依赖。
        raise ValueError('MODULE_ENUMERATION_FAILED')  # 明确失败。
    external_dlls, signed_injections = [], []  # 未知或借用库失败，其他已签名注入单独如实记录。
    packaged_names = {path.name.lower() for path in root.rglob('*') if path.is_file() and path.suffix.lower() in ('.dll', '.pyd')}  # 同名运行库必须从本安装加载。
    for index in range(needed.value // ctypes.sizeof(wintypes.HMODULE)):  # 只检查实际返回的句柄。
        buffer = ctypes.create_unicode_buffer(32768)  # 支持长路径。
        if not kernel.GetModuleFileNameW(handles[index], buffer, len(buffer)):  # 缺少任一来源证据都失败。
            raise ValueError('MODULE_PATH_UNAVAILABLE')  # 不以部分检查宣称全部通过。
        path = Path(buffer.value).resolve()  # 实际DLL或EXE路径。
        if not path.is_relative_to(root) and not path.is_relative_to(windows):  # 不允许借用外部Python或Qt运行库。
            destination = signed_injections if classify_external_library(path, packaged_names) == 'signed_external' else external_dlls  # 签名验证只用本机缓存，不请求网络。
            destination.append(path.name)  # 公开摘要不含用户名或外部目录。
    passed = bool(getattr(sys, 'frozen', False)) and not external and not external_dlls and no_workers and tab_count == len(selected)  # 综合真实观测结果。
    return {'ok': passed, 'frozen': bool(getattr(sys, 'frozen', False)), 'components': list(selected), 'tabs': tab_count, 'external_python_modules': external, 'external_native_libraries': external_dlls, 'signed_external_injections': signed_injections, 'network_requests': 0, 'workers_running': not no_workers}  # 不声称完整真实联网验收。

def main():  # 只能由固定维护EXE进入。
    parser = argparse.ArgumentParser(description=__doc__)  # 不接受任意路径、主机或凭据。
    parser.add_argument('action', choices=('check-idle', 'configure', 'unregister', 'self-test', 'acceptance-45'))  # 真实持续验收必须显式调用。
    parser.add_argument('--components')  # 安装器生成的组件编号。
    parser.add_argument('--output', type=Path)  # 真实验收输出仅保存在本机。
    parser.add_argument('--tab-id', type=int)  # 控制器明确指定新建验收标签的真实编号。
    args = parser.parse_args()  # 无认证参数。
    root = Path(sys.executable).resolve().parent  # 不接受外部安装目录。
    try:  # 输出固定类别，避免路径泄漏到CI日志。
        if args.action == 'acceptance-45':  # 不在普通启动或安装过程中运行。
            if args.output is None or args.tab_id is None:  # 缺少真实目标不生成占位操作。
                raise ValueError('ACCEPTANCE_ARGUMENTS_REQUIRED')  # 不开始请求。
            from .keepalive.acceptance import run  # 只安装保活组件时此入口才可用。
            return run(args.output.resolve(), args.tab_id)  # 同一冻结GUI与后台工作程序。
        elif args.action == 'self-test':  # 离线验收不修改注册。
            result = self_test(root)  # 检查真实打包产物。
        elif not idle():  # 安装、升级和卸载都不能抢占任务。
            result = {'ok': False, 'error': 'ASSISTANT_RUNNING'}  # 用户自行结束现有任务。
        elif args.action == 'configure':  # 文件部署成功后配置。
            result = configure(root, args.components.split(',') if args.components is not None else [])  # 禁止空选择。
        elif args.action == 'unregister':  # 卸载前恢复原连接注册。
            result = unregister(root)  # 不删除日志、研究或规则备份。
        else:  # 只读空闲检查。
            result = {'ok': True}  # 没有助手运行。
    except Exception as error:  # 详细私人路径不进入安装或CI输出。
        known = ('MAINTENANCE_CONFLICT', 'NATIVE_REGISTRATION_CONFLICT', 'NATIVE_MIGRATION_CONFLICT', 'COMPONENT_PAYLOAD_MISSING', 'NATIVE_PAYLOAD_MISSING', 'MODULE_ENUMERATION_FAILED', 'MODULE_PATH_UNAVAILABLE', 'KEEPALIVE_ACCEPTANCE_UNAVAILABLE', 'ACCEPTANCE_OUTPUT_EXISTS', 'ASSISTANT_RUNNING', 'INSTANCE_CHANNEL_UNAVAILABLE', 'VPN_NOT_CONNECTED', 'ACCEPTANCE_ARGUMENTS_REQUIRED')  # 只公开本软件定义的固定类别。
        result = {'ok': False, 'error': str(error) if type(error) is ValueError and str(error) in known else 'MAINTENANCE_FAILED'}  # 不回显系统异常、原始配置或路径。
        result['exception_type'] = type(error).__name__  # 异常类型有助于诊断，不含异常原文或私人路径。
        if isinstance(error, ModuleNotFoundError) and error.name and all(part.isidentifier() for part in error.name.split('.')):  # 只允许普通模块标识符。
            result['missing_module'] = error.name  # 不返回任意加载路径。
    print(json.dumps(result, ensure_ascii=True))  # 固定小型协议。
    return 0 if result.get('ok') else 1  # 安装器必须检查退出码。

if __name__ == '__main__':  # 导入没有注册副作用。
    raise SystemExit(main())  # 固定入口。
