"""郑州超算单文件、批量和目录下载；仅在本地指定根目录写入。"""  # 远端使用只读 SFTP。
from __future__ import annotations  # 兼容现有 Python 的注解解析。
import argparse  # 读取命令行入口。
import base64  # 编码 SSH 公钥指纹。
from collections import Counter  # 分类汇总结果。
from datetime import datetime, timedelta, timezone  # 按北京时间归档。
import getpass  # 隐藏输入密码。
import hashlib  # 计算 SHA-256。
import json  # 读取请求并写入回执。
import os  # 文件检查与无覆盖发布。
from pathlib import Path  # 处理本地路径。
import posixpath  # 处理 Linux 远端路径。
import re  # 校验名称与校验值。
import stat  # 识别文件类型。
import sys  # 输出错误并返回状态码。
import tempfile  # 排他创建临时文件。
import uuid  # 生成独立回执名称。
import warnings  # 阻止无终端时密码输入退化为明文回显。

HOST = '172.99.1.100'  # 已验证的 SSH 地址。
FINGERPRINT = 'SHA256:tC7Q4zr9XmfXFTzVNGbm6gvVLQr9+MLhEbkoUmfpbzI'  # 已批准固定的 ED25519 身份。
CHINA_TZ = timezone(timedelta(hours=8))  # 分类日期不依赖本机时区。

def validate_name(name: str) -> None:  # 防止 Linux 名称在 Windows 上发生变义。
    if not name or name in ('.', '..') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name[-1] in ' .':  # 拒绝非法字符和末尾点/空格。
        raise ValueError(f'名称无法原样保存到 Windows：{name!r}')  # 不静默重命名科研文件。
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', name, re.I):  # 包含 Windows 识别的上标设备编号。
        raise ValueError(f'名称属于 Windows 保留设备：{name!r}')  # 禁止设备路径。

def normalize_remote(value: str) -> str:  # 只接受明确的远端绝对路径。
    if not isinstance(value, str) or not value.startswith('/') or re.search(r'[\x00-\x1f\\*?\[\]]', value):  # 不解释通配符和转义字符。
        raise ValueError('RemotePath 必须是不含通配符的 Linux 绝对路径。')  # 要求实际文件或目录。
    if any(part in ('.', '..') for part in value.split('/')):  # 不折叠用户提供的相对路径段。
        raise ValueError('远端路径不能包含 . 或 .. 路径段。')  # 保持范围明确。
    result = '/' + '/'.join(part for part in value.split('/') if part)  # 允许目录末尾斜线。
    if result == '/':  # 防止把整个系统作为下载范围。
        raise ValueError('不能下载远端根目录 /。')  # 请指定实际任务文件夹。
    return result  # 返回规范化路径。

def check_local_path(path: Path) -> None:  # 防止链接和目录联接导致保存位置逃逸。
    for node in reversed((path, *path.parents)):  # 从磁盘根逐级检查。
        try:  # 只检查已经存在的层级。
            info = node.lstat()  # 检查链接本身，不跟随链接。
        except FileNotFoundError:  # 未存在目录稍后创建。
            continue  # 继续检查其他层级。
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:  # Windows 0x400 表示重解析点。
            raise ValueError(f'本地路径含链接或重解析点，已停止：{node}')  # 不向无法确认的位置写入。
        if node != path and not stat.S_ISDIR(info.st_mode):  # 所有祖先都必须为目录。
            raise ValueError(f'本地父路径不是目录：{node}')  # 提前发现类型冲突。

def file_hash(path: Path) -> str:  # 流式计算大文件校验值。
    digest = hashlib.sha256()  # 每个文件单独创建校验器。
    with path.open('rb') as stream:  # 只读打开。
        for block in iter(lambda: stream.read(1024 * 1024), b''):  # 每次读取 1 MiB。
            digest.update(block)  # 累加内容。
    return digest.hexdigest().upper()  # 与旧版 PowerShell 校验值格式一致。

