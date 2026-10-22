"""一次启动只执行一个任务，认证仅通过父进程匿名管道进入。"""  # 不接受口令参数或环境变量。
import contextlib  # 旧传输核心的终端输出不直通GUI。
import io  # 丢弃原始错误内容。
import json  # 有界JSON协议。
import sys  # 只读父进程管道。
import threading  # 接收取消命令。
import time  # 离线超时测试。
from .platform import DATA, load_platform  # 固定平台与公开主机密钥。
from .network import detect_vpn, route_matches  # 发送凭据前核对VPN目的路由。

def emit(value):  # 进程标准输出只允许结构化小消息。
    sys.__stdout__.write(json.dumps(value, ensure_ascii=True) + '\n')  # 不使用重定向的传输输出流。
    sys.__stdout__.flush()  # 及时交给GUI。

class SummaryOnly(io.TextIOBase):  # 旧核心的普通文本、路径和错误不会进入公共日志。
    def __init__(self):  # 每批独立摘要。
        self.summary = {}  # 未完成时没有成功摘要。
    def write(self, value):  # print最终JSON摘要通常单次写入。
        if value.startswith('{'):  # 其他逐项文本全部丢弃。
            try:  # 不把任意文本当协议。
                item = json.loads(value)  # 仅接收完整JSON。
                self.summary = {key: item[key] for key in ('Status', 'Destination', 'RemoteDirectory', 'Counts', 'Receipt', 'Path', 'RemoteRechecked') if key in item}  # 不返回账号、密码或正文。
            except ValueError:  # 普通非JSON文本忽略。
                pass  # 不回显。
        return len(value)  # 兼容print接口。

def transfer(payload, auth):  # 一次批次最多认证一次。
    from .transfer import context, nscc_download, nscc_upload  # 仅安装传输组件时才导入。
    allowed = {'direction', 'username', 'vpn_guid', 'remote_paths', 'download_root', 'category', 'expected_sha256', 'local_paths', 'remote_directory', 'report_root'}  # 不接受任意主机或密钥路径。
    if set(payload) - allowed or payload.get('direction') not in ('upload', 'download') or not isinstance(payload.get('username'), str) or not payload['username'].strip():  # 必要字段必须实际填写。
        raise ValueError('INVALID_REQUEST')  # 认证前停止。
    if not route_matches(payload.get('vpn_guid'), load_platform()['sftp']['host']):  # 不把密码发到错误出口。
        return {'ok': False, 'error': 'VPN_ROUTE_INVALID'}  # 不建立连接。
    if not isinstance(auth, dict) or set(auth) != {'password'} or not isinstance(auth.get('password'), str) or not auth['password']:  # 不接收文件、环境凭据。
        raise ValueError('AUTH_REQUIRED')  # 不猜测密码。
    secret = [auth.pop('password')]  # 单次读取后释放闭包引用。
    request = {key: value for key, value in payload.items() if key not in ('direction', 'vpn_guid')}  # 核心只接收实际传输字段。
    request['known_hosts'] = str(DATA / 'known_hosts')  # 用户不能改为自动信任的新密钥。
    context.notify = emit  # 进度仅传数量和结果类别。
    def listen():  # GUI取消时不开始后续文件。
        for line in sys.stdin.buffer:  # 本进程专属标准输入。
            if len(line) > 1024:  # 取消消息应非常小。
                context.cancelled.set()  # 错误协议也停止。
                return  # 不解释更多内容。
            try:  # 只接受固定取消命令。
                if json.loads(line) == {'command': 'cancel'}:  # 不执行任意命令。
                    context.cancelled.set()  # 文件事务finally有机会清理。
                    return  # 一次取消足够。
            except ValueError:  # 错误输入停止任务。
                context.cancelled.set()  # 不继续未经确认的传输。
                return  # 不回显输入。
    threading.Thread(target=listen, daemon=True).start()  # 进程退出时不遗留线程进程。
    capture = SummaryOnly()  # 不保存原始输出。
    try:  # 异常原文不能带出认证信息。
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(io.StringIO()):  # 旧CLI文本留在本工作进程。
            core = nscc_upload if payload['direction'] == 'upload' else nscc_download  # 实际共享传输核心。
            code = core.run(request, password_provider=lambda: secret.pop())  # 口令不落盘，每批一次认证。
        result = {'ok': code == 0 and not context.cancelled.is_set(), 'summary': capture.summary}  # 不能把部分成功说成全量验收。
        if context.cancelled.is_set():  # 已完成项仍保留。
            result['error'] = 'CANCELLED_CHECK_RECEIPT'  # 若网络断开，回执中可能有清理未确认项。
        elif code:  # 原核心已写私有逐项回执。
            result['error'] = 'TRANSFER_PARTIAL_FAILURE' if code == 1 else 'RECEIPT_SAVE_FAILED'  # 准确区分文件与回执。
        return result  # 只有白名单摘要。
    finally:  # 不把口令留在长期任务对象中。
        secret.clear()  # 无法承诺解释器内部内存全部覆写。
        auth.clear()  # 本次请求结束释放引用。

