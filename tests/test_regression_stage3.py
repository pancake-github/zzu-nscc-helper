"""第三阶段回归矩阵：模拟平台与临时目录，绝不连接真实超算。"""  # 测试口令和密钥均临时合成。
import base64  # 检查备份损坏。
import contextlib  # 不回显传输路径或原始错误。
import copy  # 独立改变配置场景。
import io  # 内存协议和响应。
import json  # 私有协议测试。
import os  # 临时AppData隔离。
from pathlib import Path  # 所有文件只在临时目录。
import socket  # 本机模拟控制器与SSH流。
import ssl  # 验证TLS参数未被降级。
import sys  # 当前解释器与测试入口。
import tempfile  # 隔离所有写入。
import threading  # 本机模拟服务。
import time  # 验证总截止。
from types import SimpleNamespace  # 模拟系统检测输出。
import unittest  # 标准库测试。
from unittest.mock import patch, Mock  # 不操纵真实Clash和VPN。
import uuid  # 独立本机测试管道。
import yaml  # 合成配置文件。
ROOT = Path(__file__).resolve().parents[1]  # 独立仓库边界。
sys.path.insert(0, str(ROOT / 'src'))  # 不安装包。
from zzu_nscc_helper import routing, network, controller, worker  # 活跃生产模块。
from zzu_nscc_helper.platform import DATA, load_platform  # 只读公共资源。
from zzu_nscc_helper.keepalive import live_request  # 实际HTTPS出口。
from zzu_nscc_helper.transfer import context, nscc_download, nscc_upload  # 实际传输核心。
import test_stage2 as fixtures  # 复用夹具模块，不重复导入测试类。
FakeLifecycle, DOWNLOAD_TESTS, UPLOAD_TESTS = fixtures.FakeLifecycle, fixtures.DOWNLOAD_TESTS, fixtures.UPLOAD_TESTS  # 仅取非测试类资源。

class ConfigurationMatrix(unittest.TestCase):  # 自动写入的兼容边界。
    def setUp(self):  # 模拟实际官方配置目录。
        self.temp = tempfile.TemporaryDirectory()  # 不使用用户AppData。
        self.addCleanup(self.temp.cleanup)  # 测试结束只清理自己的目录。
        self.root = Path(self.temp.name) / 'io.github.clash-verge-rev.clash-verge-rev'  # 与官方布局一致。
        self.root.mkdir()  # 创建测试配置根。
        (self.root / 'verge.yaml').write_text('enable_system_proxy: true\nsystem_proxy_bypass: "localhost;<local>"\n', encoding='utf-8')  # 没有真实配置内容。
        self.runtime = {'mode': 'rule', 'dns': {'enhanced-mode': 'fake-ip', 'fake-ip-filter-mode': 'blacklist'}, 'tun': {'enable': True}, 'mixed-port': 17890, 'port': 17891, 'socks-port': 17892, 'external-controller': '127.0.0.1:18997'}  # 非固定端口。
        self.identity = {'pid': 123, 'created': 1, 'exe': str(self.root / 'clash-verge.exe'), 'version': '2.5.8'}  # 合成进程身份。
        self.vpn = {'connected': True, 'guid': str(uuid.uuid4()), 'alias': '任意名称 VPN 8', 'dns': '172.99.2.11'}  # 不依赖开发者网卡名。
        for patcher in (patch.dict(os.environ, {'APPDATA': self.temp.name}), patch.object(routing, 'clients', return_value=[self.identity]), patch.object(routing, 'detect_vpn', return_value=self.vpn), patch.object(routing.winreg, 'OpenKey', return_value=Mock(__enter__=Mock(return_value=object()), __exit__=Mock(return_value=False))), patch.object(routing.winreg, 'QueryValueEx', side_effect=FileNotFoundError())):  # 所有系统状态均隔离。
            patcher.start()  # 只影响本测试进程。
            self.addCleanup(patcher.stop)  # 完成后恢复。

    def detect(self):  # 每种场景先写临时运行配置。
        (self.root / 'clash-verge.yaml').write_text(yaml.safe_dump(self.runtime), encoding='utf-8')  # 合成数据。
        return routing.detect()  # 真实检测逻辑。

    def test_multiple_port_and_controller_combinations(self):  # 代理端口和控制器互不混淆。
        for base in (17890, 28760, 37610):  # 覆盖不同本地端口。
            for kind in ('http', 'pipe'):  # 两种真实接口形态。
                with self.subTest(base=base, kind=kind):  # 独立记录场景。
                    self.runtime.update({'mixed-port': base, 'port': base + 1, 'socks-port': base + 2, 'external-controller': '127.0.0.1:' + str(base + 9) if kind == 'http' else '', 'external-controller-pipe': r'\\.\pipe\offline-only' if kind == 'pipe' else ''})  # 不使用7897或9090常量。
                    result = self.detect()  # 本地检测。
                    self.assertTrue(result['writable'])  # 已知环境允许生成预览。
                    self.assertEqual(result['ports']['mixed-port'], base)  # 保留实际端口。
                    self.assertEqual(result['controller']['kind'], kind)  # 管道与HTTP正确区分。

    def test_unsupported_version_multiple_clients_and_pac_are_read_only(self):  # 不猜测用户环境。
        self.detect()  # 创建有效临时配置。
        for processes, error in [([{**self.identity, 'version': '99.0.0'}], 'UNSUPPORTED_VERSION'), ([self.identity, self.identity], 'CLASH_NOT_UNIQUE')]:  # 版本与多实例边界。
            with patch.object(routing, 'clients', return_value=processes):  # 合成系统状态。
                result = routing.detect()  # 实际检测器。
                self.assertFalse(result['writable'])  # 只读。
                self.assertEqual(result['error'], error)  # 明确原因。
        with patch.object(routing.winreg, 'QueryValueEx', return_value=('http://pac.invalid/config', 1)):  # 合成特殊PAC，不发请求。
            self.assertEqual(routing.detect()['error'], 'PAC_UNSUPPORTED')  # 不修改PAC。

    def test_mode_filter_and_disabled_controller_are_read_only(self):  # 不把whitelist当成排除名单。
        for field, value, expected in [('mode', 'global', 'ROUTING_MODE_UNSUPPORTED'), ('dns', {'enhanced-mode': 'fake-ip', 'fake-ip-filter-mode': 'whitelist'}, 'FAKE_IP_UNSUPPORTED'), ('external-controller', '', 'CONTROLLER_UNAVAILABLE')]:  # 不兼容语义。
            original = copy.deepcopy(self.runtime)  # 每次从正常配置开始。
            self.runtime[field] = value  # 只改变一项。
            self.assertEqual(self.detect()['error'], expected)  # 自动修改必须拒绝。
            self.runtime = original  # 恢复夹具。

