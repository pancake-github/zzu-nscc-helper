"""第一阶段自动验收：全部离线，不关闭用户浏览器。"""  # 测试只操作自己的模拟界面。
import time  # 等待 Qt 子进程事件。
import ctypes  # 构造模拟电源消息，不实际让电脑睡眠。
from ctypes import wintypes  # 系统消息结构。
import unittest  # 标准测试框架。
from unittest.mock import patch  # 替换窗口和时间边界。
from PyQt5.QtWidgets import QApplication  # 测试事件循环。
from PyQt5.QtCore import QProcess  # 验证进程终止。
from engine import Engine  # 测试计时逻辑。
from worker import validate_response, run  # 测试响应校验与联网阻断。
from windows import Window  # 构造不触碰用户窗口的身份。
from app import MainWindow  # 测试实际界面控制器。

class EngineTests(unittest.TestCase):  # 不等待真实十三分钟。
    def test_first_success_and_interval(self):  # 首次成功才建立计划。
        e = Engine()  # 初始停止。
        e.start(100)  # 模拟启动。
        self.assertIsNone(e.due)  # 首次请求没有计划。
        self.assertTrue(e.success(101))  # 记录成功。
        self.assertEqual(e.due, 881)  # 从成功而非启动计时。
        for t in range(102, 881):  # 连续推进每秒轮询。
            self.assertIsNone(e.poll(t))  # 不提前发送。
        self.assertEqual(e.poll(881), 'SEND')  # 精确十三分钟发送。
        self.assertIsNone(e.poll(882))  # 请求中不重复发送。
        self.assertTrue(e.success(883))  # 第二次成功。
        self.assertEqual(e.due, 1663)  # 重新基于成功计时。

    def test_timeout_and_late_result(self):  # 二十秒硬上限。
        e = Engine()  # 新状态机。
        e.start(0)  # 首次请求。
        self.assertEqual(e.poll(20), 'TIMEOUT')  # 边界超时。
        self.assertFalse(e.success(20))  # 拒绝迟到成功。
        e.stop()  # 故障停止。
        self.assertFalse(e.success(21))  # 停止后也不恢复。

    def test_sleep_and_stop(self):  # 长停顿后禁止补发。
        e = Engine()  # 新会话。
        e.start(0)  # 启动。
        e.success(1)  # 首次成功。
        self.assertEqual(e.poll(50), 'SUSPEND_OR_DELAY')  # 检测系统暂停。
        e.stop()  # 停止。
        self.assertIsNone(e.poll(1000))  # 不补发。

    def test_response_rules(self):  # 不接受伪成功。
        self.assertIsNone(validate_response(200, b'expected', b'expected'))  # 真实内容特征匹配。
        for status, body, marker, expected in [(302,b'expected',b'expected','HTTP_STATUS'),(502,b'expected',b'expected','HTTP_STATUS'),(200,b'',b'a','EMPTY_BODY'),(200,b'proxy error',b'expected','CONTENT_MISMATCH'),(200,b'a'*65537,b'a','BODY_TOO_LARGE')]:  # 异常场景矩阵。
            self.assertEqual(validate_response(status,body,marker),expected)  # 所有异常拒绝。
        self.assertEqual(run('unknown')['error'], 'INVALID_MODE')  # 正式联网硬阻断。

