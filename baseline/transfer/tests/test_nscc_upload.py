"""上传助手的离线行为验收：本地使用临时目录，远端使用内存树。"""  # 不连接网络，不读取凭据或主机信任文件。
from __future__ import annotations  # 兼容现有 Python 的注解解析。
import contextlib  # 隐藏逐文件进度，突出测试失败信息。
import copy  # 独立保存远端已有内容与时间的快照。
import errno  # 模拟 SFTP 真实的不存在、冲突和拒绝访问错误码。
import hashlib  # 独立生成预期的 SHA-256。
import importlib.util  # 从指定生产文件导入被测模块。
import io  # 使用内存流模拟远端文件。
import os  # 固定本地时间及创建临时链接。
from pathlib import Path  # 构造所有本地临时路径。
import posixpath  # 按 Linux 规则构造远端路径。
import stat  # 区分普通文件、目录与符号链接。
import subprocess  # 仅在临时目录中创建 Windows 联接。
import sys  # 禁止在生产文件旁生成字节码缓存。
import tempfile  # 隔离全部本地测试文件。
from types import SimpleNamespace  # 返回与 SFTPAttributes 相容的快照。
import unittest  # 使用标准库测试框架。
from unittest import mock  # 精确模拟 Windows 文件重解析点。

MODULE_PATH = Path(__file__).resolve().parents[1] / 'nscc_upload.py'  # 定位上传生产模块。
sys.dont_write_bytecode = True  # 测试不向生产目录写入缓存。
sys.path.insert(0, str(MODULE_PATH.parent))  # 允许生产上传模块导入同目录的共享下载模块。
SPEC = importlib.util.spec_from_file_location('nscc_upload_under_test', MODULE_PATH)  # 建立独立导入描述。
UPLOAD = importlib.util.module_from_spec(SPEC)  # 创建模块对象。
SPEC.loader.exec_module(UPLOAD)  # 导入函数，不启动 main 或建立 SSH 连接。


