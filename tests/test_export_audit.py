"""检查真实公开审核器能够拦住凭据、私钥和个人安装路径。"""  # 所有输入仅在内存中构造。
import importlib.util  # 加载实际审核器。
from pathlib import Path  # 定位本仓库脚本。
import unittest  # 标准库测试。
import subprocess  # 临时Git仓库验证暂存与历史检查。
import tempfile  # 不改实际发布历史。
PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_public_tree.py'  # 不运行另一个工作区脚本。
SPEC = importlib.util.spec_from_file_location('public_export_audit', PATH)  # 唯一测试模块名。
AUDIT = importlib.util.module_from_spec(SPEC)  # 创建模块对象。
SPEC.loader.exec_module(AUDIT)  # 只加载函数，不执行Git命令。

class ExportAuditTests(unittest.TestCase):  # 检查发布拦截的实际风险边界。
    def test_blocks_private_key(self):  # 不将一份私钥误当普通源码。
        value = '-----BEGIN ' + 'OPENSSH PRIVATE KEY-----'  # 合成标记，不包含实际私钥。
        self.assertIn('PRIVATE_KEY', AUDIT.violations('sample.txt', value))  # 必须拦截。

    def test_blocks_token_without_echo(self):  # 报告不能再次泄漏匹配到的值。
        value = 'gh' + 'p_' + 'A' * 32  # 合成不可用的令牌形式。
        result = AUDIT.violations('sample.txt', value)  # 实际审核函数。
        self.assertEqual(result, ['GITHUB_TOKEN'])  # 仅报告类别，不输出原值。

    def test_blocks_personal_install_path(self):  # 安装路径不能要求另一个用户有相同用户名。
        value = 'C:' + '\\Users\\' + 'sample-account\\app.py'  # 合成路径，不是真实个人目录。
        self.assertIn('PERSONAL_ABSOLUTE_PATH', AUDIT.violations('sample.txt', value))  # 必须发现本机绑定。

    def test_blocks_session_url_without_echo(self):  # 浏览器会话参数不得随本次兼容修复公开。
        value = 'https://172.99.2.7/ac/console3/index.html;jsessionid=' + 'A' * 32 + '#/e-file'  # 仅在内存生成不可用测试标识，不使用真实会话。
        self.assertEqual(AUDIT.violations('sample.md', value), ['URL_SESSION'])  # 只返回错误类别，不泄漏网址或标识。

    def test_blocks_fixed_account(self):  # 固定用户名不能重新混入公开后端。
        self.assertIn('HARDCODED_CREDENTIAL', AUDIT.violations('sample.py', 'USER = "sample-account"'))  # AST检查实际字面量。

    def test_accepts_public_host_key(self):  # 公钥与私钥必须分清。
        root = Path(__file__).resolve().parents[1]  # 仅读取允许公开的平台资源。
        text = (root / 'src' / 'zzu_nscc_helper' / 'data' / 'known_hosts').read_text(encoding='ascii')  # 公开ED25519主机密钥。
        self.assertEqual(AUDIT.violations('known_hosts', text), [])  # 不能错误阻止公开身份资源。

    def test_inventory_cannot_escape_repository(self):  # 清单本身不能授权读取仓库外文件。
        root = Path(__file__).resolve().parents[1]  # 当前实际仓库边界。
        with self.assertRaises(ValueError):  # 即使目标尚不存在也必须拒绝越界。
            AUDIT.inside(root, '../outside.txt')  # 不创建或读取该文件。

    def test_json_config_credentials_blocked(self):  # 账户不能混进JSON资源。
        import json  # 只构造内存测试值。
        result = AUDIT.violations('sample.json', json.dumps({'auth': {'username': ''.join(('sample', '-identity'))}}))  # 合成数据，没有真实账号。
        self.assertIn('CONFIG_CREDENTIAL', result)  # 公共配置必须清理。

    def test_index_and_history_checked_when_worktree_clean(self):  # 删除工作目录凭据不等于Git已清理。
        with tempfile.TemporaryDirectory() as folder:  # 临时独立仓库。
            root = Path(folder)  # 仅在此目录写测试对象。
            def git(*arguments):  # 不设置全局Git身份。
                return subprocess.run(['git', '-C', str(root), *arguments], capture_output=True, check=True)  # 不连接远端。
            git('init', '--initial-branch=main')  # 临时空仓库。
            path = root / 'sample.py'  # 单一允许文件。
            path.write_text('password = ' + repr(''.join(('synthetic', '-value'))) + '\n', encoding='utf-8')  # 合成不可用认证字面量。
            git('add', 'sample.py')  # 敏感形式进入暂存区。
            path.write_text('value = 1\n', encoding='utf-8')  # 工作目录已经清理。
            errors, count = AUDIT.audit_git_objects(root, {'sample.py'})  # 必须检查真实暂存blob。
            self.assertIn('INDEX_HARDCODED_CREDENTIAL', [item['error'] for item in errors])  # 不被干净工作目录误导。
            git('-c', 'user.name=Offline Test', '-c', 'user.email=offline@example.invalid', 'commit', '-m', 'synthetic fixture')  # 仅临时历史。
            git('add', 'sample.py')  # 暂存区现在也干净。
            errors, count = AUDIT.audit_git_objects(root, {'sample.py'})  # 仍须检查旧提交。
            self.assertIn('HISTORY_HARDCODED_CREDENTIAL', [item['error'] for item in errors])  # 防止旧提交泄漏。
            self.assertGreaterEqual(count, 2)  # 实际扫描不同内容对象。
