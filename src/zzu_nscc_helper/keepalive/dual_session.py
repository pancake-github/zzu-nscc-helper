"""独立 VPN 保活与浏览器内 E-File 周期文件交互。"""  # 文件服务成功不代表门户会话续期。
import re  # 隐藏显示中的会话路径参数。
import time  # 使用单调时钟调度。
import uuid  # 每次网页绑定使用新的本机授权标识。
from PyQt5.QtWidgets import QLabel, QCheckBox  # 分别显示网页状态和范围。
from .app import MainWindow, stamp  # 复用已验证的独立 HTTPS 工作进程。
from .tab_app import TabWindow  # 保留扩展连接、列表及首次安装引导。

WEB_ERRORS = {  # 只将有限类别写日志，不接受网页原文。
    'WEB_LOGIN_EXPIRED': 'E-File 服务认证已失效，请在浏览器确认登录后重新绑定。',  # 不将文件认证失败冒充全部门户状态，也不自动登录。
    'WEB_TARGET_CHANGED': '网页地址或登录会话已改变，请重新绑定。',  # 不猜测新会话。
    'WEB_TARGET_CLOSED': '参与维护的网页已关闭，请选择现有业务页重新绑定。',  # 不关闭其他网页。
    'WEB_PAGE_NOT_READY': '业务页尚未就绪，请打开已登录的业务页；助手会自动重试。',  # 不要求反复重新绑定，也不把静态页面当已登录。
    'WEB_DISCONNECTED': 'Edge 或连接器已断开，网页维护已暂停。',  # VPN 不随浏览器退出。
    'WEB_TIMEOUT': '网页请求暂时超时。',  # 确认取消后自动退避恢复。
    'WEB_NETWORK': '网页网络暂时不可达。',  # 不把一次网络波动当登录失效。
    'WEB_SERVER_BUSY': '平台暂时繁忙。',  # 服务端忙时降低请求频率。
    'WEB_LOGIN_CHANGED': '浏览器登录账户已改变，请重新绑定。',  # 不把原会话响应写入另一账户页面。
    'WEB_CANCEL_UNCONFIRMED': '未收到网页请求结束确认，网页维护已暂停。',  # 不能在状态未知时叠加请求。
    'WEB_RESPONSE_INVALID': '网页接口返回内容不符合平台成功判据。',  # 错误页面不计成功。
    'WEB_NETWORK_OR_PARSE': '网页请求或响应解析失败。',  # 不记录正文。
    'WEB_CANCELLED_OR_TIMEOUT': '网页请求已取消或超过20秒。',  # 仅当前页面的请求被取消。
    'WEB_RESPONSE_TOO_LARGE': '网页响应超过64KiB上限。',  # 不放宽读取保护。
    'WEB_RESPONSE_EMPTY': '网页响应为空。',  # 必须实际读回数据。
    'WEB_SERVICE_UNSUPPORTED': '当前集群的 E-File 服务参数无法确认，网页维护已暂停。',  # 不猜测路径或扩大域名权限。
    'WEB_SERVICE_REJECTED': '文件服务暂未完成操作，将核对同一事务后重试。',  # 不增加随机文件。
    'WEB_OWNERSHIP_UNCONFIRMED': '身份、主目录或文件归属无法确认，网页维护已暂停；未自动删除文件。',  # 不越界清理。
    'WEB_FILE_MISMATCH': '专用文件大小或SHA-256不符，已保留文件并暂停网页维护。',  # 不把损坏内容当成功。
    'WEB_CLEANUP_PENDING': '本轮文件清理尚未确认，将优先处理原文件。',  # 不开始下一轮。
    'WEB_MISSED': '网页交互错过计划时刻，已暂停。',  # 不集中补发。
}  # 结束固定类别。
WEB_TRANSIENT = {'WEB_TIMEOUT', 'WEB_NETWORK', 'WEB_SERVER_BUSY', 'WEB_RESPONSE_EMPTY', 'WEB_PAGE_NOT_READY', 'WEB_CLEANUP_PENDING', 'WEB_SERVICE_REJECTED'}  # 与扩展的可恢复错误保持一致。
WEB_INTERVAL = 18000  # E-File完整文件事务成功后等待5小时；VPN仍为780秒。
WEB_STAGE_LABELS = {'dispatch': '等待扩展', 'identity': '核对身份与服务', 'directory': '核对专用目录', 'upload': '上传1KiB文件', 'readback': '完整读回与SHA-256校验', 'delete': '删除本轮文件', 'absence': '确认文件不存在', 'complete': '清理已确认', 'idle': '尚未开始'}  # 固定阶段名称不含路径。

