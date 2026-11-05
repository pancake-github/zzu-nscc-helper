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
        self.window.received({'event': 'hello', 'version': '0.4.0', 'capabilities': ['web-session-v1']})  # 需要明确新版能力。
        self.tab = {'id': 17, 'windowId': 3, 'title': 'E-File', 'url': 'https://172.99.2.7/ac/console3/index.html#/e-file', 'sessionEligible': True}  # 合成无账号页面。
        self.window.received({'event': 'tabs', 'version': '0.4.0', 'tabs': [self.tab]})  # 真实列表处理流程。

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
        self.window.received({'event': 'web_success', 'token': self.window.token, 'request': self.window.web_request_id, 'pages': 2, 'bytes': 100, 'elapsed': 0.3})  # 不含正文或令牌。

    def test_independent_counters_and_interval(self):  # 网页必须实际成功且间隔按成功计算。
        self.running()  # VPN已有首次成功。
        self.success()  # 网页独立首次成功。
        self.assertEqual((self.window.engine.count, self.window.web_count), (1, 1))  # 两类统计不混用。
        self.assertAlmostEqual(self.window.web_due - time.monotonic(), 780, delta=1)  # 严格十三分钟。
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
        self.window.received({'event': 'tabs', 'version': '0.4.0', 'tabs': [self.tab]})  # 最新列表携带新版专有资格字段。
        self.assertTrue(self.window.web_capable)  # 不要求反复重载扩展。
        self.assertTrue(self.window.start_button.isEnabled())  # VPN检测有效后可直接启动。

if __name__ == '__main__': unittest.main()  # 独立执行离线用例。