def make_plan(sftp, sources: list[str], destination: Path, expected: str) -> tuple[list[dict], str]:  # 下载前完整枚举与预检。
    common_parent = posixpath.commonpath([posixpath.dirname(path) for path in sources])  # 不同父目录中的同名文件保留层级。
    entries, seen_remote, mapped = [], set(), {}  # 记录计划、重复源和 Windows 映射。

    def visit(remote: str) -> None:  # 对选定的源递归遍历。
        if remote in seen_remote:  # 目录及其子文件同时被选定时去重。
            return  # 同一来源只处理一次。
        seen_remote.add(remote)  # 登记当前来源。
        relative = posixpath.relpath(remote, common_parent)  # 保留相对共同父目录的原始层级。
        parts = relative.split('/')  # 拆成 Windows 可保存的目录段。
        for part in parts:  # 对各级目录和文件都检查。
            validate_name(part)  # 不将非法名称静默转换。
        for depth in range(1, len(parts) + 1):  # 同时检查未单独选中的隐式祖先目录。
            prefix = '/'.join(parts[:depth])  # 逐级构造相对前缀。
            remote_prefix = posixpath.join(common_parent, prefix)  # 找到这个层级的真实来源。
            key = prefix.casefold()  # Windows 默认不区分大小写。
            if key in mapped and mapped[key] != remote_prefix:  # /a/x 和 /A/y 也不能合并祖先。
                raise ValueError(f'Windows 大小写路径冲突：{mapped[key]} 与 {remote_prefix}')  # 在任何下载前停止。
            mapped[key] = remote_prefix  # 登记每个路径层级的来源。
        local = destination.joinpath(*parts)  # 限定在任务分类和日期目录内。
        check_local_path(local)  # 检查本地祖先和目标。
        info = sftp.lstat(remote)  # 不跟随远端符号链接。
        kind = 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'unsupported'  # 只下载普通文件和目录。
        if local.exists() and ((kind == 'directory' and not local.is_dir()) or (kind == 'file' and not local.is_file())):  # 检查文件和目录互相占用。
            raise ValueError(f'本地文件与目录类型冲突：{local}')  # 不在冲突后再部分写入。
        entries.append({'remote': remote, 'local': str(local), 'kind': kind, 'size': info.st_size, 'mtime': info.st_mtime})  # 保存用于校验的元数据。
        if kind == 'directory':  # 链接和特殊对象不递归。
            for child in sorted(sftp.listdir_attr(remote), key=lambda item: item.filename):  # 稳定顺序，包含隐藏文件。
                validate_name(child.filename)  # 防止目录项含路径分隔符。
                visit(posixpath.join(remote, child.filename))  # 空目录自身已经加入计划。

    for source in sources:  # 在下载前枚举全部输入。
        visit(source)  # 展开目录，去除重叠选择。
    if expected and (len(sources) != 1 or len(entries) != 1 or entries[0]['kind'] != 'file'):  # 一个基准哈希只能校验一个文件。
        raise ValueError('ExpectedSha256 只能用于一个普通文件，不能用于文件夹或批量文件。')  # 阻止误用。
    return entries, common_parent  # 返回确定的目标列表与布局依据。