def display_url(value):  # 界面隐藏会话标识，绑定仍在内存中使用完整地址。
    return re.sub(r';jsessionid=[^?#/]*', ';jsessionid=〔已隐藏〕', value).split('?', 1)[0]  # 不把身份参数显示给截图或日志。

class DualSessionWindow(TabWindow):  # 新版默认入口；历史严格标签恢复类仅保留兼容测试。
    def __init__(self, connect=True):  # 先准备基类构造会动态访问的状态。
        self.web_capable = False  # 旧扩展不能冒充支持网页交互。
        self.web_due = None  # 首次网页真实成功前不倒计时。
        self.web_pending = False  # 严格禁止并发网页轮次。
        self.web_pages = 0  # 本次绑定的业务页数量。
        self.web_count = 0  # 成功轮数与 VPN 成功次数分离。
        self.web_request_id = 0  # 丢弃迟到或重复结果。
        self.web_failures = 0  # 连续失败次数，成功后清零。
        self.web_warned = False  # 一次持续故障只提醒一次。
        self.web_retry_notice = None  # 只记本次网页重试提醒及其绑定身份，不接管其他提醒。
        self.web_cancelling = False  # 超时后等待取消确认，禁止叠加新请求。
        self.web_synced = 0  # 页面内同步与服务器HTTP成功分别显示。
        self.web_diagnostic = None  # 固定错误位置和类型，仅供脱敏诊断。
        self.web_cleanup = '尚未开始'  # 清理状态与成功时间分开，失败不会假装已删除。
        self.web_stage = 'idle'  # 仅使用固定诊断阶段。
        self.web_first = self.web_last = '—'  # 网页真实成功时间。
        self.web_summary = '尚未启动 E-File 文件交互。'  # 不依赖 VPN 状态猜测门户登录状态。
        self.web_label = None  # 基类构造阶段尚无独立标签。
        super().__init__(connect=connect)  # 保留现有扩展安装与桥接。
        self.related = QCheckBox('关联同一登录会话下已打开的 E-File、计算服务和命令行页面（最多10页）')  # 关联本地状态不表示门户会话已续期。
        self.related.setChecked(True)  # 与界面说明一致，只在点击开始时确定页面集合。
        self.layout().insertWidget(4, self.related)  # 放在选择与状态区域附近。
        self.web_label = QLabel()  # 网页结果不混入 VPN 计数。
        self.web_label.setWordWrap(True)  # 多行显示清楚。
        self.layout().addWidget(self.web_label)  # 位于统一面板内。
        self.scope_label.setText('选择一个已登录的超算业务页。将按所选集群在个人主目录建立随机助手专用目录，上传、校验并删除1KiB测试文件；不刷新页面、不发送终端命令。\n关闭浏览器或重新登录不会结束 VPN 保活；E-File文件交互暂停后可重新绑定。')  # 准确说明新生命周期。
        self.update_mode_ui()  # 构造完成后更新真实模式提示。
        self.update_details()  # 显示两套独立状态。

    def update_mode_ui(self, unused=None):  # 不把离线模拟冒充网页传输。
        live = self.mode.currentData() == 'live'  # 当前模式。
        self.banner.setText('VPN：13分钟一次HTTPS传输；E-File文件交互：5小时一次。\n首次立即上传1KiB专用文件、读回校验、删除并确认不存在；完整成功后计时，短暂故障自动退避。文件交互成功不代表门户会话已续期。' if live else '离线模拟：不发送 VPN 或 E-File 保活流量。')  # 实际时间与认证层次分别说明。
        self.start_button.setText('重新绑定网页' if self.engine.active else '绑定并开始双通道保活' if live else '开始离线模拟')  # 无额外确认步骤。

    def target_alive(self, target):  # VPN 生命周期不再依赖标签存活。
        return True if self.engine.active else super().target_alive(target)  # 启动仍要求用户选择真实已连接的目标。

    def selection_changed(self, unused=None):  # 支持运行中网页暂停后的重新选择。
        selected = self.windows.currentData()  # 当前候选。
        free = not (self.awaiting or self.web_pending or self.web_due is not None)  # 活跃网页维护期间不直接改绑。
        live = self.mode.currentData() == 'live'  # 模拟不要求新版能力。
        allowed = bool(selected and selected.get('eligible') and self.bridge and self.bridge.peer and time.monotonic() - self.bridge.last_seen < 7)  # 仅真实当前标签可绑定。
        allowed = allowed and free and (not live or self.web_capable and bool(getattr(self, 'vpn_guid', None))) and getattr(self, 'can_start', lambda: True)()  # 尊重预览和分流事务互锁。
        self.start_button.setEnabled(allowed and (self.worker is None or self.engine.active))  # 网页重绑不另起 VPN 请求。
        self.confirm_button.setEnabled(False)  # 不复活旧的隐藏确认按钮。
        self.update_selection()  # 展示当前目标。
        self.update_mode_ui()  # 主按钮准确反映行为。

    def update_selection(self):  # 不显示账号会话参数。
        selected = self.bound if self.token else self.windows.currentData()  # 网页绑定与 VPN 分离。
        if not isinstance(selected, dict):  # 扩展尚无列表。
            self.selection.setText('请选择已登录的 E-File、计算服务或命令行页面。')  # 不要求重启其他业务页。
            return  # 无网址可展示。
        self.selection.setText(('网页已绑定' if self.token else '已选中业务页' if selected.get('eligible') else '此页不能用于 E-File 文件交互') + '\n' + display_url(selected.get('url', '')))  # 只展示脱敏地址，不声称门户续期。

    def fill_list(self):  # 使用基类选择身份逻辑后脱敏可见文本。
        super().fill_list()  # 完整 URL 仍仅保存在条目内存中。
        for index in range(self.windows.count()):  # 标题无需写日志。
            tab = self.windows.itemData(index)  # 原始身份用于精确匹配。
            self.windows.setItemText(index, ('〔仅查看〕' if not tab.get('eligible') else '') + tab.get('title', '无标题') + ' | ' + display_url(tab.get('url', '')))  # 隐藏会话参数。

    def start(self):  # 用户一次点击启动两种真实交互，或只重新绑定网页。
        if not getattr(self, 'can_start', lambda: True)() or self.awaiting or self.web_pending or self.web_due is not None:  # 不并发、不绕过事务互锁。
            return  # 保留当前任务。
        target = self.windows.currentData()  # 读取当前选择。
        live = self.mode.currentData() == 'live'  # 测试模式不发送网页请求。
        if not target or not target.get('eligible') or not self.bridge or not self.bridge.peer:  # 无效选择不启动。
            self.alert('请选择已连接 Edge 中的已登录超算业务页。')  # 不请求敏感登录信息。
            return  # 无请求。
        if live and (not self.web_capable or not getattr(self, 'vpn_guid', None)):  # 版本和路由检查都有依据。
            self.alert('请确认VPN检测通过，并将内置Edge扩展更新到0.5.3后重新加载一次。')  # 新版仍核对明确的文件交互能力。
            return  # 旧扩展不能降级成只有静态流量。
        self.bound = self.confirmed = target  # 保存当前授权身份。
        if live:  # 网页任务由首次 VPN 真实成功后开始。
            self.token = uuid.uuid4().hex  # 同本次页面集合绑定。
            self.awaiting = True  # 初次检查必须完成。
            self.operation_deadline = time.monotonic() + 25  # 覆盖 VPN 首次请求与本机绑定。
            self.web_first = self.web_last = '—'  # 不拼接旧会话结果。
            self.web_count = 0  # 重新绑定的新计数。
            self.web_failures = self.web_synced = 0  # 不拼接旧故障与页面同步状态。
            self.web_warned = self.web_cancelling = False  # 新授权有独立通知周期。
            self.web_summary = '等待 VPN 首次验证后发起 E-File 文件交互。'  # 首次没有请求不能显示成功。
            self.lock_controls()  # 绑定期间禁止改选。
            self.related.setEnabled(False)  # 页面范围固定于本次授权。
        if not self.engine.active:  # 独立 VPN 已运行时不重置其时刻。
            self.first = self.last = '—'  # 新 VPN 会话的时间。
            self.last_result = None  # 不接受旧摘要。
            self.engine.start(time.monotonic())  # 保留20秒总截止和780秒成功后间隔。
            self.log('START')  # 只记录技术事件。
            self.send()  # 使用原来经 TLS 和路由验证的工作进程。
        elif live:  # VPN 已运行，网页可独立重新绑定。
            self.bind_web()  # 不额外发 VPN 静态请求。
        self.update_details()  # 显示真实等待状态。

    def bind_web(self):  # 本地授权命令本身不计网络成功。
        if not self.token or not self.bound or not self.bridge or not self.bridge.send('web_bind', token=self.token, id=self.bound['id'], url=self.bound['url'], related=self.related.isChecked(), protocol=3):  # 新旧桌面不混淆服务器成功与页面同步。
            self.pause_web('WEB_DISCONNECTED')  # 保留已成功的 VPN。

    def finished(self, proc, code):  # 先校验原 VPN 工作进程，再启动初次网页交互。
        before = self.engine.count  # 只有新增真实成功才触发。
        MainWindow.finished(self, proc, code)  # TLS、路由、总时限及进程清理保持不变。
        if self.engine.active and self.engine.count > before and self.awaiting and self.token:  # 网页重绑之外的初次准备。
            self.bind_web()  # 不把本次静态响应当网页登录成功。

    def request_web(self):  # 仅桌面调度网页请求，扩展无后台重试或独立循环。
        if not self.engine.active or not self.token or self.web_pending:  # 停止后不再发送。
            return  # 不并发。
        self.web_due = None  # 请求期间不重复倒计时。
        self.web_pending = True  # 等待本轮完成。
        self.web_request_id += 1  # 唯一轮次丢弃迟到消息。
        self.operation_deadline = time.monotonic() + 420  # 多阶段每请求30秒；整轮七分钟上限，不随进度无限延长。
        self.web_cancelling = False  # 新轮次不继承取消状态。
        self.web_stage = 'dispatch'  # 实际网络开始由扩展另行确认。
        self.web_summary = f'正在执行本轮 E-File 文件交互（关联{self.web_pages}页）…'  # 仅完整上传校验和清理后成功。
        self.log('WEB_REQUEST')  # 只记录固定状态，便于核对请求缺口。
        if not self.bridge or not self.bridge.send('web_request', token=self.token, request=self.web_request_id):  # 只发本机请求命令。
            self.pause_web('WEB_DISCONNECTED')  # 网页停止，VPN继续。

    def received(self, msg):  # 新协议事件只接收脱敏摘要。
        event = msg.get('event')  # 有限类型。
        if event == 'hello':  # 需要明确能力，不能从旧协议号猜测。
            self.web_capable = 'web-daily-file-v1' in msg.get('capabilities', [])  # 需要后台请求与取消确认能力。
        if event in ('hello', 'tabs', 'focus_error'):  # 复用本机列表与辅助定位。
            if event == 'tabs':  # 新扩展允许命令行页面关联周期文件维护。
                self.web_capable = self.web_capable or msg.get('sessionProtocol') == 3  # 空标签列表也可重新协商，不要求反复重载。
                msg = dict(msg, tabs=[dict(t, eligible=bool(t.get('sessionEligible'))) for t in msg.get('tabs', []) if isinstance(t, dict)])  # 不扩大旧恢复范围。
            super().received(msg)  # 只处理这些无旧生命周期副作用的事件。
            if event == 'tabs' and not self.token: self.fill_list()  # VPN运行且网页已暂停时可选择新页面。
            if not self.web_capable: self.connection.setText(self.connection.text() + ' · E-File文件交互需要扩展0.5.3')  # 不静默降级。
            return  # 不进入旧版关闭即停逻辑。
        if not self.token or msg.get('token') != self.token:  # 忽略其他绑定的结果。
            return  # 不重启任务。
        if event == 'web_bound' and self.awaiting:  # 标签集合绑定完成，仍需实际交互。
            pages = msg.get('pages')  # 限制合理数量。
            if not isinstance(pages, int) or not 1 <= pages <= 10:  # 错误协议不能扩大请求量。
                self.pause_web('WEB_RESPONSE_INVALID')  # 不发送请求。
                return  # 无有效页面集合。
            self.awaiting = False  # 结束本机绑定阶段。
            self.web_pages = pages  # 本轮实际参与页面数。
            self.request_web()  # 首次立即发送网页请求。
        elif event == 'web_progress' and self.web_pending and msg.get('request') == self.web_request_id and msg.get('stage') in WEB_STAGE_LABELS:  # 不接受任意网页文本。
            self.web_stage = msg['stage']  # 当前固定阶段。
            if self.web_stage in ('upload', 'readback', 'delete', 'absence'): self.web_cleanup = '本轮待确认；未完成时先恢复原文件'  # 上传不明也保留恢复信息。
            self.log('WEB_' + self.web_stage.upper())  # 固定阶段可定位上传、校验或清理问题。
        elif event == 'web_targets' and type(msg.get('pages')) is int and 1 <= msg['pages'] <= 10:  # 单页关闭只缩小范围。
            self.web_pages = msg['pages']  # 仍有目标时继续原计时。
        elif event == 'web_success' and self.web_pending and not self.web_cancelling and msg.get('request') == self.web_request_id:  # 取消中或旧轮结果不能续期。
            valid = type(msg.get('pages')) is int and 1 <= msg['pages'] <= self.web_pages and type(msg.get('bytes')) is int and msg['bytes'] == 1024 and isinstance(msg.get('elapsed'), (int, float)) and 0 <= msg['elapsed'] <= 420 and msg.get('daily') is True and msg.get('cleanup') == 'confirmed'  # 保留兼容协议字段，旧只读成功不能冒充完整文件交互。
            if not valid or time.monotonic() >= self.operation_deadline:  # 迟到成功不能续期。
                self.pause_web('WEB_RESPONSE_INVALID')  # 不增加成功轮数。
                return  # 停止网页循环。
            self.web_pending = False  # 本轮已全部成功。
            self.web_cleanup = '已确认文件不存在；专用目录保留复用'  # 仅接受扩展完整事务回执。
            self.web_pages = msg['pages']  # 容纳请求期间关闭的非最后一个页面。
            self.web_failures = self.web_synced = 0  # 恢复后重新开始正常周期。
            self.web_warned = False  # 下一次独立故障可以重新提醒。
            notice, self.web_retry_notice = self.web_retry_notice, None  # 完整成功后释放本轮暂态提醒归属。
            if notice and notice[0] == self.token and self.notice is notice[1]:  # 仅撤销同一绑定仍在显示的网页重试提醒。
                self.notice.close()  # 不关闭后来出现的VPN故障、帮助或其他提示。
                self.notice = None  # 已撤销的旧提醒不留作当前通知。
            self.web_count += 1  # 与 VPN 次数独立。
            self.web_last = stamp()  # 用户可看到实际时间。
            if self.web_first == '—': self.web_first = self.web_last  # 首次网页成功起点。
            self.web_due = time.monotonic() + WEB_INTERVAL  # 完整事务成功后5小时，不拼接失败时间。
            self.web_summary = 'E-File 1KiB上传、完整读回校验与删除确认全部成功；专用目录保留复用，5小时后维护。'  # 不把文件服务成功冒充门户会话续期。
            self.log('WEB_SUCCESS', bytes=msg['bytes'], elapsed=msg['elapsed'])  # 不记录返回内容。
        elif event == 'web_sync' and msg.get('request') == self.web_request_id and not self.web_pending and type(msg.get('synced')) is int and 0 <= msg['synced'] <= self.web_pages:  # 页面同步与HTTP计数分离。
            self.web_synced = msg['synced']  # 冻结标签可在恢复响应后完成。
            self.web_summary = f'E-File文件交互完整成功，清理已确认；本地页面状态已同步{self.web_synced}/{self.web_pages}。' + (' 休眠或忙碌页面将在恢复响应后同步。' if self.web_synced < self.web_pages else '')  # 本地同步不是服务端门户续期。
        elif event == 'web_cancelled' and self.web_cancelling and msg.get('request') == self.web_request_id:  # 收到真实取消确认才重试。
            self.retry_web('WEB_TIMEOUT')  # 不与旧请求重叠。
        elif event == 'web_failed' and (msg.get('request') is None or msg.get('request') == self.web_request_id):  # 忽略过期失败。
            self.web_diagnostic = (msg.get('diagnostic'), msg.get('errorKind')) if msg.get('diagnostic') in ('fetch', 'body', 'profile', 'journal', 'binding') and msg.get('errorKind') in ('TypeError', 'ReferenceError', 'RangeError', 'SyntaxError', 'Error', 'Other') else None  # 不记录异常原文。
            code = msg.get('code') if msg.get('code') in WEB_ERRORS else 'WEB_RESPONSE_INVALID'  # 只接受已知类别。
            if self.web_pending and msg.get('settled') is True and code in WEB_TRANSIENT: self.retry_web(code)  # 短暂故障保留授权。
            else: self.pause_web(code)  # 身份失效或协议不匹配需要人工处理。
        self.update_details()  # 立即反映本次交互结果。

    def retry_web(self, reason):  # 短暂失败不要求重新登录，重试始终有间隔。
        self.web_pending = self.web_cancelling = False  # 已确认旧请求结束。
        self.web_failures += 1  # 用于有限快速恢复与后续降频。
        delay = 30 if self.web_failures == 1 else 60 if self.web_failures == 2 else 180  # 前两次30/60秒，持续故障每3分钟一次。
        self.web_due = time.monotonic() + delay  # 不立即重复，也不并发。
        self.web_summary = WEB_ERRORS[reason] + f' {delay}秒后自动再试；最近成功时间仍保留。'  # 不把失败计成在线。
        self.log('WEB_RETRY', error=reason)  # 只记录有限类别。
        if self.web_failures >= 3 and not self.web_warned:  # 连续故障才提醒一次。
            self.web_warned = True  # 持续重试不刷弹窗。
            self.alert('E-File文件交互连续未成功，已降低频率并继续尝试。VPN保活继续；请确认所选业务页已打开并登录。')  # 不把文件服务失败统称门户认证过期。
            self.web_retry_notice = (self.token, self.notice) if self.notice is not None else None  # 记录实际生成的专属提醒，后续成功才能准确撤销。

    def pause_web(self, reason, notify=True):  # 网页停止不牵连 VPN 或 SFTP。
        active = bool(self.token)  # 同一故障最多提醒一次。
        self.token = None  # 先拒绝迟到事件。
        self.awaiting = self.recovering = self.web_pending = False  # 清除网页异步状态。
        self.web_cancelling = False  # 停止不再等待旧取消回执。
        self.web_due = None  # 取消所有后续网页计时。
        if self.bridge: self.bridge.send('web_stop')  # 取消浏览器内正在执行的专用请求。
        self.web_summary = WEB_ERRORS.get(reason, '网页维护已停止。')  # 用户信息不进入日志。
        self.windows.setEnabled(True)  # 允许在 VPN 保活中选择重新登录后的页面。
        if hasattr(self, 'related'): self.related.setEnabled(True)  # 下一次绑定重新确认范围。
        self.selection_changed()  # 主按钮成为重新绑定网页。
        if active: self.log('WEB_STOP', error=reason if reason in WEB_ERRORS else 'WEB_STOPPED')  # 记录固定类别。
        self.update_details()  # 保留最近成功供判断。
        if active and notify: self.alert(self.web_summary + ('\nVPN 保活继续运行；处理后可点击“重新绑定网页”。' if self.engine.active else ''))  # 不把所有错误都解释为需要重新登录。

    def disconnected(self):  # Edge断线只是网页通道中断。
        self.web_capable = False  # 下次握手重新验证能力。
        self.pause_web('WEB_DISCONNECTED')  # 独立VPN不停止。
        self.connection.setText('Edge已断开；VPN保活状态请看下方，E-File文件交互已暂停。')  # 不把通道断开误报为门户到期。
        self.tabs = {}  # 清除旧候选。
        self.fill_list()  # 不自动重绑。

    def tick(self):  # 每秒只做本机计时与桥接检查。
        MainWindow.tick(self)  # 原引擎负责睡眠、错过时刻与请求失败时停止全部。
        if not self.engine.active or not self.token: return  # 没有授权不发送网页请求。
        now = time.monotonic()  # 单调时间避免校时影响。
        if not self.bridge or not self.bridge.peer or now - self.bridge.last_seen > 7: self.pause_web('WEB_DISCONNECTED')  # 桥接失联后只停止网页。
        elif (self.awaiting or self.web_pending) and now >= self.operation_deadline:  # 扩展超时也先取消确认。
            if self.web_pending and not self.web_cancelling:  # 第一次总截止。
                self.web_cancelling = True  # 拒绝迟到成功。
                self.operation_deadline = now + 10  # 本机取消回执单独有界。
                self.bridge.send('web_cancel', token=self.token, request=self.web_request_id)  # 后台取消不依赖网页渲染器。
                self.web_summary = '正在结束超时请求，确认后自动恢复…'  # 不立即弹窗停止。
            else: self.pause_web('WEB_CANCEL_UNCONFIRMED' if self.web_pending else 'WEB_TIMEOUT')  # 状态仍未知才停止网页。
        elif self.web_due is not None and now > self.web_due + 30: self.pause_web('WEB_MISSED')  # 不补发错过的网页轮次。
        elif self.web_due is not None and now >= self.web_due and self.worker is None: self.request_web()  # 避开独立VPN请求正在执行的时刻。
        self.update_details()  # 更新网页倒计时。

    def update_details(self):  # 两类计数和时间分开显示。
        MainWindow.update_details(self)  # 仍显示实际 HTTPS 字节、TLS 与次数。
        self.details.setText('VPN传输（13分钟）\n' + self.details.text())  # 不把静态响应叫网页登录成功。
        if self.web_label is not None:  # 构造早期尚未创建。
            seconds = max(0, int(self.web_due - time.monotonic())) if self.web_due is not None else None  # 网页独立倒计时。
            countdown = f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}' if seconds is not None else '—'  # 分秒显示。
            next_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + seconds)) if seconds is not None else '—'  # 日期仅供显示，实际调度继续使用单调时钟。
            self.web_label.setText(f'E-File文件交互（5小时）：{self.web_summary}\n阶段：{WEB_STAGE_LABELS.get(self.web_stage, "等待")}　清理：{self.web_cleanup}\n首次完整成功：{self.web_first}　最近完整成功：{self.web_last}\n下次维护：{next_time}（{countdown}后）　维护成功次数：{self.web_count}')  # 不显示响应正文或把门户状态混入文件计数。

    def stop(self, reason=None):  # 手动停止、VPN失败和睡眠都取消两类请求。
        self.pause_web('WEB_STOPPED', notify=False)  # 先撤销浏览器任务。
        MainWindow.stop(self, reason)  # 原进程清理及停止理由保持。
        self.state.setText('VPN传输已停止' + (' · ' + str(reason) if reason else ''))  # 不再声称必须绑定窗口。
        self.selection_changed()  # 下一次启动必须用户点击。
