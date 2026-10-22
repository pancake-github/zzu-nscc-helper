"""融合阶段离线回归；只使用临时目录和模拟远端，不访问超算。"""  # 不操作真实Clash和浏览器。
import base64  # 检查私有备份的原字节。
import importlib.util  # 复用已验收的传输测试材料。
import io  # 内存模拟下载流。
import itertools  # 覆盖所有组件组合。
import json  # 后台协议测试。
import os  # 临时隔离应用数据目录。
from pathlib import Path  # 所有测试写入临时目录。
import subprocess  # 执行真实后台入口。
import shutil  # 查找已有Node，不安装依赖。
import sys  # 本测试解释器。
import tempfile  # 隔离测试文件。
import time  # 有界Qt事件等待。
import unittest  # 标准库测试。
from unittest.mock import patch  # 无真实网络、注册表或进程退出。
ROOT = Path(__file__).resolve().parents[1]  # 独立发布仓库。
sys.path.insert(0, str(ROOT / 'src'))  # 不安装依赖。
from zzu_nscc_helper import routing, network  # 实际生产模块。
from zzu_nscc_helper.transfer import context, nscc_download, nscc_upload  # 活跃传输核心。
from zzu_nscc_helper.keepalive import live_request  # 活跃请求判据。
from zzu_nscc_helper.components import COMPONENTS  # 实际组件契约。

def fixture_module(name, path):  # 只加载仓库内的离线测试材料。
    spec = importlib.util.spec_from_file_location(name, path)  # 独立模块名。
    module = importlib.util.module_from_spec(spec)  # 创建模块对象。
    spec.loader.exec_module(module)  # 导入不认证也不连接网络。
    return module  # 供后续重用测试。

DOWNLOAD_TESTS = fixture_module('download_fixtures', ROOT / 'baseline/transfer/tests/test_nscc_download.py')  # 已有完整下载场景。
UPLOAD_TESTS = fixture_module('upload_fixtures', ROOT / 'baseline/transfer/tests/test_nscc_upload.py')  # 已有完整上传场景。
DOWNLOAD_TESTS.DOWNLOAD = nscc_download  # 同一套用例改测实际融合核心。
UPLOAD_TESTS.UPLOAD = nscc_upload  # 不复制一份测试实现。

class FakeLifecycle:  # 不启动或关闭真实应用。
    instances = []  # 核对是否尝试退出。
    def __init__(self, identity):  # 保留接口契约。
        self.stopped = False  # 尚未退出。
        self.restarts = 0  # 重启次数。
        self.instances.append(self)  # 供测试检查。
    def stop(self):  # 模拟正常退出。
        self.stopped = True  # 可执行本机临时文件写入。
        return True  # 不使用真实Restart Manager。
    def restart(self):  # 模拟客户端重启。
        if self.stopped:  # 不重复启动。
            self.restarts += 1  # 记录实际重启调用。
            self.stopped = False  # 恢复运行状态。

