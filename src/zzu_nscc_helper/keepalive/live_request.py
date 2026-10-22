"""固定内网目标的真实 HTTPS 只读交互；证书链和名称必须同时通过。"""  # 不继承浏览器会话或系统代理。
import ctypes as C  # 查询当前 Windows 目的路由。
from ctypes import wintypes as W  # Windows 原生类型。
import socket  # IPv4 地址编码。
import ssl  # 强制证书校验。
import time  # 请求截止时间。
import requests  # 复用现有可信 CA 集合。
from ..network import route_matches  # 核对已检测到的稳定VPN身份。
import urllib3  # 显式连接内网 IP 并指定 TLS 认证名称。
from ..platform import load_platform  # 共用版本化的平台预设。

PROFILE = load_platform()['keepalive']  # 载入时核对固定范围。
ADDRESS = PROFILE['address']  # 本平台内网地址。
TLS_NAME = PROFILE['tls_name']  # 已验证的TLS名称。
RESOURCE = PROFILE['resource']  # 只读静态平台页面。
MARKERS = tuple(value.encode('utf-8') for value in PROFILE['content_markers'])  # 共用响应判据。
LIMIT = PROFILE['body_limit_bytes']  # 有界读取。

def check_response(status, content_type, body):  # 真实请求验证，不接受任意二百页面。
    if status != 200:  # 跳转、认证失败与网关错误均停止。
        return 'HTTP_STATUS'  # 不跟随跳转。
    if 'text/html' not in content_type.lower():  # 目标应为静态平台 HTML。
        return 'CONTENT_TYPE'  # 拒绝异常格式。
    if not body:  # 必须读回实际数据。
        return 'EMPTY_BODY'  # 空响应不计成功。
    if len(body) > LIMIT:  # 限制意外大响应。
        return 'BODY_TOO_LARGE'  # 不当文件下载器使用。
    if not all(marker in body for marker in MARKERS):  # 必须匹配平台页面。
        return 'CONTENT_MISMATCH'  # 代理错误页不计成功。
    return None  # 已有真实数据与内容证据。

def perform(expected_guid):  # 每次调用创建新连接，确保真实跨 VPN 数据交互。
    started = time.monotonic()  # 记录总耗时。
    if not route_matches(expected_guid, ADDRESS):  # 阻止 VPN 退出后的错误出口。
        return {'ok': False, 'error': 'VPN_ROUTE_INVALID', 'mode': 'live'}  # 不建立网络连接。
    pool = urllib3.HTTPSConnectionPool(ADDRESS, port=443, server_hostname=TLS_NAME, assert_hostname=TLS_NAME, cert_reqs=ssl.CERT_REQUIRED, ca_certs=requests.certs.where(), timeout=urllib3.Timeout(connect=5, read=8), retries=False)  # 完整证书验证；直接连接，不使用代理或 DNS 改写。
    response = None  # 确保任何路径都能清理。
    try:  # 只有这一处真实 GET 出口。
        response = pool.urlopen('GET', RESOURCE, headers={'Host': TLS_NAME, 'Cache-Control': 'no-cache, no-store', 'Pragma': 'no-cache', 'Accept': 'text/html', 'User-Agent': 'ZZDX-VPN-Keepalive/0.4'}, redirect=False, preload_content=False)  # 不传 Cookie，不登录。
        if response.status != 200:  # 状态错误无需再读取正文。
            return {'ok': False, 'error': 'HTTP_STATUS', 'mode': 'live'}  # 立即停止。
        body = bytearray()  # 受限响应缓冲。
        while len(body) < LIMIT:  # 不超过六十四 KiB。
            if time.monotonic() - started >= 20:  # 补充工作进程内部截止检查。
                return {'ok': False, 'error': 'TIMEOUT', 'mode': 'live'}  # GUI 父进程另有二十秒硬终止。
            block = response.read(min(4096, LIMIT - len(body)))  # 分块读取实际网络数据。
            if not block:  # 读到完整响应结束。
                break  # 继续验证正文。
            body.extend(block)  # 累加实际读回字节。
        if len(body) >= LIMIT:  # 触及上限时保守拒绝，不再读取额外字节。
            return {'ok': False, 'error': 'BODY_TOO_LARGE', 'mode': 'live'}  # 关闭连接。
        error = check_response(response.status, response.headers.get('Content-Type', ''), body)  # 检查平台内容。
        if error:  # 任何验证失败不进入计时。
            return {'ok': False, 'error': error, 'mode': 'live'}  # 固定错误类型。
        if not route_matches(expected_guid, ADDRESS):  # 响应期间出口改变也不报保活成功。
            return {'ok': False, 'error': 'VPN_ROUTE_INVALID', 'mode': 'live'}  # 需要手动重启。
        return {'ok': True, 'bytes': len(body), 'elapsed': time.monotonic() - started, 'status': 200, 'tls_verified': True, 'mode': 'live'}  # 不返回或记录页面正文。
    except urllib3.exceptions.SSLError:  # 证书到期、名称或链失败。
        return {'ok': False, 'error': 'TLS_VALIDATION_FAILED', 'mode': 'live'}  # 禁止退回不验证模式。
    except urllib3.exceptions.TimeoutError:  # 网络阶段超时。
        return {'ok': False, 'error': 'TIMEOUT', 'mode': 'live'}  # 无自动重试。
    except (urllib3.exceptions.HTTPError, OSError):  # 网络断开或协议错误。
        return {'ok': False, 'error': 'NETWORK_ERROR', 'mode': 'live'}  # 不输出敏感异常原文。
    finally:  # 成功或失败都清理。
        if response is not None:  # 已收到响应头。
            response.close()  # 不继续后台读取。
        pool.close()  # 不遗留连接或复用缓存。