class VpnMatrix(unittest.TestCase):  # 所有查询都替换，不发探测数据包。
    def test_interface_metadata_and_routes(self):  # GUID、接口运行状态与平台DNS共同核对。
        base = {'index': 9, 'guid': str(uuid.uuid4()), 'alias': '重命名后的VPN', 'description': 'Virtual Adapter', 'up': True}  # 任意稳定身份。
        for hardware, dns, description, expected in [(False, ['172.99.2.11'], 'Virtual Adapter', True), (True, ['172.99.2.11'], 'Ethernet', False), (False, ['198.18.0.2'], 'Virtual Adapter', False), (False, ['172.99.2.11'], 'Meta Tunnel', False)]:  # 防Clash TUN或硬件网卡误认。
            with self.subTest(hardware=hardware, description=description):  # 分场景报告。
                metadata = SimpleNamespace(returncode=0, stdout=json.dumps([{'index': 9, 'hardware': hardware, 'dns': dns}]).encode())  # 模拟PowerShell元数据。
                with patch.object(network, 'best_interface', return_value={**base, 'description': description}), patch.object(network.subprocess, 'run', return_value=metadata):  # 没有真实路由操作。
                    self.assertEqual(network.detect_vpn()['connected'], expected)  # 与名称无关。
        with patch.object(network, 'best_interface', side_effect=[base, {**base, 'guid': str(uuid.uuid4())}, base]), patch.object(network.subprocess, 'run') as command:  # 三目标出口不一致。
            self.assertFalse(network.detect_vpn()['connected'])  # 不借用默认路由。
            command.assert_not_called()  # 基础路由不符时无需额外检测。

