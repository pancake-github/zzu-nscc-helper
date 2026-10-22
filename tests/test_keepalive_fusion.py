"""融合保活的真实本机管道测试；浏览器、平台和标签均为模拟。"""  # 不加载用户扩展或访问内网。
import ctypes  # 构造本地电源消息。
from ctypes import wintypes  # Windows消息布局。
import importlib.util  # 复用历史标签恢复用例。
import os  # 隔离测试日志目录。
from pathlib import Path  # 定位基线用例。
import sys  # 测试导入。
import tempfile  # 所有运行数据在临时目录。
import unittest  # 标准测试框架。
from unittest.mock import patch  # 不写实际原生组件注册。
ROOT = Path(__file__).resolve().parents[1]  # 当前独立仓库。
sys.path.insert(0, str(ROOT / 'src'))  # 不安装包。
from zzu_nscc_helper.keepalive import app as keeper_app, tab_app  # 活跃融合实现。
SPEC = importlib.util.spec_from_file_location('baseline_tab_scenarios', ROOT / 'baseline/keepalive/test_tabs.py')  # 只复用模拟场景。
SCENARIOS = importlib.util.module_from_spec(SPEC)  # 独立模块对象。
with patch.dict(sys.modules, {'app': keeper_app, 'tab_app': tab_app}):  # 让基线用例实际测试融合代码。
    SPEC.loader.exec_module(SCENARIOS)  # 不启动任何真实任务。

class TabRecoveryTests(SCENARIOS.TabTests):  # 继承五个完整IPC场景。
    def setUp(self):  # 环境和注册必须隔离。
        self.heartbeat = None  # 长请求测试需要模拟扩展心跳。
        self.temp = tempfile.TemporaryDirectory()  # 本测试独立目录。
        self.addCleanup(self.temp.cleanup)  # 所有句柄释放后清理。
        environment = patch.dict(os.environ, {'LOCALAPPDATA': self.temp.name})  # Native Host日志也隔离。
        environment.start()  # 仅影响本测试及其子进程。
        self.addCleanup(environment.stop)  # 恢复环境。
        registration = patch.object(tab_app, 'prepare', return_value=(True, '离线测试组件'))  # 绝不注册真实Edge主机。
        registration.start()  # 测试只使用独立管道。
        self.addCleanup(registration.stop)  # 恢复函数。
        self.addCleanup(self.close_logger)  # 在临时目录删除前关闭日志。
        super().setUp()  # 原测试只创建模拟标签与专用宿主。

    def tearDown(self):  # 先停止模拟扩展心跳，再关闭专用宿主。
        if self.heartbeat is not None:  # 只清理本测试的计时器。
            self.heartbeat.stop()  # 不向关闭后的管道写入。
        super().tearDown()  # 原用例核对进程退出。

    def close_logger(self):  # 避免Windows打开句柄影响测试清理。
        if hasattr(self, 'window'):  # 初始化失败也可安全结束。
            for handler in tuple(self.window.logger.handlers):  # 仅当前测试日志。
                handler.close()  # 释放文件。
                self.window.logger.removeHandler(handler)  # 不沿用旧目录。

    def start_long_request(self):  # 使用真实工作进程的离线超时模式。
        from PyQt5.QtCore import QTimer  # 真实扩展每秒发出的本机心跳。
        self.heartbeat = QTimer()  # 无网络的测试计时器。
        self.heartbeat.timeout.connect(lambda: self.emit({'event': 'heartbeat'}))  # 保持扩展在线，单独验证请求超时。
        self.heartbeat.start(1000)  # 与实际心跳频率一致。
        self.window.mode.setCurrentIndex(self.window.mode.findData('timeout'))  # 不联网。
        self.window.start()  # 发送绑定请求。
        self.emit({'event': 'bound', 'token': self.window.token, 'tab': self.tab})  # 虚拟页面确认。
        self.wait(lambda: self.window.worker is not None)  # 真正创建独立后台。
        process = self.window.worker  # 保存身份。
        self.wait(lambda: process.state() == process.Running)  # 确认子进程已启动。
        return process  # 供终止断言。

    def test_fused_worker_timeout_cleans_and_notifies_once(self):  # 请求硬截止确实作用于新后台入口。
        process = self.start_long_request()  # 六十秒离线阻塞请求。
        self.wait(lambda: not self.window.engine.active, 23)  # 父进程二十秒截止。
        self.assertIsNone(self.window.worker)  # 网络工作进程引用已清理。
        self.assertEqual(len(self.alerts), 1)  # 单次提醒。
        self.assertIn('二十秒', self.alerts[0])  # 准确原因。

    def test_fused_sleep_cancels_without_restart(self):  # 不真的让电脑睡眠。
        process = self.start_long_request()  # 真实子进程、离线请求。
        message = wintypes.MSG()  # 合成Windows通知。
        message.message, message.wParam = 0x218, 4  # WM_POWERBROADCAST/PBT_APMSUSPEND。
        self.window.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message))  # 实际停止处理器。
        self.assertFalse(self.window.engine.active)  # 不再计时。
        self.assertIsNone(self.window.worker)  # 子进程已清理。
        self.assertIsNone(self.window.token)  # 恢复授权已撤销。
