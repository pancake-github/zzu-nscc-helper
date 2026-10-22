"""45分钟真实验收入口；复用正式界面、扩展和网络工作进程，不改变13分钟间隔。"""  # 仅在用户确认本阶段后运行。
import hashlib  # 核对实际被测冻结程序字节。
import json  # 只保存有限状态和响应摘要。
import os  # 保存本次助手进程编号。
import re  # 从VPN日志中提取脱敏事件词。
import sys  # 使用现有Python环境。
import time  # 以单调时钟测量实际时长。
from pathlib import Path  # 限定输出目录。
from PyQt5.QtCore import QTimer  # 本机每秒检查，不增加网络请求。
from PyQt5.QtNetwork import QLocalServer  # 保持正式单实例唤醒入口。
from PyQt5.QtWidgets import QApplication  # 正式桌面事件循环。
from .app import stamp  # 沿用北京时间与项目目录。
from .tab_app import TabWindow  # 使用未经替换的正式标签控制器。
from ..network import detect_vpn, route_matches  # 只读查询实际目的路由。
from ..instance import InstanceGuard  # 与桌面快捷方式共用单实例锁。

class Audit:  # 仅观测正式控制器并在有界时长结束后停止。
    def __init__(self, window, folder, tab_id, vpn_guid):  # 每次验收独立记录。
        self.window = window  # 同一桌面界面与网络请求出口。
        self.tab_id, self.vpn_guid = tab_id, vpn_guid  # 仅绑定调用者明确指定的新建验收标签。
        self.folder = folder  # 实际记录目录。
        self.folder.mkdir(parents=True, exist_ok=False)  # 拒绝覆盖旧验收。
        self.started = time.monotonic()  # 启动等待截止的基准。
        self.first = None  # 首次真实成功后才开始45分钟。
        self.first_stamp = None  # 识别中途恢复或计时重置。
        self.last_poll = self.started  # 观测本地检查间隔。
        self.max_gap = 0.0  # 不声称未观测到的时间完全在线。
        self.attempted = False  # 只尝试启动一次，不自动重试。
        self.done = False  # 一次验收只结束一次。
        self.receipts = []  # 仅成功摘要，不存响应正文或标签标题。
        self.samples = 0  # 本机路由检查总次数。
        self.bad_routes = 0  # 任一路由异常立即终止。
        self.log_events = []  # 只保留时间和连接事件类别。
        self.log_faults = []  # 日志读取问题与网络结论分开。
        self.offsets = {}  # 增量读取，避免反复扫描大日志。
        self.saved_at = 0.0  # 最多每五秒写一次状态。
        log_root = Path(os.environ['ProgramFiles(x86)']) / 'SafeConnect/SSLVPN Client'  # 现场确认的VPN目录。
        for name in ('client.log', 'userlog.log', 'sslvpn-service.log', 'sslvpn-msc.log'):  # 不修改现有客户端日志。
            path = log_root / name  # 固定已有日志。
            try:  # 日志证据缺失时不能标为通过。
                self.offsets[path] = path.stat().st_size  # 基线只记录长度，不复制历史正文。
            except OSError:  # 保留具体缺失类别，不读取其他私人文件。
                self.log_faults.append({'file': name, 'error': 'BASELINE_LOG_UNAVAILABLE'})  # 终态必须标为证据不足。
        self.timer = QTimer(window)  # 与桌面进程共用生命周期。
        self.timer.setInterval(1000)  # 每秒只做本机检查。
        self.timer.timeout.connect(self.poll)  # 观察正式计时，不发送额外请求。
        self.timer.start()  # 开始有界验收。
        self.save('WAITING_FOR_EDGE')  # 启动立即有状态可查。

    def read_logs(self):  # 只读取基线后的新内容。
        for path, offset in list(self.offsets.items()):  # 不扫描其他日志。
            try:  # 日志轮转或占用不影响GUI事件循环。
                size = path.stat().st_size  # 获取当前大小。
                if size < offset:  # 识别截断或轮转。
                    self.log_faults.append({'time': stamp(), 'file': path.name, 'error': 'LOG_TRUNCATED'})  # 不隐瞒证据缺口。
                    offset = 0  # 仅对新文件从头读取。
                if size == offset:  # 没有新增日志。
                    continue  # 不读取历史数据。
                with path.open('rb') as stream:  # 只读访问。
                    stream.seek(offset)  # 从本次已处理位置开始。
                    data = stream.read(min(size - offset, 262144))  # 单次最多256KiB。
                self.offsets[path] = offset + len(data)  # 后续继续增量读取。
                text = data.decode('utf-16-le', errors='replace').replace('\x00', '')  # 现场日志为UTF16，清理嵌入空字符。
                for line in text.splitlines():  # 不保存原始行。
                    pattern = r'(?i)disconnect\w*|reconnect\w*|登录|退出|断开|重连'  # 只提取可疑会话事件。
                    if path.name == 'userlog.log':  # 用户级日志的连接事件也需检查。
                        pattern += r'|连接|login|logout|connected'  # 防止遗漏自动重连。
                    events = re.findall(pattern, line)  # 不返回账号、IP、口令或正文。
                    if events:  # 仅记录需要复核的事件。
                        times = re.findall(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}:\d{2}', line)  # 提取原有时间。
                        self.log_events.append({'observed': stamp(), 'time': times[:1], 'file': path.name, 'events': events[:8]})  # 固定脱敏字段。
            except OSError:  # 日志被独占或移走。
                item = {'file': path.name, 'error': 'LOG_READ_FAILED'}  # 不记录异常原文。
                if item not in self.log_faults:  # 避免每秒重复记录。
                    self.log_faults.append(item)  # 结果标为需要复核。

    def snapshot(self, state, reason=None):  # 不读取浏览器登录态。
        now = time.monotonic()  # 统一时长依据。
        return {'time': stamp(), 'pid': os.getpid(), 'state': state, 'reason': reason, 'duration_target_seconds': 2700, 'elapsed_seconds': round(now - self.first, 3) if self.first is not None else 0, 'extension_version': self.window.extension_version, 'connected': bool(self.window.bridge.peer), 'active': self.window.engine.active, 'count': self.window.engine.count, 'receipts': self.receipts, 'route_samples': self.samples, 'invalid_route_samples': self.bad_routes, 'max_sample_gap_seconds': round(self.max_gap, 3), 'vpn_log_events': self.log_events, 'vpn_log_faults': self.log_faults, 'extra_probe_requests': 0, 'frozen': bool(getattr(sys, 'frozen', False)), 'network_worker_remaining': self.window.worker is not None, 'test_scope': 'explicit_disposable_tab_only'}  # 仅运行摘要。

    def save(self, state, reason=None, final=False):  # 原子替换本次状态文件。
        data = self.snapshot(state, reason)  # 只含白名单字段。
        path = self.folder / ('result.json' if final else 'progress.json')  # 终态与进度分开。
        temporary = path.with_suffix('.tmp')  # 本验收专用临时文件。
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')  # 不写响应正文。
        temporary.replace(path)  # 避免读取半份JSON。
        self.saved_at = time.monotonic()  # 更新写入时刻。

    def finish(self, state, reason=None):  # 结束只停止助手，不关闭浏览器。
        if self.done:  # 丢弃迟到的结束信号。
            return  # 不重复提示。
        self.done = True  # 先阻止任何后续观测启动。
        self.timer.stop()  # 不留下验收轮询。
        self.read_logs()  # 保存结束前的连接日志变化。
        self.window.grab().save(str(self.folder / '结束前界面.png'))  # 仅保存本软件验收界面。
        self.window.stop()  # 清理网络子进程和所有后续计划。
        self.window.state.setText('任务状态：45分钟验收已结束 · 已停止保活\n' + state + ((' · ' + reason) if reason else ''))  # 保留真实结果供查看。
        self.save(state, reason, final=True)  # 终态在停止后落盘。
        self.save(state, reason)  # 进度文件同步终态。
        if state != 'PASSED':  # 失败时只补充本次验收的明确说明。
            self.window.alert('本次持续验收已停止。\n' + (reason or state) + '\n结果已保存，请核对后手动处理。')  # 替换旧弹窗，不自动重试。

    def poll(self):  # 每秒本地观测，网络仍由正式控制器按780秒发送。
        if self.done:  # 完成后不再进入。
            return  # 无后台动作。
        now = time.monotonic()  # 单调时钟。
        self.max_gap = max(self.max_gap, now - self.last_poll)  # 记录采样缺口。
        self.last_poll = now  # 更新本地采样时刻。
        self.samples += 1  # 记录实际检查次数。
        try:  # 原生路由查询也必须安全失败。
            route_ok = route_matches(self.vpn_guid, '172.99.2.7')  # 不发ping或HTTP探针。
        except OSError:  # 无法确认本机出口。
            route_ok = False  # 不猜测在线。
        if not route_ok:  # 路由消失或改走其他网卡。
            self.bad_routes += 1  # 保存断线证据。
            self.finish('FAILED', 'VPN_ROUTE_INVALID')  # 立即停止后续传输。
            return  # 不自动重新连接。
        self.read_logs()  # 检查VPN是否曾断开或重新登录。
        if not self.attempted:  # 用户仅授权本次一次启动。
            if self.window.bridge.peer and self.window.extension_version == '0.4.0':  # 需要真实新版扩展。
                candidates = [(i, self.window.windows.itemData(i)) for i in range(self.window.windows.count())]  # 内存中筛选已打开页面。
                eligible = [(i, tab) for i, tab in candidates if tab.get('eligible') and tab.get('id') == self.tab_id and getattr(self.window, 'vpn_guid', None) == self.vpn_guid]  # 不新开网页，不绑定无关站点。
                # 不自动选择其他已打开页面；找不到指定验收标签即失败。
                if eligible:  # 存在实际授权标签。
                    self.attempted = True  # 不重试首次绑定。
                    self.window.windows.setCurrentIndex(eligible[0][0])  # 明确当前绑定对象。
                    self.window.start()  # 走正式绑定、真实请求和计时逻辑。
            if not self.attempted and now - self.started >= 60:  # 等待扩展有界。
                self.finish('FAILED', 'EDGE_OR_ELIGIBLE_TAB_UNAVAILABLE')  # 不启动浏览器。
                return  # 结束等待。
        if self.attempted and not (self.window.engine.active or self.window.awaiting or self.window.recovering):  # 正式控制器已经停止。
            self.finish('STOPPED', self.window.state.text())  # 保留停止原因，不重新启动。
            return  # 无补发。
        if self.window.engine.count > len(self.receipts):  # 只收录真实成功。
            result = self.window.last_result or {}  # 正式控制器已验证的摘要。
            if result.get('mode') != 'live' or result.get('tls_verified') is not True or result.get('status') != 200:  # 不接受模拟结果。
                self.finish('FAILED', 'INVALID_REAL_RECEIPT')  # 终止而非伪造成功。
                return  # 不计数。
            succeeded = self.window.engine.due - 780  # 正式计时器的成功时刻，不更改它。
            if self.first is None:  # 首次成功才确定本阶段起点。
                self.first = succeeded  # 开始完整2700秒观察。
                self.first_stamp = self.window.first  # 用于识别中途重置。
                self.window.grab().save(str(self.folder / '首次成功界面.png'))  # 保存本软件起点证据。
            self.receipts.append({'time': self.window.last, 'offset_seconds': round(succeeded - self.first, 3), 'bytes': result.get('bytes'), 'elapsed_seconds': result.get('elapsed'), 'status': 200, 'tls_verified': True})  # 不保存页面正文。
            self.save('RUNNING')  # 成功记录立即可查。
        if self.first is not None and (self.window.first != self.first_stamp or self.window.recovering):  # 中途关闭恢复不算连续验收。
            self.finish('INCONCLUSIVE', 'TARGET_RESTORED_OR_CHANGED_DURING_TEST')  # 另行按终止阶段测试。
            return  # 不冒充连续成功。
        if self.first is not None and now - self.first >= 2700:  # 必须实际经过45分钟。
            offsets = [item['offset_seconds'] for item in self.receipts]  # 已完成请求的相对时刻。
            intervals_ok = len(offsets) == 4 and all(780 <= b - a <= 811 for a, b in zip(offsets, offsets[1:]))  # 正式间隔与宽限内完成。
            clean = continuous_passes(self.receipts, now - self.first, self.max_gap, self.log_events, self.log_faults) and bool(getattr(sys, 'frozen', False))  # 有证据缺口不标为通过。
            self.finish('PASSED' if clean else 'INCONCLUSIVE', None if clean else 'REVIEW_TIMING_OR_VPN_LOG_EVIDENCE')  # 有界结束并停止。
            return  # 不继续第五次请求。
        if now - self.saved_at >= 5:  # 低频本地进度落盘。
            self.save('RUNNING' if self.first is not None else 'STARTING')  # 不发送额外流量。


