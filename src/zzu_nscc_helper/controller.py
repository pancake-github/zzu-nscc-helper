"""只读查询本机Mihomo核心；HTTP仅限回环地址，命名管道仅限本机。"""  # 不返回认证头或原始错误。
import http.client  # 标准库HTTP，无系统代理与自动重试。
import io  # 有界命名管道响应解析。
import ipaddress  # 不通过DNS把控制器请求发到外部。
import json  # 核心API的只读JSON结果。
import time  # 整次本机管道交互的截止。
from urllib.parse import urlsplit  # 严格解析控制器地址。
from PyQt5.QtCore import QCoreApplication  # 工作进程没有GUI时支持本机管道。
from PyQt5.QtNetwork import QLocalSocket, QTcpSocket, QNetworkProxy  # 本机管道与明确禁用代理的TCP。

LIMIT = 1048576  # 核心返回超一MiB则不宣称已核验。
APPLICATION = None  # 后台进程共用一个Qt核心应用。

class ControllerError(Exception):  # 所有外部失败转换为固定类别。
    pass  # 不附secret或API响应。

def address(endpoint):  # 返回实际回环IP和端口，不接受外部主机。
    value = urlsplit('http://' + str(endpoint))  # Mihomo字段应为host:port。
    if value.username or value.password or value.path or value.query or value.fragment or not value.port:  # URL认证和路径不属于控制器入口。
        raise ControllerError('CONTROLLER_ADDRESS')  # 不回显原地址。
    host = value.hostname  # 只接受明确本机地址。
    if host == 'localhost':  # 不依赖用户DNS或hosts。
        host = '127.0.0.1'  # 固定实际回环地址。
    try:  # 只允许IPv4/IPv6字面量。
        ip = ipaddress.ip_address(host)  # 不执行DNS查询。
    except ValueError:  # 非本机域名一律拒绝。
        raise ControllerError('CONTROLLER_ADDRESS') from None  # 不输出主机名。
    if ip.is_unspecified:  # 核心监听所有地址时仍通过本机访问。
        ip = ipaddress.ip_address('127.0.0.1' if ip.version == 4 else '::1')  # 不向0.0.0.0发送。
    if not ip.is_loopback:  # 不把认证头传到局域网或互联网。
        raise ControllerError('CONTROLLER_NOT_LOCAL')  # 固定错误。
    return str(ip), value.port  # 不更改核心监听设置。

def headers(runtime):  # 密钥只在本次本机请求中使用。
    value = runtime.get('secret') or ''  # 不输出实际值。
    if not isinstance(value, str) or any(char in value for char in '\r\n') or len(value) > 4096:  # 不允许注入请求头。
        raise ControllerError('CONTROLLER_AUTH_FORMAT')  # 不回显认证信息。
    result = {'Connection': 'close', 'Accept': 'application/json'}  # 每次查询关闭连接。
    if value:  # 无密钥控制器不发送空Bearer。
        result['Authorization'] = 'Bearer ' + value  # 只留在内存。
    return result  # 调用方不保存或打印。

def parse_body(status, content_type, body):  # 代理错误页和跳转不能当核心状态。
    if status != 200 or 'application/json' not in content_type.casefold() or not body or len(body) > LIMIT:  # 固定响应约束。
        raise ControllerError('CONTROLLER_RESPONSE')  # 不输出响应正文。
    value = json.loads(body)  # 只解释JSON，不执行。
    if not isinstance(value, dict):  # 核心/configs和/rules均返回映射。
        raise ControllerError('CONTROLLER_RESPONSE')  # 数组、标量不可接受。
    return value  # 只交给验证器，不持久化。

