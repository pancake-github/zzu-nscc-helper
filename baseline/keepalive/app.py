"""SSL VPN 保活助手：第一阶段界面与离线模拟版。"""  # 尚未通过真实联网验收。
import ctypes  # 解析 Windows 电源通知。
from ctypes import wintypes  # 使用系统消息结构。
import json  # 解析工作进程返回值。
import logging  # 记录最少运行信息。
from logging.handlers import TimedRotatingFileHandler  # 日志每日轮转。
from pathlib import Path  # 所有应用文件限定在项目目录。
import sys  # 获取当前 Python 环境。
import time  # 单调时钟计时。
import re  # 限定可清理的应用日志文件名。
from datetime import datetime, timezone, timedelta  # 固定北京时间显示。
from PyQt5.QtCore import QTimer, QProcess, QLockFile, QStandardPaths  # 定时器、隔离进程和单实例锁。
from PyQt5.QtNetwork import QLocalServer, QLocalSocket  # 本机进程间唤醒，无互联网请求。
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QSystemTrayIcon, QMenu, QMessageBox, QStyle  # 中文桌面控件。
from engine import Engine  # 独立测试的状态机。
import windows  # 只识别 Edge 顶层窗口。

ROOT = Path(__file__).resolve().parent  # 项目根目录。
BJ = timezone(timedelta(hours=8))  # 北京时间。
ERRORS = {'WINDOW_CLOSED': '所选 Edge 窗口已关闭或身份无法确认。', 'TIMEOUT': '单次交互超过二十秒。', 'SUSPEND_OR_DELAY': '电脑睡眠或应用长时间暂停。', 'MISSED_DEADLINE': '已错过计划发送时间，未补发。', 'SIMULATED_FAILURE': '模拟请求失败（没有实际联网）。', 'WORKER_ERROR': '工作进程异常或结果无效。', 'POWER_SUSPEND': '电脑已进入睡眠或休眠，保活已停止。'}  # 仅记录固定错误类别。

ERRORS.update({'VPN_ROUTE_INVALID': '未检测到目标经过 SSL VPN，请检查 VPN 连接。', 'TLS_VALIDATION_FAILED': 'HTTPS 证书名称或证书链验证失败。', 'NETWORK_ERROR': '真实内网传输失败。', 'HTTP_STATUS': '平台返回异常状态或跳转。', 'CONTENT_TYPE': '平台响应格式不符合预期。', 'EMPTY_BODY': '平台未返回数据。', 'BODY_TOO_LARGE': '响应超过允许大小。', 'CONTENT_MISMATCH': '响应不是预期的平台页面。', 'INVALID_MODE': '请求模式无效。'})  # 真实请求的固定错误类别。

def stamp():  # 界面使用固定时区。
    return datetime.now(BJ).strftime('%Y-%m-%d %H:%M:%S')  # 不受主机时区设置影响。

def make_logger():  # 创建本地最小日志。
    folder = ROOT / 'logs'  # 不写入研究数据目录。
    folder.mkdir(exist_ok=True)  # 首次启动建立日志目录。
    for old in folder.glob('events.log.*'):  # 只检查本应用轮转日志。
        suffix = old.name.removeprefix('events.log.')  # 提取日志日期。
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', suffix):  # 不删除其他扩展文件。
            if datetime.strptime(suffix, '%Y-%m-%d').date() < datetime.now(BJ).date() - timedelta(days=6):  # 仅保留最近七个日期。
                old.unlink(missing_ok=True)  # 清理过期应用日志。
    logger = logging.getLogger('vpn-assistant')  # 独立记录器。
    logger.setLevel(logging.INFO)  # 不记录调试请求内容。
    if not logger.handlers:  # 防止测试或重复初始化添加重复处理器。
        handler = TimedRotatingFileHandler(folder / 'events.log', when='midnight', backupCount=6, encoding='utf-8')  # 当前加六份备份。
        handler.setFormatter(logging.Formatter('%(message)s'))  # 时间由应用统一提供。
        logger.addHandler(handler)  # 安装处理器。
    return logger  # 返回记录器。