class TransactionFaults(unittest.TestCase):  # 复用临时目录夹具，不继承已有测试以避免重复计数。
    setUp = fixtures.RoutingTests.setUp  # 相同的原配置与假生命周期。

    def test_manually_changed_managed_script_is_preserved(self):  # 不丢弃包裹层外的用户修改。
        managed = routing.managed_script(self.script, self.snapshot['vpn'])  # 真实生成器。
        changed = managed + b'// manual edit after managed block\n'  # 模拟后续人工修改。
        with self.assertRaisesRegex(routing.RoutingError, 'MANAGED_SCRIPT_CONFLICT'):  # 只能报告冲突。
            routing.managed_script(changed, self.snapshot['vpn'])  # 不生成覆盖内容。
        with self.assertRaisesRegex(routing.RoutingError, 'MANAGED_SCRIPT_CONFLICT'):  # 编辑器改换行也不偷偷套新包装。
            routing.managed_script(managed.replace(b'\n', b'\r\n'), self.snapshot['vpn'])  # 原文件仍由用户决定。

    def test_corrupt_backup_is_rejected_before_client_stop(self):  # 有损备份不能用于应用。
        result = routing.preview(self.snapshot)  # 创建完整计划。
        plan = routing.load_plan(result['id'])  # 真实私有记录。
        plan['files'][0]['before'] = base64.b64encode(b'corrupt').decode()  # 哈希与字节不符。
        routing.save_plan(plan)  # 仅修改测试私有记录。
        with self.assertRaisesRegex(routing.RoutingError, 'INVALID_PLAN'):  # 不关闭Clash。
            routing.transact(result['id'], lifecycle_factory=FakeLifecycle)  # 假生命周期。
        self.assertEqual(FakeLifecycle.instances, [])  # 没有任何进程动作。
        self.assertEqual(routing.history()[0]['status'], 'Unreadable')  # 重启后的GUI必须知道存在损坏备份。

    def test_normal_exit_refusal_does_not_write(self):  # 不强杀、不继续写。
        result = routing.preview(self.snapshot)  # 实际预览。
        life = Mock(stop=Mock(return_value=False))  # 模拟客户端拒绝正常退出。
        with self.assertRaisesRegex(routing.RoutingError, 'WAIT_FOR_CLASH_EXIT'):  # 等用户处理。
            routing.transact(result['id'], lifecycle_factory=lambda identity: life)  # 无真实生命周期。
        self.assertEqual((self.root / 'verge.yaml').read_bytes(), self.verge)  # 原字节保留。
        life.restart.assert_not_called()  # 没退出就不重复启动。

    def test_restore_write_failure_is_not_reported_as_restored(self):  # 失败恢复也需要实际证据。
        result = routing.preview(self.snapshot)  # 两文件计划。
        actual, calls = routing.atomic_write, []  # 保存真实临时文件写入器。
        def fail_writes(root, name, content):  # 第一项写入后，后续写入及恢复都失败。
            calls.append(name)  # 记录尝试。
            if len(calls) > 1:  # 模拟磁盘故障。
                raise OSError('offline fault')  # 没有私人数据。
            return actual(root, name, content)  # 第一项真实写入临时目录。
        with patch.object(routing, 'atomic_write', side_effect=fail_writes):  # 不影响用户配置。
            with self.assertRaisesRegex(routing.RoutingError, 'RecoveryConflict'):  # 不能误报恢复成功。
                routing.transact(result['id'], lifecycle_factory=FakeLifecycle)  # 假Clash。
        self.assertEqual(routing.load_plan(result['id'])['status'], 'RecoveryConflict')  # 备份和异常终态保留。

    def test_generated_script_rejects_async_entry(self):  # 避免对Promise误加DNS字段。
        with self.assertRaisesRegex(routing.RoutingError, 'SCRIPT_ENTRY_UNSUPPORTED'):  # 未知行为只读。
            routing.managed_script(b'async function main(config) { return config; }', self.snapshot['vpn'])  # 不执行异步脚本。

    def effect_fixture(self):  # 构造合法运行文件，不使用实际Clash配置。
        profile = load_platform()  # 公共平台目标。
        bypass, unused = routing.patch_bypass(self.verge, profile['routing']['system_proxy_bypass'])  # 临时新增系统代理绕过。
        (self.root / 'verge.yaml').write_bytes(bypass)  # 仅测试目录。
        resolver = 'udp://172.99.2.11:53#' + self.snapshot['vpn']['alias']  # 合成接口别名。
        runtime = {**self.snapshot['ports'], 'dns': {'enhanced-mode': 'fake-ip', 'fake-ip-filter-mode': 'blacklist', 'fake-ip-filter': profile['routing']['dns_domains'], 'nameserver-policy': {domain: resolver for domain in profile['routing']['dns_domains']}}, 'tun': {'enable': True, 'route-exclude-address': ['222.22.12.2/32']}, 'rules': routing.rule_specs()}  # 完整本方案字段。
        (self.root / 'clash-verge.yaml').write_text(yaml.safe_dump(runtime), encoding='utf-8')  # 运行配置夹具。
        plan = {'root': str(self.root), 'vpn': self.snapshot['vpn'], 'switches': {'system_proxy': True, 'tun': True}, 'ports': self.snapshot['ports'], 'client': self.snapshot['client']}  # 验证所需最小计划。
        general = {**self.snapshot['ports'], 'mode': 'rule', 'tun': {'enable': True, 'route-exclude-address': ['222.22.12.2/32']}}  # 合成核心/configs。
        rules = [{'type': 'Domain', 'payload': domain, 'proxy': 'DIRECT'} for domain in profile['routing']['dns_domains']] + [{'type': 'IPCIDR', 'payload': ip + '/32', 'proxy': 'DIRECT'} for ip in ('172.99.2.7', '172.99.2.103', '172.99.1.100', '222.22.12.2')]  # 独立核对具体目标。
        return plan, general, {'rules': rules}  # 不返回或使用任何真实核心信息。

    def test_effect_requires_actual_core_rules_ports_and_tun(self):  # 写入成功不等于核心已经加载。
        plan, general, rules = self.effect_fixture()  # 合法文件条件。
        def registry(key, name):  # 系统代理实际生效结果替身。
            return (1, 4) if name == 'ProxyEnable' else (';'.join(load_platform()['routing']['system_proxy_bypass']), 1)  # 合成WinINET值。
        with patch.object(routing.winreg, 'OpenKey', return_value=Mock(__enter__=Mock(return_value=object()), __exit__=Mock(return_value=False))), patch.object(routing.winreg, 'QueryValueEx', side_effect=registry):  # 不读取实际系统代理。
            with patch.object(routing, 'query_core', side_effect=[general, rules]):  # 核心实际状态匹配。
                self.assertTrue(routing.validate_effect(plan))  # 各层都匹配才能通过。
            for bad_general, bad_rules in [({**general, 'mixed-port': 1}, rules), ({**general, 'tun': {'enable': False}}, rules), ({**general, 'mode': 'global'}, rules), ({**general, 'tun': {'enable': True, 'route-exclude-address': []}}, rules), (general, {'rules': [{**rules['rules'][0], 'proxy': 'ExistingGroup'}, *rules['rules'][1:]]}), (general, {'rules': [{**rules['rules'][0], 'extra': {'disabled': True}}, *rules['rules'][1:]]})]:  # 核心端口、模式、TUN或规则禁用都不能误过。
                with patch.object(routing, 'query_core', side_effect=[bad_general, bad_rules]):  # 文件仍然全部正确。
                    self.assertFalse(routing.validate_effect(plan))  # 不能只凭文件报成功。

    def test_stale_runtime_file_is_not_restart_evidence(self):  # 防核心重启失败后使用旧文件通过。
        plan, unused, ignored = self.effect_fixture()  # 合成完整旧配置。
        plan['runtime_before_mtime'] = (self.root / 'clash-verge.yaml').stat().st_mtime_ns  # 仍是同一个旧运行文件。
        with patch.object(routing, 'query_core') as query:  # 不执行真实查询。
            self.assertFalse(routing.validate_effect(plan))  # 必须等待重启生成的文件。
            query.assert_not_called()  # 旧文件阶段无需查核心。

