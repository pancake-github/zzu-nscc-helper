"""下载助手的离线行为测试：所有文件均位于临时目录，不连接超算。"""  # 不读取任何密码或主机信任文件。
from __future__ import annotations  # 支持较旧 Python 的类型注解解析。
import contextlib  # 隐藏被测函数的逐文件进度，保留测试结果。
import hashlib  # 独立生成预期 SHA-256。
import importlib.util  # 从工作区文件导入被测模块。
import io  # 接收进度输出。
import os  # 创建本地目录符号链接，并检查 Windows 无覆盖行为。
from pathlib import Path  # 在临时目录中构造本地路径。
import posixpath  # 模拟 Linux 目录层级。
import stat  # 构造普通文件、目录和链接的类型。
import subprocess  # 在隔离的临时目录中尝试创建不要求管理员权限的 Windows 目录联接。
import sys  # 禁止测试导入时生成生产文件旁的字节码缓存。
import tempfile  # 隔离每个测试的本地写入。
from types import SimpleNamespace  # 提供与 SFTPAttributes 相同的必需属性。
import unittest  # 使用标准库测试框架，不安装依赖。
from unittest import mock  # 模拟发布瞬间的并发创建。

MODULE_PATH = Path(__file__).resolve().parents[1] / 'nscc_download.py'  # 定位唯一被测生产文件。
sys.dont_write_bytecode = True  # 测试只修改明确授权的测试文件及系统临时目录。
SPEC = importlib.util.spec_from_file_location('nscc_download_under_test', MODULE_PATH)  # 构造文件导入描述。
DOWNLOAD = importlib.util.module_from_spec(SPEC)  # 创建独立模块对象。
SPEC.loader.exec_module(DOWNLOAD)  # 导入不会触发 main 或 SSH 连接。