class RoutingTests(unittest.TestCase):  # 保护原配置和事务边界。
    def setUp(self):  # 每项测试独立私有目录。
        self.temp = tempfile.TemporaryDirectory()  # 不用用户配置目录。
        self.addCleanup(self.temp.cleanup)  # 测试后仅清理这个临时目录。
        self.root = Path(self.temp.name) / 'clash'  # 模拟配置目录。
        (self.root / 'profiles').mkdir(parents=True)  # 模拟真实目录结构。
        self.verge = b'enable_system_proxy: true\nsystem_proxy_bypass: "localhost;127.*;<local>" # keep comment\ncustom_setting: 97\n'  # 不含真实订阅或口令。
        self.script = b'function main(config) { config.custom = "preserved"; return config; }\n'  # 现有增强逻辑必须保留。
        (self.root / 'verge.yaml').write_bytes(self.verge)  # 临时原文件。
        (self.root / 'profiles/Script.js').write_bytes(self.script)  # 临时原脚本。
        self.snapshot = {'writable': True, 'config_root': str(self.root), 'client': {'pid': 123, 'created': 1, 'exe': str(self.root / 'clash-verge.exe'), 'version': '2.5.8'}, 'vpn': {'connected': True, 'alias': 'VPN 测试接口 9', 'guid': '00000000-0000-0000-0000-000000000009'}, 'system_proxy': True, 'tun': True, 'ports': {'mixed-port': 11789, 'port': 11800, 'socks-port': 11801}}  # 不依赖固定网卡名和端口。
        patcher = patch.object(routing, 'data_root', return_value=Path(self.temp.name) / 'private')  # 备份也只能写临时目录。
        patcher.start()  # 应用于本测试。
        self.addCleanup(patcher.stop)  # 恢复真实函数。
        process_patcher = patch.object(routing, 'clients', return_value=[self.snapshot['client']])  # 不读取或管理真实Clash进程。
        process_patcher.start()  # 模拟当前身份。
        self.addCleanup(process_patcher.stop)  # 恢复函数。
        FakeLifecycle.instances = []  # 清除前一项测试状态。

    def test_preview_preserves_originals_and_is_private(self):  # 预览不写Clash。
        result = routing.preview(self.snapshot)  # 真实计划生成器。
        self.assertEqual((self.root / 'verge.yaml').read_bytes(), self.verge)  # 原配置未变。
        self.assertEqual((self.root / 'profiles/Script.js').read_bytes(), self.script)  # 原逻辑未变。
        plan = json.loads(routing.store_path(result['id']).read_text(encoding='utf-8'))  # 本机私有计划。
        self.assertEqual(plan['ports']['mixed-port'], 11789)  # 保留探测端口。
        self.assertNotIn('before', result)  # GUI摘要没有原始配置。
        self.assertIn('VPN 测试接口 9', base64.b64decode(plan['files'][1]['after']).decode())  # 绑定实际别名。

    def test_bypass_exact_and_idempotent(self):  # 原条目和注释保留。
        updated, missing = routing.patch_bypass(self.verge, ['172.99.2.7', '222.22.12.2'])  # 精确平台条目。
        again, second = routing.patch_bypass(updated, ['172.99.2.7', '222.22.12.2'])  # 重复应用。
        self.assertEqual(updated, again)  # 字节不变。
        self.assertEqual(second, [])  # 没有重复追加。
        self.assertIn(b'custom_setting: 97', updated)  # 其他字段保留。
        self.assertIn(b'# keep comment', updated)  # 其他注释保留。
        self.assertNotIn(b'172.*', updated)  # 不扩大网段。

    def test_script_preserves_and_reuses_original(self):  # 不叠加多层增强入口。
        first = routing.managed_script(self.script, self.snapshot['vpn'])  # 真实包装器。
        again = routing.managed_script(first, self.snapshot['vpn'])  # 第二次生成。
        self.assertEqual(first, again)  # 幂等字节结果。
        self.assertIn(self.script, first)  # 原脚本字节存在。
        self.assertNotIn(b'DST-PORT,22', first)  # 不放行所有SSH流量。

    def test_generated_script_executes_and_preserves_configuration(self):  # 不仅检查字符串，还执行真实生成脚本。
        node = shutil.which('node')  # 使用已有运行库。
        if not node:  # 缺少测试运行库时明确记录跳过。
            self.skipTest('未找到已有Node，未验证JavaScript实际执行。')  # 不自动安装。
        script = routing.managed_script(self.script, self.snapshot['vpn']).decode()  # 真实增强生成器。
        configuration = {'mixed-port': 11789, 'proxies': [{'name': 'offline-only'}], 'rules': ['DOMAIN,hpc01.v.zzu.edu.cn,DIRECT', 'MATCH,ExistingGroup'], 'dns': {'nameserver-policy': {'existing.invalid': '1.1.1.1'}, 'fake-ip-filter': ['existing.invalid']}, 'tun': {'enable': False, 'route-exclude-address': ['192.0.2.1/32']}}  # 全部为合成数据。
        result = subprocess.run([node, str(ROOT / 'tests/test_routing_script.cjs')], input=json.dumps({'script': script, 'config': configuration}).encode(), capture_output=True, timeout=10)  # 无真实代理或平台请求。
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))  # 实际运行失败必须阻止交付。
        self.assertIn(b'ROUTING_SCRIPT_PASSED', result.stdout)  # 确认所有独立断言执行。

    def test_reject_unknown_script_and_alias(self):  # 不猜特殊脚本入口。
        with self.assertRaises(routing.RoutingError):  # 未知入口只能导出说明。
            routing.managed_script(b'export default config;', self.snapshot['vpn'])  # 不执行脚本。
        with self.assertRaises(routing.RoutingError):  # 别名不能注入DNS绑定语法。
            routing.managed_script(self.script, {'alias': 'vpn#other'})  # 无真实网卡更改。

    def test_http_and_pipe_controller_never_expose_secret(self):  # 实际控制器类型来自runtime。
        for configuration, expected in [({'external-controller': '127.0.0.1:18997'}, 'http'), ({'external-controller': '', 'external-controller-pipe': r'\\.\pipe\test-only'}, 'pipe')]:  # 不硬编码常用端口。
            configuration['secret'] = ''.join(('synthetic', '-credential-value'))  # 合成不可用测试值，与管道名不同。
            result = routing.controller(configuration)  # 实际脱敏函数。
            self.assertEqual(result['kind'], expected)  # 管道不误当HTTP。
            self.assertTrue(result['secret_present'])  # 只报告是否存在。
            self.assertNotIn(configuration['secret'], json.dumps(result))  # 不泄露值。

    def test_conflict_blocks_before_stop(self):  # 预览后人工修改必须保留。
        result = routing.preview(self.snapshot)  # 建立原哈希。
        (self.root / 'verge.yaml').write_bytes(self.verge + b'new_setting: true\n')  # 模拟用户修改。
        with self.assertRaisesRegex(routing.RoutingError, 'CONFIG_CONFLICT'):  # 必须在退出Clash之前失败。
            routing.transact(result['id'], lifecycle_factory=FakeLifecycle)  # 绝不调用真实生命周期。
        self.assertEqual(FakeLifecycle.instances, [])  # 没有干扰应用。

    def test_apply_and_rollback_exact_bytes(self):  # 完整事务与原字节恢复。
        result = routing.preview(self.snapshot)  # 真实计划。
        with patch.object(routing, 'route_matches', return_value=True):  # 不查询真实VPN。
            applied = routing.transact(result['id'], lifecycle_factory=FakeLifecycle, validator=lambda plan: True)  # 模拟生效核对。
        self.assertEqual(applied['status'], 'Applied')  # 真实写入临时配置后才成功。
        rolled = routing.transact(result['id'], rollback=True, lifecycle_factory=FakeLifecycle)  # 回滚同一计划。
        self.assertEqual(rolled['status'], 'RolledBack')  # 完成恢复。
        self.assertEqual((self.root / 'verge.yaml').read_bytes(), self.verge)  # 精确原配置。
        self.assertEqual((self.root / 'profiles/Script.js').read_bytes(), self.script)  # 精确原脚本。

    def test_rollback_preserves_later_manual_edit(self):  # 用户后续修改不能被旧备份覆盖。
        result = routing.preview(self.snapshot)  # 创建计划。
        with patch.object(routing, 'route_matches', return_value=False):  # 模拟应用时VPN退出。
            applied = routing.transact(result['id'], lifecycle_factory=FakeLifecycle, validator=lambda plan: True)  # 仅临时目录。
        self.assertEqual(applied['status'], 'AppliedPendingVPN')  # 不宣称联网通过。
        path = self.root / 'profiles/Script.js'  # 本软件曾修改的文件。
        changed = path.read_bytes() + b'// later user edit\n'  # 模拟后续人工更改。
        path.write_bytes(changed)  # 测试数据。
        with self.assertRaisesRegex(routing.RoutingError, 'CONFIG_CONFLICT'):  # 不整份覆盖。
            routing.transact(result['id'], rollback=True, lifecycle_factory=FakeLifecycle)  # 模拟回滚。
        self.assertEqual(path.read_bytes(), changed)  # 人工改动仍存在。

    def test_restart_history_and_new_process_identity(self):  # 重启后回滚必须使用新PID。
        result = routing.preview(self.snapshot)  # 临时事务。
        with patch.object(routing, 'route_matches', return_value=True):  # 不查询实际网络。
            routing.transact(result['id'], lifecycle_factory=FakeLifecycle, validator=lambda plan: True)  # 模拟应用。
        rows = routing.history()  # 模拟新GUI重新加载记录。
        self.assertEqual(rows[0]['id'], result['id'])  # 记录可找回。
        self.assertNotIn('files', rows[0])  # 不返回原配置。
        observed = []  # 核对真正使用的进程身份。
        def factory(identity):  # 记录交给生命周期的PID。
            observed.append(identity['pid'])  # 不关闭真实程序。
            return FakeLifecycle(identity)  # 模拟正常退出。
        with patch.object(routing, 'clients', return_value=[{**self.snapshot['client'], 'pid': 456, 'created': 2}]):  # 重启后的新进程。
            routing.transact(result['id'], rollback=True, lifecycle_factory=factory)  # 使用历史记录回滚。
        self.assertEqual(observed, [456])  # 不能以旧PID消失为由在新Clash运行时写入。

    def test_failed_second_write_restores_first(self):  # 多文件事务不能半成功。
        result = routing.preview(self.snapshot)  # 两文件修改计划。
        actual, attempts = routing.atomic_write, []  # 保存真实临时写入函数。
        def fail_once(root, name, content):  # 第二个文件仅失败一次。
            attempts.append(name)  # 记录次序。
            if len(attempts) == 2:  # 模拟磁盘写入失败。
                raise OSError('simulated')  # 不涉及用户磁盘配置。
            return actual(root, name, content)  # 第一项及恢复真实写临时目录。
        with patch.object(routing, 'atomic_write', side_effect=fail_once):  # 注入边界故障。
            with self.assertRaisesRegex(routing.RoutingError, 'FailedRestored'):  # 必须恢复第一项。
                routing.transact(result['id'], lifecycle_factory=FakeLifecycle)  # 不进入真实生效查询。
        self.assertEqual((self.root / 'verge.yaml').read_bytes(), self.verge)  # 原字节已恢复。
        self.assertEqual((self.root / 'profiles/Script.js').read_bytes(), self.script)  # 未写第二项保持原样。

    def test_failed_effect_rolls_back_after_normal_stop(self):  # 生效检查失败不能报告应用成功。
        result = routing.preview(self.snapshot)  # 临时计划。
        with patch.object(routing, 'clients', return_value=[self.snapshot['client']]):  # 模拟重启后的唯一客户端。
            with self.assertRaisesRegex(routing.RoutingError, 'FailedRestored'):  # 第二次正常退出后恢复。
                routing.transact(result['id'], lifecycle_factory=FakeLifecycle, validator=lambda plan: False, validation_timeout=0)  # 不等待二十秒。
        self.assertEqual((self.root / 'verge.yaml').read_bytes(), self.verge)  # 原配置恢复。
        self.assertEqual((self.root / 'profiles/Script.js').read_bytes(), self.script)  # 原脚本恢复。