class ProcessProtocolTests(unittest.TestCase):  # 工作进程无效输出不能当成功。
    @classmethod  # 与所有Qt测试共用应用。
    def setUpClass(cls):  # 不显示窗口。
        from PyQt5.QtWidgets import QApplication  # 已有Qt环境。
        cls.app = QApplication.instance() or QApplication([])  # 可分发进程信号。

    def test_success_followed_by_bad_output_is_failure(self):  # 成功帧不能掩盖后面的错误输出。
        from zzu_nscc_helper.processes import WorkerTask  # 活跃协议控制器。
        task, results = WorkerTask(), []  # 无真实进程。
        process = Mock()  # 只模拟协议输入。
        process.readAllStandardOutput.side_effect = [b'{"event":"result","ok":true}\nnot-json\n', b'']  # 错误后置。
        task.process = process  # 绑定当前身份。
        task.completed.connect(results.append)  # 捕获唯一终态。
        task.read(process)  # 实际协议解析。
        task.finish(process, 0)  # 即使退出码0也不能成功。
        task.finish(process, 0)  # 迟到信号不得重复通知。
        self.assertEqual(len(results), 1)  # 单次终态。
        self.assertFalse(results[0]['ok'])  # 严格失败。
        process.kill.assert_called()  # 已要求结束无效进程。

    def test_unfinished_transaction_blocks_new_gui_writes(self):  # 不等用户选到异常历史才阻止叠加修改。
        from zzu_nscc_helper.gui import MainWindow  # 活跃统一界面。
        window = MainWindow(('routing',), preview=True)  # 不做实际检测或读取个人备份。
        try:  # 只注入合成历史事件。
            window.preview_mode = False  # 检查真实按钮资格，无启动自动任务。
            window.environment = {'writable': True}  # 合成兼容检测结果。
            panel = window.routing  # 分流组件。
            panel.plan = {'id': str(uuid.uuid4())}  # 合成已生成预览。
            panel.operation = 'history'  # 模拟历史读取终态。
            panel.finished({'ok': True, 'history': [{'id': str(uuid.uuid4()), 'status': 'Writing', 'created': ''}]})  # 前一次事务未结束。
            self.assertTrue(panel.recovery_pending)  # 立即进入需核对状态。
            self.assertFalse(panel.apply_button.isEnabled())  # 不允许新写入。
            self.assertIn('未完成', panel.status.text())  # 用户可见原因。
        finally:  # 清理测试GUI。
            window.cleanup()  # 不残留本地计时器。
            window.deleteLater()  # 释放控件。
            self.app.processEvents()  # 完成销毁。

    def test_empty_component_override_is_not_all_components(self):  # 安装选择至少一项。
        from zzu_nscc_helper.gui import installed_components  # 活跃清单入口。
        for value in ('', 'unknown', 'sftp,'):  # 空、未知或不完整组合。
            with self.assertRaises(ValueError):  # 不猜测成全部安装。
                installed_components(value)  # 只检查选择，不创建GUI。

    def test_frozen_component_manifest_and_worker_location(self):  # 不需要本机Python路径。
        from zzu_nscc_helper.gui import installed_components  # 安装版真实入口。
        from zzu_nscc_helper.paths import worker_command  # 实际后台路径选择。
        with tempfile.TemporaryDirectory() as folder:  # 模拟实际安装位置。
            root = Path(folder)  # 不写真实安装目录。
            manifest = root / 'components.json'  # 安装器生成的本机清单。
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(root / 'zzu-nscc-helper.exe')):  # 合成打包状态。
                manifest.write_text(json.dumps({'schema': 1, 'components': ['sftp']}), encoding='utf-8')  # 单组件清单。
                self.assertEqual(installed_components(), ('sftp',))  # 只打开已安装组件。
                self.assertEqual(worker_command(), [str(root.resolve() / 'zzu-nscc-worker.exe')])  # 比较真实目录，兼容Windows临时目录的8.3短名称。
                for value in ({'schema': 999, 'components': ['sftp']}, {'schema': 1, 'components': []}):  # 升级与损坏清单边界。
                    manifest.write_text(json.dumps(value), encoding='utf-8')  # 修改测试文件。
                    with self.assertRaises(ValueError):  # 必须在启动任务前失败。
                        installed_components()  # 不载入不存在的组件。

    def test_single_instance_mutex_releases(self):  # 重复启动不创建第二套定时任务。
        from zzu_nscc_helper.instance import InstanceGuard  # 真实Windows互斥实现。
        prefix = 'ZZU-Offline-Test-' + uuid.uuid4().hex  # 不占用生产互斥。
        first, second = InstanceGuard(prefix), InstanceGuard(prefix)  # 同一个测试作用域。
        try:  # 即使断言失败也释放句柄。
            self.assertTrue(first.primary)  # 第一实例持有控制权。
            self.assertFalse(second.primary)  # 第二实例不能运行。
        finally:  # 不遗留内核引用。
            second.close()  # 释放第二引用。
            first.close()  # 释放第一引用。
        third = InstanceGuard(prefix)  # 旧实例退出后可正常重启。
        try:  # 仍需回收最后句柄。
            self.assertTrue(third.primary)  # 不会变成永久锁死。
        finally:  # 测试结束。
            third.close()  # 无残留互斥。

    def test_cancellation_timeout_cleans_real_child_without_cleanup_claim(self):  # 实际后台无响应时父进程有界停止。
        from zzu_nscc_helper import processes  # 活跃Qt进程控制器。
        def launch(process, request):  # 仅创建本测试的睡眠进程。
            process.setProgram(sys.executable)  # 当前已有解释器。
            process.setArguments(['-c', 'import time; time.sleep(60)'])  # 无网络、无凭据。
        task, results = processes.WorkerTask(), []  # 独立控制器。
        task.completed.connect(results.append)  # 捕获终态。
        with patch.object(processes, 'prepare_process', side_effect=launch):  # 不执行任何真实传输。
            task.start('sftp', {})  # 模拟失去响应的网络工作程序。
        deadline = time.monotonic() + 3  # 等待实际进程启动。
        while task.busy and task.process.state() != task.process.Running and time.monotonic() < deadline:  # 分发启动信号。
            self.app.processEvents()  # 不阻塞Qt。
            time.sleep(0.01)  # 有界等待。
        self.assertTrue(task.busy)  # 确实已启动。
        task.cancel()  # 发送协作取消并等待七秒清理宽限。
        deadline = time.monotonic() + 9  # 给父进程终止留少量调度余量。
        while task.busy and time.monotonic() < deadline:  # 必须确认实际退出。
            self.app.processEvents()  # 接收QProcess信号。
            time.sleep(0.01)  # 低开销等待。
        if task.busy:  # 即使测试失败也回收自己的子进程。
            task.force_stop()  # 只结束本测试进程。
            task.process.waitForFinished(2000)  # 不遗留睡眠进程。
        self.assertFalse(task.busy)  # 已实际退出。
        self.assertEqual(len(results), 1)  # 只通知一次。
        self.assertEqual(results[0]['error'], 'CANCELLED_CLEANUP_UNCONFIRMED')  # 不伪造临时清理成功。

