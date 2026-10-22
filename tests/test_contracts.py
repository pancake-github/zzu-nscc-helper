"""离线验证平台身份、发布资源与组件组合，不连接任何外部服务。"""  # 第一阶段的实际契约测试。
import copy  # 独立变更测试预设，不修改资源文件。
import itertools  # 覆盖所有非空组件组合。
from pathlib import Path  # 直接从源码运行测试。
import sys  # 不需要安装项目到现有环境。
import unittest  # 使用标准库。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))  # 只影响本测试进程。
from zzu_nscc_helper.components import COMPONENTS, download_units, normalize_selection  # 真实安装契约。
from zzu_nscc_helper.platform import load_platform, validate_profile, verify_host_key  # 真实资源校验。

class PlatformTests(unittest.TestCase):  # 防止跨平台、账号或范围污染。
    def test_approved_host_key(self):  # 公钥必须与预设的独立指纹一致。
        profile = load_platform()  # 同时校验所有固定目标。
        self.assertTrue(verify_host_key(profile).is_file())  # 实际打包资源存在。
        self.assertEqual(profile['sftp']['port'], 22)  # 平台端口不随本地代理端口改变。

    def test_reject_personal_account(self):  # 个人账号不得混入共享预设。
        profile = copy.deepcopy(load_platform())  # 使用实际资源作为合法基线。
        profile['sftp']['username'] = 'not-a-published-account'  # 仅内存测试值，不是真实账号。
        with self.assertRaisesRegex(ValueError, '账户'):  # 必须在连接前拒绝。
            validate_profile(profile)  # 不联网。

    def test_reject_broad_tun_exclusion(self):  # 不能从精确网关扩大到整个网段。
        profile = copy.deepcopy(load_platform())  # 不修改文件。
        profile['routing']['tun_exclusions'] = ['172.0.0.0/8']  # 模拟错误规则生成结果。
        with self.assertRaises(ValueError):  # 预设边界必须阻止扩大。
            validate_profile(profile)  # 不调用系统配置。

    def test_reject_other_platform(self):  # 不能宣称支持尚未适配的平台。
        profile = copy.deepcopy(load_platform())  # 保留其他字段合法。
        profile['id'] = 'another-center'  # 模拟错误配置来源。
        with self.assertRaises(ValueError):  # 必须明确失败。
            validate_profile(profile)  # 不做猜测替换。

    def test_reject_modified_https_identity(self):  # 防止固定IP和TLS身份被拆散。
        profile = copy.deepcopy(load_platform())  # 合法基线。
        profile['keepalive']['tls_name'] = 'unapproved.example'  # 仅内存中替换身份。
        with self.assertRaises(ValueError):  # 不允许任意目标。
            validate_profile(profile)  # 不发起TLS连接。

class ComponentTests(unittest.TestCase):  # 下载集合与安装选择必须一致。
    def test_all_seven_nonempty_combinations(self):  # 覆盖三个单项、三个双项与全部。
        for size in (1, 2, 3):  # 穷举合法大小。
            for selection in itertools.combinations(COMPONENTS, size):  # 每组选择独立检查。
                with self.subTest(selection=selection):  # 失败时显示具体组合。
                    self.assertEqual(download_units(selection), ('core',) + selection)  # 不混入未选组件。

    def test_deduplicate_and_keep_order(self):  # 重复选择不重复下载运行库或组件。
        self.assertEqual(normalize_selection(['sftp', 'keepalive', 'sftp']), ('keepalive', 'sftp'))  # 稳定顺序。

    def test_reject_empty_unknown_and_string(self):  # 不接受空安装或隐藏模块名。
        for value in ([], ['unknown'], 'sftp'):  # 每类错误都要被拦住。
            with self.subTest(value=value), self.assertRaises(ValueError):  # 精确检查失败。
                download_units(value)  # 不执行下载。
