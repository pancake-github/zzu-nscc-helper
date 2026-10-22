"""标签桥接测试：仅本机模拟，不操作用户浏览器。"""  # 验证真正的 Native Messaging 帧。
import json  # 本机测试消息。
import struct  # 长度前缀。
import subprocess  # 启动已编译的桥接程序。
import time  # 有限等待。
import unittest  # 自动测试。
import os  # 子进程测试环境。
import uuid  # 每项测试使用独立管道。
from unittest.mock import patch  # 不修改系统环境变量。
from PyQt5.QtWidgets import QApplication  # Qt 事件分发。
from PyQt5.QtCore import QProcess  # 子进程状态。
from app import ROOT  # 应用目录。
from tab_app import TabWindow  # 实际标签页控制器。

class TabTests(unittest.TestCase):  # 用桥接程序代替真实扩展。
    @classmethod  # 共用事件循环。
    def setUpClass(cls):  # 初始化 Qt。
        cls.app = QApplication.instance() or QApplication([])  # 不联网。
        cls.app.setQuitOnLastWindowClosed(False)  # 测试期间保持循环。

    def setUp(self):  # 每项测试独立桥接。
        env_patch = patch.dict(os.environ, {'ZZDX_VPN_TEST_PIPE': 'ZZDX-VPN-Test-' + uuid.uuid4().hex})  # 与真实 Edge 完全隔离。
        env_patch.start()  # 仅当前测试进程与其子进程继承。
        self.addCleanup(env_patch.stop)  # 即使初始化失败也恢复环境。
        self.window = TabWindow()  # 实际界面。
        self.window.mode.setCurrentIndex(self.window.mode.findData('success'))  # 自动测试明确使用模拟，禁止发真实请求。
        self.assertTrue(self.window.bridge.listening)  # 保证没有另一个标签助手占用。
        self.alerts = []  # 收集提醒，不显示弹窗。
        self.window.alert = self.alerts.append  # 替换仅提示入口。
        eid = (ROOT / 'extension-id.txt').read_text().strip()  # 固定扩展身份。
        self.host = subprocess.Popen([str(ROOT / 'native_host.exe'), 'chrome-extension://' + eid + '/'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)  # 真正的本机桥接进程。
        self.tab = {'id': 17, 'windowId': 3, 'title': '计算服务', 'url': 'https://172.99.2.7/ac/console3/index.html#/space/dashboard', 'eligible': True, 'status': 'complete'}  # 虚拟标签，不发实际请求。
        self.wait(lambda: self.window.bridge.peer is not None)  # 模拟桌面握手后，Edge 响应最新列表。
        self.emit({'event': 'hello'})  # 与桌面握手。
        self.emit({'event': 'tabs', 'tabs': [self.tab], 'total': 1})  # 提供虚拟列表。
        self.wait(lambda: self.window.windows.count() == 1)  # 验证真实传输链。

    def emit(self, item):  # 模拟 Edge Native Messaging 输出。
        body = json.dumps(item).encode()  # JSON 协议。
        self.host.stdin.write(struct.pack('<I',len(body)) + body)  # 长度帧。
        self.host.stdin.flush()  # 立即送达。

    def wait(self, condition, limit=4):  # 有限等待 Qt 消息。
        end = time.monotonic() + limit  # 截止时间。
        while not condition() and time.monotonic() < end:  # 等待异步进程。
            self.app.processEvents()  # 分发本机事件。
            time.sleep(.01)  # 避免高 CPU。
        self.assertTrue(condition())  # 明确失败。

    def tearDown(self):  # 所有测试进程均回收。
        self.window.stop()  # 清理模拟工作进程。
        self.window.bridge.close()  # 桥接自动退出。
        self.window.timer.stop()  # 停止本地检查。
        self.window.tray.hide()  # 清理测试托盘。
        if not self.host.stdin.closed:  # Edge 拥有宿主，桌面关闭后不应立即杀掉宿主。
            self.host.stdin.close()  # 模拟 Edge 关闭连接。
        self.host.wait(timeout=4)  # 验证 Edge 断开后桥接不残留。
        self.host.stdout.close()  # 释放管道。
        self.window.deleteLater()  # 释放界面。
        self.app.processEvents()  # 完成 Qt 清理。

    def begin(self):  # 模拟扩展确认目标。
        self.assertTrue(self.window.start_button.isEnabled())  # 选择后可直接一步启动。
        self.window.start()  # 发起绑定请求。
        token = self.window.token  # 本次会话标识。
        self.emit({'event': 'bound', 'token': token, 'tab': self.tab})  # 虚拟页面已验证。
        self.wait(lambda: self.window.engine.count == 1)  # 模拟交互成功。
        return token  # 供恢复消息关联。

    def test_list_and_restore(self):  # 列表和单次恢复重新计时。
        self.assertIn('https://', self.window.windows.itemText(0))  # 下拉项包含独立网址。
        token = self.begin()  # 开始模拟。
        self.emit({'event':'closed', 'token': token})  # 虚拟标签关闭。
        self.wait(lambda: self.window.recovering)  # 等待暂停状态。
        self.assertFalse(self.window.engine.active)  # 原计时停止。
        restored = {**self.tab, 'id': 18}  # 重开得到新标签编号。
        self.emit({'event':'restored','token':token,'tab':restored})  # 虚拟恢复验证通过。
        self.wait(lambda: self.window.engine.active and self.window.engine.count == 1)  # 必须重新交互成功。
        self.assertEqual(self.window.bound['id'],18)  # 绑定新身份。
        self.assertEqual(self.alerts,[])  # 成功过程安静。

    def test_failure_and_stale_restore(self):  # 失败只提醒一次，不接受迟到恢复。
        token=self.begin()  # 启动模拟。
        self.emit({'event':'failed','token':token,'code':'RESTORE_PAGE_INVALID'})  # 登录失败等场景。
        self.wait(lambda: not self.window.engine.active)  # 立即停止。
        self.emit({'event':'restored','token':token,'tab':self.tab})  # 迟到成功。
        self.app.processEvents()  # 处理消息。
        self.assertEqual(len(self.alerts),1)  # 单次提示。
        self.assertIsNone(self.window.token)  # 恢复授权已撤销。

    def test_disconnect_stops(self):  # Edge 关闭等价于管道断开。
        self.begin()  # 先启动会话。
        self.host.terminate()  # 仅结束本测试拥有的桥接程序。
        self.wait(lambda: not self.window.engine.active)  # 断线即停止。
        self.assertEqual(len(self.alerts),1)  # 提醒一次。

    def test_single_action_controls(self):  # 简化界面仍保留目标限制。
        self.assertTrue(self.window.locate_button.isHidden())  # 定位不占主界面。
        self.assertTrue(self.window.confirm_button.isHidden())  # 不要求单独确认。
        self.assertEqual(self.window.start_button.text(), '绑定并开始（离线测试）')  # 名称反映当前能力。
        self.assertTrue(self.window.start_button.isEnabled())  # 合法目标选中即可启动。
        other = {**self.tab, 'id': 19, 'url': 'https://example.com/', 'eligible': False}  # 非目标页面。
        self.emit({'event':'tabs','tabs':[other],'total':1})  # 更新下拉列表。
        self.wait(lambda: self.window.windows.currentData()['id'] == 19)  # 等待真实 IPC 接收。
        self.assertFalse(self.window.start_button.isEnabled())  # 非目标依然不能启动。
        self.window.start()  # 直接调用也不可绕过目标检查。
        self.assertFalse(self.window.awaiting)  # 不进入预检。
        self.assertIsNone(self.window.worker)  # 无工作进程。

    def test_host_survives_desktop_restart(self):  # 不重载扩展也能重新接入桌面。
        self.begin()  # 初始会话成功。
        host_pid = self.host.pid  # 同一 Edge 宿主。
        self.window.bridge.close()  # 模拟桌面通道退出。
        self.wait(lambda: not self.window.engine.active)  # 立即停止旧任务。
        self.assertIsNone(self.host.poll())  # 宿主保持等待，不依赖扩展三十秒唤醒。
        start = time.monotonic()  # 测量重新接入时间。
        self.assertTrue(self.window.bridge.server.listen(self.window.bridge.name))  # 同一独立测试通道再次监听。
        self.wait(lambda: self.window.bridge.peer is not None, 3)  # 自动重新连接。
        self.emit({'event':'tabs','tabs':[self.tab],'total':1})  # 新列表通过同一宿主转发。
        self.wait(lambda: self.window.windows.count() == 1 and len(self.window.tabs) == 1)  # 列表重新显示。
        self.assertLess(time.monotonic() - start, 3)  # 不等待三十秒重试。
        self.assertEqual(self.host.pid, host_pid)  # 没有重启扩展宿主。
        self.assertIsNone(self.window.token)  # 旧恢复权限没有复活。
        self.assertFalse(self.window.engine.active)  # 重连不自动开始保活。

if __name__ == '__main__':  # 自动测试入口。
    unittest.main(verbosity=2)  # 输出验收结果。