class TransferCancellationTests(unittest.TestCase):  # 检查协作取消和密码边界。
    def tearDown(self):  # 不污染其他测试的全局上下文。
        context.cancelled.clear()  # 下一个工作进程本来会重建模块。
        context.notify = lambda event: None  # 不留事件接收器。

    def test_download_cancel_before_write(self):  # 取消后不再把字节写入临时文件。
        target = io.BytesIO()  # 内存数据。
        context.cancelled.set()  # 模拟父进程取消命令。
        with self.assertRaises(context.Cancelled):  # 必须立即停止。
            context.Output(target).write(b'not-written')  # 不连接SFTP。
        self.assertEqual(target.getvalue(), b'')  # 没有新增数据。

    def test_batch_cancel_does_not_start_next_file(self):  # 不把未执行项目列为成功。
        context.cancelled.set()  # 取消发生在下一项之前。
        self.assertEqual(nscc_download.execute_plan(None, [{'kind': 'file'}], ''), [])  # 不访问模拟远端。
        self.assertEqual(nscc_upload.execute_plan(None, [{'kind': 'file'}]), [])  # 不产生上传临时文件。

    def test_missing_username_fails_before_password(self):  # 不能回退开发者账号。
        for core in (nscc_download, nscc_upload):  # 双方向一致。
            with patch.object(core.getpass, 'getpass') as prompt:  # 不实际询问密码。
                with self.assertRaises(ValueError):  # 参数不完整先失败。
                    core.run({})  # 无来源和账号，不认证。
                prompt.assert_not_called()  # 没有隐藏认证副作用。