class MainWindow(QWidget):  # 托盘控制器，不创建浏览器。
    def __init__(self):  # 构建主界面。
        super().__init__()  # 初始化 Qt 窗口。
        self.engine = Engine()  # 默认停止。
        self.bound = None  # 尚未绑定窗口。
        self.confirmed = None  # 选择不等于确认或运行绑定。
        self.worker = None  # 没有网络或模拟进程。
        self.exiting = False  # 区分收起和退出。
        self.notice = None  # 同时最多一个异常弹窗。
        self.deferred_notice = None  # 睡眠期间延迟通知。
        self.first = '—'  # 首次成功时间。
        self.last = '—'  # 最近成功时间。
        self.last_result = None  # 真实响应摘要，仅在界面展示元数据。
        self.logger = make_logger()  # 日志不保存标题、密码或响应正文。
        self.setWindowTitle('SSL VPN 保活助手 · 离线验收版 0.2')  # 防止误认为正式保活。
        self.resize(760, 610)  # 适合中文信息的默认尺寸。
        self.setStyleSheet('QWidget {font-family: Microsoft YaHei; font-size: 14px;} QPushButton {padding: 8px;} QLabel {padding: 4px;}')  # 简洁原生风格。
        layout = QVBoxLayout(self)  # 纵向布局。
        banner = QLabel('第一阶段：仅离线模拟，不能保持 VPN 在线。\n正式保活等待平台地址、证书与路由验收。')  # 常驻说明。
        banner.setStyleSheet('background: #fff2ce; color: #654500; padding: 12px;')  # 醒目标识。
        self.banner = banner  # 子类可更新阶段提示。
        layout.addWidget(banner)  # 放在界面顶部。
        scope = QLabel('选择的是整个 Edge 窗口，不是单个标签页。\n“和另外 N 个页面”是 Edge 自带标题；关闭其中一个标签页不会停止任务。')  # 解释选择范围。
        scope.setWordWrap(True)  # 长说明自动换行。
        self.scope_label = scope  # 标签页模式显示不同范围。
        layout.addWidget(scope)  # 常驻提示。
        self.windows = QComboBox()  # Edge 窗口选择框。
        layout.addWidget(self.windows)  # 显示当前可选窗口。
        self.selection = QLabel()  # 选择和任务状态分开显示。
        self.selection.setWordWrap(True)  # 标题允许换行。
        self.selection.setTextFormat(0)  # 标题只作为纯文本展示。
        self.selection.setStyleSheet('background: #eaf2fa; padding: 10px;')  # 窗口确认卡片。
        layout.addWidget(self.selection)  # 显示当前选择。
        row = QHBoxLayout()  # 窗口操作按钮行。
        self.refresh_button = QPushButton('刷新窗口')  # 手动重新枚举。
        self.refresh_button.clicked.connect(self.refresh)  # 无网络操作。
        row.addWidget(self.refresh_button)  # 添加刷新按钮。
        locate = QPushButton('定位所选窗口')  # 用户主动前置窗口。
        locate.clicked.connect(self.locate)  # 只操作选中窗口。
        self.locate_button = locate  # 标签页模式更新按钮名称。
        row.addWidget(locate)  # 添加定位按钮。
        self.confirm_button = QPushButton('确认使用此窗口')  # 定位后手动确认。
        self.confirm_button.clicked.connect(self.confirm_selection)  # 不自动启动。
        row.addWidget(self.confirm_button)  # 确认按钮。
        layout.addLayout(row)  # 结束窗口操作行。
        self.mode = QComboBox()  # 供第一阶段验收选择场景。
        for title, value in [('模拟成功（仍按13分钟计时）', 'success'), ('模拟请求失败', 'failure'), ('模拟超时（20秒后停止）', 'timeout')]:  # 不提供正式联网选项。
            self.mode.addItem(title, value)  # 保存固定场景参数。
        layout.addWidget(self.mode)  # 显示模拟场景。
        self.state = QLabel('任务状态：未启动 · 尚未绑定窗口')  # 与候选状态区分。
        self.state.setWordWrap(True)  # 故障说明允许换行。
        layout.addWidget(self.state)  # 状态文本。
        self.details = QLabel()  # 时间与计数。
        layout.addWidget(self.details)  # 添加详情。
        buttons = QHBoxLayout()  # 会话按钮行。
        self.start_button = QPushButton('开始离线模拟')  # 不宣称正式可用。
        self.start_button.clicked.connect(self.start)  # 首次立即交互。
        buttons.addWidget(self.start_button)  # 开始按钮。
        live = QPushButton('正式保活：等待平台资料')  # 明确阻塞项。
        self.live_button = live  # 标签页简化界面可以隐藏尚未开放的入口。
        live.setEnabled(False)  # 无法绕过前提。
        buttons.addWidget(live)  # 显示但禁用。
        stop = QPushButton('停止保活')  # 主动停止不弹窗。
        stop.clicked.connect(lambda: self.stop())  # 不将 checked 参数当错误码。
        buttons.addWidget(stop)  # 停止按钮。
        layout.addLayout(buttons)  # 添加控制行。
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), self)  # 使用系统图标。
        menu = QMenu(self)  # 托盘菜单。
        menu.addAction('显示主界面', self.reveal)  # 唤回窗口。
        menu.addAction('停止保活', lambda: self.stop())  # 手动停止。
        menu.addSeparator()  # 分隔退出操作。
        menu.addAction('退出', self.quit)  # 完全清理退出。
        self.tray.setContextMenu(menu)  # 绑定菜单。
        self.tray.activated.connect(lambda reason: self.reveal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)  # 双击打开。
        self.tray.show()  # 驻留系统托盘。
        self.timer = QTimer(self)  # 主线程只做轻量本地检查。
        self.timer.setInterval(1000)  # 每秒检查绑定窗口。
        self.timer.timeout.connect(self.tick)  # 驱动状态机。
        self.timer.start()  # 停止状态也更新界面。
        self.windows.currentIndexChanged.connect(self.selection_changed)  # 换选撤销旧确认。
        self.refresh()  # 初始读取可见 Edge 窗口。
        self.update_details()  # 显示空时间和零计数。

    def log(self, event, **values):  # 严格限制日志字段。
        record = {'time': stamp(), 'state': event, 'mode': 'live' if self.mode.currentData() == 'live' else 'simulation'}  # 永远标注离线模拟。
        record.update({k: v for k, v in values.items() if k in ('error', 'bytes', 'elapsed')})  # 丢弃未知字段。
        self.logger.info(json.dumps(record, ensure_ascii=False))  # 不记录窗口标题。

    def target_alive(self, target):  # 可被标签页模式替换的身份检查。
        return windows.alive(target)  # 原窗口模式用于回归测试。

    def refresh(self):  # 仅停止时允许改绑。
        if self.engine.active:  # 不改变正在运行的身份。
            return  # 保持原绑定。
        self.windows.clear()  # 清空过期列表。
        for index, window in enumerate(windows.enumerate_edge(), 1):  # 编号表示窗口而非标签页。
            self.windows.addItem(f'窗口 {index} · Edge · ' + window.title, window)  # 标题仅作快照。
        self.selection_changed()  # 刷新后重新确认。

    def selection_changed(self, unused=None):  # 选择变化不启动任务。
        self.confirmed = None  # 旧确认失效。
        self.start_button.setEnabled(False)  # 未确认不能开始。
        self.confirm_button.setEnabled(self.windows.currentData() is not None and not self.engine.active)  # 无目标不能确认。
        self.update_selection()  # 更新选择卡片。

    def update_selection(self):  # 明确区分候选、确认和运行绑定。
        target = self.bound if self.engine.active else self.windows.currentData()  # 运行中显示真实绑定。
        if not target:  # 无 Edge 窗口。
            self.selection.setText('当前选择：无。请打开 Edge 后刷新窗口列表。')  # 空状态说明。
            return  # 不显示旧窗口。
        phase = '已绑定，正在监测窗口关闭' if self.engine.active else ('已确认，尚未启动' if self.confirmed == target else '已选中候选，尚未确认／绑定')  # 三态区分。
        self.selection.setText(f'窗口状态：{phase}\n窗口标识：{target.hwnd:X}（区分同名窗口）\n选择时标题：{target.title}\n范围：整个窗口；不读取或判断网页地址、登录状态。')  # 标题不代表登录验证。

    def confirm_selection(self):  # 用户核对后确认。
        target = self.windows.currentData()  # 当前候选。
        if self.engine.active or not target or not self.target_alive(target):  # 重新验证身份。
            self.alert('窗口已失效或任务正在运行，请停止后刷新。')  # 不接受过期确认。
            return  # 不启动。
        self.confirmed = target  # 保存确认对象。
        self.start_button.setEnabled(self.worker is None)  # 未清理进程不允许启动。
        self.update_selection()  # 立刻展示已确认。

    def locate(self):  # 定位当前选中对象。
        target = self.bound if self.engine.active else self.windows.currentData()  # 运行时用固定绑定。
        if target:  # 空列表不操作。
            if not self.engine.active:  # 定位不等于确认。
                self.selection.setText(self.selection.text() + '\n定位后返回助手，核对窗口，再点“确认使用此窗口”。')  # 明确下一步。
            windows.locate(target)  # 校验身份后前置。

    def reveal(self):  # 单实例唤醒与托盘共用。
        self.showNormal()  # 恢复窗口。
        self.raise_()  # 提升窗口层级。
        self.activateWindow()  # 请求键盘焦点。

    def start(self):  # 显式手动启动。
        if self.engine.active or self.worker is not None:  # 禁止并发会话。
            return  # 不创建额外工作进程。
        self.bound = self.windows.currentData()  # 固定本次窗口。
        if self.bound is None or self.confirmed != self.bound:  # 不靠默认首项自动启动。
            self.alert('请先定位核对目标，再点击“确认使用此窗口”。')  # 提示确认步骤。
            return  # 无请求进程。
        if not self.bound or not self.target_alive(self.bound):  # 防止选择后窗口已关闭。
            self.alert('所选 Edge 窗口已失效，请刷新后重新选择。')  # 无后台请求。
            return  # 不启动计时。
        self.first = self.last = '—'  # 清除上一会话时间。
        self.last_result = None  # 不把上一会话的传输当成本次成功。
        self.engine.start(time.monotonic())  # 首次成功前不进入等待状态。
        self.windows.setEnabled(False)  # 禁止运行中改绑。
        self.refresh_button.setEnabled(False)  # 禁止刷新覆盖列表。
        self.mode.setEnabled(False)  # 固定模拟模式。
        self.start_button.setEnabled(False)  # 防止重复点击。
        self.confirm_button.setEnabled(False)  # 运行中不能改确认。
        self.update_selection()  # 显示实际绑定。
        self.log('START')  # 记录启动。
        self.send()  # 立即创建单次请求进程。

    def send(self):  # 所有请求必须走同一出口。
        if not self.engine.active or self.worker is not None:  # 确保最多一个工作进程。
            return  # 不并发。
        proc = QProcess(self)  # 不经 shell 启动。
        self.worker = proc  # 保存可终止对象。
        proc.setProgram(str(Path(sys.executable).with_name('python.exe')))  # 同一现有 Python 环境。
        proc.setArguments(['-X', 'utf8', str(ROOT / 'worker.py'), self.mode.currentData()])  # 无密码、URL或Cookie参数。
        proc.finished.connect(lambda code, status: self.finished(proc, code))  # 回调校验进程身份。
        proc.errorOccurred.connect(lambda error: self.fail('WORKER_ERROR') if self.worker is proc and error == QProcess.ProcessError.FailedToStart else None)  # 启动失败立即停止。
        self.state.setText('任务状态：正在进行真实 HTTPS 交互…' if self.mode.currentData() == 'live' else '任务状态：离线模拟交互中…')  # 不误报网络已成功。
        proc.start()  # Windows Qt 创建无控制台子进程。

    def finished(self, proc, code):  # 只处理当前请求结果。
        if self.worker is not proc or not self.engine.active:  # 丢弃取消后的信号。
            return  # 不重启计时。
        self.worker = None  # 进程已退出。
        data = bytes(proc.readAllStandardOutput())  # 仅接收结构化结果。
        proc.deleteLater()  # 释放 Qt 对象。
        if not self.target_alive(self.bound):  # 结果到达时再次检查窗口。
            self.fail('WINDOW_CLOSED')  # 不接受关闭后的成功。
            return  # 结束。
        try:  # 进程崩溃或输出错误都视为失败。
            result = json.loads(data)  # 解码小型结果。
            if code != 0 or not isinstance(result, dict):  # 验证基本格式。
                raise ValueError()  # 统一固定错误类别。
            if not result.get('ok'):  # 明确失败，不重试。
                self.fail(result.get('error') if result.get('error') in ERRORS else 'WORKER_ERROR')  # 白名单错误码。
                return  # 不接受为成功。
            if self.mode.currentData() == 'live' and (result.get('mode') != 'live' or result.get('status') != 200 or result.get('tls_verified') is not True):  # 真实模式不可接受模拟或未验证结果。
                raise ValueError()  # 不增加成功次数。
            if not self.engine.success(time.monotonic()):  # 二十秒截止时间检查。
                self.fail('TIMEOUT')  # 不接受迟到成功。
                return  # 停止。
        except (ValueError, TypeError):  # 输出不是合法协议。
            self.fail('WORKER_ERROR')  # 保守停止。
            return  # 不计数。
        self.last_result = result  # 仅保存已验证的摘要。
        self.last = stamp()  # 记录最近成功。
        if self.first == '—':  # 首次成功建立时间基准。
            self.first = self.last  # 初次成功时间。
        self.state.setText('任务状态：保活运行中 · 已完成真实 HTTPS 传输' if self.mode.currentData() == 'live' else '任务状态：离线模拟运行中（没有保活流量）')  # 强调模拟性质。
        self.log('SUCCESS', bytes=result.get('bytes'), elapsed=result.get('elapsed'))  # 仅最小元数据。
        self.update_details()  # 立即更新计数。

    def tick(self):  # 每秒本地检查。
        if self.engine.active:  # 只检查运行中的窗口。
            if not self.target_alive(self.bound):  # 最小化不会被判关闭。
                self.fail('WINDOW_CLOSED')  # 停止并提醒。
            else:  # 窗口有效才检查请求时刻。
                event = self.engine.poll(time.monotonic())  # 不使用墙上时钟。
                if event == 'SEND':  # 十三分钟到期。
                    self.send()  # 单次请求。
                elif event:  # 超时、睡眠或错过时间。
                    self.fail(event)  # 不补发。
        self.update_details()  # 刷新剩余时间。

    def update_details(self):  # 时间仅作界面显示。
        seconds = max(0, int(self.engine.due - time.monotonic())) if self.engine.active and self.engine.due else None  # 首次成功前无倒计时。
        countdown = f'{seconds // 60:02d}:{seconds % 60:02d}' if seconds is not None else '—'  # 分秒格式。
        self.details.setText(f'首次成功：{self.first}\n最近成功：{self.last}\n下次交互：{countdown}　成功次数：{self.engine.count}')  # 北京时间文本。
        receipt = f"\n最近实际读回：{self.last_result['bytes']} 字节（HTTP 200，TLS 已验证）" if self.last_result and self.last_result.get('mode') == 'live' else ''  # 真实交互必须有字节和校验结果。
        self.details.setText(self.details.text() + receipt)  # 只有真实结果才显示传输摘要。
        self.tray.setToolTip('SSL VPN 助手 · ' + (('保活运行中' if self.mode.currentData() == 'live' else '离线模拟运行中') if self.engine.active else '已停止'))  # 托盘状态。

    def stop(self, reason=None):  # 先取消计划，再清理进程。
        self.engine.stop()  # 任何后续信号都不能恢复。
        self.bound = None  # 停止即解除绑定。
        self.confirmed = None  # 再启动前重新核对。
        proc, self.worker = self.worker, None  # 先解除回调身份。
        if proc is not None:  # 请求仍在运行。
            proc.kill()  # 直接结束隔离请求进程。
            if not proc.waitForFinished(1500):  # 核实终止结果。
                self.worker = proc  # 保留引用，禁止启动另一进程。
                self.alert('工作进程未确认退出，请关闭助手并检查进程。')  # 不谎报已清理。
            else:  # 子进程退出已确认。
                proc.deleteLater()  # 释放对象。
        self.windows.setEnabled(True)  # 停止后可重新选择。
        self.refresh_button.setEnabled(True)  # 恢复刷新。
        self.mode.setEnabled(True)  # 恢复场景选择。
        self.start_button.setEnabled(False)  # 必须重新确认。
        self.confirm_button.setEnabled(self.windows.count() > 0 and self.worker is None)  # 清理后允许确认。
        self.update_selection()  # 清除已绑定提示。
        self.state.setText('任务状态：已停止 · 已解除窗口绑定' + (' · ' + ERRORS.get(reason, reason) if reason else ''))  # 明确停止原因。
        self.log('STOP', error=reason)  # 不记录异常原文。
        self.update_details()  # 清空倒计时。

    def fail(self, reason):  # 单次故障只通知一次。
        if not self.engine.active:  # 避免多个信号重复通知。
            return  # 已停止不再弹窗。
        self.stop(reason)  # 网络先停止。
        self.alert('保活任务已停止。\n' + ERRORS.get(reason, '未知错误') + '\n浏览器未被关闭；需要手动重新开始。')  # 非模态提醒。

    def alert(self, message):  # 不阻塞事件循环。
        if self.notice:  # 替换旧提示，最多一个。
            self.notice.close()  # 不积累弹窗。
        self.reveal()  # 即使在托盘也展示通知。
        self.notice = QMessageBox(QMessageBox.Icon.Warning, 'SSL VPN 助手提醒', message, QMessageBox.StandardButton.Ok, self)  # 中文错误说明。
        self.notice.open()  # 不使用阻塞式 exec。

    def nativeEvent(self, event_type, message):  # 接收隐藏窗口也能收到的电源通知。
        msg = wintypes.MSG.from_address(int(message))  # 读取系统消息。
        if msg.message == 0x218:  # WM_POWERBROADCAST。
            if msg.wParam == 4 and self.engine.active:  # PBT_APMSUSPEND。
                self.stop('POWER_SUSPEND')  # 睡眠前终止任务。
                self.deferred_notice = '电脑睡眠前已停止保活，唤醒后不会自动恢复。'  # 唤醒时提醒。
            elif msg.wParam in (7, 18) and self.deferred_notice:  # 恢复通知。
                text, self.deferred_notice = self.deferred_notice, None  # 只通知一次。
                QTimer.singleShot(0, lambda: self.alert(text))  # 返回事件循环后展示。
        return super().nativeEvent(event_type, message)  # 其他消息交由 Qt。

    def closeEvent(self, event):  # 主窗口关闭默认收起。
        if self.exiting:  # 明确退出时允许关闭。
            event.accept()  # 完成退出。
        elif QSystemTrayIcon.isSystemTrayAvailable():  # 托盘存在才允许隐藏。
            self.hide()  # 保持后台模拟。
            event.ignore()  # 不关闭进程。
        else:  # 托盘不可用时避免隐藏失联。
            self.quit()  # 安全停止退出。
            event.accept()  # 关闭界面。

    def quit(self):  # 所有退出入口统一清理。
        self.stop()  # 停止请求和计时。
        self.timer.stop()  # 停止本地轮询。
        self.tray.hide()  # 清理托盘图标。
        self.exiting = True  # 标记明确退出。
        QApplication.instance().quit()  # 不关闭浏览器。