class RequestMatrix(unittest.TestCase):  # 使用真实请求函数和模拟连接池。
    def test_tls_content_route_and_cleanup(self):  # HTTPS参数、正文和出口变化均有校验。
        valid = b' '.join(live_request.MARKERS)  # 无真实页面内容。
        for status, body, route_after, error in [(200, valid, True, None), (302, valid, True, 'HTTP_STATUS'), (200, b'', True, 'EMPTY_BODY'), (200, b'proxy error', True, 'CONTENT_MISMATCH'), (200, valid, False, 'VPN_ROUTE_INVALID'), (200, b'x' * 65536, True, 'BODY_TOO_LARGE')]:  # 错误页或超限不计成功。
            with self.subTest(status=status, expected=error):  # 独立显示失败。
                response = Mock(status=status, headers={'Content-Type': 'text/html'})  # 模拟HTTP头。
                stream = io.BytesIO(body)  # 有界合成正文。
                response.read.side_effect = stream.read  # 真正按请求的块大小读取。
                pool = Mock()  # 不创建网络连接。
                pool.urlopen.return_value = response  # 模拟单次响应。
                with patch.object(live_request, 'route_matches', side_effect=[True, route_after]), patch.object(live_request.urllib3, 'HTTPSConnectionPool', return_value=pool) as factory:  # 固定真实出口替身。
                    result = live_request.perform(str(uuid.uuid4()))  # 活跃请求入口。
                self.assertEqual(result.get('error'), error)  # 明确失败类别。
                self.assertEqual(factory.call_args.kwargs['cert_reqs'], ssl.CERT_REQUIRED)  # 禁止关闭证书校验。
                self.assertEqual(factory.call_args.kwargs['server_hostname'], 'v.zzu.edu.cn')  # SNI与证书名称正确。
                self.assertFalse(pool.urlopen.call_args.kwargs['redirect'])  # 不跟随SSO或代理跳转。
                self.assertNotIn('Cookie', pool.urlopen.call_args.kwargs['headers'])  # 不复用网页登录态。
                response.close.assert_called_once()  # 任意结果都清理响应。
                pool.close.assert_called_once()  # 无残留连接。

    def test_tls_and_network_exceptions_are_fixed_categories(self):  # 不返回异常中的潜在认证内容。
        for error, expected in [(live_request.urllib3.exceptions.SSLError('synthetic'), 'TLS_VALIDATION_FAILED'), (live_request.urllib3.exceptions.ReadTimeoutError(None, '/', 'synthetic'), 'TIMEOUT'), (OSError('synthetic'), 'NETWORK_ERROR')]:  # 只在内存构造。
            pool = Mock()  # 不联网。
            pool.urlopen.side_effect = error  # 注入真实异常类型。
            with patch.object(live_request, 'route_matches', return_value=True), patch.object(live_request.urllib3, 'HTTPSConnectionPool', return_value=pool):  # 模拟安全路由。
                self.assertEqual(live_request.perform(str(uuid.uuid4()))['error'], expected)  # 不输出原文。
            pool.close.assert_called_once()  # 失败也关闭连接池。