class FakeSFTP:  # 只模拟下载需要的只读接口，任何行为均发生在内存中。
    def __init__(self):  # 为每个测试建立独立的远端树。
        self.nodes = {}  # 保存类型、内容与修改时间。
        self.downloads = []  # 记录真正读取了哪些普通文件。
        self.listings = []  # 记录递归列出了哪些目录。
        self.failures = set()  # 标记传输中途抛出异常的文件。
        self.mutations = {}  # 标记读取结束后需要变化的元数据。

    def directory(self, path):  # 添加显式目录，包括空目录。
        self.nodes[path] = {'mode': stat.S_IFDIR | 0o755, 'data': b'', 'mtime': 100}  # 设置稳定的初始时间。
        return self  # 允许串联构造测试树。

    def file(self, path, data):  # 添加普通文件。
        self.nodes[path] = {'mode': stat.S_IFREG | 0o644, 'data': data, 'mtime': 100}  # 保存独立二进制内容。
        return self  # 允许串联构造测试树。

    def link(self, path):  # 添加不会解析目标的符号链接。
        self.nodes[path] = {'mode': stat.S_IFLNK | 0o777, 'data': b'/outside', 'mtime': 100}  # 链接内容只用于类型识别。
        return self  # 允许串联构造测试树。

    def lstat(self, path):  # 模拟不跟随符号链接的属性查询。
        node = self.nodes[path]  # 不存在路径直接报错，暴露错误枚举。
        return SimpleNamespace(st_mode=node['mode'], st_size=len(node['data']), st_mtime=node['mtime'])  # 返回新的属性快照。

    def listdir_attr(self, path):  # 只返回给定目录的直接子项。
        self.listings.append(path)  # 保留递归行为证据。
        if not stat.S_ISDIR(self.nodes[path]['mode']):  # 链接或普通文件不能被当成目录展开。
            raise AssertionError('测试检测到非目录被递归访问。')  # 防止假实现掩盖错误。
        children = []  # 建立本层目录项。
        for candidate in self.nodes:  # 检查所有内存节点。
            if candidate != path and posixpath.dirname(candidate) == path:  # 仅选直接子项。
                attribute = self.lstat(candidate)  # 复用与 lstat 一致的类型和大小。
                attribute.filename = posixpath.basename(candidate)  # 补充 listdir_attr 的文件名属性。
                children.append(attribute)  # 加入本层结果。
        return children  # 排序由被测代码负责。

    def getfo(self, path, stream):  # 模拟将远端普通文件写入已打开的本地流。
        self.downloads.append(path)  # 记录实际下载行为。
        data = self.nodes[path]['data']  # 读取当前内容。
        if path in self.failures:  # 在写入一部分后模拟连接中断。
            stream.write(data[:max(1, len(data) // 2)])  # 确保产生真实的临时部分文件。
            raise OSError('模拟 SFTP 传输中断')  # 要求生产代码清理自己的 part。
        stream.write(data)  # 普通路径写入全部内容，包括零字节文件。
        if path in self.mutations:  # 模拟传输过程中远端文件被修改。
            self.nodes[path].update(self.mutations[path])  # 更新后续 lstat 可见的属性。
        return len(data)  # 与常见 SFTP getfo 返回值一致。


class DownloadBehaviorTests(unittest.TestCase):  # 测试用户可观察到的文件与状态结果。
    def setUp(self):  # 每个测试使用全新的本地目录。
        self.temporary = tempfile.TemporaryDirectory(prefix='nscc-download-test-')  # 系统临时目录，不触碰实际下载文件。
        self.addCleanup(self.temporary.cleanup)  # 测试完成后只移除本次临时目录。
        self.destination = Path(self.temporary.name) / '分类' / '2026-10-12'  # 模拟任务与日期分类。
        self.sftp = FakeSFTP()  # 为每个用例使用独立假远端。

    def plan(self, paths, expected=''):  # 通过实际生产函数创建计划。
        return DOWNLOAD.make_plan(self.sftp, paths, self.destination, expected)[0]  # 不复制生产映射算法。

    def execute(self, entries, expected=''):  # 运行真实下载逻辑，仅远端接口为内存模拟。
        with contextlib.redirect_stdout(io.StringIO()):  # 避免正常逐项日志淹没 unittest 的失败信息。
            return DOWNLOAD.execute_plan(self.sftp, entries, expected)  # 返回实际逐项状态。

    def assert_no_parts(self):  # 验证没有遗留本次随机临时文件。
        self.assertEqual(list(Path(self.temporary.name).rglob('.nscc-*.part')), [])  # 只检查助手自身命名的临时文件。

    def test_recursive_unicode_spaces_hidden_empty_and_zero(self):  # 检查完整目录结构与边界内容。
        self.sftp.directory('/home/任务 文件夹').directory('/home/任务 文件夹/空目录')  # 建立含空格和中文的任务及空目录。
        self.sftp.directory('/home/任务 文件夹/子目录').file('/home/任务 文件夹/子目录/结果 数据.txt', '氢浓度\n'.encode('utf-8'))  # 建立嵌套中文文件。
        self.sftp.file('/home/任务 文件夹/.hidden', b'hidden').file('/home/任务 文件夹/zero.dat', b'')  # 加入隐藏和零字节文件。
        results = self.execute(self.plan(['/home/任务 文件夹']))  # 下载完整文件夹。
        root = self.destination / '任务 文件夹'  # 顶层原始目录名必须保留。
        self.assertEqual((root / '子目录' / '结果 数据.txt').read_bytes(), '氢浓度\n'.encode('utf-8'))  # 确认内容和中文路径。
        self.assertEqual((root / '.hidden').read_bytes(), b'hidden')  # 隐藏文件不能遗漏。
        self.assertEqual((root / 'zero.dat').stat().st_size, 0)  # 零字节文件必须真正存在。
        self.assertEqual(list((root / '空目录').iterdir()), [])  # 空目录必须保留为空。
        self.assertEqual(sum(item['status'] == 'Downloaded' for item in results), 3)  # 三个普通文件全部下载。
        self.assert_no_parts()  # 成功后不留下部分文件。

    def test_batch_same_basename_keeps_parent_directories(self):  # 不同父目录的同名文件不能互相覆盖。
        self.sftp.file('/home/job/A/result.txt', b'A').file('/home/job/B/result.txt', b'B')  # 使用有意同名但内容不同的来源。
        results = self.execute(self.plan(['/home/job/A/result.txt', '/home/job/B/result.txt']))  # 一次批量选择两个文件。
        self.assertEqual((self.destination / 'A' / 'result.txt').read_bytes(), b'A')  # 保留 A 层级及内容。
        self.assertEqual((self.destination / 'B' / 'result.txt').read_bytes(), b'B')  # 保留 B 层级及内容。
        self.assertEqual([item['status'] for item in results], ['Downloaded', 'Downloaded'])  # 两者均应独立成功。

    def test_overlapping_selection_downloads_child_once(self):  # 文件夹和其中的文件重复选中时只读一次。
        self.sftp.directory('/home/job').file('/home/job/result.txt', b'once')  # 建立最小重叠选择。
        entries = self.plan(['/home/job', '/home/job/result.txt', '/home/job'])  # 重复父目录和子文件。
        self.execute(entries)  # 执行去重后的计划。
        self.assertEqual(self.sftp.downloads, ['/home/job/result.txt'])  # 实际下载只发生一次。
        self.assertEqual(len(entries), 2)  # 计划仅包含一个目录及一个文件。

    def test_existing_file_is_untouched_and_missing_file_is_added(self):  # 合并目录时必须原样保留已有内容。
        self.sftp.directory('/home/job').file('/home/job/existing.txt', b'remote different').file('/home/job/new.txt', b'new')  # 远端已有项故意不同。
        existing = self.destination / 'job' / 'existing.txt'  # 定位本地已存在的目标。
        existing.parent.mkdir(parents=True)  # 预先建立本地目录。
        existing.write_bytes(b'local precious')  # 放入不可覆盖的现有内容。
        os.utime(existing, ns=(1_000_000_000_000, 2_000_000_000_000))  # 固定修改时间以验证未重写。
        before = existing.stat()  # 记录文件状态。
        results = self.execute(self.plan(['/home/job']))  # 进行目录合并下载。
        self.assertEqual(existing.read_bytes(), b'local precious')  # 已有字节完全不变。
        self.assertEqual(existing.stat().st_mtime_ns, before.st_mtime_ns)  # 修改时间也不变。
        self.assertEqual((existing.parent / 'new.txt').read_bytes(), b'new')  # 缺失项仍正常下载。
        self.assertIn('SkippedExistingUnverified', [item['status'] for item in results])  # 跳过不能宣称已校验一致。
        self.assertEqual(self.sftp.downloads, ['/home/job/new.txt'])  # 已有目标不会从远端重复读取。

    def test_existing_expected_hash_mismatch_preserves_content(self):  # 明确哈希不一致时必须失败且不覆盖。
        self.sftp.file('/home/check.txt', b'remote')  # 定义单个远端源。
        self.destination.mkdir(parents=True)  # 建立本地分类目录。
        target = self.destination / 'check.txt'  # 单文件兼容旧版平面布局。
        target.write_bytes(b'local')  # 放入与预期不同的已有文件。
        expected = hashlib.sha256(b'remote').hexdigest().upper()  # 独立生成远端预期哈希。
        results = self.execute(self.plan(['/home/check.txt'], expected), expected)  # 执行带基准的下载。
        self.assertEqual(results[0]['status'], 'Failed')  # 不一致不能报告成功或已验证。
        self.assertEqual(target.read_bytes(), b'local')  # 仍保留原始本地内容。
        self.assertEqual(self.sftp.downloads, [])  # 不需要为已知冲突传输文件。

    def test_existing_matching_hash_is_verified_without_download(self):  # 验证已有正确文件可安全复用。
        self.sftp.file('/home/check.txt', b'same')  # 定义一个已知内容的源。
        self.destination.mkdir(parents=True)  # 建立目标目录。
        (self.destination / 'check.txt').write_bytes(b'same')  # 预置相同本地内容。
        expected = hashlib.sha256(b'same').hexdigest().upper()  # 独立计算校验基准。
        result = self.execute(self.plan(['/home/check.txt'], expected), expected)[0]  # 进行带基准的重复下载。
        self.assertEqual(result['status'], 'AlreadyVerified')  # 必须明确为已验证已有文件。
        self.assertTrue(result['verified_against_expected_hash'])  # 校验标志必须对应实际基准。
        self.assertEqual(self.sftp.downloads, [])  # 不浪费网络重复下载。

    def test_interruption_cleans_own_part_and_keeps_other_success(self):  # 单个中断不能删除其他已完成文件。
        self.sftp.directory('/home/job').file('/home/job/a-good.txt', b'good').file('/home/job/b-broken.txt', b'broken data')  # 确保成功文件先执行。
        self.sftp.failures.add('/home/job/b-broken.txt')  # 让第二个文件传输到一半失败。
        folder = self.destination / 'job'  # 准备分类目标目录。
        folder.mkdir(parents=True)  # 建立已有目录。
        unrelated = folder / 'other-download.part'  # 模拟其他程序的部分下载。
        unrelated.write_bytes(b'do not delete')  # 这不是本次助手创建的文件。
        results = self.execute(self.plan(['/home/job']))  # 在同一计划中发生成功和中断。
        self.assertEqual((folder / 'a-good.txt').read_bytes(), b'good')  # 已成功文件必须保留。
        self.assertFalse((folder / 'b-broken.txt').exists())  # 中断内容不能发布为正式文件。
        self.assertEqual(unrelated.read_bytes(), b'do not delete')  # 不能清理其他程序的 part。
        self.assertEqual(sum(item['status'] == 'Failed' for item in results), 1)  # 结果明确记录局部失败。
        self.assert_no_parts()  # 本次随机部分文件必须清理。

    def test_remote_symlink_is_reported_and_never_followed(self):  # 链接跳过需可见，不能下载链接目标。
        self.sftp.directory('/home/job').link('/home/job/external').file('/home/job/normal.txt', b'ok')  # 同时设置链接与普通文件。
        self.sftp.file('/outside/secret.txt', b'not selected')  # 未授权范围内的节点不得读取。
        results = self.execute(self.plan(['/home/job']))  # 递归下载选定目录。
        linked = next(item for item in results if item['remote'].endswith('/external'))  # 查找链接项状态。
        self.assertEqual(linked['status'], 'SkippedUnsupported')  # 必须记录跳过。
        self.assertFalse((self.destination / 'job' / 'external').exists())  # 不创建本地链接或伪造普通文件。
        self.assertEqual(self.sftp.listings, ['/home/job'])  # 不递归进入链接。
        self.assertEqual(self.sftp.downloads, ['/home/job/normal.txt'])  # 只读取授权普通文件。

    def test_explicit_case_collision_is_rejected_before_writes(self):  # Linux 大小写不同文件在 Windows 下不能映射同一位置。
        self.sftp.directory('/home/job').file('/home/job/A.txt', b'A').file('/home/job/a.txt', b'a')  # 制造直接同名冲突。
        with self.assertRaisesRegex(ValueError, '大小写'):  # 预检必须清楚报告冲突。
            self.plan(['/home/job'])  # 不进入执行阶段。
        self.assertFalse(self.destination.exists())  # 冲突时不能先写入部分内容。

    def test_implicit_parent_case_collision_is_rejected_before_writes(self):  # 批量选择叶子文件时也不能静默合并大小写不同的父目录。
        self.sftp.file('/home/a/x.txt', b'x').file('/home/A/y.txt', b'y')  # 两个目录未被显式枚举，但仍代表不同来源。
        with self.assertRaisesRegex(ValueError, '大小写'):  # 不能只检查完整叶子路径是否相同。
            self.plan(['/home/a/x.txt', '/home/A/y.txt'])  # 使用隐式父目录构造映射。
        self.assertFalse(self.destination.exists())  # 全部预检应发生在任何写入之前。

    def test_remote_change_before_transfer_is_rejected(self):  # 枚举后来源发生变化应停止该文件。
        self.sftp.file('/home/changing.txt', b'old')  # 建立初始稳定文件。
        entries = self.plan(['/home/changing.txt'])  # 固定初始元数据。
        self.sftp.nodes['/home/changing.txt']['mtime'] += 1  # 模拟下载前被修改。
        results = self.execute(entries)  # 使用先前计划执行。
        self.assertEqual(results[0]['status'], 'Failed')  # 不下载身份已变化的源。
        self.assertEqual(self.sftp.downloads, [])  # 校验发生在实际读取之前。
        self.assertFalse((self.destination / 'changing.txt').exists())  # 不能产生正式文件。

    def test_remote_size_or_mtime_change_during_transfer_is_rejected(self):  # 分别验证大小和修改时间变化。
        for change in ({'mtime': 101}, {'data': b'new and longer'}):  # 两种变化分别独立覆盖。
            with self.subTest(change=change):  # 失败时显示具体变化类型。
                self.sftp = FakeSFTP().file('/home/changing.txt', b'original')  # 每轮重建同一个稳定来源。
                self.sftp.mutations['/home/changing.txt'] = change  # 读取结束时改变元数据。
                results = self.execute(self.plan(['/home/changing.txt']))  # 执行真实临时下载与发布逻辑。
                self.assertEqual(results[0]['status'], 'Failed')  # 变化后必须报告失败。
                self.assertFalse((self.destination / 'changing.txt').exists())  # 不能发布不稳定内容。
                self.assert_no_parts()  # 即使完整读取也需清理临时文件。

    def test_downloaded_expected_hash_mismatch_is_not_published(self):  # 大小一致但内容不符合已知哈希也不能发布。
        self.sftp.file('/home/check.txt', b'wrong')  # 使用稳定但内容错误的来源。
        expected = hashlib.sha256(b'right').hexdigest().upper()  # 基准来自独立的正确内容。
        results = self.execute(self.plan(['/home/check.txt'], expected), expected)  # 经过下载后执行真实哈希校验。
        self.assertEqual(results[0]['status'], 'Failed')  # 错误内容不能称为成功。
        self.assertFalse((self.destination / 'check.txt').exists())  # 正式目标仍不存在。
        self.assert_no_parts()  # 清理校验不通过的临时内容。

    @unittest.skipUnless(os.name == 'nt', '此用例验证 Windows 的 rename 拒绝覆盖语义。')  # 不在 POSIX 上模拟不同的发布保证。
    def test_concurrent_target_creation_is_never_overwritten(self):  # 预检之后其他程序创建同名文件也必须保留。
        self.sftp.file('/home/check.txt', b'remote')  # 准备待发布内容。
        original_rename = os.rename  # 保留真实 Windows 无覆盖操作。
        def create_then_rename(source, target):  # 在发布瞬间模拟其他程序抢先创建。
            Path(target).write_bytes(b'concurrent local')  # 写入并发产生的宝贵内容。
            return original_rename(source, target)  # 实际 Windows 调用应抛出 FileExistsError。
        with mock.patch.object(DOWNLOAD.os, 'rename', side_effect=create_then_rename):  # 仅改变发生竞态的时机。
            results = self.execute(self.plan(['/home/check.txt']))  # 经过完整下载、校验与发布尝试。
        self.assertEqual(results[0]['status'], 'SkippedExistingUnverified')  # 明确记录被并发目标阻止。
        self.assertEqual((self.destination / 'check.txt').read_bytes(), b'concurrent local')  # 并发文件不被替换。
        self.assert_no_parts()  # 自己未发布的文件应清理。

    def test_local_directory_symlink_is_rejected_when_available(self):  # 环境允许创建链接时检查禁止越界写入。
        outside = Path(self.temporary.name) / 'outside'  # 仍位于同一个临时目录，避免影响真实位置。
        outside.mkdir()  # 创建链接目标目录。
        self.destination.mkdir(parents=True)  # 创建任务目录。
        linked = self.destination / 'job'  # 将下载文件夹位置变为链接。
        try:  # 普通 Windows 用户可能没有创建符号链接的权限。
            os.symlink(outside, linked, target_is_directory=True)  # 不使用管理员权限或更改系统设置。
        except (OSError, NotImplementedError) as error:  # 不可用时准确标记测试跳过。
            self.skipTest(f'本机不能创建目录符号链接：{error}')  # 不把未执行的检查称为通过。
        self.sftp.directory('/home/job').file('/home/job/check.txt', b'must not write')  # 设置会经过链接的源。
        with self.assertRaisesRegex(ValueError, '链接|重解析'):  # 预检必须识别链接祖先。
            self.plan(['/home/job'])  # 不进入实际下载。
        self.assertEqual(list(outside.iterdir()), [])  # 链接目标中没有产生任何文件。

    @unittest.skipUnless(os.name == 'nt', '目录联接是 Windows 特性。')  # 在 Windows 上补充真实重解析点验证。
    def test_local_directory_junction_is_rejected_when_available(self):  # 普通用户通常可以创建目录联接，补充符号链接权限不足的情况。
        outside = Path(self.temporary.name) / 'junction-target'  # 联接目标仍严格限制在本测试临时目录。
        outside.mkdir()  # 创建没有任何用户文件的空目标。
        self.destination.mkdir(parents=True)  # 创建分类目录。
        linked = self.destination / 'job'  # 把选定任务的本地路径变为联接。
        outcome = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(linked), str(outside)], capture_output=True, timeout=10)  # 参数均由 tempfile 派生，无外部输入。
        if outcome.returncode != 0:  # 若该机器禁止联接，准确记录未能执行。
            self.skipTest(f'本机不能创建目录联接，返回码：{outcome.returncode}')  # 不请求提升权限。
        try:  # 确保无论断言结果如何都只删除联接自身。
            self.sftp.directory('/home/job').file('/home/job/check.txt', b'must not write')  # 创建会经过联接的下载计划。
            with self.assertRaisesRegex(ValueError, '链接|重解析'):  # 应在下载前识别 Windows 重解析点。
                self.plan(['/home/job'])  # 不连接网络或写入目标内容。
            self.assertEqual(list(outside.iterdir()), [])  # 联接目标必须保持空目录。
        finally:  # 不递归进入或删除联接目标。
            os.rmdir(linked)  # 对已知临时路径的目录联接只移除联接本身。


if __name__ == '__main__':  # 仅作为脚本运行时启动测试。
    unittest.main(verbosity=2)  # 显示每个行为用例的真实通过、失败或跳过状态。