def transfer_file(sftp, entry: dict, expected: str) -> dict:  # 单个文件先校验，再原子无覆盖发布。
    target = Path(entry['local'])  # 使用经过预检的目的地。
    check_local_path(target)  # 传输前再次检查本地路径。
    if target.exists():  # 所有现有文件一律保留。
        if not target.is_file():  # 防止预检后变成目录。
            raise ValueError(f'目标已变成非文件：{target}')  # 报告类型变化。
        if expected:  # 只有已知哈希才能证明已有内容一致。
            actual = file_hash(target)  # 只读计算已有内容。
            if actual != expected:  # 同名但与基准不同不能称为已验证。
                raise ValueError(f'已有文件与 ExpectedSha256 不一致，未覆盖：{target}')  # 保留原文件。
            return {**entry, 'status': 'AlreadyVerified', 'sha256': actual, 'verified_against_expected_hash': True}  # 不重复传输。
        return {**entry, 'status': 'SkippedExistingUnverified'}  # 跳过不代表与远端内容相同。
    before = sftp.lstat(entry['remote'])  # 检查枚举后文件是否变化。
    if not stat.S_ISREG(before.st_mode) or (before.st_size, before.st_mtime) != (entry['size'], entry['mtime']):  # 拒绝变化后的链接和文件。
        raise ValueError(f'远端文件在枚举后发生变化：{entry["remote"]}')  # 等来源稳定后可重试。
    target.parent.mkdir(parents=True, exist_ok=True)  # 创建缺失目录，保留已有目录。
    check_local_path(target)  # 创建后再次核对位置。
    descriptor, partial_name = tempfile.mkstemp(prefix='.nscc-', suffix='.part', dir=target.parent)  # 排他创建同目录临时文件。
    partial = Path(partial_name)  # 仅此路径允许在失败后删除。
    try:  # 保证传输失败也不会留下伪装成成品的文件。
        with os.fdopen(descriptor, 'wb') as output:  # 接管已有描述符，避免重新按名字创建。
            sftp.getfo(entry['remote'], output)  # 通过现有 SFTP 会话下载，不执行远端 shell。
            output.flush()  # 刷新 Python 缓冲。
            os.fsync(output.fileno())  # 发布之前同步内容。
        after = sftp.lstat(entry['remote'])  # 下载后复核远端元数据。
        if not stat.S_ISREG(after.st_mode) or (after.st_size, after.st_mtime) != (before.st_size, before.st_mtime) or partial.stat().st_size != before.st_size:  # 检测变化和截断。
            raise ValueError('远端文件在传输中变化或下载大小不符，未发布。')  # 不发布明显不完整内容。
        digest = file_hash(partial)  # 校验实际下载内容。
        if expected and digest != expected:  # 有独立基准时严格比较。
            raise ValueError('下载内容与 ExpectedSha256 不一致，未发布。')  # 错误内容仍仅存在于临时文件。
        check_local_path(target)  # 发布前检查是否出现目录联接。
        try:  # Windows os.rename 在目标存在时拒绝覆盖。
            os.rename(partial, target)  # 不使用会覆盖已有文件的 os.replace。
        except FileExistsError:  # 其他程序抢先创建了目标。
            return {**entry, 'status': 'SkippedExistingUnverified', 'reason': '目标在传输期间被其他程序创建'}  # 保留该文件，清理本次临时文件。
        return {**entry, 'status': 'Downloaded', 'bytes': before.st_size, 'sha256': digest, 'verified_against_expected_hash': bool(expected)}  # 仅记录成功发布的内容。
    finally:  # 不删除远端文件或正式下载文件。
        if partial.exists():  # 成功重命名时临时路径已不存在。
            partial.unlink()  # 只清理本次创建的随机临时文件。

def execute_plan(sftp, entries: list[dict], expected: str) -> list[dict]:  # 逐项执行，保留已成功的内容。
    results = []  # 收集每一项的真实结果。
    for entry in entries:  # 父目录排在子项之前。
        try:  # 单项失败不掩盖此前的成功。
            if entry['kind'] == 'unsupported':  # 不跟随符号链接和设备等特殊对象。
                result = {**entry, 'status': 'SkippedUnsupported'}  # 最终状态明确包含跳过。
            elif entry['kind'] == 'directory':  # 保存空目录并合并已有目录。
                target = Path(entry['local'])  # 获取目录路径。
                check_local_path(target)  # 创建前再次核对。
                existed = target.exists()  # 区分新建与已有目录。
                target.mkdir(parents=True, exist_ok=True)  # 只创建缺失目录。
                result = {**entry, 'status': 'DirectoryExists' if existed else 'DirectoryCreated'}  # 目录不计入文件数量。
            else:  # 处理普通文件。
                result = transfer_file(sftp, entry, expected)  # 使用无覆盖的单文件事务。
        except Exception as error:  # 网络、校验和文件系统异常均有明确记录。
            result = {**entry, 'status': 'Failed', 'error': str(error)}  # 不记录密码。
        results.append(result)  # 保留该项状态。
        print(f'{result["status"]}: {entry["remote"]}', flush=True)  # 持续显示批量进度。
    return results  # 用于完整回执和汇总。

