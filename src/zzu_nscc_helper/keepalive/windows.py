"""只枚举和定位 Edge 顶层窗口，不读取标签页或账户信息。"""  # 模块用途。
import ctypes as C  # 调用原生窗口接口。
from ctypes import wintypes as W  # 使用正确的指针宽度。
from dataclasses import dataclass  # 保存不可变窗口身份。
import psutil  # 验证进程创建时间。

user = C.WinDLL('user32', use_last_error=True)  # Windows 原生接口。
user.IsWindow.argtypes = [W.HWND]  # 避免六十四位句柄截断。
user.IsWindowVisible.argtypes = [W.HWND]  # 可见性检查。
user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]  # 进程身份。
user.GetWindowTextLengthW.argtypes = [W.HWND]  # 标题长度。
user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]  # 仅读取窗口标题。
user.GetWindow.argtypes = [W.HWND, W.UINT]  # 查询所有者。
user.GetWindow.restype = W.HWND  # 保持完整句柄。
user.ShowWindow.argtypes = [W.HWND, C.c_int]  # 定位时还原窗口。
user.SetForegroundWindow.argtypes = [W.HWND]  # 请求系统前置。
CALLBACK = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)  # 枚举回调签名。
user.EnumWindows.argtypes = [CALLBACK, W.LPARAM]  # 枚举顶层窗口。

@dataclass(frozen=True)  # 身份信息不可在运行中变更。
class Window:  # 保存绑定对象。
    hwnd: int  # 窗口句柄。
    pid: int  # 所属进程编号。
    born: float  # 进程创建时间。
    title: str  # 仅供界面显示，不写日志。

def identity(hwnd):  # 根据当前句柄读取进程身份。
    pid = W.DWORD()  # 接收原生进程编号。
    user.GetWindowThreadProcessId(hwnd, C.byref(pid))  # 查询所属进程。
    proc = psutil.Process(pid.value)  # 获取进程元数据。
    if proc.name().lower() != 'msedge.exe':  # 首版仅允许 Edge。
        raise ValueError('NOT_EDGE')  # 拒绝其他应用。
    return pid.value, proc.create_time()  # 防止进程编号复用。

def alive(window):  # 每秒进行本地检查。
    try:  # 进程可能在查询中退出。
        return bool(user.IsWindow(window.hwnd)) and identity(window.hwnd) == (window.pid, window.born)  # 最小化仍有效。
    except (psutil.Error, ValueError, OSError):  # 身份无法确认即视为关闭。
        return False  # 不猜测旧窗口仍存在。

def enumerate_edge():  # 获取可选窗口列表。
    result = []  # 只保留符合条件的窗口。
    @CALLBACK  # 保持回调引用直到枚举完成。
    def visit(hwnd, unused):  # 处理一个顶层窗口。
        if user.IsWindowVisible(hwnd) and not user.GetWindow(hwnd, 4):  # 排除隐藏窗口和附属弹窗。
            try:  # 忽略已退出或无法访问的进程。
                pid, born = identity(hwnd)  # 限定 Edge。
                title = C.create_unicode_buffer(user.GetWindowTextLengthW(hwnd) + 1)  # 分配标题缓冲区。
                user.GetWindowTextW(hwnd, title, len(title))  # 读取标题。
                if title.value:  # 排除无标题的辅助窗口。
                    result.append(Window(hwnd, pid, born, title.value))  # 保存完整身份。
            except (psutil.Error, ValueError, OSError):  # 不中断其他窗口枚举。
                pass  # 安全忽略。
        return True  # 继续枚举。
    user.EnumWindows(visit, 0)  # 本地读取，不产生网络流量。
    return result  # 返回界面列表。

def locate(window):  # 用户主动点击定位按钮。
    if alive(window):  # 定位前再次验证身份。
        user.ShowWindow(window.hwnd, 9)  # 还原最小化窗口。
        user.SetForegroundWindow(window.hwnd)  # 系统可能限制抢占焦点。
