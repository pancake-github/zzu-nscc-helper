"""通过Windows实际目的路由识别VPN接口，不依赖固定网卡名称。"""  # 所有检测均为本机查询。
import ctypes as C  # 使用Windows原生网络接口。
from ctypes import wintypes as W  # 保持原生字段宽度。
import json  # 读取本机检测摘要。
import os  # 限定Windows环境。
import socket  # 编码IPv4目的地址。
import subprocess  # 查询网卡的硬件属性与DNS。
import uuid  # 使用稳定GUID而非临时网卡编号。
from .platform import load_platform  # 平台目标来自经过校验的公共资源。

class Address(C.Structure):  # Windows sockaddr_in。
    _fields_ = [('family', W.USHORT), ('port', W.USHORT), ('ip', C.c_ubyte * 4), ('zero', C.c_ubyte * 8)]  # 固定IPv4布局。

class Interface(C.Structure):  # MIB_IFROW布局。
    _fields_ = [('name', W.WCHAR * 256), ('index', W.DWORD), ('kind', W.DWORD), ('mtu', W.DWORD), ('speed', W.DWORD), ('mac_len', W.DWORD), ('mac', C.c_ubyte * 8)] + [(name, W.DWORD) for name in ('admin', 'oper', 'changed', 'in_bytes', 'in_unicast', 'in_multicast', 'in_drops', 'in_errors', 'in_unknown', 'out_bytes', 'out_unicast', 'out_multicast', 'out_drops', 'out_errors', 'out_queue', 'description_len')] + [('description', C.c_ubyte * 256)]  # 复用已测试原生结构。

def best_interface(destination):  # 每次请求前后快速查询，不启动PowerShell。
    if os.name != 'nt':  # 不猜测其他操作系统路由。
        raise OSError('WINDOWS_REQUIRED')  # 固定错误类别。
    api = C.WinDLL('iphlpapi')  # Windows系统库。
    api.GetBestInterfaceEx.argtypes = [C.POINTER(Address), C.POINTER(W.DWORD)]  # 原生声明。
    api.GetIfEntry.argtypes = [C.POINTER(Interface)]  # 接口说明查询。
    api.ConvertInterfaceIndexToLuid.argtypes = [W.DWORD, C.POINTER(C.c_ulonglong)]  # 临时编号转稳定接口身份。
    api.ConvertInterfaceLuidToGuid.argtypes = [C.POINTER(C.c_ulonglong), C.c_void_p]  # GUID转换。
    api.ConvertInterfaceLuidToAlias.argtypes = [C.POINTER(C.c_ulonglong), W.LPWSTR, C.c_size_t]  # 读取当前显示名称。
    address = Address()  # 初始化结构。
    address.family = socket.AF_INET  # 固定IPv4目标。
    address.ip[:] = socket.inet_aton(destination)  # 只接受实际IPv4地址。
    index = W.DWORD()  # 接口编号输出。
    if api.GetBestInterfaceEx(C.byref(address), C.byref(index)):  # 未找到路由。
        return None  # 不猜测出口。
    row, luid, guid = Interface(), C.c_ulonglong(), (C.c_ubyte * 16)()  # 查询所需缓冲。
    row.index = index.value  # 只查实际目的出口。
    if api.GetIfEntry(C.byref(row)) or api.ConvertInterfaceIndexToLuid(index.value, C.byref(luid)) or api.ConvertInterfaceLuidToGuid(C.byref(luid), guid):  # 任何身份查询失败均拒绝。
        return None  # 不能确认身份。
    alias = C.create_unicode_buffer(257)  # Windows接口名称上限。
    if api.ConvertInterfaceLuidToAlias(C.byref(luid), alias, len(alias)):  # 名称仅用于本机展示和DNS接口绑定。
        return None  # 不发布错误名称。
    description = bytes(row.description[:min(row.description_len, 256)]).decode('utf-8', errors='replace').rstrip('\x00')  # 仅当前接口说明。
    return {'index': index.value, 'guid': str(uuid.UUID(bytes_le=bytes(guid))), 'alias': alias.value, 'description': description, 'up': row.oper in (4, 5)}  # 无账号或凭据。

def route_matches(guid, destination=None):  # 请求阶段只核对已经确认过的VPN身份。
    if not isinstance(guid, str):  # 没有明确身份不能进入真实请求。
        return False  # 需要先检测VPN。
    try:  # GUID或路由异常按失败处理。
        expected = str(uuid.UUID(guid))  # 规范大小写与格式。
        current = best_interface(destination or load_platform()['keepalive']['address'])  # 查询实际目的接口。
        return bool(current and current['up'] and current['guid'] == expected)  # 不依赖接口编号或名称。
    except (OSError, ValueError):  # Windows状态变化或无效身份。
        return False  # 不自动选择新的接口。

def detect_vpn():  # 用户启动或主动刷新时执行较完整的本机核对。
    profile = load_platform()  # 公共平台目标先校验。
    routes = [best_interface(ip) for ip in (profile['keepalive']['address'], profile['sftp']['host'], profile['vpn']['dns'])]  # 仅本机路由查询，无探测流量。
    if any(not row or not row['up'] for row in routes) or len({row['guid'] for row in routes}) != 1:  # 三个目标应经同一已连接VPN接口。
        return {'connected': False, 'error': 'VPN_ROUTES_UNAVAILABLE'}  # 不借用系统默认出口。
    current = routes[0]  # 候选唯一接口。
    script = "$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $a=Get-NetAdapter -IncludeHidden; $d=Get-DnsClientServerAddress -AddressFamily IPv4; @($a | ForEach-Object { $i=$_.ifIndex; [pscustomobject]@{index=$i;hardware=$_.HardwareInterface;dns=@($d | Where-Object InterfaceIndex -eq $i | ForEach-Object ServerAddresses)} }) | ConvertTo-Json -Compress -Depth 4"  # 固定只读查询，不拼接用户名称。
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)  # 不弹控制台，不更改网卡。
    if result.returncode:  # 不输出可能含本机信息的原始错误。
        return {'connected': False, 'error': 'VPN_METADATA_UNAVAILABLE'}  # 需要用户检查。
    records = json.loads(result.stdout.decode('utf-8-sig'))  # 仅系统接口元数据。
    records = records if isinstance(records, list) else [records] if isinstance(records, dict) else []  # 空查询不能冒充接口。
    metadata = next((row for row in records if row['index'] == current['index']), None)  # 精确匹配目的接口。
    if not metadata or metadata.get('hardware') is not False or profile['vpn']['dns'] not in (metadata.get('dns') or []):  # 需要明确虚拟接口并配置了本平台DNS。
        return {'connected': False, 'error': 'VPN_IDENTITY_NOT_CONFIRMED'}  # 不按网卡标题猜测。
    if any(word in current['description'].casefold() for word in ('clash', 'mihomo', 'meta tunnel')):  # Clash TUN不能冒充平台VPN。
        return {'connected': False, 'error': 'TARGET_CAPTURED_BY_CLASH'}  # 不发送实际保活或凭据。
    return {'connected': True, **current, 'dns': profile['vpn']['dns']}  # 只在当前进程和私有IPC中使用。
