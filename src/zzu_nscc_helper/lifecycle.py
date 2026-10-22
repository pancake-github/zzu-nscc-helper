"""只请求经过身份核对的Clash正常退出，绝不强杀。"""  # 供分流事务使用。
import ctypes as C  # Windows Restart Manager和版本资源。
from ctypes import wintypes as W  # 正确句柄宽度。
from pathlib import Path  # 比较实际程序路径。
import subprocess  # 按原命令行重启。
import time  # 有界等待。
import psutil  # 精确进程身份与启动时间。

def file_version(path):  # 不执行未知程序来获取版本。
    api = C.WinDLL('version')  # Windows版本资源接口。
    api.GetFileVersionInfoSizeW.argtypes = [W.LPCWSTR, C.POINTER(W.DWORD)]  # 原生声明。
    api.GetFileVersionInfoW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p]  # 原生声明。
    api.VerQueryValueW.argtypes = [C.c_void_p, W.LPCWSTR, C.POINTER(C.c_void_p), C.POINTER(W.UINT)]  # 原生声明。
    size = api.GetFileVersionInfoSizeW(str(path), None)  # 只读版本块。
    if not size or size > 1048576:  # 无版本或资源异常不猜测。
        return None  # 不允许自动写入未知客户端。
    data = C.create_string_buffer(size)  # 有界缓冲。
    pointer, length = C.c_void_p(), W.UINT()  # 固定版本结构。
    if not api.GetFileVersionInfoW(str(path), 0, size, data) or not api.VerQueryValueW(data, '\\', C.byref(pointer), C.byref(length)) or length.value < 16:  # 查询失败。
        return None  # 只读降级。
    values = C.cast(pointer, C.POINTER(W.DWORD))  # VS_FIXEDFILEINFO固定字段。
    return '.'.join(map(str, (values[2] >> 16, values[2] & 65535, values[3] >> 16)))  # 主、次、修订号。

def clients():  # 不读取环境变量、浏览器参数或其他应用配置。
    found = []  # 多实例由上层拒绝自动修改。
    for process in psutil.process_iter(['pid', 'name', 'exe', 'create_time']):  # 只收集客户端身份。
        try:  # 已退出或权限不足可跳过。
            if (process.info['name'] or '').casefold() == 'clash-verge.exe' and process.info['exe']:  # 不把Mihomo核心当GUI。
                found.append({'pid': process.pid, 'created': process.info['create_time'], 'exe': process.info['exe'], 'version': file_version(process.info['exe'])})  # 不包含控制器凭据。
        except (psutil.Error, OSError):  # 不输出原始系统错误。
            continue  # 仍可显示其他候选。
    return found  # 仅本机私有IPC使用路径。

class ProcessIdentity(C.Structure):  # Restart Manager唯一进程标识。
    _fields_ = [('pid', W.DWORD), ('started', W.FILETIME)]  # PID和内核创建时间共同防复用。

class ClashLifecycle:  # 一个事务只管理一个已确认客户端。
    def __init__(self, identity):  # 构造不停止任何程序。
        self.identity = identity  # 快照身份。
        self.command = None  # 原启动参数只保留在内存，不写备份。
        self.stopped = False  # 只在真实退出后重启。

    def matches(self, process):  # 路径和创建时间都必须一致。
        return abs(process.create_time() - self.identity['created']) < 0.01 and Path(process.exe()).resolve() == Path(self.identity['exe']).resolve()  # 防PID复用。

    def stop(self):  # flags=0明确不启用RmForceShutdown。
        try:  # 客户端可能由用户刚刚退出。
            process = psutil.Process(self.identity['pid'])  # 限定唯一PID。
            if not self.matches(process):  # 身份变化时停止事务。
                return False  # 不对新进程发消息。
            self.command = process.cmdline()  # 重启参数留内存，不返回UI或日志。
            api, session = C.WinDLL('rstrtmgr'), W.DWORD()  # 每次独立会话。
            api.RmStartSession.argtypes = [C.POINTER(W.DWORD), W.DWORD, W.LPWSTR]  # 原生声明。
            api.RmRegisterResources.argtypes = [W.DWORD, W.UINT, C.c_void_p, W.UINT, C.POINTER(ProcessIdentity), W.UINT, C.c_void_p]  # 只登记进程，不登记文件或服务。
            api.RmShutdown.argtypes = [W.DWORD, W.ULONG, C.c_void_p]  # 不强制终止。
            key = C.create_unicode_buffer(33)  # Restart Manager会话键。
            if api.RmStartSession(C.byref(session), 0, key):  # 无法建立正常退出会话。
                return False  # 请用户手动退出。
            try:  # 始终结束会话。
                kernel = C.WinDLL('kernel32', use_last_error=True)  # 直接取得内核时间，避免浮点数损失精度。
                kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]  # 只请求查询权限。
                kernel.OpenProcess.restype = W.HANDLE  # 保留六十四位句柄。
                kernel.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4  # 原生时间布局。
                kernel.CloseHandle.argtypes = [W.HANDLE]  # 只关闭自己打开的句柄。
                handle = kernel.OpenProcess(0x1000, False, process.pid)  # PROCESS_QUERY_LIMITED_INFORMATION。
                if not handle:  # 无权限时不请求退出。
                    return False  # 等用户手动退出。
                created, exited, kernel_time, user_time = (W.FILETIME() for unused in range(4))  # 原始FILETIME输出。
                try:  # 查询后总会关闭句柄。
                    if not kernel.GetProcessTimes(handle, C.byref(created), C.byref(exited), C.byref(kernel_time), C.byref(user_time)) or not self.matches(process):  # 查询期间也防止身份变化。
                        return False  # 不登记错误进程。
                finally:  # 不泄漏进程句柄。
                    kernel.CloseHandle(handle)  # 释放查询句柄。
                entry = ProcessIdentity(process.pid, created)  # 精确的内核创建时间。
                if api.RmRegisterResources(session, 0, None, 1, C.byref(entry), 0, None) or api.RmShutdown(session, 0, None):  # 不使用强杀标志。
                    return False  # 不写配置。
                process.wait(timeout=10)  # 确认进程确实退出。
                self.stopped = True  # 只在确认后授权写入。
                return True  # 正常退出完成。
            finally:  # 即使失败也释放Restart Manager会话。
                api.RmEndSession(session)  # 不关闭其他应用。
        except psutil.NoSuchProcess:  # 原进程已经不存在。
            self.stopped = True  # 可以写入后按已知路径启动。
            return True  # 不匹配其他PID。
        except (psutil.Error, OSError):  # 超时或权限不足。
            return False  # 留给用户处理，绝不强杀。

    def restart(self):  # 只有事务正常停止的应用才重启。
        if self.stopped:  # 拒绝重复或无关启动。
            subprocess.Popen(self.command or [self.identity['exe']], cwd=str(Path(self.identity['exe']).parent), creationflags=subprocess.CREATE_NO_WINDOW)  # 不经shell，不打印启动参数。
            self.stopped = False  # 防重复启动。