def run(request: dict) -> int:  # 一次运行只进行一次密码认证。
    username = request.get('username', '').strip()  # 公开版必须使用调用者自己的SSH账号。
    if not username:  # 不猜测或复用原开发者账号。
        raise ValueError('请填写本人的SSH用户名。')  # 缺少账号时在连接前停止。
    if os.name != 'nt':  # 依赖 Windows 重命名的无覆盖语义。
        raise RuntimeError('此版本仅支持 Windows 本地运行。')  # 不在其他系统冒险覆盖。
    import paramiko  # 使用现有环境，不安装新依赖。
    raw_paths = request['remote_paths']  # 接收 PowerShell 数组。
    if not isinstance(raw_paths, list) or not raw_paths:  # 至少指定一个实际来源。
        raise ValueError('请至少指定一个 RemotePath。')  # 不扫描未指定目录。
    sources = list(dict.fromkeys(normalize_remote(value) for value in raw_paths))  # 规范化并保持顺序去重。
    expected = request.get('expected_sha256', '').upper()  # 与本地校验值统一大小写。
    if expected and (len(sources) != 1 or not re.fullmatch('[0-9A-F]{64}', expected)):  # 先检查参数适用范围。
        raise ValueError('ExpectedSha256 必须是单文件的 64 位 SHA-256。')  # 不误用整批校验。
    root = Path(request['download_root'])  # 根目录可以由用户指定。
    if not root.is_absolute():  # 禁止相对本地路径。
        raise ValueError('DownloadRoot 必须是绝对路径。')  # 避免工作目录变化导致错放。
    root = Path(os.path.abspath(root))  # 规范本地绝对路径。
    check_local_path(root)  # 认证前检查本地根目录。
    category = request.get('category', '')  # 显式分类优先。
    if category:  # 指定分类可以提前检查。
        validate_name(category)  # 分类只能为一个目录名。
    known_hosts = Path(request['known_hosts'])  # 使用独立公钥记录。
    client = paramiko.SSHClient()  # 不导入其他来源的主机信任。
    client.load_host_keys(str(known_hosts))  # 缺失时直接停止，尚不读取密码。
    key = client.get_host_keys().lookup(HOST)  # 获取该地址已固定的密钥。
    ed25519 = key.get('ssh-ed25519') if key else None  # 仅接受批准的 ED25519 身份。
    observed = 'SHA256:' + base64.b64encode(hashlib.sha256(ed25519.asbytes()).digest()).decode().rstrip('=') if ed25519 else ''  # 计算本地公钥记录指纹。
    if observed != FINGERPRINT:  # 记录被改变时不自动首次信任。
        raise ValueError('known_hosts 与已批准的服务器指纹不一致，已停止。')  # 不发送密码给新身份。
    client.get_host_keys().clear()  # 清除文件中可能存在的其他主机或算法身份。
    client.get_host_keys().add(HOST, 'ssh-ed25519', ed25519)  # 本次连接只允许这个已经批准的密钥。
    client.set_missing_host_key_policy(paramiko.RejectPolicy())  # 拒绝未固定的服务器公钥。
    if expected:  # 保留旧版单文件已存在且有基准时的离线验证行为。
        local_category = category or posixpath.basename(posixpath.dirname(sources[0]))  # 单文件默认分类与旧版一致。
        validate_name(local_category)  # 认证前校验推导分类。
        validate_name(posixpath.basename(sources[0]))  # 单文件名称也必须符合 Windows 规则。
        existing = root / local_category / datetime.now(CHINA_TZ).strftime('%Y-%m-%d') / posixpath.basename(sources[0])  # 与正常下载的单文件布局一致。
        check_local_path(existing)  # 不通过本地链接校验其他位置的文件。
        if existing.is_file():  # 有现有普通文件时可以避免重新认证。
            if file_hash(existing) != expected:  # 同名内容不符时停止而非覆盖。
                raise ValueError(f'已有文件与 ExpectedSha256 不一致，未覆盖：{existing}')  # 保留原有内容。
            print(json.dumps({'Status': 'AlreadyVerified', 'Path': str(existing), 'SHA256': expected, 'RemoteRechecked': False}, ensure_ascii=False, indent=2))  # 只证明本地内容匹配已知值，没有重新查询远端。
            return 0  # 无须发送密码或连接远端。
    with warnings.catch_warnings():  # 只在读取密码时严格处理回显风险。
        warnings.simplefilter('error', getpass.GetPassWarning)  # 无法隐藏输入时直接停止，要求使用交互终端。
        password = getpass.getpass(f'{username}@{HOST} SSH password: ')  # 密码仅通过隐藏终端输入。
    try:  # 确保连接总会关闭。
        client.connect(HOST, port=22, username=username, password=password, look_for_keys=False, allow_agent=False, timeout=15, banner_timeout=20, auth_timeout=30)  # 主机公钥检查先于认证。
        del password  # 尽早删除此变量，不保存到文件或环境变量。
        client.get_transport().set_keepalive(20)  # 保持长会话连接。
        with client.open_sftp() as sftp:  # 单会话完成枚举与全部下载。
            sftp.get_channel().settimeout(60)  # 中断时有界等待。
            if not category:  # 自动推导清晰的任务分类。
                first = sftp.lstat(sources[0])  # 不跟随源根的链接。
                base = sources[0] if len(sources) == 1 and stat.S_ISDIR(first.st_mode) else posixpath.commonpath([posixpath.dirname(path) for path in sources])  # 单目录用自身名，其余取共同父目录。
                category = posixpath.basename(base)  # 提取分类目录名称。
                validate_name(category)  # 共同父目录为 / 时应显式提供分类。
            destination = root / category / datetime.now(CHINA_TZ).strftime('%Y-%m-%d')  # 按任务及北京时间日期保存。
            check_local_path(destination)  # 检查已有分类目录。
            entries, common_parent = make_plan(sftp, sources, destination, expected)  # 整批预检后才写入。
            report_directory = root / '_nscc_transfer_reports'  # 回执与下载内容分开，避免真实文件同名冲突。
            check_local_path(report_directory)  # 回执位置也禁止链接。
            report_directory.mkdir(parents=True, exist_ok=True)  # 仅在下载根目录创建记录目录。
            report_path = report_directory / (datetime.now(CHINA_TZ).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex + '.json')  # 唯一回执名。
            with report_path.open('x', encoding='utf-8') as report_stream:  # 下载前排他创建，拒绝覆盖旧记录。
                report = {'server': HOST, 'user': username, 'sources': sources, 'common_remote_parent': common_parent, 'destination': str(destination), 'started_at': datetime.now(CHINA_TZ).isoformat(), 'status': 'InProgress', 'results': []}  # 不含凭据。
                json.dump(report, report_stream, ensure_ascii=False, indent=2)  # 先写进行中状态，异常退出不留下虚假成功。
                report_stream.flush()  # 刷新初始回执。
                print(f'保存目录：{destination}\n计划：{sum(item["kind"] == "file" for item in entries)} 个文件；回执：{report_path}', flush=True)  # 显示实际保存位置。
                results = execute_plan(sftp, entries, expected)  # 逐文件下载并明确记录错误。
                counts = Counter(item['status'] for item in results)  # 分开统计下载、目录、跳过和失败。
                status = 'PartialFailure' if counts['Failed'] else 'CompletedWithSkips' if counts['SkippedExistingUnverified'] or counts['SkippedUnsupported'] else 'Completed'  # 跳过不能等同完整内容验收。
                report.update(status=status, finished_at=datetime.now(CHINA_TZ).isoformat(), counts=dict(counts), results=results)  # 保存实际结果。
                try:  # 区分文件已完成和回执保存失败。
                    report_stream.seek(0)  # 仅更新本次创建的回执。
                    json.dump(report, report_stream, ensure_ascii=False, indent=2)  # 完整记录来源、目标与 SHA-256。
                    report_stream.truncate()  # 删除初始回执可能剩余的尾部。
                    report_stream.flush()  # 刷新内容。
                    os.fsync(report_stream.fileno())  # 同步回执。
                except OSError as error:  # 文件已经发布时不误报为没有下载。
                    print(f'文件传输已执行，但完整回执保存失败：{error}；统计：{dict(counts)}', file=sys.stderr)  # 明确保留成功文件。
                    return 2  # 要求核查回执，不回滚下载内容。
                print(json.dumps({'Status': status, 'Destination': str(destination), 'Counts': dict(counts), 'Receipt': str(report_path)}, ensure_ascii=False, indent=2))  # 返回可核查摘要。
                return 1 if counts['Failed'] else 0  # 存在失败时不报告全成功。
    finally:  # 不删除远端任何内容。
        client.close()  # 关闭 SSH 和 SFTP 连接。

def main() -> int:  # 为 PowerShell 提供命令行入口。
    parser = argparse.ArgumentParser(description=__doc__)  # 参数帮助说明用途。
    parser.add_argument('--request-file', required=True)  # 不接受通过参数传密码。
    args = parser.parse_args()  # 读取请求文件名。
    try:  # 输入、网络和认证异常均明确失败。
        with open(args.request_file, encoding='utf-8-sig') as stream:  # 兼容 UTF-8 BOM。
            return run(json.load(stream))  # 执行本次下载。
    except (Exception, KeyboardInterrupt) as error:  # 中断时不把已完成部分称为全部成功。
        print(f'下载停止：{type(error).__name__}: {error}', file=sys.stderr)  # 不输出密码。
        return 1  # 供入口脚本判断。

if __name__ == '__main__':  # 被测试导入时不连接网络。
    sys.exit(main())  # 直接运行才开始下载。
