"""双通道生命周期离线回归，不启动实际网络进程或 Edge。"""  # 只注入合成协议摘要。
import logging  # 使用无磁盘日志替身。
from pathlib import Path  # 定位仓库。
import sys  # 使用当前源码。
import time  # 单调时钟测试时刻。
from types import SimpleNamespace  # 本机桥接替身。
import unittest  # 标准测试框架。
from unittest.mock import Mock, patch  # 禁止真实网络与注册操作。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))  # 不安装依赖。
from PyQt5.QtWidgets import QApplication  # 隐藏的实际 Qt 界面。
from zzu_nscc_helper.keepalive.dual_session import DualSessionWindow, display_url  # 实际生产类。

class DualSessionTests(unittest.TestCase):  # 不继承旧版关闭即停的验收结论。
    @classmethod
    def setUpClass(cls):  # 复用唯一 Qt 应用。
        cls.app = QApplication.instance() or QApplication([])  # 不进入真实浏览器。

    def setUp(self):  # 每项有独立界面状态。
        with patch('zzu_nscc_helper.keepalive.app.make_logger', return_value=logging.getLogger('offline-dual-test')):  # 不创建真实日志。
            self.window = DualSessionWindow(connect=False)  # 不注册、不监听真实管道。
        self.window.timer.stop()  # 由测试显式推进时刻。
        self.window.tray.hide()  # 不留下托盘图标。
        self.window.send = Mock()  # 不执行真实 HTTPS 工作程序。
        self.window.alert = Mock()  # 不弹窗影响用户。
        self.window.bridge = SimpleNamespace(peer=True, last_seen=time.monotonic(), send=Mock(return_value=True))  # 本机消息仅内存记录。
        self.window.vpn_guid = 'offline-vpn-interface'  # 合成身份不做真实路由检测。
        self.window.received({'event': 'hello', 'version': '0.4.0', 'capabilities': ['web-daily-file-v1']})  # 需要明确新版能力。
        self.tab = {'id': 17, 'windowId': 3, 'title': 'E-File', 'url': 'https://172.99.2.7/ac/console3/index.html#/e-file', 'sessionEligible': True}  # 合成无账号页面。
        self.window.received({'event': 'tabs', 'version': '0.4.0', 'sessionProtocol': 3, 'tabs': [self.tab]})  # 真实列表处理流程。

    def tearDown(self):  # 清理测试 Qt 对象。
        self.window.stop()  # 不残留计时任务。
        self.window.deleteLater()  # 释放隐藏窗口。
        self.app.processEvents()  # 完成延迟释放。

    def running(self):  # 建立一次已验证 VPN 与网页绑定。
        self.window.start()  # 授权开始。
        self.assertTrue(self.window.engine.active)  # 独立状态机必须运行。
        self.assertTrue(self.window.engine.success(time.monotonic()))  # 注入首次静态响应成功。
        self.window.received({'event': 'web_bound', 'token': self.window.token, 'pages': 2})  # 本机绑定不算网页成功。
        self.assertEqual(self.window.web_count, 0)  # 必须等待实际响应摘要。
        self.assertTrue(self.window.web_pending)  # 只有一个待处理网页轮次。

    def success(self):  # 注入通过扩展判据的无敏感摘要。
        self.window.received({'event': 'web_success', 'token': self.window.token, 'request': self.window.web_request_id, 'pages': 2, 'bytes': 1024, 'elapsed': 0.3, 'daily': True, 'cleanup': 'confirmed'})  # 不含正文或令牌。

    def test_independent_counters_and_interval(self):  # 网页必须实际成功且间隔按成功计算。
        self.running()  # VPN已有首次成功。
        self.success()  # 网页独立首次成功。
        self.assertEqual((self.window.engine.count, self.window.web_count), (1, 1))  # 两类统计不混用。
        self.assertAlmostEqual(self.window.web_due - time.monotonic(), 18000, delta=1)  # E-File完整成功后5小时。
        self.assertAlmostEqual(self.window.engine.due - time.monotonic(), 780, delta=1)  # VPN仍独立使用13分钟。
        previous = self.window.web_due  # 记录旧截止。
        self.success()  # 重复回调必须忽略。
        self.assertEqual(self.window.web_count, 1)  # 不重复计数。
        self.assertEqual(self.window.web_due, previous)  # 不延后下一请求。

    def test_browser_closed_keeps_vpn_and_alerts_once(self):  # 修复关闭浏览器导致15分钟后VPN掉线的链条。
        self.running()  # 已授权的双通道。
        self.window.disconnected()  # 模拟真实桥接断线。
        self.window.disconnected()  # 重复断线事件。
        self.assertTrue(self.window.engine.active)  # VPN保持原计时。
        self.assertIsNone(self.window.token)  # 网页授权撤销。
        self.assertIsNone(self.window.web_due)  # 不继续网页请求。
        self.window.alert.assert_called_once()  # 只提醒一次。

    def test_expired_web_can_rebind_without_reset_vpn(self):  # 重新登录不丢VPN成功和计划时刻。
        self.running()  # 原VPN已运行。
        due = self.window.engine.due  # 保存原时刻。
        self.window.received({'event': 'web_failed', 'token': self.window.token, 'code': 'WEB_LOGIN_EXPIRED'})  # 明确认证失败。
        self.assertTrue(self.window.start_button.isEnabled())  # 可手动重绑。
        self.window.start()  # 不新起第二套VPN周期。
        self.assertEqual(self.window.engine.due, due)  # 原计时不受重绑影响。
        self.assertEqual(self.window.send.call_count, 1)  # 只有第一次独立VPN发送。
        self.assertEqual(self.window.bridge.send.call_args.args[0], 'web_bind')  # 重绑只发网页授权命令。

    def test_vpn_failure_stops_both_channels(self):  # 路由或HTTPS失败仍安全停止。
        self.running()  # 有正在执行的网页请求。
        self.window.fail('VPN_ROUTE_INVALID')  # 网络安全条件失败。
        self.assertFalse(self.window.engine.active)  # VPN停止。
        self.assertIsNone(self.window.token)  # 网页也停止。
        self.assertFalse(self.window.web_pending)  # 不等待迟到结果。
        self.window.alert.assert_called_once()  # 一次故障一次提醒。

    def test_late_web_success_and_timeout(self):  # 超时不能靠迟到消息复活。
        self.running()  # 模拟进行中。
        token = self.window.token  # 保存旧轮身份。
        self.window.operation_deadline = time.monotonic() - 1  # 网页超过总期限。
        self.window.tick()  # 触发独立网页停止。
        self.assertTrue(self.window.engine.active)  # VPN未失败则继续。
        self.window.received({'event': 'web_success', 'token': token, 'request': 1, 'pages': 2, 'bytes': 100, 'elapsed': 0.1})  # 注入迟到成功。
        self.assertEqual(self.window.web_count, 0)  # 不能重启。

    def test_sleep_and_manual_stop_cancel_everything(self):  # 停止与睡眠不会自动重启。
        self.running()  # 有双通道活动。
        self.window.engine.last_tick = time.monotonic() - 31  # 模拟唤醒后的单调时间缺口。
        self.window.tick()  # 原引擎保守停止。
        self.assertFalse(self.window.engine.active)  # 不补发。
        self.assertIsNone(self.window.token)  # 也撤销网页。
        self.window.stop()  # 重复手动停止应幂等。
        self.assertFalse(self.window.web_pending)  # 没有残留异步状态。

    def test_private_url_display_and_old_extension(self):  # UI不泄漏会话值且旧插件不能降级启动。
        value = 'a1' * 16  # 合成会话标识。
        self.assertNotIn(value, display_url(self.tab['url'].replace('#', ';jsessionid=' + value + '#')))  # 不显示真实标识。
        self.window.received({'event': 'hello', 'version': '0.4.0'})  # 旧版本没有网页能力。
        self.window.start()  # 用户点击也不能绕过能力检查。
        self.assertFalse(self.window.engine.active)  # 不只启动静态请求冒充双通道。
        self.window.send.assert_not_called()  # 无额外网络。

    def test_desktop_reconnect_negotiates_from_list(self):  # NativeHost在助手重启时只请求列表，不重发旧hello。
        self.window.web_capable = False  # 新桌面实例没有收到初始握手。
        self.window.received({'event': 'tabs', 'version': '0.4.0', 'sessionProtocol': 3, 'tabs': [self.tab]})  # 最新列表携带新版专有资格字段。
        self.assertTrue(self.window.web_capable)  # 不要求反复重载扩展。
        self.assertTrue(self.window.start_button.isEnabled())  # VPN检测有效后可直接启动。

    def test_transient_backoff_recovers_without_manual_rebind(self):  # 单次波动不要求重新登录。
        self.running()  # 同一授权和VPN周期。
        token, vpn_due = self.window.token, self.window.engine.due  # 核对重试不重置VPN。
        for index, delay in enumerate((30, 60, 180, 180)):  # 两次快速退避，之后降频。
            if index: self.window.request_web()  # 测试直接推进到下一次发起点。
            self.window.received({'event': 'web_failed', 'token': token, 'request': self.window.web_request_id, 'code': 'WEB_TIMEOUT', 'settled': True})  # 旧请求确已停止。
            self.assertAlmostEqual(self.window.web_due - time.monotonic(), delay, delta=1)  # 实际退避间隔。
            self.assertEqual(self.window.token, token)  # 不需要重新绑定。
            self.assertEqual(self.window.engine.due, vpn_due)  # VPN保持原计时。
        self.window.alert.assert_called_once()  # 连续失败只提醒一次。
        self.window.request_web()  # 后台恢复。
        self.success()  # 新轮返回真实成功。
        self.assertEqual(self.window.web_failures, 0)  # 清除连续失败。
        self.assertAlmostEqual(self.window.web_due - time.monotonic(), 18000, delta=1)  # 恢复完整成功后重新等待5小时。
        self.assertEqual(self.window.engine.due, vpn_due)  # 故障恢复不更改VPN原定时刻。

    def test_deadline_requires_cancel_ack_before_retry(self):  # 不在状态未知时发第二个请求。
        self.running()  # 原请求正在执行。
        self.window.operation_deadline = time.monotonic() - 1  # 桌面总截止。
        self.window.tick()  # 先发取消，不停止VPN。
        self.assertTrue(self.window.web_cancelling)  # 等待确认期间不可重试。
        self.assertIsNone(self.window.web_due)  # 未安排第二个请求。
        self.assertEqual(self.window.bridge.send.call_args.args[0], 'web_cancel')  # 专用取消指令。
        self.success()  # 取消期间的迟到成功必须丢弃。
        self.assertEqual(self.window.web_count, 0)  # 不误增计数。
        self.window.received({'event': 'web_cancelled', 'token': self.window.token, 'request': self.window.web_request_id})  # 正确轮次确认。
        self.assertFalse(self.window.web_pending)  # 旧请求已结束。
        self.assertAlmostEqual(self.window.web_due - time.monotonic(), 30, delta=1)  # 此时才可自动重试。

    def test_frozen_page_sync_does_not_invalidate_server_success(self):  # 页面冻结与服务器登录状态分开显示。
        self.running()  # 两页参与。
        self.success()  # 后台HTTP真实成功。
        self.window.received({'event': 'web_sync', 'token': self.window.token, 'request': self.window.web_request_id, 'pages': 2, 'synced': 1})  # 一页冻结。
        self.assertEqual(self.window.web_count, 1)  # HTTP成功保持有效。
        self.assertIn('1/2', self.window.web_summary)  # 同步不足不隐瞒。
        self.window.alert.assert_not_called()  # 单页休眠不弹异常。
        self.window.received({'event': 'web_targets', 'token': self.window.token, 'pages': 1})  # 关闭其中一页。
        self.assertIsNotNone(self.window.web_due)  # 剩余页面继续。
        self.assertEqual(self.window.web_pages, 1)  # 范围确已缩小。

    def test_old_extension_list_cannot_claim_background_support(self):  # 新旧能力不能靠同名字段混淆。
        self.window.web_capable = False  # 模拟刚启动。
        self.window.received({'event': 'tabs', 'version': '0.4.0', 'tabs': [self.tab]})  # 旧0.5.0列表仍有sessionEligible。
        self.assertFalse(self.window.web_capable)  # 必须声明协议2。

    def test_file_due_does_not_send_between_cycles(self):  # 模拟时钟证明5小时前无网页文件请求。
        self.running()  # 两个通道已启动。
        self.success()  # 首轮完整文件事务完成。
        due = self.window.web_due  # 真实生产调度的到期点。
        self.window.bridge.send.reset_mock()  # 只统计之后的命令。
        with patch('zzu_nscc_helper.keepalive.dual_session.MainWindow.tick'), patch('zzu_nscc_helper.keepalive.dual_session.time.monotonic', return_value=due - 1):  # 仅推进网页时钟，不虚构实际运行5小时。
            self.window.bridge.last_seen = due - 1  # 本机心跳正常。
            self.window.tick()  # 还差一秒。
        self.window.bridge.send.assert_not_called()  # 未到期完全不请求网页。
        with patch('zzu_nscc_helper.keepalive.dual_session.MainWindow.tick'), patch('zzu_nscc_helper.keepalive.dual_session.time.monotonic', return_value=due):  # 到期时刻。
            self.window.bridge.last_seen = due  # 本机连接保持。
            self.window.tick()  # 仅发起一个新轮次。
            self.window.tick()  # 同一秒重复本机轮询不得重复发起。
        self.assertEqual(self.window.bridge.send.call_count, 1)  # 无补发积压。
        self.assertEqual(self.window.bridge.send.call_args.args[0], 'web_request')  # 实际调度命令。
        self.assertTrue(self.window.web_pending)  # 等完整结果再计时。

    def test_file_schedule_grace_boundary_does_not_replay_missed_round(self):  # 区分允许的30秒调度余量与错过计划后补发。
        for delay, allowed in ((30, True), (30.001, False)):  # 精确检查边界及刚刚超出边界。
            with self.subTest(delay=delay):  # 每种情况独立授权，不复用上次待处理请求。
                self.window.stop()  # 清理上一种情况的本机状态。
                self.running()  # 建立新的合成VPN成功与文件绑定。
                self.success()  # 首轮完整文件事务已确认。
                due = self.window.web_due  # 以实际生产代码给出的成功后时刻为准。
                self.window.bridge.send.reset_mock()  # 不计此前绑定及首轮命令。
                with patch('zzu_nscc_helper.keepalive.dual_session.MainWindow.tick'), patch('zzu_nscc_helper.keepalive.dual_session.time.monotonic', return_value=due + delay):  # 仅模拟文件调度，隔离VPN自己的长时间停顿保护。
                    self.window.bridge.last_seen = due + delay  # 本机桥接仍然健康。
                    self.window.tick()  # 执行真实文件通道到期判断。
                self.assertEqual(self.window.web_pending, allowed)  # 仅在余量内允许发起一轮。
                self.assertEqual(self.window.bridge.send.call_args.args[0], 'web_request' if allowed else 'web_stop')  # 超时仅撤销，不补发文件交互。
                self.assertTrue(self.window.engine.active)  # 单独文件通道错过时刻不停止VPN。

    def test_vpn_780_second_due_runs_while_file_waits_five_hours(self):  # VPN到期不受更长文件周期限制。
        with patch('zzu_nscc_helper.keepalive.dual_session.time.monotonic', return_value=1000):  # 所有合成成功使用同一明确基准。
            self.running()  # 不启动任何网络工作程序。
            self.success()  # 文件首轮完整成功。
        self.assertEqual(self.window.engine.due, 1780)  # VPN成功后780秒。
        self.assertEqual(self.window.web_due, 19000)  # 文件成功后18000秒。
        self.window.send.reset_mock()  # 只统计之后VPN发送。
        self.window.bridge.send.reset_mock()  # 文件请求必须继续安静等待。
        self.window.engine.last_tick = 1779  # 模拟后台此前每秒正常轮询，非睡眠唤醒。
        self.window.bridge.last_seen = 1780  # 本机心跳同时正常。
        with patch('zzu_nscc_helper.keepalive.dual_session.time.monotonic', return_value=1780):  # 精确抵达VPN下次发送时刻。
            self.window.tick()  # 保留真实MainWindow.tick与Engine.poll，不替换VPN状态机。
        self.window.send.assert_called_once()  # 只触发VPN工作程序入口替身。
        self.window.bridge.send.assert_not_called()  # 未提前触发文件交互。
        self.assertTrue(self.window.engine.success(1780.5))  # 注入第二次VPN验证成功。
        self.assertEqual(self.window.engine.due, 2560.5)  # 下一次仍从VPN成功后等待780秒。
        self.assertEqual(self.window.web_due, 19000)  # 文件周期保持原截止。

    def retry_notice(self):  # 模拟通用提醒创建与替换合同，不显示实际弹窗。
        def capture(message):  # 仅建立可观察的关闭行为。
            if self.window.notice is not None: self.window.notice.close()  # 与现有通用alert替换旧提醒一致。
            self.window.notice = Mock()  # 每个提醒拥有独立对象身份。
        self.window.alert.side_effect = capture  # 禁止实际窗口交互。
        for index in range(3):  # 连续三次暂态失败才显示一次提醒。
            if index: self.window.request_web()  # 仅模拟下一次退避到期后的请求。
            self.window.received({'event': 'web_failed', 'token': self.window.token, 'request': self.window.web_request_id, 'code': 'WEB_PAGE_NOT_READY', 'settled': True})  # 业务页未就绪的真实失败协议。
        self.window.alert.assert_called_once()  # 同一次持续故障只创建一个提醒。
        return self.window.notice  # 返回用户当前看到的提醒替身。

    def test_recovered_file_round_closes_its_retry_notice(self):  # 修复完整成功后仍残留旧失败提示。
        self.running()  # 同一已授权的业务页。
        notice = self.retry_notice()  # 触发实际重试控制器的一次提示。
        self.window.request_web()  # 进入恢复请求。
        self.success()  # 只有完整上传校验与清理成功才撤销旧提醒。
        notice.close.assert_called_once()  # 原故障提示确已消退。
        self.assertIsNone(self.window.notice)  # 不再将旧提示保留为当前提醒。
        self.assertFalse(self.window.web_warned)  # 后续独立故障仍可提醒。
        self.assertAlmostEqual(self.window.web_due - time.monotonic(), 18000, delta=1)  # 自动恢复后仍等待完整5小时。

    def test_file_recovery_preserves_newer_other_notice(self):  # 不能误关VPN、帮助或其他类别提醒。
        self.running()  # 本次文件交互已授权。
        old_notice = self.retry_notice()  # 文件暂态故障提示先出现。
        self.window.alert('其他需要处理的提示')  # 用户随后看到其他提醒，通用机制关闭旧框。
        other_notice = self.window.notice  # 保存真正当前的提醒对象。
        self.window.request_web()  # 文件服务后来恢复。
        self.success()  # 完整成功仅有权清理原网页故障提醒。
        old_notice.close.assert_called_once()  # 只在其他提醒替换时关闭一次，成功不重复操作。
        other_notice.close.assert_not_called()  # 当前其他提醒必须保留。
        self.assertIs(self.window.notice, other_notice)  # 不清空其他提醒引用。

    def test_old_request_success_does_not_dismiss_current_retry_notice(self):  # 迟到的旧请求不能消除当前故障。
        self.running()  # 初次授权。
        notice = self.retry_notice()  # 当前仍未恢复。
        old_request = self.window.web_request_id  # 保存已失败轮次。
        self.window.request_web()  # 新一轮待确认。
        self.window.received({'event': 'web_success', 'token': self.window.token, 'request': old_request, 'pages': 2, 'bytes': 1024, 'elapsed': 0.3, 'daily': True, 'cleanup': 'confirmed'})  # 注入协议合法但过期的成功。
        notice.close.assert_not_called()  # 旧成功无权撤销当前提示。
        self.assertEqual(self.window.web_count, 0)  # 不误计成功。
        self.assertTrue(self.window.web_pending)  # 继续等待当前请求的真实结果。

    def test_readonly_success_cannot_complete_daily_transaction(self):  # 旧扩展成功格式必须被拒绝。
        self.running()  # 新版绑定。
        self.window.received({'event': 'web_success', 'token': self.window.token, 'request': self.window.web_request_id, 'pages': 2, 'bytes': 1024, 'elapsed': 1})  # 缺少兼容文件事务标识及清理确认。
        self.assertEqual(self.window.web_count, 0)  # 不能把只读请求计为文件成功。
        self.assertTrue(self.window.engine.active)  # 独立VPN不受影响。

if __name__ == '__main__': unittest.main()  # 独立执行离线用例。