class TransferFaults(unittest.TestCase):  # 取消与身份失败不影响已有文件。
    def tearDown(self):  # 每个新工作进程本来会重建上下文。
        context.cancelled.clear()  # 不污染其他场景。
        context.notify = lambda message: None  # 不保留进度接收器。

    def test_upload_cancel_cleans_only_own_partial(self):  # 写入之后取消，正式目标不能出现。
        with tempfile.TemporaryDirectory() as folder:  # 明确测试来源。
            source = Path(folder) / 'source.bin'  # 临时来源。
            source.write_bytes(b'offline-transfer-data')  # 不用研究数据。
            remote = UPLOAD_TESTS.FakeSFTP().directory('/home/job').file('/home/job/existing', b'keep')  # 已有远端文件。
            remote.on_first_write = context.cancelled.set  # 首个数据块后取消。
            entries, unused = nscc_upload.make_plan([source], '/home/job')  # 活跃计划。
            with contextlib.redirect_stdout(io.StringIO()):  # 不回显临时路径。
                results = nscc_upload.execute_plan(remote, entries)  # 真实事务和finally清理。
            self.assertEqual(results[0]['status'], 'Failed')  # 当前未完成文件不是成功。
            self.assertNotIn('/home/job/source.bin', remote.nodes)  # 没有未校验成品。
            self.assertEqual(remote.nodes['/home/job/existing']['data'], b'keep')  # 已有文件保留。
            self.assertTrue(remote.removed)  # 自己的临时文件已清理。

    def test_download_cancel_keeps_success_and_cleans_only_own_partial(self):  # 下载也能在块边界取消。
        with tempfile.TemporaryDirectory() as folder:  # 所有本地写入隔离。
            destination = Path(folder) / 'download'  # 临时目标。
            remote = DOWNLOAD_TESTS.FakeSFTP().directory('/home').directory('/home/job').file('/home/job/a', b'keep-success').file('/home/job/b', b'cancel-this').file('/home/job/c', b'do-not-start')  # 三个合成来源。
            original = remote.getfo  # 保留正常下载行为。
            def getfo(path, stream):  # 第二个文件产生部分字节后取消。
                if path.endswith('/b'):  # 只在目标项注入取消。
                    remote.downloads.append(path)  # 记录确实开始过。
                    stream.write(b'cancel')  # 已写入临时文件。
                    context.cancelled.set()  # 父进程取消标志。
                    stream.write(b'-this')  # 必须在真正写入前停止。
                else:  # 第一项正常完成。
                    return original(path, stream)  # 真实有界写入器。
            remote.getfo = getfo  # 不替换核心事务。
            entries, unused = nscc_download.make_plan(remote, ['/home/job/a', '/home/job/b', '/home/job/c'], destination, '')  # 完整计划。
            with contextlib.redirect_stdout(io.StringIO()):  # 不显示临时路径。
                results = nscc_download.execute_plan(remote, entries, '')  # 实际取消与清理。
            self.assertEqual([item['status'] for item in results], ['Downloaded', 'Failed'])  # 第三项尚未开始。
            self.assertEqual((destination / 'a').read_bytes(), b'keep-success')  # 已成功内容保留。
            self.assertFalse((destination / 'b').exists())  # 部分内容没有伪装成成品。
            self.assertFalse(list(destination.glob('.nscc-*.part')))  # 仅本次随机临时文件被清理。
            self.assertNotIn('/home/job/c', remote.downloads)  # 取消后没有补发。

    def test_upload_disconnection_reports_unconfirmed_cleanup(self):  # 远端不可达时不能谎称已删除临时文件。
        with tempfile.TemporaryDirectory() as folder:  # 临时本地文件。
            source = Path(folder) / 'source.bin'  # 来源。
            source.write_bytes(b'offline-transfer-data')  # 合成字节。
            remote = UPLOAD_TESTS.FakeSFTP().directory('/home/job')  # 模拟SFTP。
            remote.fail_writes = True  # 产生部分写入后断网。
            remote.remove = Mock(side_effect=OSError('offline disconnect'))  # 清理也无法完成。
            entries, unused = nscc_upload.make_plan([source], '/home/job')  # 实际计划。
            with contextlib.redirect_stdout(io.StringIO()):  # 不输出路径。
                results = nscc_upload.execute_plan(remote, entries)  # 活跃上传。
            self.assertIn('清理未确认', results[0]['error'])  # 回执明确保留具体待核对临时路径。
            self.assertTrue(any(name.endswith('.part') for name in remote.nodes))  # 不能把尚存在对象报告已删除。

    def test_local_pin_change_fails_before_password(self):  # 本地公开身份资源被篡改时不认证。
        with tempfile.TemporaryDirectory() as folder:  # 不改实际公钥文件。
            base = Path(folder)  # 隔离目录。
            source = base / 'source.bin'  # 上传来源。
            source.write_bytes(b'x')  # 合成内容。
            trust = base / 'known_hosts'  # 合成损坏信任文件。
            trust.write_text('', encoding='ascii')  # 没有批准公钥。
            requests = [(nscc_upload, {'local_paths': [str(source)], 'remote_directory': '/home/job', 'report_root': str(base / 'reports')}), (nscc_download, {'remote_paths': ['/home/job/source.bin'], 'download_root': str(base / 'download'), 'category': '离线任务'})]  # 双方向实际参数格式。
            for core, request in requests:  # 不查询远端。
                request.update(username='offline-fixture', known_hosts=str(trust))  # 合成账号，仅在测试请求中。
                provider = Mock(return_value=''.join(('synthetic', '-value')))  # 不可用的测试口令。
                with self.assertRaises(ValueError):  # 应在读取密码前失败。
                    core.run(request, password_provider=provider)  # 活跃核心。
                provider.assert_not_called()  # 身份变化不读取凭据。

    def test_auth_error_does_not_echo_input(self):  # 错误认证返回固定类别。
        import paramiko  # 已安装依赖，不访问服务器。
        value = ''.join(('synthetic', '-credential-never-log'))  # 不可用口令。
        packet = {'task': 'sftp', 'payload': {'direction': 'upload', 'username': 'offline-fixture', 'vpn_guid': str(uuid.uuid4())}, 'auth': {'password': value}}  # 内存请求。
        incoming = io.TextIOWrapper(io.BytesIO(json.dumps(packet).encode() + b'\n'))  # 不创建请求文件。
        outgoing = io.StringIO()  # 捕获只读协议结果。
        with patch.object(sys, 'stdin', incoming), patch.object(sys, '__stdout__', outgoing), patch.object(worker, 'route_matches', return_value=True), patch.object(worker.threading.Thread, 'start'), patch.object(nscc_upload, 'run', side_effect=paramiko.AuthenticationException(value)):  # 不启动SSH或取消线程。
            worker.main()  # 实际异常过滤。
        result = json.loads(outgoing.getvalue())  # 固定JSON。
        self.assertEqual(result['error'], 'AUTH_FAILED')  # 准确类别。
        self.assertNotIn(value, outgoing.getvalue())  # 不泄露输入。

    def test_server_key_change_blocks_authentication(self):  # 真实Paramiko握手，仅使用本机socketpair。
        import paramiko  # 现有SSH实现。
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # 内存中生成不受信任的测试主机身份。
        from cryptography.hazmat.primitives import serialization  # 不将测试私钥写入文件。
        generated = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())  # 临时不可复用测试材料。
        key = paramiko.Ed25519Key(file_obj=io.StringIO(generated.decode()))  # 仅交给本机模拟服务。
        class Server(paramiko.ServerInterface):  # 记录是否到达密码认证阶段。
            def __init__(self):  # 每个方向重新创建。
                self.authentication_seen = False  # 身份不符时必须保持False。
            def check_auth_password(self, username, value):  # 不保存收到的认证内容。
                self.authentication_seen = True  # 只记录是否被调用。
                return paramiko.AUTH_FAILED  # 测试服务永不接受认证。
        for direction in ('upload', 'download'):  # 两种核心都要受同一主机身份保护。
            with self.subTest(direction=direction), tempfile.TemporaryDirectory() as folder:  # 临时本地来源和目标。
                base = Path(folder)  # 不接触实际研究文件。
                source = base / 'source.bin'  # 上传预检需要存在文件。
                source.write_bytes(b'offline-only')  # 合成数据。
                client_socket, server_socket = socket.socketpair()  # 只连接本机内存测试端点。
                server, server_interface = paramiko.Transport(server_socket), Server()  # 临时SSH服务。
                server.add_server_key(key)  # 与批准公钥明确不同的ED25519身份。
                server.start_server(event=threading.Event(), server=server_interface)  # 异步握手，无外部监听。
                client = paramiko.SSHClient()  # 使用真实SSHClient的主机密钥检查。
                original_connect = client.connect  # 只替换网络流，不替换认证逻辑。
                def connect(host, **arguments):  # 平台主机名仍参与主机密钥匹配。
                    arguments['sock'] = client_socket  # 不会连接172.99.1.100。
                    return original_connect(host, **arguments)  # 完整真实密钥核对。
                request = {'username': 'offline-fixture', 'known_hosts': str(DATA / 'known_hosts')}  # 公开批准公钥，不含开发者身份。
                request.update({'local_paths': [str(source)], 'remote_directory': '/home/job', 'report_root': str(base / 'reports')} if direction == 'upload' else {'remote_paths': ['/home/job/source.bin'], 'download_root': str(base / 'download'), 'category': '离线任务'})  # 明确实际格式参数。
                provider = Mock(return_value=''.join(('synthetic', '-password')))  # 不可用测试口令。
                try:  # 即使失败也关闭本机SSH线程。
                    with patch.object(paramiko, 'SSHClient', return_value=client), patch.object(client, 'connect', side_effect=connect):  # 仅替换真实出口。
                        with self.assertRaises(paramiko.BadHostKeyException):  # 服务端身份改变必须拒绝。
                            (nscc_upload if direction == 'upload' else nscc_download).run(request, password_provider=provider)  # 活跃核心。
                    self.assertFalse(server_interface.authentication_seen)  # 密码没有发送给不受信任身份。
                    provider.assert_called_once()  # GUI每批只提供一次认证输入。
                finally:  # 不遗留测试连接或线程。
                    client.close()  # 关闭真实SSHClient。
                    server.close()  # 停止测试Transport。
                    client_socket.close()  # 释放本机流。
                    server_socket.close()  # 释放本机流。
                    server.join(timeout=2)  # 有界确认线程结束。
                self.assertFalse(server.is_alive())  # 没有测试SSH后台残留。