class WorkerTests(unittest.TestCase):  # 使用实际独立工作入口。
    def run_worker(self, request):  # 口令只走测试stdin。
        result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'worker_entry.py')], input=json.dumps(request).encode() + b'\n', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)  # 无环境口令和网络任务。
        self.assertEqual(result.returncode, 0)  # 业务错误用固定JSON返回。
        return json.loads(result.stdout), result.stderr  # 测试不回显完整请求。

    def test_unknown_task_and_credential_are_not_echoed(self):  # 错误协议也不能泄漏。
        value = ''.join(('not-real', '-private-value'))  # 合成不可用测试口令。
        result, errors = self.run_worker({'task': 'not-a-task', 'payload': {}, 'auth': {'password': value}})  # 触发认证字段拒绝。
        self.assertFalse(result['ok'])  # 不执行未知任务。
        self.assertNotIn(value, json.dumps(result))  # JSON不回显。
        self.assertNotIn(value.encode(), errors)  # stderr也不回显。

    def test_live_missing_vpn_never_connects(self):  # 无身份的正式请求在连接前失败。
        with patch.object(live_request, 'route_matches', return_value=False), patch.object(live_request.urllib3, 'HTTPSConnectionPool') as pool:  # 无实际HTTPS。
            result = live_request.perform(None)  # 活跃入口。
            self.assertEqual(result['error'], 'VPN_ROUTE_INVALID')  # 固定错误。
            pool.assert_not_called()  # 未创建连接。

    def test_simulation_cannot_claim_real_success(self):  # 显式模拟结果不会通过真实模式验收。
        result, unused = self.run_worker({'task': 'keepalive', 'payload': {'mode': 'success'}})  # 纯离线模式。
        self.assertTrue(result['ok'])  # 模拟成功。
        self.assertEqual(result['mode'], 'simulation')  # 不能冒充live。
        self.assertNotIn('tls_verified', result)  # 没有伪造证书证据。

    def test_route_guid_survives_alias_change(self):  # 不绑定固定网卡名或索引。
        guid = '00000000-0000-0000-0000-000000000007'  # 合成稳定身份。
        with patch.object(network, 'best_interface', return_value={'guid': guid, 'up': True, 'alias': '重命名VPN', 'index': 80}):  # 本地模拟路由。
            self.assertTrue(network.route_matches(guid))  # 别名改变仍能识别。
            self.assertFalse(network.route_matches('00000000-0000-0000-0000-000000000008'))  # 其他接口不能冒充。

    def test_optional_clash_failure_does_not_hide_vpn(self):  # 单独SFTP或保活不要求Clash配置可读。
        from zzu_nscc_helper import worker  # 实际任务分发。
        with patch.object(routing, 'detect', side_effect=PermissionError()), patch.object(worker, 'detect_vpn', return_value={'connected': True, 'guid': '00000000-0000-0000-0000-000000000009'}):  # 合成VPN身份，无网络。
            result = worker.dispatch('detect', {})  # 走真实降级路径。
        self.assertTrue(result['environment']['vpn']['connected'])  # 独立VPN结果仍可用。
        self.assertFalse(result['environment']['writable'])  # 分流仍禁止修改。