class GuiTests(unittest.TestCase):  # 测试真实 QProcess 与 UI 生命周期。
    @classmethod  # 全部界面测试共享 Qt 应用。
    def setUpClass(cls):  # 初始化事件循环。
        cls.app = QApplication.instance() or QApplication([])  # 不启动真实联网。
        cls.app.setQuitOnLastWindowClosed(False)  # 单个测试关闭不退出。

    def setUp(self):  # 每个测试使用受控模拟窗口。
        self.fake = Window(123,456,789,'测试窗口')  # 无真实窗口句柄。
        self.p1 = patch('windows.enumerate_edge', return_value=[self.fake])  # 不枚举用户浏览器。
        self.p2 = patch('windows.alive', return_value=True)  # 初始窗口有效。
        self.p1.start()  # 启用窗口列表替身。
        self.alive = self.p2.start()  # 可在测试中模拟关闭。
        self.window = MainWindow()  # 使用实际控制器。
        self.alerts = []  # 收集弹窗，不打扰用户。
        self.window.alert = self.alerts.append  # 断言提醒次数。
        self.window.confirm_selection()  # 既有运行测试先确认目标。

    def tearDown(self):  # 清理每个测试实例。
        self.window.stop()  # 确保子进程退出。
        self.window.timer.stop()  # 取消定时器。
        self.window.tray.hide()  # 清理测试托盘。
        self.window.deleteLater()  # 释放 Qt 控件。
        self.app.processEvents()  # 处理清理事件。
        self.p1.stop()  # 恢复真实函数。
        self.p2.stop()  # 恢复真实检查。

    def wait(self, condition, limit=5):  # 有限等待，不做忙循环。
        deadline = time.monotonic() + limit  # 测试超时。
        while not condition() and time.monotonic() < deadline:  # 允许子进程完成。
            self.app.processEvents()  # 分发 QProcess 信号。
            time.sleep(.01)  # 降低 CPU 消耗。
        self.assertTrue(condition())  # 不无限等待。

    def test_success_binding_and_minimize(self):  # 正常模拟与收起。
        self.window.start()  # 首次立即执行。
        self.assertFalse(self.window.windows.isEnabled())  # 运行中禁止改绑。
        self.wait(lambda: self.window.engine.count == 1)  # 真实子进程成功。
        self.assertTrue(self.window.engine.active)  # 进入十三分钟等待。
        self.window.showMinimized()  # 最小化助手。
        self.window.tick()  # 检查仍继续。
        self.assertTrue(self.window.engine.active)  # 最小化不停止。
        self.window.close()  # 主窗口关闭收起。
        self.assertTrue(self.window.engine.active)  # 托盘继续运行。
        self.assertFalse(self.window.isVisible())  # 确实隐藏。
        self.window.stop()  # 手动停止。
        self.assertEqual(self.alerts, [])  # 手动停止不报警。

    def test_failure_once(self):  # 失败不重试。
        self.window.mode.setCurrentIndex(1)  # 请求失败场景。
        self.window.start()  # 发起模拟。
        self.wait(lambda: not self.window.engine.active)  # 等待停止。
        self.window.fail('WORKER_ERROR')  # 注入重复故障信号。
        self.assertEqual(len(self.alerts), 1)  # 只提醒一次。
        self.assertIsNone(self.window.worker)  # 无残留工作进程。

    def test_selection_confirmation_states(self):  # 验证用户能区分选择、确认与绑定。
        self.window.refresh()  # 刷新撤销旧确认。
        self.assertIn('尚未确认', self.window.selection.text())  # 初始不是已绑定。
        self.assertFalse(self.window.start_button.isEnabled())  # 未确认不能开始。
        self.window.start()  # 即使直接调用也不能绕过。
        self.assertFalse(self.window.engine.active)  # 未启动任何任务。
        self.assertIsNone(self.window.worker)  # 没有进程。
        self.window.confirm_selection()  # 手动确认。
        self.assertIn('已确认，尚未启动', self.window.selection.text())  # 确认不是运行。
        self.window.start()  # 开始模拟。
        self.assertIn('已绑定', self.window.selection.text())  # 展示实际绑定。
        self.window.stop()  # 主动停止。
        self.assertIsNone(self.window.bound)  # 真正解除绑定。
        self.assertIn('已解除窗口绑定', self.window.state.text())  # 界面同步。
        self.assertFalse(self.window.start_button.isEnabled())  # 重启需再确认。

    def test_close_kills_worker(self):  # 窗口关闭终止正在进行的请求。
        self.window.mode.setCurrentIndex(2)  # 长请求模拟。
        self.window.start()  # 启动隔离进程。
        proc = self.window.worker  # 保存对象供断言。
        self.wait(lambda: proc.state() == QProcess.ProcessState.Running)  # 确保进程确实启动。
        self.alive.return_value = False  # 模拟绑定窗口关闭。
        self.window.tick()  # 执行本地检测。
        self.assertEqual(proc.state(), QProcess.ProcessState.NotRunning)  # 核实终止。
        self.assertFalse(self.window.engine.active)  # 停止计时。
        self.assertEqual(len(self.alerts), 1)  # 单次提示。

    def test_hard_timeout_kills_worker(self):  # 实际等二十秒验证硬截止。
        self.window.mode.setCurrentIndex(2)  # 子进程睡眠六十秒。
        self.window.start()  # 生产控制器启动。
        self.wait(lambda: not self.window.engine.active, 23)  # 二十秒应被父进程结束。
        self.assertIsNone(self.window.worker)  # 已清理。
        self.assertEqual(len(self.alerts), 1)  # 仅一次提醒。
        self.assertIn('二十秒', self.alerts[0])  # 原因准确。

    def test_power_suspend_resume(self):  # 注入消息验证睡眠停止和延迟提醒。
        self.window.mode.setCurrentIndex(2)  # 使用长模拟请求。
        self.window.start()  # 创建工作进程。
        proc = self.window.worker  # 保存进程引用。
        self.wait(lambda: proc.state() == QProcess.ProcessState.Running)  # 确认真实子进程启动。
        msg = wintypes.MSG()  # 本地合成消息。
        msg.message = 0x218  # WM_POWERBROADCAST。
        msg.wParam = 4  # 模拟系统挂起。
        self.window.nativeEvent(b'windows_generic_MSG', ctypes.addressof(msg))  # 调用实际处理器。
        self.assertFalse(self.window.engine.active)  # 睡眠前停止。
        self.assertEqual(proc.state(), QProcess.ProcessState.NotRunning)  # 子进程已退出。
        self.assertEqual(self.alerts, [])  # 睡眠期间不弹提示。
        msg.wParam = 18  # 模拟恢复通知。
        self.window.nativeEvent(b'windows_generic_MSG', ctypes.addressof(msg))  # 唤醒处理。
        self.app.processEvents()  # 投递延迟提醒。
        self.assertEqual(len(self.alerts), 1)  # 唤醒后只提醒一次。
        self.assertFalse(self.window.engine.active)  # 不自动恢复。

if __name__ == '__main__':  # 标准测试入口。
    unittest.main(verbosity=2)  # 展示逐项验收结果。
