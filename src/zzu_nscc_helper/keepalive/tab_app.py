"""统一桌面入口：Edge 标签选择、本机扩展接入与单次恢复。"""  # 真实 HTTPS 请求已接入，持续保活仍需验收。
import time  # 恢复与连接超时。
import uuid  # 每次绑定独立标识，丢弃旧事件。
import os  # 打开本地扩展目录。
import ctypes  # 解析电源消息。
from ctypes import wintypes  # 原生消息结构。
from PyQt5.QtCore import Qt  # 标签选择框右键菜单。
from PyQt5.QtWidgets import QLabel, QPushButton, QHBoxLayout, QApplication, QMenu  # 集成引导控件。
from .app import MainWindow, ROOT, ERRORS  # 复用托盘与隔离模拟工作进程。
from .tab_bridge import TabBridge  # 本机消息通道。
from .native_setup import prepare  # 自动准备内置本机组件。

class TabWindow(MainWindow):  # 替换窗口选择为真实标签页选择。
    def __init__(self, connect=True):  # 子类初始化前准备多态方法所需字段。
        self.bridge = None  # 基类构造期间尚无连接。
        self.tabs = {}  # 仅内存保存标签元数据。
        self.incoming_tabs = {}  # 批量标签快照缓冲，不写入日志。
        self.extension_version = None  # 防止旧版扩展静默进入真实绑定。
        self.token = None  # 未授权恢复。
        self.awaiting = False  # 是否等待页面预检。
        self.recovering = False  # 是否正在单次恢复。
        self.operation_deadline = 0  # 二十秒截止时间。
        super().__init__()  # 创建统一主窗口。
        self.setWindowTitle('SSL VPN 保活助手 · 标签页版 0.4')  # 标明简化操作版本。
        self.resize(880, 540)  # 减少安装和确认步骤占用的空间。
        self.banner.setText('当前：标签页连接与恢复验收阶段；保活仍为离线模拟。\n扩展加载后显示真实标签页；正式 HTTPS 保活仍等待平台资料。')  # 不混淆阶段。
        self.scope_label.setText('选择具体标签页（标题＋网址）。只对手动绑定的超算页面尝试一次关闭后恢复。\n关闭整个窗口、登录失效或恢复失败时停止；不自动重启 Edge。')  # 解释恢复范围。
        self.refresh_button.setText('刷新标签页')  # 不再显示窗口列表。
        self.locate_button.setText('切换到所选标签页')  # 精确定位。
        self.confirm_button.setText('确认绑定此标签页')  # 清晰确认。
        self.locate_button.hide()  # 定位移到右键菜单。
        self.confirm_button.hide()  # 不再要求单独确认。
        self.refresh_button.hide()  # 顶部已有检查与刷新入口。
        self.live_button.hide()  # 尚未开放的正式入口不占主操作区。
        self.mode.hide()  # 离线故障注入场景收进帮助菜单。
        self.mode.insertItem(0, '真实 HTTPS 保活（每13分钟）', 'live')  # 正常入口使用真实请求。
        self.mode.setCurrentIndex(0)  # 不再默认运行模拟。
        self.start_button.setText('绑定并开始（离线验证）')  # 一个动作完成绑定和启动。
        self.windows.setContextMenuPolicy(Qt.CustomContextMenu)  # 在选择框提供辅助定位。
        self.windows.customContextMenuRequested.connect(self.tab_menu)  # 用户右键才显示。
        self.state.setText('任务状态：未启动 · 尚未绑定标签页')  # 初始状态采用标签页表述。
        self.connection = QLabel('正在等待 Edge 标签页连接…')  # 不将未连接误报为未安装。
        self.connection.setWordWrap(True)  # 说明自动换行。
        self.layout().insertWidget(1, self.connection)  # 常驻连接提示。
        row = QHBoxLayout()  # 安装入口集成到同一软件。
        retry = QPushButton('检查连接并刷新标签页')  # 主界面直接面向可执行操作。
        retry.clicked.connect(self.check_connection)  # 可见反馈，不静默无效。
        row.addWidget(retry)  # 放入主操作区。
        help_button = QPushButton('帮助与首次安装')  # 低频工具收进菜单。
        menu = QMenu(help_button)  # 主界面不再占用三个安装按钮。
        menu.addAction('首次安装说明', self.install_help)  # 用户需要时才查看。
        menu.addAction('打开内置扩展目录', lambda: os.startfile(str(ROOT / 'extension')))  # 保留本地引导入口。
        menu.addAction('复制扩展管理地址', lambda: QApplication.clipboard().setText('edge://extensions'))  # 只在帮助内提供。
        scenarios = menu.addMenu('运行模式与离线测试')  # 高级故障注入放在帮助内。
        for index in range(self.mode.count()):  # 保留原有三种离线测试能力。
            scenarios.addAction(self.mode.itemText(index), lambda checked=False, i=index: self.choose_scenario(i))  # 点击时设置隐藏模式。
        help_button.setMenu(menu)  # 单个帮助下拉入口。
        row.addWidget(help_button)  # 完成引导按钮。
        self.layout().insertLayout(2, row)  # 放在选择列表之前。
        self.bridge = TabBridge(self) if connect else None  # 开始仅本机的命名管道服务。
        if connect:  # 预览不创建正式管道或写注册表。
            self.bridge.message.connect(self.received)  # 消息驱动列表与恢复。
            self.bridge.lost.connect(self.disconnected)  # 失联立即停止。
            self.bridge.connected.connect(lambda: self.connection.setText('Edge 本机通道已接入，正在读取标签页…'))  # 接入阶段有明确反馈。
            ready, detail = prepare(ROOT)  # 同一软件启动即准备专用连接键。
            self.connection.setText(detail)  # 显示准备结果。
            if not self.bridge.listening:  # 不冒充已经可连接。
                self.connection.setText('本机扩展通道不可用，请退出重复助手后重新打开。')  # 明确错误。
        else:  # 离线界面验收入口。
            self.connection.setText("界面预览：未连接浏览器，也不发送网络请求。")  # 不冒充正式保活。
        self.mode.currentIndexChanged.connect(self.update_mode_ui)  # 测试模式变更必须同步文案。
        self.update_mode_ui()  # 主按钮明确反映真实或模拟模式。
        self.update_selection()  # 显示未连接状态。

    def check_connection(self):  # 不把无连接刷新当作成功。
        if self.bridge and self.bridge.peer:  # 真实本机连接已存在。
            self.connection.setText('正在向 Edge 请求最新标签页列表…')  # 显示请求状态。
            self.bridge.send('list')  # 直接请求本机标签枚举。
        else:  # 桌面不能假装唤醒未连接的扩展。
            self.connection.setText('尚未连接 Edge。请保持 Edge 打开，软件会自动等待连接；首次升级组件可能需等待一次扩展唤醒。')  # 给出具体操作和原因。

    def update_mode_ui(self, unused=None):  # 模拟和真实模式不能混淆。
        live = self.mode.currentData() == 'live'  # 当前启动模式。
        self.start_button.setText('绑定并开始保活' if live else '绑定并开始（离线测试）')  # 一眼区分是否产生流量。
        self.banner.setText('真实内网传输：首次成功后，每13分钟交互一次。\nTLS 与 VPN 路由检查已启用；融合版仍待打包与真实验收。' if live else '离线测试模式：不发送保活流量。\n要保持 VPN 在线，请在帮助菜单切回“真实 HTTPS 保活”。')  # 不把模拟包装成可用保活。

    def choose_scenario(self, index):  # 停止状态下才允许调整离线场景。
        if not (self.engine.active or self.awaiting or self.recovering):  # 运行中不更换请求行为。
            self.mode.setCurrentIndex(index)  # 仅影响模拟工作进程。
            self.state.setText('任务状态：未启动 · ' + self.mode.itemText(index))  # 明确告知当前测试场景。

    def tab_menu(self, point):  # 辅助定位不再占主界面按钮。
        menu = QMenu(self.windows)  # 选择框的右键菜单。
        action = menu.addAction('切换到所选标签页')  # 原定位功能保留。
        action.setEnabled(self.windows.currentData() is not None and bool(self.bridge and self.bridge.peer))  # 无标签或未连接时禁用。
        action.triggered.connect(self.locate)  # 仅用户点击菜单才切换。
        menu.exec_(self.windows.mapToGlobal(point))  # 在点击位置展示菜单。

    def install_help(self):  # 用户主动打开引导。
        self.alert('扩展已随软件提供。\n在 Edge 打开 edge://extensions，手动启用开发人员模式，选择“加载解压缩的扩展”，选择本软件的 extension 文件夹。\n加载后约30秒内会连接；也可以点击扩展图标立即连接。\n扩展只与本机助手通信；不会读取密码或 Cookie。')  # 不代替用户授予浏览器权限。

    def refresh(self):  # 仅向扩展请求标签列表。
        if getattr(self, 'engine', None) and (self.engine.active or self.awaiting or self.recovering):  # 运行中不换选。
            return  # 保留固定绑定。
        if self.bridge:  # 构造后可发命令。
            self.bridge.send('list')  # 本机 IPC，不访问网页。
        self.fill_list()  # 先显示已有快照。

    def fill_list(self):  # 每个下拉项对应一个标签。
        old = self.windows.currentData()  # 保留当前选择身份。
        old_id = old.get('id') if isinstance(old, dict) else None  # 读取标签编号。
        self.windows.blockSignals(True)  # 列表更新不不断撤销用户选择。
        self.windows.clear()  # 清除失效快照。
        for tab in self.tabs.values():  # 展示真实标签列表。
            prefix = '' if tab.get('eligible') else '〔仅查看〕'  # 非超算页面不能绑定。
            self.windows.addItem(f"{prefix}{tab.get('title', '无标题')}  |  {tab.get('url', '')}", tab)  # 标题网址分别可辨认。
        index = next((i for i in range(self.windows.count()) if self.windows.itemData(i).get('id') == old_id), -1)  # 恢复已选择标签。
        self.windows.setCurrentIndex(index if index >= 0 else (0 if self.windows.count() else -1))  # 默认首项仍不算确认。
        self.windows.blockSignals(False)  # 恢复用户选择信号。
        selected = self.windows.currentData()  # 当前快照。
        if not selected or not old or selected.get('id') != old_id or selected.get('url') != old.get('url'):  # 身份或地址变更。
            self.selection_changed()  # 重新确认。
        else:  # 标题更新不改变绑定授权。
            if self.confirmed:  # 同一地址的新快照替换旧确认数据。
                self.confirmed = selected  # 不因标题变化误判不同目标。
            self.selection_changed()  # 更新版本变化后的启动资格。

    def selection_changed(self, unused=None):  # 用户换选标签。
        self.confirmed = None  # 只在点击绑定并开始时固定目标。
        selected = self.windows.currentData()  # 读取候选。
        allowed = (self.mode.currentData() != 'live' or self.extension_version == '0.4.0' and bool(getattr(self, 'vpn_guid', None))) and bool(selected and selected.get('eligible')) and self.target_alive(selected) and self.worker is None and not (self.engine.active or self.awaiting or self.recovering)  # 正式模式同时要求已检测VPN身份。
        self.start_button.setEnabled(allowed)  # 选择可用目标后即可一步启动。
        self.confirm_button.setEnabled(False)  # 隐藏的兼容按钮不再参与交互。
        self.update_selection()  # 显示独立网址。

    def update_selection(self):  # 清楚展示实际选择和恢复状态。
        target = self.bound if self.engine.active or self.awaiting or self.recovering else self.windows.currentData()  # 运行期用固定目标。
        if not isinstance(target, dict):  # 未连接或没有标签。
            self.selection.setText('标签页列表尚未取得。连接建立后，这里将逐项显示“标题＋网址”。')  # 不反复误报未安装。
            return  # 避免混淆。
        phase = '正在恢复，计时已暂停' if self.recovering else '正在验证目标页面' if self.awaiting else '已绑定，正在监测标签关闭' if self.engine.active else '已选中，点击下方按钮即可绑定并开始'  # 不再显示多余的确认阶段。
        self.selection.setText(f"标签状态：{phase}\n标题：{target.get('title', '')}\n网址：{target.get('url', '')}\n标签编号：{target.get('id')}　窗口编号：{target.get('windowId')}\n{'关闭后尝试重开一次；页面恢复后重新交互计时。' if target.get('eligible') else '此页面仅可查看和定位，不属于已知超算保活目标。'}")  # 不显示混合窗口标题。

    def target_alive(self, target):  # 标签级身份检查。
        return bool(self.bridge and self.bridge.peer and isinstance(target, dict) and target.get('id') in self.tabs and time.monotonic() - self.bridge.last_seen < 7)  # 扩展失联不当作仍存活。

    def locate(self):  # 真正切换所选标签页。
        target = self.bound if self.engine.active else self.windows.currentData()  # 运行时定位绑定目标。
        if target and self.bridge:  # 连接可用时发送。
            self.bridge.send('focus', id=target['id'])  # 扩展激活对应标签并前置窗口。

    def confirm_selection(self):  # 确认目标标签，无联网动作。
        target = self.windows.currentData()  # 当前候选。
        if not target or not target.get('eligible') or not self.target_alive(target):  # 限已知平台页面。
            self.alert('请选择已连接 Edge 中的“计算服务”或“E-File”标签页。其他网页仅可定位。')  # 不绑定任意站点。
            return  # 保持停止。
        self.confirmed = target  # 保存确认。
        self.start_button.setEnabled(True)  # 允许模拟验收。
        self.update_selection()  # 显示已确认。

    def lock_controls(self):  # 异步验证期间也禁止换目标。
        for widget in (self.windows, self.refresh_button, self.confirm_button, self.mode, self.start_button):  # 只锁会话相关控件。
            widget.setEnabled(False)  # 避免重入。

    def start(self):  # 页面预检通过才启动模拟交互。
        if not getattr(self, 'can_start', lambda: True)():  # 统一界面在分流事务或预览期间拒绝启动。
            return  # 不仅依赖按钮禁用状态。
        if self.engine.active or self.awaiting or self.recovering:  # 不并发会话。
            return  # 忽略重复点击。
        if self.mode.currentData() == 'live' and not getattr(self, 'vpn_guid', None):  # 先取得VPN稳定身份。
            self.alert('请先在软件顶部完成本机环境检测并确认VPN已连接。')  # 不猜测接口。
            return  # 不发送实际请求。
        target = self.windows.currentData()  # 候选数据。
        if self.mode.currentData() == 'live' and self.extension_version != '0.4.0':  # 旧扩展绑定逻辑尚未升级。
            self.alert('已接通真实请求，但需要在 Edge 将本地连接器重新加载一次，更新到0.4.0。')  # 明确这是版本更新。
            return  # 不让旧扩展产生无反馈超时。
        if not target or not target.get('eligible') or not self.target_alive(target) or self.worker is not None:  # 一步启动仍检查实际目标与连接。
            self.alert('请选择已连接的“计算服务”或“E-File”标签页。')  # 给出可执行操作。
            return  # 结束。
        self.confirmed = target  # 点击合并按钮即授权本次目标。
        self.bound = target  # 固定当前目标。
        self.token = uuid.uuid4().hex  # 防止旧事件重启新会话。
        self.awaiting = True  # 等待扩展检查页面。
        self.operation_deadline = time.monotonic() + 20  # 验证最多二十秒。
        self.lock_controls()  # 禁止过程中改选。
        self.update_selection()  # 显示正在验证。
        self.state.setText('任务状态：正在验证标签页，尚未开始交互计时。')  # 明确尚无请求。
        if not self.bridge.send('bind', id=target['id'], url=target['url'], token=self.token):  # 指定实际标签。
            self.fail('扩展未连接，无法绑定。')  # 不无限等待。

    def received(self, msg):  # 接收扩展的有限事件。
        event = msg.get('event')  # 固定事件名称。
        if event == 'hello':  # 扩展握手。
            self.extension_version = msg.get('version')  # 接入版本与当前任务分离。
            self.connection.setText('Edge 扩展已连接 · 标签页控制就绪')  # 显示连接成功。
        elif event == 'tabs':  # 真实标签列表。
            self.extension_version = msg.get('version', self.extension_version or '0.3.0')  # 重连时从新列表取得版本。
            incoming = msg.get('tabs', [])  # 缺少列表按空处理。
            if not isinstance(incoming, list):  # 拒绝错误协议。
                return  # 不覆盖现有列表。
            if msg.get('first', True):  # 每一轮快照开始清空临时集合。
                self.incoming_tabs = {}  # 不混合两轮标签列表。
            self.incoming_tabs.update({t['id']: t for t in incoming if isinstance(t, dict) and isinstance(t.get('id'), int) and isinstance(t.get('url'), str)})  # 接收有大小限制的批次。
            if not msg.get('final', True):  # 全部批次到齐前不覆盖当前列表。
                return  # 避免暂时丢失绑定标签。
            self.tabs = self.incoming_tabs  # 原子替换完整列表。
            self.connection.setText(f"Edge 已连接 · 收到 {len(self.tabs)} 个独立标签页（总数 {msg.get('total', len(self.tabs))}）")  # 超过上限时可见。
            if self.extension_version != '0.4.0':  # 旧扩展已连接但尚不支持当前绑定修正。
                self.connection.setText(self.connection.text() + ' · 请重新加载一次扩展以更新到0.4.0')  # 不要求反复尝试。
            if not (self.engine.active or self.awaiting or self.recovering):  # 运行期不改下拉选择。
                self.fill_list()  # 展示全部收到的标签。
        elif event == 'focus_error':  # 标签已关闭导致定位失败。
            self.alert('该标签页已不存在，请刷新列表。')  # 不自动打开未绑定页面。
        elif self.token and msg.get('token') == self.token:  # 以下事件必须属于当前手动会话。
            if event == 'bound' and self.awaiting:  # 页面验证成功。
                self.awaiting = False  # 结束预检。
                MainWindow.start(self)  # 复用隔离模拟请求和十三分钟计时。
            elif event == 'closed' and self.engine.active:  # 目标标签关闭。
                target = self.bound  # 保存固定原网址。
                MainWindow.stop(self)  # 立即取消计时并结束当前工作进程。
                self.bound = target  # 恢复目标描述供单次重开。
                self.recovering = True  # 显示恢复中。
                self.operation_deadline = time.monotonic() + 20  # 连接命令也计入总恢复时限。
                self.lock_controls()  # 恢复中不换选。
                self.state.setText('任务状态：标签页已关闭，正在尝试恢复一次；计时暂停。')  # 用户可随时停止。
                self.update_selection()  # 显示恢复状态。
                self.bridge.send('recover', token=self.token)  # 桌面停好进程后才授权重开。
            elif event == 'restored' and self.recovering:  # 新标签通过页面检查。
                tab = msg.get('tab')  # 恢复后的新身份。
                if not isinstance(tab, dict) or tab.get('url') != self.bound.get('url') or not isinstance(tab.get('id'), int):  # 必须是原目标。
                    self.fail('恢复后的页面与绑定地址不一致。')  # 拒绝错误目标。
                    return  # 停止。
                self.recovering = False  # 结束恢复。
                self.bound = tab  # 更新新标签编号。
                self.tabs[tab['id']] = tab  # 同步身份缓存。
                self.confirmed = tab  # 原恢复授权仅限原网址。
                self.engine.start(time.monotonic())  # 重新开始首次交互，尚不计算十三分钟。
                self.first = self.last = '—'  # 明确本次恢复计时重置。
                self.last_result = None  # 恢复后需要新的真实响应。
                self.update_selection()  # 显示新绑定。
                self.send()  # 成功后再进入十三分钟等待。
            elif event == 'failed':  # 一次尝试失败即停止。
                self.fail('标签页无法验证或恢复（' + str(msg.get('code', 'UNKNOWN'))[:60] + '）。')  # 不自动登录。

    def disconnected(self):  # 桥接程序或 Edge 退出。
        self.connection.setText('Edge 扩展已断开；未自动恢复任务。')  # 不假装在线。
        if self.engine.active or self.awaiting or self.recovering:  # 运行任务必须停止。
            self.fail('Edge 或扩展已断开连接。')  # 立即撤销恢复授权。
        self.tabs = {}  # 不显示过期列表。
        self.fill_list()  # 提示重新连接。

    def tick(self):  # 本地心跳与恢复期限。
        busy = self.engine.active or self.awaiting or self.recovering  # 所有运行阶段。
        if busy and (not self.bridge or not self.bridge.peer or time.monotonic() - self.bridge.last_seen > 7):  # 心跳失联。
            self.fail('扩展心跳中断，任务已停止。')  # 不继续后台交互。
            return  # 不执行旧计时。
        if self.awaiting or self.recovering:  # 恢复与初始检查单独计时。
            if time.monotonic() >= self.operation_deadline:  # 超过二十秒。
                self.fail('标签页验证或恢复超时。')  # 不重试。
            return  # 暂停十三分钟状态机。
        MainWindow.tick(self)  # 正常期使用原状态机。

    def stop(self, reason=None):  # 所有手动或故障停止都撤销扩展权限。
        self.token = None  # 旧事件全部失效。
        self.awaiting = self.recovering = False  # 停止恢复。
        if self.bridge:  # 构造早期可能没有桥接对象。
            self.bridge.send('stop')  # 清除扩展绑定与恢复计时器。
        MainWindow.stop(self, reason)  # 清理工作进程和 UI。
        self.state.setText('任务状态：已停止 · 已解除标签页绑定' + ('\n' + str(reason) if reason else ''))  # 不再提窗口。
        self.selection_changed()  # 需重新确认。

    def fail(self, reason):  # 覆盖异步恢复阶段也能失败。
        if not (self.engine.active or self.awaiting or self.recovering):  # 不重复弹窗。
            return  # 已停止。
        readable = ERRORS.get(reason, str(reason))  # 已知计时错误使用中文说明。
        self.stop(readable)  # 先终止任务。
        self.alert('任务已停止。\n' + readable + '\n请处理后手动重新开始。')  # 一次通知。

    def quit(self):  # 软件退出同时撤销扩展恢复。
        self.stop()  # 不留后台保活。
        if self.bridge:  # 关闭本机通信。
            self.bridge.close()  # 桥接进程随断连退出。
        MainWindow.quit(self)  # 清理托盘退出。

    def nativeEvent(self, event_type, message):  # 异步恢复期间也必须响应睡眠。
        msg = wintypes.MSG.from_address(int(message))  # 读取本地系统消息。
        if msg.message == 0x218 and msg.wParam == 4 and (self.awaiting or self.recovering):  # 睡眠时处于非计时阶段。
            self.stop('电脑即将睡眠，已撤销标签恢复。')  # 同时清除扩展权限。
            self.deferred_notice = '睡眠前已停止标签验证或恢复，请手动重新开始。'  # 唤醒后提醒。
        return MainWindow.nativeEvent(self, event_type, message)  # 正常运行期与唤醒复用基类。
