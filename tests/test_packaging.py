"""安装迁移和发布载荷边界的离线故障测试，不改真实注册表。"""  # 临时目录及内存注册夹具。
import importlib.util  # 加载构建工具而不启动构建。
import json  # 校验实际清单。
import os  # 隔离私有数据目录。
from pathlib import Path  # 全部写入临时目录。
import sys  # 导入活跃源码。
import tempfile  # 独立测试材料。
import unittest  # 现有标准库测试框架。
from unittest.mock import patch  # 不访问真实注册表或生产进程。
import yaml  # 工作流必须先通过语法检查。
ROOT = Path(__file__).resolve().parents[1]  # 独立仓库。
sys.path.insert(0, str(ROOT / 'src'))  # 不安装包。
sys.path.insert(0, str(ROOT / 'scripts'))  # 导入资产审核模块。
from zzu_nscc_helper import installation  # 活跃安装迁移逻辑。

class InstallationTests(unittest.TestCase):  # 迁移必须可重入且不能覆盖外部修改。
    def test_workflow_is_valid_yaml(self):  # 防止命令参数中的冒号让云构建根本无法启动。
        workflow = yaml.load((ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)  # 只解析配置，不执行动作。
        self.assertIn('push', workflow['on'])  # 推送能触发候选构建。
        self.assertTrue(workflow['jobs']['build']['steps'])  # 有实际构建步骤。
    def setUp(self):  # 每个测试独立安装与数据树。
        self.temp = tempfile.TemporaryDirectory()  # 不使用用户AppData。
        self.addCleanup(self.temp.cleanup)  # 测试后只清理本次目录。
        self.root = Path(self.temp.name) / 'program'  # 模拟程序目录。
        self.data = Path(self.temp.name) / 'data'  # 模拟私有迁移目录。
        self.root.mkdir()  # 创建实际安装根。
        self.current = None  # 内存模拟未注册的初始状态。
        def write(value):  # 无注册表写入。
            self.current = value  # 独立保存本产品当前注册。
        for patcher in (patch.object(installation, 'data_root', return_value=self.data), patch.object(installation, 'registration', side_effect=lambda: self.current), patch.object(installation, 'write_registration', side_effect=write)):  # 完全隔离系统副作用。
            patcher.start()  # 仅此测试进程有效。
            self.addCleanup(patcher.stop)  # 恢复真实对象。
        for relative in ('keepalive/tab_app.py', 'keepalive/native_host.exe', 'routing.py', 'transfer/nscc_download.py'):  # 仅模拟存在性，不执行这些材料。
            target = self.root / 'modules/zzu_nscc_helper' / relative  # 固定组件布局。
            target.parent.mkdir(parents=True, exist_ok=True)  # 不使用链接。
            target.write_bytes(b'fixture')  # 非可执行模拟内容。

    def test_no_browser_registration_for_sftp_only(self):  # 独立传输无需Edge。
        result = installation.configure(self.root, ['sftp'])  # 真实配置逻辑。
        self.assertTrue(result['ok'])  # 非保活安装成功。
        self.assertIsNone(self.current)  # 未改注册。
        self.assertFalse(self.data.exists())  # 不生成不需要的连接备份。
        self.assertEqual(json.loads((self.root / 'components.json').read_text()), {'schema': 1, 'components': ['sftp']})  # 不默认全装。

    def test_first_install_upgrade_and_uninstall_restore_absent_registration(self):  # 三次维护保持同一原状态。
        installation.configure(self.root, ['keepalive'])  # 首次备份原本未注册状态。
        backup = (self.data / 'native-migration.json').read_bytes()  # 只读私有备份快照。
        installation.configure(self.root, ['keepalive', 'sftp'])  # 升级添加传输。
        self.assertEqual((self.data / 'native-migration.json').read_bytes(), backup)  # 不覆盖首次备份。
        self.assertTrue(installation.unregister(self.root)['ok'])  # 只撤销自己的连接。
        self.assertIsNone(self.current)  # 恢复无注册状态。
        self.assertFalse((self.data / 'native-host.json').exists())  # 本产品连接文件已清理。

    def test_restore_known_legacy_registration(self):  # 旧助手原文件保留。
        old = Path(self.temp.name) / 'old-native.json'  # 仅本次测试的旧清单。
        old.write_text(json.dumps({'name': 'cn.zzdx.vpn_tabs', 'description': 'SSL VPN assistant local tab bridge', 'path': str(old.with_name('native_host.exe')), 'allowed_origins': [installation.ORIGIN]}), encoding='utf-8')  # 无个人信息。
        before = old.read_bytes()  # 原清单不可被覆盖。
        self.current = str(old)  # 模拟旧注册。
        installation.configure(self.root, ['keepalive'])  # 升级迁移。
        self.assertTrue(installation.unregister(self.root)['ok'])  # 卸载还原。
        self.assertEqual(self.current, str(old))  # 还原原连接目标。
        self.assertEqual(old.read_bytes(), before)  # 不写旧安装目录。

    def test_changed_registration_is_preserved(self):  # 人工改动不被卸载覆盖。
        installation.configure(self.root, ['keepalive'])  # 正常安装。
        self.current = 'another-local-install'  # 模拟后续修改，不是实际路径。
        result = installation.unregister(self.root)  # 尝试撤销旧安装。
        self.assertFalse(result['ok'])  # 明确冲突。
        self.assertEqual(self.current, 'another-local-install')  # 保留新状态。
        self.assertTrue((self.data / 'native-migration.json').is_file())  # 保留原备份供核对。

    def test_unknown_old_host_is_not_overwritten(self):  # 不以相同键名猜测迁移权。
        old = Path(self.temp.name) / 'foreign.json'  # 合成其他主机。
        old.write_text(json.dumps({'name': 'foreign', 'description': 'other', 'allowed_origins': []}), encoding='utf-8')  # 无真实注册。
        self.current = str(old)  # 模拟冲突。
        with self.assertRaisesRegex(ValueError, 'CONFLICT'):  # 写入前拒绝。
            installation.configure(self.root, ['keepalive'])  # 不能覆盖。
        self.assertEqual(self.current, str(old))  # 原注册保留。
        self.assertFalse((self.root / 'components.json').exists())  # 不报告安装成功。

    def test_manifest_write_failure_restores_registration(self):  # 后置安装失败不留下半迁移。
        original = installation.atomic_json  # 包装真实原子写入。
        def fail(path, value):  # 只让组件清单写入失败。
            if path.name == 'components.json':  # 模拟磁盘错误。
                raise OSError('synthetic disk failure')  # 无私人内容。
            return original(path, value)  # 其他仍真实写入临时目录。
        with patch.object(installation, 'atomic_json', side_effect=fail), self.assertRaises(OSError):  # 必须如实失败。
            installation.configure(self.root, ['keepalive'])  # 已注册后组件提交出错。
        self.assertIsNone(self.current)  # 注册已恢复。
        self.assertFalse((self.data / 'native-host.json').exists())  # 没有悬空清单。
        installation.configure(self.root, ['keepalive'])  # 保留的备份允许安全重入。
        self.assertTrue(installation.unregister(self.root)['ok'])  # 重入后仍能撤销。

    def test_atomic_conflict_does_not_delete_other_file(self):  # 临时文件也不能误删。
        target = self.root / 'components.json'  # 测试目标。
        other = target.with_name(target.name + '.new')  # 模拟上次任务或其他进程文件。
        other.write_bytes(b'keep')  # 必须保留。
        with self.assertRaisesRegex(ValueError, 'CONFLICT'):  # 排他冲突应拒绝。
            installation.atomic_json(target, {'schema': 1})  # 不覆盖或删除。
        self.assertEqual(other.read_bytes(), b'keep')  # 原内容仍在。

if __name__ == '__main__':  # 导入不执行安装。
    unittest.main()  # 离线测试入口。