def exchange(endpoint, route, request_headers, pipe=True):  # 每次最多五秒，不开放本机监听端口。
    global APPLICATION  # 保留Qt应用到工作进程退出。
    if pipe and (not isinstance(endpoint, str) or not endpoint.startswith('\\\\.\\pipe\\') or any(char in endpoint for char in '\r\n')):  # 拒绝远端UNC管道。
        raise ControllerError('CONTROLLER_NOT_LOCAL')  # 认证不发送给远端。
    APPLICATION = QCoreApplication.instance() or APPLICATION or QCoreApplication([])  # 不创建桌面窗口。
    socket = QLocalSocket() if pipe else QTcpSocket()  # 仅本次本机连接。
    deadline = time.monotonic() + 5  # 总截止包括连接、写入和读取。
    def remaining():  # 每个等待共用同一截止。
        return max(0, int((deadline - time.monotonic()) * 1000))  # 不累计超时。
    try:  # 成功或失败都中断连接。
        if pipe:  # 不要求控制器开放TCP端口。
            socket.connectToServer(endpoint)  # 使用实际运行配置中的本机管道名。
        else:  # 所有地址已经通过回环验证。
            socket.setProxy(QNetworkProxy(QNetworkProxy.NoProxy))  # 忽略系统及应用代理。
            socket.connectToHost(*endpoint)  # 只连接明确的本机IP和实际端口。
        if not socket.waitForConnected(remaining()):  # 无可用核心不继续。
            raise ControllerError('CONTROLLER_UNAVAILABLE')  # 不泄露管道内部错误。
        packet = ('GET ' + route + ' HTTP/1.1\r\nHost: localhost\r\n' + ''.join(key + ': ' + value + '\r\n' for key, value in request_headers.items()) + '\r\n').encode('utf-8')  # 只允许调用者白名单GET路径。
        socket.write(packet)  # 认证只通过本机管道。
        if not socket.waitForBytesWritten(remaining()) and socket.bytesToWrite():  # 所有字节必须有界写出。
            raise ControllerError('CONTROLLER_TIMEOUT')  # 不重试。
        content = bytearray()  # 限定响应缓冲。
        while True:  # HTTP Connection: close完成响应边界。
            content.extend(bytes(socket.readAll()))  # 不记录原文。
            if len(content) > LIMIT + 65536:  # 正文和头部总上限。
                raise ControllerError('CONTROLLER_RESPONSE')  # 不无限读大规则集。
            if socket.state() == socket.UnconnectedState:  # 对方已关闭，尾部已读出。
                break  # 继续标准HTTP解析。
            if remaining() <= 0:  # 严格总截止。
                raise ControllerError('CONTROLLER_TIMEOUT')  # 不留未完成查询。
            socket.waitForReadyRead(remaining())  # 断开时也返回，不忙等。
        class MemorySocket:  # HTTPResponse需要makefile接口。
            def makefile(self, *unused):  # 只解析已受限的内存字节。
                return io.BytesIO(content)  # 不创建文件。
        response = http.client.HTTPResponse(MemorySocket())  # 使用标准chunked和Content-Length解析。
        response.begin()  # 验证HTTP响应头。
        return parse_body(response.status, response.getheader('Content-Type', ''), response.read(LIMIT + 1))  # 有界读取解析后正文。
    finally:  # 不复用认证连接。
        socket.abort()  # 立即清理本次本机请求。

def query(runtime, route):  # 不提供任意API调用能力。
    if route not in ('/configs', '/rules'):  # 禁止PATCH、重载、关闭核心等写操作。
        raise ControllerError('CONTROLLER_ROUTE')  # 固定只读白名单。
    try:  # 第三方库和系统错误均不能带出认证信息。
        request_headers = headers(runtime)  # 临时认证头。
        if runtime.get('external-controller-pipe'):  # Windows实际运行配置可只启用管道。
            return exchange(runtime['external-controller-pipe'], route, request_headers)  # 不要求HTTP端口。
        host, port = address(runtime.get('external-controller') or '')  # 严格本机地址。
        return exchange((host, port), route, request_headers, pipe=False)  # TCP与管道共用严格总截止和有界解析。
    except Exception:  # 任何原始异常可能带本机路径或头内容。
        raise ControllerError('CONTROLLER_CHECK_FAILED') from None  # 固定错误，不回显密钥。