def dispatch(task, payload, auth=None):  # 任务名称固定，不导入任意模块。
    if not isinstance(payload, dict):  # 不接受任意JSON类型。
        raise ValueError('INVALID_REQUEST')  # 固定失败。
    if task == 'keepalive':  # 此分支兼容原保活状态机的单JSON结果。
        mode = payload.get('mode')  # 正式模式和测试模式必须区分。
        if mode == 'live':  # 唯一真实HTTPS出口。
            from .keepalive.live_request import perform  # 仅保活组件依赖。
            return perform(payload.get('vpn_guid'))  # 稳定VPN身份在请求前后复核。
        if mode == 'success':  # 用户主动选择的离线验收。
            return {'ok': True, 'bytes': 128, 'elapsed': 0.0, 'mode': 'simulation'}  # 绝不伪装真实结果。
        if mode == 'timeout':  # 父进程应在二十秒终止。
            time.sleep(60)  # 仅离线测试分支。
        return {'ok': False, 'error': 'SIMULATED_FAILURE' if mode == 'failure' else 'INVALID_MODE'}  # 无自动重试。
    if task == 'detect':  # 只读本机环境。
        try:  # 可选Clash检测失败不能阻止单独使用SFTP或保活。
            from .routing import detect  # 未安装分流组件时不强制加载它。
            environment = detect(payload.get('config_root'))  # 摘要由检测器逐字段过滤。
        except Exception:  # 不回显可能包含订阅的解析错误。
            environment = {'vpn': detect_vpn(), 'writable': False, 'error': 'CLASH_DETECTION_UNAVAILABLE'}  # 仍独立核对VPN，不允许分流写入。
        return {'ok': True, 'environment': environment}  # 组件之间保持独立。
    if task == 'routing_preview':  # 不能信任GUI传回的旧完整快照。
        from .routing import detect, preview  # 重新核对真实配置及版本。
        return {'ok': True, 'plan': preview(detect(payload.get('config_root')))}  # 不写Clash配置。
    if task == 'routing_history':  # 重启后仅读取本机事务摘要。
        from .routing import history  # 不返回原配置。
        return {'ok': True, 'history': history()}  # 不上传历史记录。
    if task in ('routing_apply', 'routing_rollback'):  # 必须由GUI明确点击确认。
        from .routing import transact  # 文件写入限制在精确计划。
        return {'ok': True, 'transaction': transact(payload['id'], rollback=task == 'routing_rollback')}  # 不返回备份内容。
    if task == 'sftp':  # 传输与保活分别拥有工作进程。
        return transfer(payload, auth)  # 不复用浏览器会话。
    raise ValueError('UNKNOWN_TASK')  # 拒绝任意代码执行入口。

def main():  # PyInstaller独立工作程序与源码入口共用。
    task = None  # 解析失败也能安全返回固定错误。
    try:  # 不打印原始请求或异常。
        packet = sys.stdin.buffer.readline(1048577)  # 最大一MiB初始请求。
        if len(packet) > 1048576 or not packet.endswith(b'\n'):  # 帧必须完整。
            raise ValueError('INVALID_REQUEST')  # 不接受截断消息。
        request = json.loads(packet)  # 不使用pickle或eval。
        packet = b''  # 尽早释放带口令的原始字节。
        if not isinstance(request, dict) or set(request) - {'task', 'payload', 'auth'}:  # 协议严格限制。
            raise ValueError('INVALID_REQUEST')  # 不处理额外指令。
        task = request.pop('task', None)  # 固定任务。
        auth = request.pop('auth', None)  # 仅保存在本次工作进程。
        if auth is not None and task != 'sftp':  # 其他模块没有认证需要。
            raise ValueError('UNEXPECTED_AUTH')  # 不接受凭据混入其他任务。
        result = dispatch(task, request.pop('payload', {}), auth)  # 执行一个任务。
    except Exception as error:  # 任何失败只返回固定类别。
        try:  # 仅保活或SFTP安装也必须能安全返回失败。
            from .routing import RoutingError  # 已安装分流组件时使用其固定错误类型。
            routing_errors = (RoutingError,)  # 不以任意异常原文作为公开错误。
        except ImportError:  # 分流业务代码可能没有安装。
            routing_errors = ()  # 不依赖未选组件来处理异常。
        known = ('VPN_ROUTE_INVALID', 'INVALID_REQUEST', 'UNKNOWN_TASK', 'AUTH_REQUIRED', 'UNEXPECTED_AUTH')  # 不接受任意异常字符串。
        category = str(error) if isinstance(error, routing_errors) or type(error) is ValueError and str(error) in known else {'AuthenticationException': 'AUTH_FAILED', 'BadHostKeyException': 'HOST_KEY_MISMATCH', 'Cancelled': 'CANCELLED_CHECK_RECEIPT', 'TimeoutExpired': 'LOCAL_DETECTION_TIMEOUT', 'TimeoutError': 'NETWORK_TIMEOUT'}.get(type(error).__name__, 'TASK_FAILED')  # 不输出账户密码或服务器异常原文。
        result = {'ok': False, 'error': category}  # 不附堆栈。
    if task != 'keepalive':  # GUI任务使用事件帧。
        result = {'event': 'result', **result}  # 保活旧状态机则仍使用原协议。
    emit(result)  # 只有此处输出终态。
    return 0  # 业务失败由ok明确表示，进程退出用于确认清理。
