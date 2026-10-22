"""使用 Windows 内核对象保证同一用户会话只有一个助手。"""  # 不依赖 Python 或 pythonw 的应用名。
import ctypes  # 调用内核对象接口。
from ctypes import wintypes  # 正确的句柄宽度。
import hashlib  # 为当前用户生成不含明文路径的作用域。
import os  # 获取当前用户本地数据路径。

class InstanceGuard:  # 生命周期与主应用一致。
    def __init__(self, prefix='ZZUNSCCHelper-'):  # 不创建磁盘锁文件；升级时可同时持有旧版互斥名。
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)  # Windows 内核接口。
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]  # 声明宽字符接口。
        self.kernel.CreateMutexW.restype = wintypes.HANDLE  # 六十四位进程保留完整句柄。
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]  # 关闭自身句柄。
        scope = hashlib.sha256(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')).casefold().encode()).hexdigest()[:24]  # 同一用户的不同 Python 启动方式使用同一标识。
        ctypes.set_last_error(0)  # 清理旧调用错误。
        self.handle = self.kernel.CreateMutexW(None, False, 'Local\\' + prefix + scope)  # 限当前登录会话。
        error = ctypes.get_last_error()  # 必须紧接创建调用读取。
        if not self.handle:  # 创建失败不能冒险启动第二实例。
            raise OSError(error, '无法创建助手单实例锁。')  # 让上层明确报告。
        self.primary = error != 183  # ERROR_ALREADY_EXISTS 表示已有实例。

    def close(self):  # 退出时释放当前进程持有的内核引用。
        if self.handle:  # 允许多次调用清理。
            self.kernel.CloseHandle(self.handle)  # 进程崩溃时系统也会自动释放。
            self.handle = None  # 防止重复关闭。