class FakeRemoteFile(io.BytesIO):  # 在内存中提供上传和回读所需的文件行为。
    def __init__(self, sftp, path, writing):  # 记录所属远端和当前打开方式。
        self.sftp, self.path, self.writing = sftp, path, writing  # 保留操作上下文。
        super().__init__(b'' if writing else sftp.nodes[path]['data'])  # 写入流初始为空，读取流复制已有内容。

    def write(self, data):  # 在写入边界注入连接中断或来源变化。
        if self.sftp.fail_writes:  # 让传输真正产生部分内容后失败。
            count = super().write(data[:max(1, len(data) // 2)])  # 只写入部分字节。
            self.sftp.nodes[self.path]['data'] = self.getvalue()  # 让部分文件可见。
            raise OSError('模拟上传过程中连接中断')  # 生产代码必须删除自身临时文件。
        count = super().write(data)  # 普通写入完整保存本次块。
        self.sftp.nodes[self.path]['data'] = self.getvalue()  # 同步可观察到的远端字节。
        if self.sftp.on_first_write is not None:  # 模拟本地来源在传输中被其他程序修改。
            callback, self.sftp.on_first_write = self.sftp.on_first_write, None  # 保证只触发一次。
            callback()  # 由用例决定改变本地大小或时间。
        return count  # 与普通文件 write 接口相同。

    def read(self, size=-1):  # 独立模拟回读失败或内容不一致。
        if self.sftp.fail_reads:  # 上传已完成但远端回读失败。
            raise OSError('模拟远端校验回读失败')  # 不能发布未验收的部分文件。
        data = super().read(size)  # 正常读取内存内容。
        if data and self.sftp.corrupt_reads:  # 保留大小但改变内容，避免只比较长度的假校验。
            return bytes([data[0] ^ 1]) + data[1:]  # 每块翻转一个字节。
        return data  # 空流和正常读取保持原样。

    def set_pipelined(self, enabled=True):  # 兼容 Paramiko 的可选上传优化接口。
        return None  # 不改变内存模拟的同步语义。


class FakeSFTP:  # 模拟标准 SFTP 排他创建、回读与不覆盖 rename。
    def __init__(self):  # 每个用例建立全新的远端树。
        self.nodes = {}  # 保存类型、内容和修改时间。
        self.writes, self.reads, self.removed, self.renames = [], [], [], []  # 记录实际写入、读取、清理与发布。
        self.fail_writes = self.fail_reads = self.corrupt_reads = False  # 初始不注入传输或校验故障。
        self.on_first_write = self.before_rename = None  # 初始没有来源变化或并发发布钩子。
        self.directory('/').directory('/home')  # 只预置明确的系统根和主目录。

    def directory(self, path):  # 直接构造测试目录。
        self.nodes[path] = {'mode': stat.S_IFDIR | 0o755, 'data': b'', 'mtime': 100}  # 固定时间便于比较。
        return self  # 允许链式构造场景。

    def file(self, path, data, mtime=100):  # 直接构造已有普通文件。
        self.nodes[path] = {'mode': stat.S_IFREG | 0o644, 'data': data, 'mtime': mtime}  # 保留用户指定的字节与时间。
        return self  # 允许链式构造场景。

    def link(self, path, target='/outside'):  # 直接构造不应跟随的远端符号链接。
        self.nodes[path] = {'mode': stat.S_IFLNK | 0o777, 'data': target.encode('utf-8'), 'mtime': 100}  # 不解析目标。
        return self  # 允许链式构造场景。

    def lstat(self, path):  # 查询路径本身而非链接目标。
        if path not in self.nodes:  # SFTP 缺失文件应带 ENOENT。
            raise FileNotFoundError(errno.ENOENT, '模拟远端路径不存在', path)  # 供生产检查区分其他错误。
        node = self.nodes[path]  # 读取独立节点。
        return SimpleNamespace(st_mode=node['mode'], st_size=len(node['data']), st_mtime=node['mtime'])  # 返回属性快照。

    def mkdir(self, path, mode=0o777):  # 创建一个目录，保留真实父目录约束。
        if path in self.nodes:  # 不允许以 mkdir 覆盖现有节点。
            raise FileExistsError(errno.EEXIST, '模拟远端目标已存在', path)  # 暴露重复创建问题。
        parent = self.lstat(posixpath.dirname(path))  # 父目录必须存在。
        if not stat.S_ISDIR(parent.st_mode):  # 普通文件和链接都不能成为写入父目录。
            raise NotADirectoryError(errno.ENOTDIR, '模拟远端父路径不是目录', path)  # 防止假实现掩盖越界。
        self.directory(path)  # 创建空目录。

    def open(self, path, mode='r', bufsize=-1):  # 只允许只读打开和排他新建。
        if 'x' in mode:  # Paramiko 的 wx 模式必须排他创建。
            if path in self.nodes:  # 现有临时文件也不能被截断。
                raise FileExistsError(errno.EEXIST, '模拟远端文件已存在', path)  # 检查真实无覆盖行为。
            parent = self.lstat(posixpath.dirname(path))  # 临时文件所在目录必须已存在。
            if not stat.S_ISDIR(parent.st_mode):  # 不能通过远端链接写入。
                raise NotADirectoryError(errno.ENOTDIR, '模拟远端父路径不是目录', path)  # 明确拒绝。
            self.file(path, b'')  # 排他创建新的零字节临时文件。
            self.writes.append(path)  # 记录唯一由本次流程创建的对象。
            return FakeRemoteFile(self, path, True)  # 返回写入流。
        if mode not in ('r', 'rb'):  # 禁止生产代码使用覆盖式 w、a 或其他未审查方式。
            raise AssertionError(f'测试发现非排他写入方式：{mode}')  # 防止覆盖被模拟器放行。
        info = self.lstat(path)  # 只读打开必须存在。
        if not stat.S_ISREG(info.st_mode):  # 链接和目录不能被伪装为普通文件读取。
            raise OSError('测试发现尝试读取非普通远端文件')  # 保持链接隔离。
        self.reads.append(path)  # 记录回读校验使用了什么文件。
        return FakeRemoteFile(self, path, False)  # 返回内容快照流。

    def rename(self, source, target):  # 模拟 SSH_FXP_RENAME 的标准不覆盖发布。
        if self.before_rename is not None:  # 在最终发布瞬间制造目标竞态。
            callback, self.before_rename = self.before_rename, None  # 只触发一次。
            callback(source, target)  # 由用例创建需要保护的目标。
        if target in self.nodes:  # 标准 rename 拒绝覆盖已有对象。
            raise FileExistsError(errno.EEXIST, '模拟远端目标已存在', target)  # 不能退化成覆盖式 posix_rename。
        self.lstat(source)  # 被发布的临时文件必须存在。
        self.nodes[target] = self.nodes.pop(source)  # 原子转移内存节点。
        self.renames.append((source, target))  # 记录正式发布证据。

    def remove(self, path):  # 仅删除一个明确的普通文件。
        info = self.lstat(path)  # 不能悄悄忽略不存在路径。
        if not stat.S_ISREG(info.st_mode):  # 不能递归删除目录或链接。
            raise OSError('测试发现试图清理非普通文件')  # 暴露清理范围错误。
        self.removed.append(path)  # 记录实际清理对象。
        del self.nodes[path]  # 删除该明确节点。


class UploadBehaviorTests(unittest.TestCase):  # 验证用户可观察到的目录、内容和状态。
    def setUp(self):  # 每个测试完全隔离本地与远端状态。
        self.temporary = tempfile.TemporaryDirectory(prefix='nscc-upload-test-')  # 不触碰工作区研究文件。
        self.addCleanup(self.temporary.cleanup)  # 测试后仅清理自己的系统临时目录。
        self.source = Path(self.temporary.name) / '本地源'  # 为本地输入建立独立父目录。
        self.source.mkdir()  # 初始化普通目录。
        self.destination = '/home/远端任务 目录'  # 使用真实格式的中文空格目标。
        self.sftp = FakeSFTP()  # 每个用例独立的内存远端。

    def local_file(self, relative, data):  # 在授权临时目录内创建一个来源。
        path = self.source / relative  # 不使用外部现有路径。
        path.parent.mkdir(parents=True, exist_ok=True)  # 保留指定层级。
        path.write_bytes(data)  # 写入专用测试内容。
        return path  # 返回可交给实际生产计划的路径。

    def plan(self, paths):  # 调用真实生产计划构造函数。
        return UPLOAD.make_plan(paths, self.destination)[0]  # 不复制生产映射规则。

    def execute(self, entries):  # 以真实执行逻辑操作内存 SFTP。
        UPLOAD.preflight_remote(self.sftp, entries, self.destination)  # 所有目标先整批只读预检。
        with contextlib.redirect_stdout(io.StringIO()):  # 避免正常进度淹没 unittest 的结果。
            return UPLOAD.execute_plan(self.sftp, entries)  # 返回真实逐项状态。

    def assert_no_parts(self):  # 检查所有助手临时文件均已发布或清理。
        self.assertEqual([path for path in self.sftp.nodes if posixpath.basename(path).startswith('.nscc-') and path.endswith('.part')], [])  # 不把正式内容误认为成功。

    def test_recursive_unicode_spaces_hidden_empty_and_zero(self):  # 完整文件夹上传必须保持所有普通层级。
        folder = self.source / '任务 文件夹'  # 构造包含中文和空格的根目录。
        (folder / '空目录').mkdir(parents=True)  # 添加需要保留的空目录。
        self.local_file('任务 文件夹/子目录/结果 数据.txt', '氢浓度\n'.encode('utf-8'))  # 添加嵌套中文文件。
        self.local_file('任务 文件夹/.hidden', b'hidden')  # 隐藏文件也应被枚举。
        self.local_file('任务 文件夹/zero.dat', b'')  # 添加零字节文件。
        results = self.execute(self.plan([folder]))  # 上传实际完整目录。
        remote = self.destination + '/任务 文件夹'  # 原始目录名必须保留。
        self.assertEqual(self.sftp.nodes[remote + '/子目录/结果 数据.txt']['data'], '氢浓度\n'.encode('utf-8'))  # 内容和层级一致。
        self.assertEqual(self.sftp.nodes[remote + '/.hidden']['data'], b'hidden')  # 隐藏文件没有遗漏。
        self.assertEqual(self.sftp.nodes[remote + '/zero.dat']['data'], b'')  # 零字节文件真正发布。
        self.assertTrue(stat.S_ISDIR(self.sftp.nodes[remote + '/空目录']['mode']))  # 空目录真实存在。
        self.assertEqual(sum(item['status'] == 'UploadedVerified' for item in results), 3)  # 三个普通文件均已完整回读验收上传。
        for result in results:  # 成功状态必须附带实际远端回读证据。
            if result['status'] == 'UploadedVerified':  # 目录不参与内容校验统计。
                expected = hashlib.sha256(self.sftp.nodes[result['remote']]['data']).hexdigest().upper()  # 独立计算正式远端文件内容。
                self.assertEqual(result['sha256'], expected)  # 发送内容校验值必须匹配。
                self.assertEqual(result['remote_sha256'], expected)  # 回读校验值必须匹配。
                self.assertTrue(result['verified_by_sftp_readback'])  # 标志必须明确为已完成回读。
        self.assert_no_parts()  # 成功后不遗留临时文件。

    def test_batch_same_basename_preserves_parent_directories(self):  # 不同父目录中的同名文件应保留各自层级。
        left = self.local_file('A/result.txt', b'A')  # 来源 A 内容。
        right = self.local_file('B/result.txt', b'B')  # 来源 B 故意采用同名文件。
        results = self.execute(self.plan([left, right]))  # 单次批量上传。
        self.assertEqual(self.sftp.nodes[self.destination + '/A/result.txt']['data'], b'A')  # A 没有被摊平覆盖。
        self.assertEqual(self.sftp.nodes[self.destination + '/B/result.txt']['data'], b'B')  # B 保留自己的内容。
        self.assertEqual(sum(item['status'] == 'UploadedVerified' for item in results), 2)  # 两个文件都应完成回读验收。

    def test_overlapping_selection_uploads_each_file_once(self):  # 同时选择目录与子文件不能重复上传。
        child = self.local_file('任务/result.txt', b'once')  # 准备最小重叠源。
        folder = child.parent  # 选定包含子文件的目录。
        entries = self.plan([folder, child, folder])  # 重复目录及其子文件。
        self.execute(entries)  # 使用真实去重后的计划执行。
        self.assertEqual(len(self.sftp.writes), 1)  # 实际临时上传只发生一次。
        self.assertEqual(len(entries), 2)  # 计划只有一个目录和一个文件。

    def test_existing_remote_content_and_mtime_are_untouched(self):  # 合并远端任务时不覆盖已有文件。
        folder = self.source / '任务'  # 设置目录上传场景。
        self.local_file('任务/existing.txt', b'local different')  # 本地同名文件刻意不同。
        self.local_file('任务/new.txt', b'new')  # 新文件仍应上传。
        remote = self.destination + '/任务'  # 保留源目录名。
        self.sftp.directory(self.destination).directory(remote).file(remote + '/existing.txt', b'remote precious', 123456)  # 预置远端已有字节及时间。
        before = copy.deepcopy(self.sftp.nodes[remote + '/existing.txt'])  # 保留原状态。
        results = self.execute(self.plan([folder]))  # 执行目录合并。
        self.assertEqual(self.sftp.nodes[remote + '/existing.txt'], before)  # 字节、时间、类型完全未改。
        self.assertEqual(self.sftp.nodes[remote + '/new.txt']['data'], b'new')  # 缺失项正常补充。
        existing = next(item for item in results if item['remote'].endswith('/existing.txt'))  # 查找跳过记录。
        self.assertEqual(existing['status'], 'SkippedExistingUnverified')  # 同名跳过不能宣称已验证内容相同。
        self.assertEqual(len(self.sftp.writes), 1)  # 不对已有目标重复传输。

    def test_upload_failure_only_removes_own_partial(self):  # 上传中断不得清理其他程序或已有文件。
        source = self.local_file('broken.txt', b'upload failure content')  # 创建会部分写入的来源。
        self.sftp.directory(self.destination).file(self.destination + '/other-upload.part', b'keep other upload', 77)  # 放入需要保护的他人部分文件。
        protected = copy.deepcopy(self.sftp.nodes[self.destination + '/other-upload.part'])  # 记录原字节与时间。
        self.sftp.fail_writes = True  # 在首次写入之后模拟连接中断。
        result = self.execute(self.plan([source]))[0]  # 使用真实异常和清理路径。
        self.assertEqual(result['status'], 'Failed')  # 中断不能报告成功。
        self.assertNotIn(self.destination + '/broken.txt', self.sftp.nodes)  # 部分内容不能正式发布。
        self.assertEqual(self.sftp.nodes[self.destination + '/other-upload.part'], protected)  # 他人文件完整保留。
        self.assertEqual(self.sftp.removed, self.sftp.writes)  # 只删除本次排他创建的临时对象。
        self.assert_no_parts()  # 自己的临时文件已经清理。

    def test_remote_readback_failure_or_corruption_is_not_published(self):  # 回读异常或同大小错误内容都不能发布。
        for setting in ('fail_reads', 'corrupt_reads'):  # 分别覆盖连接中断和哈希不一致。
            with self.subTest(setting=setting):  # 失败时明确指出故障类型。
                self.sftp = FakeSFTP().directory(self.destination)  # 每轮独立远端。
                self.sftp.file(self.destination + '/other-upload.part', b'keep', 88)  # 添加不可清理的他人文件。
                source = self.local_file('checked.txt', b'content requiring independent hash verification')  # 提供稳定的本地来源。
                setattr(self.sftp, setting, True)  # 启用本轮回读故障。
                result = self.execute(self.plan([source]))[0]  # 完整上传后进行真实校验。
                self.assertEqual(result['status'], 'Failed')  # 未完成校验不能认为成功。
                self.assertNotIn(self.destination + '/checked.txt', self.sftp.nodes)  # 正式目标不应存在。
                self.assertEqual(self.sftp.nodes[self.destination + '/other-upload.part']['data'], b'keep')  # 他人临时文件没有修改。
                self.assertEqual(self.sftp.removed, self.sftp.writes)  # 清理范围仅限本次新建的对象。
                self.assert_no_parts()  # 校验失败后没有自己的部分文件。

    def test_concurrent_target_at_rename_is_never_overwritten(self):  # 上传和回读完成后产生同名目标也必须保护。
        source = self.local_file('result.txt', b'uploaded candidate')  # 准备待发布内容。
        self.sftp.before_rename = lambda partial, target: self.sftp.file(target, b'concurrent remote precious', 54321)  # 在最终 rename 前模拟其他人写入。
        result = self.execute(self.plan([source]))[0]  # 经真实完整上传和校验后尝试发布。
        target = self.sftp.nodes[self.destination + '/result.txt']  # 检查并发产生的目标。
        self.assertEqual(target['data'], b'concurrent remote precious')  # 原字节绝不能被替换。
        self.assertEqual(target['mtime'], 54321)  # 原时间也不能改变。
        self.assertIn(result['status'], ('SkippedExistingUnverified', 'Failed'))  # 准确报告未发布，不宣称成功。
        self.assertEqual(self.sftp.renames, [])  # 标准无覆盖 rename 从未成功。
        self.assert_no_parts()  # 本次未发布临时内容应清理。

    def test_remote_symlink_rejects_entire_batch_before_writes(self):  # 任意目标链上的链接应阻止整批执行。
        safe = self.local_file('a-good.txt', b'would be safe')  # 第一项原本可上传。
        blocked = self.local_file('z-linked.txt', b'must not follow')  # 第二项将命中远端链接。
        self.sftp.directory(self.destination).link(self.destination + '/z-linked.txt')  # 直接目标是链接。
        entries = self.plan([safe, blocked])  # 创建包含正常项和危险项的全批计划。
        before = copy.deepcopy(self.sftp.nodes)  # 记录整棵远端树。
        with self.assertRaises((ValueError, OSError)):  # 必须整批预检拒绝。
            UPLOAD.preflight_remote(self.sftp, entries, self.destination)  # 只读检查全部目标。
        self.assertEqual(self.sftp.nodes, before)  # 安全的第一项也不能抢先写入。
        self.assertEqual(self.sftp.writes, [])  # 尚无上传临时文件。

    def test_remote_ancestor_symlink_rejects_before_writes(self):  # 不能只检查远端叶子对象而遗漏父目录链接。
        source = self.local_file('result.txt', b'must not escape')  # 准备普通来源。
        self.sftp.link(self.destination)  # 把目标任务目录本身变成链接。
        entries = self.plan([source])  # 此计划本地完全正常。
        before = copy.deepcopy(self.sftp.nodes)  # 保存危险链的原状态。
        with self.assertRaises((ValueError, OSError)):  # 链接父目录应直接拒绝。
            UPLOAD.preflight_remote(self.sftp, entries, self.destination)  # 执行只读检查。
        self.assertEqual(self.sftp.nodes, before)  # 没有越界修改。
        self.assertEqual(self.sftp.writes, [])  # 没有创建任何临时文件。

    def test_remote_file_directory_conflict_rejects_entire_batch(self):  # 文件和目录互相占位时整批预检失败。
        safe = self.local_file('a-good.txt', b'safe')  # 第一项原本可成功。
        folder = self.source / 'z-folder'  # 第二项需要目录位置。
        folder.mkdir()  # 使用真实空目录。
        self.sftp.directory(self.destination).file(self.destination + '/z-folder', b'remote existing file', 9876)  # 远端位置被文件占用。
        before = copy.deepcopy(self.sftp.nodes)  # 保存内容及时间。
        with self.assertRaises((ValueError, OSError)):  # 不能等第一项写完才发现冲突。
            UPLOAD.preflight_remote(self.sftp, self.plan([safe, folder]), self.destination)  # 一次预检所有项。
        self.assertEqual(self.sftp.nodes, before)  # 原远端树完全保留。
        self.assertEqual(self.sftp.writes, [])  # 没有发生部分上传。

    def test_remote_directory_in_file_slot_rejects_before_writes(self):  # 上传文件的远端目标为目录时同样不能改写。
        source = self.local_file('occupied.txt', b'local file')  # 来源是明确的普通文件。
        self.sftp.directory(self.destination).directory(self.destination + '/occupied.txt')  # 对应远端名称已是目录。
        before = copy.deepcopy(self.sftp.nodes)  # 保存已有目录原状态。
        with self.assertRaises((ValueError, OSError)):  # 文件不能替换目录。
            UPLOAD.preflight_remote(self.sftp, self.plan([source]), self.destination)  # 只读预检。
        self.assertEqual(self.sftp.nodes, before)  # 目录完全原样保留。
        self.assertEqual(self.sftp.writes, [])  # 没有上传临时文件。

    def test_existing_same_random_partial_is_never_truncated_or_removed(self):  # 即使随机名称发生冲突也不能破坏他人临时文件。
        source = self.local_file('result.txt', b'new content')  # 准备普通来源。
        partial = self.destination + '/.nscc-upload-fixed.part'  # 用固定随机号制造可重复的碰撞。
        self.sftp.directory(self.destination).file(partial, b'other session precious', 24680)  # 该对象不是本次流程创建。
        before = copy.deepcopy(self.sftp.nodes[partial])  # 保存需要保护的字节及时间。
        with mock.patch.object(UPLOAD.uuid, 'uuid4', return_value=SimpleNamespace(hex='fixed')):  # 只固定临时文件命名，不改变 SFTP 排他语义。
            result = self.execute(self.plan([source]))[0]  # 排他 open 必须失败。
        self.assertEqual(result['status'], 'Failed')  # 不把临时名称冲突误认为上传成功。
        self.assertEqual(self.sftp.nodes[partial], before)  # 他人临时文件既不截断也不改时间。
        self.assertEqual(self.sftp.writes, [])  # 本次没有成功创建对象。
        self.assertEqual(self.sftp.removed, [])  # 不能清理未由自己创建的随机同名对象。

    def test_local_source_change_before_upload_is_rejected(self):  # 枚举之后本地源改变不能上传旧身份。
        source = self.local_file('changing.txt', b'initial')  # 建立稳定初始来源。
        entries = self.plan([source])  # 固定初始大小与时间。
        source.write_bytes(b'changed and longer')  # 在传输前改变内容与长度。
        result = self.execute(entries)[0]  # 执行已有计划。
        self.assertEqual(result['status'], 'Failed')  # 变化后的来源需要重建计划。
        self.assertEqual(self.sftp.writes, [])  # 拒绝发生在真正上传之前。
        self.assertNotIn(self.destination + '/changing.txt', self.sftp.nodes)  # 没有正式文件。

    def test_local_size_or_mtime_change_during_upload_is_rejected(self):  # 文件传输过程中变化不能正式发布。
        for change in ('size', 'mtime'):  # 分别覆盖长度和同长度修改时间变化。
            with self.subTest(change=change):  # 保留具体变化类型。
                self.sftp = FakeSFTP()  # 每轮独立远端树。
                source = self.local_file('changing.txt', b'original stable bytes')  # 每轮写入固定原始内容。
                before = source.stat()  # 记录传输开始前的时间。
                self.sftp.on_first_write = (lambda: source.write_bytes(b'new longer contents for local mutation')) if change == 'size' else (lambda: os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000)))  # 在远端首次写入时改变本地来源。
                result = self.execute(self.plan([source]))[0]  # 经真实上传及后置复核。
                self.assertEqual(result['status'], 'Failed')  # 两种变化均必须被拒绝。
                self.assertNotIn(self.destination + '/changing.txt', self.sftp.nodes)  # 不发布不稳定来源。
                self.assert_no_parts()  # 清理自己未通过复核的临时文件。

    def test_read_remote_hash_matches_independent_digest_and_size(self):  # 回读校验必须读取全部内容并返回正确字节数。
        content = '远端回读校验\n'.encode('utf-8') + b'\x00' * (1024 * 1024 + 17)  # 超过一个常见 1 MiB 块并含二进制零字节。
        self.sftp.directory(self.destination).file(self.destination + '/hash.dat', content)  # 提供稳定普通文件。
        actual, size = UPLOAD.read_remote_hash(self.sftp, self.destination + '/hash.dat')  # 调用真实流式回读校验。
        self.assertEqual(actual, hashlib.sha256(content).hexdigest().upper())  # 与独立标准库计算一致。
        self.assertEqual(size, len(content))  # 不能仅使用远端声明的长度。

    def assert_link_not_followed(self, linked):  # 接受明确拒绝或可见跳过，但绝不展开目标。
        try:  # 生产策略可以在计划阶段直接拒绝链接。
            entries = self.plan([linked])  # 只选择链接本身。
        except ValueError:  # 明确拒绝也是安全可观察的结果。
            return  # 不进入任何远端写入。
        self.assertEqual(len(entries), 1)  # 不能枚举链接目标中的文件。
        self.assertEqual(entries[0]['kind'], 'unsupported')  # 若允许计划，必须标为不支持。
        result = self.execute(entries)[0]  # 验证执行阶段也不跟随链接。
        self.assertEqual(result['status'], 'SkippedUnsupported')  # 用户可见地报告跳过。
        self.assertEqual(self.sftp.writes, [])  # 链接内容完全未读取上传。

    def test_local_symbolic_directory_link_is_never_followed_when_available(self):  # 环境允许时验收真实目录符号链接。
        outside = Path(self.temporary.name) / 'outside'  # 目标仍局限于本次临时测试范围。
        outside.mkdir()  # 建立独立目标。
        (outside / 'secret.txt').write_bytes(b'not selected')  # 此文件不能被链接间接授权上传。
        linked = self.source / 'linked'  # 将来源本身设为链接。
        try:  # Windows 普通账号可能不具备符号链接权限。
            os.symlink(outside, linked, target_is_directory=True)  # 不提升权限或改系统设置。
        except (OSError, NotImplementedError) as error:  # 保留实际未执行的原因。
            self.skipTest(f'本机不能创建符号链接：{error}')  # 不把跳过称为通过。
        self.assert_link_not_followed(linked)  # 检查真实链接的处理。
        self.assertEqual((outside / 'secret.txt').read_bytes(), b'not selected')  # 链接目标也没有被修改。

    @unittest.skipUnless(os.name == 'nt', '目录联接是 Windows 特性。')  # 仅在 Windows 验证真实重解析点。
    def test_local_directory_junction_is_never_followed_when_available(self):  # 通常不要求管理员权限的联接补足符号链接权限限制。
        outside = Path(self.temporary.name) / 'junction-target'  # 联接目标位于已知临时目录。
        outside.mkdir()  # 创建独立空目标。
        (outside / 'secret.txt').write_bytes(b'not selected')  # 链接目标含未直接选择的文件。
        linked = self.source / 'linked'  # 临时联接路径。
        outcome = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(linked), str(outside)], capture_output=True, timeout=10)  # 参数全部由本测试临时目录派生。
        if outcome.returncode != 0:  # 不修改机器策略以强行创建。
            self.skipTest(f'本机不能创建目录联接，返回码：{outcome.returncode}')  # 准确显示跳过。
        try:  # 无论断言结果如何都只移除联接本身。
            self.assert_link_not_followed(linked)  # 禁止递归进入联接目标。
            self.assertEqual((outside / 'secret.txt').read_bytes(), b'not selected')  # 目标内容仍原样保留。
        finally:  # 不递归删除联接或目标。
            os.rmdir(linked)  # 对核实位于测试临时目录中的联接只删除链接自身。

    @unittest.skipUnless(os.name == 'nt', '目录联接是 Windows 特性。')  # 验证明确选定叶文件也不能绕过祖先检查。
    def test_local_ancestor_junction_is_rejected_when_available(self):  # 不能通过联接祖先选择目标中的普通文件。
        outside = Path(self.temporary.name) / 'ancestor-junction-target'  # 目标仍限于本次临时目录。
        outside.mkdir()  # 创建普通目标目录。
        (outside / 'secret.txt').write_bytes(b'not directly selected')  # 联接后的叶文件本身看似普通。
        linked = self.source / 'ancestor-link'  # 仅祖先路径是联接。
        outcome = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(linked), str(outside)], capture_output=True, timeout=10)  # 参数仅来源于本次 tempfile。
        if outcome.returncode != 0:  # 联接创建受限制时不升级权限。
            self.skipTest(f'本机不能创建目录联接，返回码：{outcome.returncode}')  # 如实报告未执行。
        try:  # 确保测试后只删除明确联接自身。
            with self.assertRaisesRegex(ValueError, '链接|重解析'):  # 不允许将祖先链接当作普通源目录。
                self.plan([linked / 'secret.txt'])  # 直接选择祖先联接下的叶子。
            self.assertEqual(self.sftp.writes, [])  # 尚未操作任何远端文件。
        finally:  # 不递归触碰目标内容。
            os.rmdir(linked)  # 已核实路径位于本次测试临时根内。

    def test_local_file_reparse_point_is_never_followed(self):  # 不依赖权限覆盖 Windows 文件重解析点检测。
        source = self.local_file('reparse.txt', b'must not read')  # 使用普通测试文件承载模拟属性。
        original_lstat = Path.lstat  # 保存真实的本地属性查询。
        def mark_reparse(path, *args, **kwargs):  # 仅为一个明确来源增加重解析点标志。
            info = original_lstat(path, *args, **kwargs)  # 其他路径仍使用真实属性。
            if path == source:  # 不影响父目录和无关临时文件。
                return SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size, st_mtime=info.st_mtime, st_mtime_ns=info.st_mtime_ns, st_file_attributes=0x400)  # 标记 Windows FILE_ATTRIBUTE_REPARSE_POINT。
            return info  # 保留其他路径真实行为。
        with mock.patch.object(Path, 'lstat', new=mark_reparse):  # 只模拟无法保证普通账号可创建的文件型重解析点。
            self.assert_link_not_followed(source)  # 核验计划拒绝或报告跳过，并且不上传。


if __name__ == '__main__':  # 仅直接执行此文件时运行测试。
    unittest.main(verbosity=2)  # 展示每个行为的通过、失败或实际跳过。