class CoreTransportTests(unittest.TestCase):  # 验证本机HTTP和Windows管道，无真实Clash交互。
    @classmethod  # 与后续GUI测试共用QApplication。
    def setUpClass(cls):  # 不创建可见界面。
        from PyQt5.QtWidgets import QApplication  # 使用已有Qt依赖。
        cls.app = QApplication.instance() or QApplication([])  # 不能先创建仅QCoreApplication影响GUI测试。

    def test_only_loopback_addresses_and_read_only_paths(self):  # 认证头不能发往外部网络。
        for value in ('192.0.2.8:19001', 'example.invalid:19001', '127.0.0.1:19001/configs'):  # 非本机或非入口格式。
            with self.assertRaises((controller.ControllerError, ValueError)):  # 在连接之前拒绝。
                controller.address(value)  # 不执行DNS。
        for value, expected in [('127.0.0.1:19001', '127.0.0.1'), ('localhost:19002', '127.0.0.1'), ('0.0.0.0:19003', '127.0.0.1'), ('[::1]:19004', '::1')]:  # 实际本机形式。
            self.assertEqual(controller.address(value)[0], expected)  # 始终选择实际回环IP。
        with self.assertRaises(controller.ControllerError):  # 任意写入API都不开放。
            controller.query({}, '/restart')  # 不建立连接。

    def test_unexpected_response_never_counts_as_core_state(self):  # 跳转、错误格式、空正文和超限均拒绝。
        for status, kind, body in [(302, 'application/json', b'{}'), (200, 'text/html', b'{}'), (200, 'application/json', b''), (200, 'application/json', b'x' * (controller.LIMIT + 1)), (200, 'application/json', b'[]')]:  # 合成异常矩阵。
            with self.assertRaises(controller.ControllerError):  # 不报生效成功。
                controller.parse_body(status, kind, body)  # 无实际连接。

    def tcp_fixture(self, response, drip=False):  # 临时回环监听，仅用于测试实际客户端。
        listener = socket.socket()  # 不绑定外部网卡。
        listener.bind(('127.0.0.1', 0))  # 由系统分配临时端口。
        listener.listen(1)  # 一次测试仅一个连接。
        self.addCleanup(listener.close)  # 任何结果都释放监听。
        state = {}  # 请求仅留在本测试内存。
        def serve():  # 不执行请求内容。
            try:  # 客户端超时关闭时允许复位。
                with listener.accept()[0] as connection:  # 单次本机连接。
                    data = b''  # 有界请求缓冲。
                    connection.settimeout(7)  # 避免错误测试残留。
                    while b'\r\n\r\n' not in data and len(data) < 16384:  # 只读取HTTP头。
                        data += connection.recv(4096)  # 不接收任何文件上传。
                    state['request'] = data  # 供断言GET和认证，不落盘。
                    if drip:  # 头部慢速到达也必须受总截止约束。
                        for value in response:  # 每次一个字节。
                            connection.sendall(bytes([value]))  # 不发送真实内容。
                            time.sleep(0.2)  # 模拟挂起的本机核心。
                    else:  # 普通模拟核心。
                        connection.sendall(response)  # 发送固定合成HTTP响应后关闭。
            except OSError:  # 正常超时断开。
                pass  # 不回显请求。
        thread = threading.Thread(target=serve, daemon=True)  # 本机测试线程。
        thread.start()  # 开始等待测试客户端。
        self.addCleanup(lambda: thread.join(timeout=3))  # 保证测试结束后回收。
        return listener.getsockname()[1], state  # 不返回实际系统端口配置。

    def test_tcp_actual_transport_ignores_proxy_and_hides_auth(self):  # 真实回环传输，使用合成控制器口令。
        body = b'{"mixed-port":17890}'  # 合成只读结果。
        response = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body  # 完整响应。
        port, state = self.tcp_fixture(response)  # 动态端口。
        value = ''.join(('synthetic', '-controller-auth'))  # 不可用的合成口令。
        result = controller.query({'external-controller': '127.0.0.1:' + str(port), 'secret': value}, '/configs')  # 实际本机只读查询。
        self.assertEqual(result['mixed-port'], 17890)  # 读取实际测试响应。
        self.assertTrue(state['request'].startswith(b'GET /configs '))  # 没有写操作。
        self.assertNotIn(value, json.dumps(result))  # 结果不回显认证头。

    def test_tcp_total_deadline_includes_slow_headers(self):  # 防逐字节慢响应无限延长事务。
        port, unused = self.tcp_fixture(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{}', drip=True)  # 不触及真实核心。
        start = time.monotonic()  # 单调计时。
        with self.assertRaises(controller.ControllerError):  # 五秒整体截止。
            controller.query({'external-controller': '127.0.0.1:' + str(port)}, '/configs')  # 实际有界客户端。
        self.assertLess(time.monotonic() - start, 6.5)  # 不因字节持续到达而延期。

    def test_named_pipe_actual_transport(self):  # 不依赖HTTP端口的真实本机管道。
        from PyQt5.QtNetwork import QLocalServer  # Windows原生命名管道服务器。
        name = 'ZZU-Core-Test-' + uuid.uuid4().hex  # 不占用生产管道。
        ready, state = threading.Event(), {}  # 协调监听，不创建定时任务。
        def serve():  # 所有Qt服务对象都在此线程创建和释放。
            server = QLocalServer()  # 独立本机管道。
            server.setSocketOptions(QLocalServer.UserAccessOption)  # 仅当前用户。
            state['listening'] = server.listen(name)  # 不修改真实Clash。
            ready.set()  # 允许测试客户端连接。
            if server.waitForNewConnection(5000):  # 有界等待。
                peer = server.nextPendingConnection()  # 单一测试客户端。
                if peer.waitForReadyRead(5000):  # 获取GET请求。
                    state['request'] = bytes(peer.readAll())  # 不保存到文件。
                    peer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 12\r\nConnection: close\r\n\r\n{"rules":[]}')  # 合成只读响应。
                    peer.waitForBytesWritten(3000)  # 完整写出后关闭。
                peer.disconnectFromServer()  # HTTP Connection: close。
            server.close()  # 释放测试命名管道。
        thread = threading.Thread(target=serve, daemon=True)  # 不创建助手工作进程。
        thread.start()  # 等待本机客户端。
        self.assertTrue(ready.wait(2))  # 不无限等。
        self.assertTrue(state['listening'])  # 管道创建确实成功。
        try:  # 即使断言失败也回收服务线程。
            result = controller.query({'external-controller-pipe': '\\\\.\\pipe\\' + name}, '/rules')  # 实际管道客户端。
            self.assertEqual(result, {'rules': []})  # 只读JSON解析。
        finally:  # 不遗留本机服务。
            thread.join(timeout=6)  # 有界清理。
        self.assertFalse(thread.is_alive())  # 确认线程退出。