def main():  # 无控制台启动入口。
    app = QApplication(sys.argv)  # 建立桌面应用。
    app.setQuitOnLastWindowClosed(False)  # 收起窗口不退出。
    name = 'ZZDX-VPN-Keepalive-Stage1'  # 固定本机单实例通道。
    from instance_guard import InstanceGuard  # 不依赖解释器名称的 Windows 锁。
    guard = InstanceGuard()  # 进程退出时由内核自动释放。
    if not guard.primary:  # 已有实例时只唤醒。
        socket = QLocalSocket()  # 本机命名管道。
        socket.connectToServer(name)  # 不访问互联网。
        if socket.waitForConnected(2000):  # 等待现有实例回应。
            socket.write(b'SHOW')  # 仅发送显示请求。
            socket.waitForBytesWritten(1000)  # 确保请求送达。
        else:  # 现有实例启动中或失去响应。
            QMessageBox.information(None, 'SSL VPN 助手', '已有实例正在启动或没有响应，请稍后从托盘打开。')  # 不创建第二套任务。
        guard.close()  # 关闭第二实例的内核引用。
        return 0  # 第二实例退出。
    QLocalServer.removeServer(name)  # 持锁后清除崩溃遗留的管道。
    server = QLocalServer()  # 本机监听器。
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)  # 限当前用户。
    if not server.listen(name):  # 通道不可用则不运行。
        QMessageBox.critical(None, '启动失败', '无法创建本机单实例通道。')  # 明确错误。
        guard.close()  # 关闭当前实例锁。
        return 1  # 退出并释放锁。
    from tab_app import TabWindow  # 正式入口统一使用标签页模式。
    window = TabWindow()  # 创建唯一控制器。
    def awaken():  # 接收重复启动事件。
        client = server.nextPendingConnection()  # 取本机连接。
        window.reveal()  # 只显示现有界面。
        if client:  # 唤醒时同时提供不含标签内容的本机诊断。
            status = {'pid': __import__('os').getpid(), 'connected': bool(getattr(window, 'bridge', None) and window.bridge.peer), 'tabs': len(getattr(window, 'tabs', {})), 'active': window.engine.active, 'state': window.state.text(), 'connection': getattr(window, 'connection', window.state).text()}  # 只提供计数和运行阶段。
            client.write(json.dumps(status, ensure_ascii=True).encode() + b'\n')  # 本机状态回包。
            client.disconnectFromServer()  # 无长期连接。
            client.disconnected.connect(client.deleteLater)  # 回包完成后释放对象。
    server.newConnection.connect(awaken)  # 绑定唤醒事件。
    app.aboutToQuit.connect(lambda: window.stop())  # 异常正常退出路径再保障一次。
    window.show()  # 初始显示，不自动运行。
    code = app.exec()  # 进入桌面事件循环。
    server.close()  # 释放单实例通道。
    guard.close()  # 释放内核单实例引用。
    return code  # 返回退出状态。

if __name__ == '__main__':  # 禁止导入时自动启动。
    sys.exit(main())  # 应用入口。