def continuous_passes(receipts, elapsed, max_gap, events, faults):  # 独立核对连续验收的所有门槛。
    if elapsed < 2700 or max_gap > 30 or events or faults or len(receipts) != 4:  # 时间、采样或日志证据不完整均不能通过。
        return False  # 不以最后一次页面能打开冒充连续在线。
    if any(item.get('status') != 200 or item.get('tls_verified') is not True or not item.get('bytes') for item in receipts):  # 四次都必须有真实TLS和数据。
        return False  # 拒绝模拟或空响应。
    offsets = [item['offset_seconds'] for item in receipts]  # 使用正式引擎的成功时间。
    return offsets[0] == 0 and all(780 <= second - first <= 811 for first, second in zip(offsets, offsets[1:]))  # 不改变780秒间隔。


def run(output, tab_id):  # 维护EXE的明确验收动作，不在普通启动中运行。
    from ..gui import MainWindow, installed_components  # 使用真实统一界面和安装清单。
    selected = installed_components()  # 必须是实际已安装组件。
    if 'keepalive' not in selected or tab_id <= 0:  # 不为缺失组件或未知标签启动测试。
        raise ValueError('KEEPALIVE_ACCEPTANCE_UNAVAILABLE')  # 无网络动作。
    if output.exists():  # 每轮验收必须单独目录。
        raise ValueError('ACCEPTANCE_OUTPUT_EXISTS')  # 不覆盖失败历史。
    app = QApplication.instance() or QApplication(sys.argv[:1])  # 冻结程序正常Qt事件循环。
    app.setQuitOnLastWindowClosed(False)  # 测试期间关闭窗口仍遵循托盘行为。
    guards = [InstanceGuard(), InstanceGuard(prefix='ZZDXVPNKeepalive-')]  # 不抢占原助手或另一个统一版。
    if not all(guard.primary for guard in guards):  # 先核对空闲。
        for guard in guards:  # 只释放本进程的引用。
            guard.close()  # 原任务保持原样。
        raise ValueError('ASSISTANT_RUNNING')  # 不启动第二套请求。
    server = QLocalServer()  # 保持统一软件的重复启动唤醒通道。
    server.setSocketOptions(QLocalServer.UserAccessOption)  # 仅当前用户。
    if not server.listen('ZZU-NSCC-Helper-v1'):  # 不能受管理时不启动请求。
        for guard in guards:  # 回收临时引用。
            guard.close()  # 不影响其他进程。
        raise ValueError('INSTANCE_CHANNEL_UNAVAILABLE')  # 明确拒绝。
    try:  # 所有退出路径都清理自己的界面和网络进程。
        vpn = detect_vpn()  # 仅读取本机路由及DNS。
        if not vpn.get('connected'):  # 不在错误出口做真实测试。
            raise ValueError('VPN_NOT_CONNECTED')  # 等待用户登录。
        owner = MainWindow(selected)  # 真实GUI、后台EXE、扩展和任务互斥。
        audit = Audit(owner.keepalive, output, tab_id, vpn['guid'])  # 不替换网络函数、时钟或绑定实现。
        timer = QTimer(owner)  # 结束后自动释放唯一实例。
        def finished():  # 只在终态已落盘后退出本次验收进程。
            if audit.done:  # 不延长已完成验收。
                timer.stop()  # 不重复执行退出。
                owner.finish_quit()  # 走统一软件的正常清理。
        timer.timeout.connect(finished)  # 不产生额外请求。
        timer.start(1000)  # 结果保存后最多一秒退出。
        def awaken():  # 重复启动只显示当前验收界面。
            peer = server.nextPendingConnection()  # 本机短连接。
            owner.reveal()  # 不新增或重启保活。
            if peer:  # 立即释放客户端。
                peer.disconnectFromServer()  # 不回传标签元数据。
                peer.deleteLater()  # 无长期控制通道。
        server.newConnection.connect(awaken)  # 与普通启动行为一致。
        app.aboutToQuit.connect(lambda: audit.finish('CANCELLED', 'ASSISTANT_EXITED') if not audit.done else None)  # 手动退出必须有终态。
        app.aboutToQuit.connect(owner.cleanup)  # 清理全部本产品子进程。
        owner.show()  # 用户可以查看真实所选标签和计时。
        code = app.exec_()  # 正常780秒计时，无快进或补发。
        result_path = output / 'result.json'  # 补充实际冻结程序身份。
        if result_path.is_file():  # 只更新本次已生成的终态。
            result = json.loads(result_path.read_text(encoding='utf-8'))  # 白名单运行摘要。
            root = Path(sys.executable).resolve().parent  # 实际安装目录。
            result['binary_sha256'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ('zzu-nscc-maintenance.exe', 'zzu-nscc-worker.exe')}  # 与下载资产交叉核对。
            result['network_worker_remaining'] = owner.keepalive.worker is not None  # 退出前再次核对清理。
            if result['network_worker_remaining'] and result['state'] == 'PASSED':  # 不能带残留工作进程通过。
                result.update(state='INCONCLUSIVE', reason='NETWORK_WORKER_REMAINS')  # 保留证据限制。
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')  # 不含账号、正文或浏览器完整标题。
        return code  # 控制器仍须读取终态判定。
    finally:  # 不留下监听或互斥句柄。
        server.close()  # 释放当前用户通道。
        for guard in guards:  # 只释放本次验收锁。
            guard.close()  # 不关闭Edge或其他程序。