class GuiTests(unittest.TestCase):  # 七种组合均只创建选中组件。
    @classmethod  # 单一Qt应用。
    def setUpClass(cls):  # 不进入真实任务。
        from PyQt5.QtWidgets import QApplication  # 本机已安装PyQt5。
        cls.app = QApplication.instance() or QApplication([])  # 共用事件分发。

    def test_component_combinations_have_no_network_or_registration(self):  # 无扩展也能使用传输/分流界面。
        from zzu_nscc_helper.gui import MainWindow  # 活跃统一界面。
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'LOCALAPPDATA': folder}):  # 日志也留在临时目录。
            for count in (1, 2, 3):  # 所有非空选择。
                for chosen in itertools.combinations(COMPONENTS, count):  # 共七种。
                    window = MainWindow(chosen, preview=True)  # 禁止联网和注册表。
                    try:  # 即使断言失败也清理窗口。
                        self.assertEqual(window.tabs.count(), count)  # 未选择模块不显示。
                        self.assertFalse(window.network_busy())  # 没有后台任务。
                        if window.keepalive:  # 预览不抢占真实浏览器通道。
                            self.assertIsNone(window.keepalive.bridge)  # 不创建生产管道。
                        if window.transfer:  # 用户账号必须初始空白。
                            self.assertEqual(window.transfer.username.text(), '')  # 无个人账户默认值。
                            self.assertFalse(window.transfer.start_button.isEnabled())  # 预览不能认证。
                    finally:  # 所有测试控件结束。
                        window.cleanup()  # 清理托盘和计时器。
                        window.deleteLater()  # 释放Qt对象。
                        self.app.processEvents()  # 完成延迟销毁。

    def test_private_worker_finishes_and_cleans_process(self):  # 实际Qt匿名管道和进程退出。
        from zzu_nscc_helper.processes import WorkerTask  # 实际控制器。
        task, results = WorkerTask(), []  # 单次测试任务。
        task.completed.connect(results.append)  # 捕获固定终态。
        task.start('not-a-task', {})  # 无实际网络请求。
        end = time.monotonic() + 10  # 有界等待。
        while task.busy and time.monotonic() < end:  # 分发进程信号。
            self.app.processEvents()  # 不阻塞Qt。
            time.sleep(0.01)  # 避免忙等。
        self.assertFalse(task.busy)  # 子进程已退出。
        self.assertEqual(len(results), 1)  # 只返回一次终态。
        self.assertFalse(results[0]['ok'])  # 未知任务不能成功。

def load_tests(loader, tests, pattern):  # 新增场景与已有35项传输场景一起测融合实现。
    tests.addTests(loader.loadTestsFromModule(DOWNLOAD_TESTS))  # 实际融合下载核心。
    tests.addTests(loader.loadTestsFromModule(UPLOAD_TESTS))  # 实际融合上传核心。
    return tests  # 返回完整离线测试集。
