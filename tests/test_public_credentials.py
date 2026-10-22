"""公开后端不得在缺少本人用户名时进入认证流程。"""  # 仅测试公开副本，不触碰原工具。
import importlib.util  # 从实际公开副本加载模块。
from pathlib import Path  # 定位导入基线。
import sys  # 处理上传后端的同目录共享导入。
import unittest  # 标准库测试。
from unittest.mock import patch  # 确认隐藏输入不会被调用。
ROOT = Path(__file__).resolve().parents[1] / 'baseline' / 'transfer'  # 只使用新仓库内的公开副本。
sys.path.insert(0, str(ROOT))  # 不修改系统路径或环境变量。

class CredentialBoundaryTests(unittest.TestCase):  # 两个方向都必须明确账号。
    def test_missing_username_stops_before_authentication(self):  # 缺少真实信息不能偷偷借用旧账号。
        for name in ('nscc_download', 'nscc_upload'):  # 上传与下载共享同一边界。
            with self.subTest(module=name):  # 失败时指出方向。
                spec = importlib.util.spec_from_file_location(name + '_public_test', ROOT / (name + '.py'))  # 实际文件导入。
                module = importlib.util.module_from_spec(spec)  # 不运行CLI入口。
                spec.loader.exec_module(module)  # 导入不会建立SSH连接。
                self.assertFalse(hasattr(module, 'USER'))  # 没有开发者固定账号常量。
                with patch('getpass.getpass', side_effect=AssertionError('不应读取密码')):  # 密码输入也应尚未开始。
                    with self.assertRaisesRegex(ValueError, '用户名'):  # 在读取请求其他路径前失败。
                        module.run({})  # 不生成占位用户或目标。
