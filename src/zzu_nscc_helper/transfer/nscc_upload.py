"""Windows 文件夹与批量文件安全上传到指定超算任务目录。"""  # 临时上传、回读校验、普通 SFTP 无覆盖发布。
from __future__ import annotations  # 兼容现有 Python 的类型注解。
import argparse  # 解析非敏感请求文件路径。
import base64  # 编码公钥指纹。
from collections import Counter  # 汇总实际结果。
from datetime import datetime  # 使用共享北京时间生成回执时间。
import errno  # 仅将明确的不存在错误视为可创建。
from . import context  # 本批次协作取消和脱敏进度。
import getpass  # 隐藏输入本次认证密码。
import hashlib  # 计算发送内容及远端回读内容校验值。
import json  # 保存传输来源和逐项结果。
import os  # 规范本地路径、同步本地回执。
from pathlib import Path  # 管理 Windows 源路径。
import posixpath  # 管理远端 Linux 目标路径。
import re  # 校验本地绝对路径格式。
import stat  # 识别目录、文件与链接。
import sys  # 返回调用方可检查的退出码。
import uuid  # 创建独立的临时文件与回执名称。
import warnings  # 禁止密码输入回显退化。
from .nscc_download import HOST, FINGERPRINT, CHINA_TZ, validate_name, normalize_remote, check_local_path  # 沿用已批准的身份和路径边界。

def normalize_local(value: str) -> Path:  # 只接受真实且明确的 Windows 本地来源。
    if not isinstance(value, str) or not re.match(r'^[A-Za-z]:[\\/]', value) or re.search(r'[\x00-\x1f*?]', value):  # 不解释通配符、网络共享或控制字符。
        raise ValueError('LocalPath 必须是带盘符、不含通配符的本地绝对路径。')  # 请指定实际文件或文件夹。
    path = Path(os.path.abspath(value))  # 规范绝对路径但不跟随符号链接。
    if path == Path(path.anchor):  # 不将整个磁盘作为本次任务。
        raise ValueError('不能上传本地磁盘根目录。')  # 限定到明确的文件或任务文件夹。
    return path  # 保留源目录名称。

def make_plan(sources: list[Path], destination: str) -> tuple[list[dict], str]:  # 网络认证前枚举本地树。
    if not sources:  # 防止无输入时扫描工作区。
        raise ValueError('请至少指定一个 LocalPath。')  # 不推测来源。
    drives = {path.drive.casefold() for path in sources}  # 判断批量来源是否跨盘。
    common = os.path.commonpath([str(path.parent) for path in sources]) if len(drives) == 1 else ''  # 同盘按共同父目录映射。
    entries, seen, mapped = [], set(), {}  # 保存计划、重复来源与逐级路径映射。

    def visit(path: Path) -> None:  # 对每个实际源递归遍历。
        context.check()  # 大目录本地枚举也可取消。
        spelling = str(path)  # 保留路径原始拼写供冲突检查。
        if spelling in seen:  # 重复选择相同来源时去重。
            return  # 不重复传输同一来源。
        seen.add(spelling)  # 登记已遍历的来源。
        check_local_path(path.parent)  # 祖先目录含链接或联接时停止。
        info = path.lstat()  # 不跟随源根和子项的链接。
        linked = stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)  # Windows 目录联接也属于链接对象。
        kind = 'unsupported' if linked else 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'unsupported'  # 仅传输普通文件和目录。
        parts = list(Path(os.path.relpath(path, common)).parts) if common else [path.drive.rstrip(':').upper(), *path.parts[1:]]  # 跨盘用盘符目录保留原层级。
        for part in parts:  # 对全部目录段校验，避免远端路径逃逸。
            validate_name(part)  # 保持与下载助手兼容的 Windows 名称。
        for depth in range(1, len(parts) + 1):  # 检查隐式父目录的大小写冲突。
            prefix = '/'.join(parts[:depth])  # 构造目标相对前缀。
            folded = prefix.casefold()  # 拒绝不明确的大小写合并。
            if folded in mapped and mapped[folded] != prefix:  # 同一层级不同拼写不能合并成一个任务路径。
                raise ValueError(f'批量路径大小写冲突：{mapped[folded]} 与 {prefix}')  # 上传任何内容前停止。
            mapped[folded] = prefix  # 登记当前目标层级。
        remote = posixpath.join(destination, *parts)  # 指定远端任务目录下的实际目标。
        entries.append({'local': spelling, 'remote': remote, 'kind': kind, 'size': info.st_size, 'mtime_ns': info.st_mtime_ns})  # 留存上传前的源状态。
        if kind == 'directory':  # 仅递归真实目录，不展开链接和联接。
            for child in sorted(path.iterdir(), key=lambda item: item.name):  # 包含隐藏文件，顺序稳定。
                visit(child)  # 空目录本身也已登记。

    for source in sources:  # 展开本次所有明确指定的来源。
        visit(source)  # 文件夹与内部重复选择只保留一次。
    return entries, common or '(cross-drive: drive-letter prefixes)'  # 回执明确说明布局依据。

def remote_info(sftp, path: str):  # 只将 ENOENT 视为目标尚未存在。
    try:  # 权限或连接问题不能被误判为可创建。
        return sftp.lstat(path)  # 不跟随远端符号链接。
    except OSError as error:  # Paramiko 将 SFTP 状态转换为 OSError。
        if error.errno == errno.ENOENT:  # 文件或其父目录明确不存在。
            return None  # 可在后续无覆盖步骤创建。
        raise  # 其他错误停止操作。

def check_remote_chain(sftp, path: str):  # 检查任务目录祖先及目标叶对象。
    parts = path.strip('/').split('/')  # 远端路径均已规范为绝对路径。
    leaf = None  # 不存在时返回 None。
    for index in range(1, len(parts) + 1):  # 逐级 lstat，不依赖跟随链接的 stat。
        node = '/' + '/'.join(parts[:index])  # 当前祖先或叶路径。
        info = remote_info(sftp, node)  # 读取对象本身属性。
        if info is None:  # 不存在的祖先下不可能有已存在子项。
            return None  # 后续 mkdir 时仍会逐级复核。
        if stat.S_ISLNK(info.st_mode):  # 不沿远端链接写入其他范围。
            raise ValueError(f'远端路径含符号链接，已停止：{node}')  # 明确指出冲突层级。
        if index < len(parts) and not stat.S_ISDIR(info.st_mode):  # 所有父层级必须为目录。
            raise ValueError(f'远端父路径不是目录：{node}')  # 文件不能被转换为目录。
        leaf = info  # 最后一次赋值即目标对象属性。
    return leaf  # 调用方进一步检查期望类型。

def preflight_remote(sftp, entries: list[dict], destination: str) -> None:  # 完整只读检查通过后才写入远端。
    root = check_remote_chain(sftp, destination)  # 检查指定任务目录及其祖先。
    if root is not None and not stat.S_ISDIR(root.st_mode):  # 任务目录不能是普通文件。
        raise ValueError(f'远端任务目录已被非目录对象占用：{destination}')  # 不覆盖。
    for entry in entries:  # 对计划内每项检查现有远端状态。
        if entry['kind'] == 'unsupported':  # 本地链接或特殊对象不会传输。
            continue  # 不为其创建任何远端对象。
        info = check_remote_chain(sftp, entry['remote'])  # 父目录链接也会被拒绝。
        if info is not None and ((entry['kind'] == 'directory' and not stat.S_ISDIR(info.st_mode)) or (entry['kind'] == 'file' and not stat.S_ISREG(info.st_mode))):  # 普通文件与目录类型冲突。
            raise ValueError(f'远端文件与目录类型冲突：{entry["remote"]}')  # 本批尚未写入。

def ensure_remote_directory(sftp, path: str) -> None:  # 只创建缺失目录，保留已有目录。
    parts = path.strip('/').split('/')  # 分解需创建的绝对路径。
    for depth in range(1, len(parts) + 1):  # 从现有祖先向任务目录逐级处理。
        node = '/' + '/'.join(parts[:depth])  # 当前完整路径。
        info = check_remote_chain(sftp, node)  # 每次创建前复核祖先和当前对象。
        if info is None:  # 此层级尚未存在。
            try:  # 另一程序并发创建目录时需要重新确认类型。
                sftp.mkdir(node)  # 不改变现有目录权限或所有权。
            except OSError:  # 并发存在或权限问题均需再检查。
                info = check_remote_chain(sftp, node)  # 不自动忽略创建失败。
                if info is None or not stat.S_ISDIR(info.st_mode):  # 非合法已有目录时保持失败。
                    raise  # 不吞掉权限或类型错误。
            info = check_remote_chain(sftp, node)  # 创建成功后也再检查。
        if info is None or not stat.S_ISDIR(info.st_mode):  # 不接受链接或普通文件作父目录。
            raise ValueError(f'远端路径不是普通目录：{node}')  # 不继续创建子项。

def read_remote_hash(sftp, path: str) -> tuple[str, int]:  # 回读实际收到的临时内容，不执行远端 shell。
    info = check_remote_chain(sftp, path)  # 回读前复核临时文件及祖先，拒绝符号链接。
    if info is None or not stat.S_ISREG(info.st_mode):  # 不读被替换为目录或链接的临时对象。
        raise ValueError(f'待校验远端对象不是普通文件：{path}')  # 不跟随到范围外。
    digest, total = hashlib.sha256(), 0  # 同时核对内容与字节数。
    with sftp.open(path, 'rb') as stream:  # 仅只读访问本次临时文件。
        while True:  # 逐块回读，支持大文件。
            block = stream.read(1024 * 1024)  # 每次最多 1 MiB。
            if not block:  # 远端读取完成。
                break  # 结束校验。
            context.advance(len(block))  # 回读时也能取消。
            digest.update(block)  # 累加实际远端内容。
            total += len(block)  # 统计实际字节数。
    return digest.hexdigest().upper(), total  # 返回完整远端内容校验结果。

def upload_file(sftp, entry: dict) -> dict:  # 单文件上传事务，不触及远端既有正式文件。
    source, target = Path(entry['local']), entry['remote']  # 获取确定的源与目标。
    check_local_path(source)  # 传输前拒绝本地链接或目录联接。
    before = source.lstat()  # 检查枚举后来源状态。
    if not stat.S_ISREG(before.st_mode) or (before.st_size, before.st_mtime_ns) != (entry['size'], entry['mtime_ns']):  # 不上传已变化来源。
        raise ValueError(f'本地源文件在枚举后变化：{source}')  # 等来源稳定后可重试。
    existing = check_remote_chain(sftp, target)  # 检查正式目标及其父目录。
    if existing is not None:  # 保留所有已有正式对象。
        if not stat.S_ISREG(existing.st_mode):  # 不能向同名目录或特殊对象上传文件。
            raise ValueError(f'远端目标已变成非普通文件：{target}')  # 不改变它。
        return {**entry, 'status': 'SkippedExistingUnverified'}  # 不把跳过称为内容相同。
    ensure_remote_directory(sftp, posixpath.dirname(target))  # 创建缺失父目录并逐级复核。
    partial = posixpath.join(posixpath.dirname(target), '.nscc-upload-' + uuid.uuid4().hex + '.part')  # 与目标同目录的独立临时名称。
    created = False  # 只有本次成功排他创建的临时文件才允许清理。
    digest, total = hashlib.sha256(), 0  # 校验真正读出并发送的内容。
    try:  # 上传、回读或发布失败时清理本次临时对象。
        output = sftp.open(partial, 'wx')  # WRITE + CREATE + EXCL，已有同名临时文件也绝不截断。
        created = True  # 从此确认此临时文件由本次调用创建。
        with output, source.open('rb') as stream:  # 任一打开/写入失败均关闭句柄。
            opened = os.fstat(stream.fileno())  # 核对真正打开的源文件状态。
            if (opened.st_size, opened.st_mtime_ns) != (before.st_size, before.st_mtime_ns):  # 防止打开前发生变化。
                raise ValueError('本地源文件在打开前变化，未发布。')  # 不上传新的未批准内容。
            while True:  # 流式上传以支持大文件。
                block = stream.read(1024 * 1024)  # 每块最多 1 MiB。
                if not block:  # 已读取完整来源。
                    break  # 结束上传。
                context.check()  # 不再写入取消后的数据块。
                output.write(block)  # SFTP 写入本次独占临时文件。
                digest.update(block)  # 对实际发送的内容计算 SHA-256。
                context.advance(len(block))  # 仅发送脱敏字节进度。
                total += len(block)  # 留存真实传输字节数。
            after_open = os.fstat(stream.fileno())  # 读取后再核对文件句柄状态。
        check_local_path(source)  # 再检查路径是否被改为链接。
        after = source.lstat()  # 核对传输后的本地来源元数据。
        if (after_open.st_size, after_open.st_mtime_ns) != (before.st_size, before.st_mtime_ns) or (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns) or total != before.st_size:  # 检测写入中的文件与截断。
            raise ValueError('本地源文件在上传中变化，未发布。')  # 不将不稳定内容作为正式结果。
        remote_digest, remote_bytes = read_remote_hash(sftp, partial)  # 默认完整回读，校验实际远端内容。
        local_digest = digest.hexdigest().upper()  # 固定真正发送内容的校验值。
        if remote_digest != local_digest or remote_bytes != total:  # 大小相同也必须校验内容。
            raise ValueError('远端回读内容或大小不符，未发布。')  # 正式目标仍未创建。
        existing = check_remote_chain(sftp, target)  # 发布前再次检查目标和祖先。
        if existing is not None:  # 其他程序已创建目标时保留它。
            if not stat.S_ISREG(existing.st_mode):  # 类型变化明确失败。
                raise ValueError(f'发布前目标已被非文件占用：{target}')  # 不覆盖同名目录。
            return {**entry, 'status': 'SkippedExistingUnverified', 'reason': '目标在上传期间由其他程序创建'}  # 临时内容由 finally 清理。
        try:  # 最终依赖标准 SFTP rename 的拒绝覆盖语义保护竞态。
            context.check()  # 发布前取消时只清理本次临时文件。
            sftp.rename(partial, target)  # 禁止使用会覆盖目标的 posix_rename 扩展。
        except OSError:  # 目标并发出现或其他发布失败必须明确检查。
            concurrent = check_remote_chain(sftp, target)  # 不删除并发创建的正式对象。
            if concurrent is not None and stat.S_ISREG(concurrent.st_mode):  # 若目标现为普通文件则安全跳过。
                return {**entry, 'status': 'SkippedExistingUnverified', 'reason': '无覆盖发布时目标已存在'}  # 保留它，清理本次临时文件。
            raise  # 其他重命名失败记录为失败。
        created = False  # 发布成功后不再按临时对象清理。
        return {**entry, 'status': 'UploadedVerified', 'bytes': total, 'sha256': local_digest, 'remote_sha256': remote_digest, 'verified_by_sftp_readback': True}  # 内容已由远端完整回读验证。
    finally:  # 永不删除正式目标或其他用户的文件。
        if created:  # 仅清理本次排他创建的随机 .part。
            try:  # 连接中断可能导致清理失败，需要给出确切临时路径。
                info = check_remote_chain(sftp, partial)  # 清理前再核对父目录和对象，不能沿链接删除其他位置。
                if info is not None:  # 连接正常时清理上传未发布内容。
                    if not stat.S_ISREG(info.st_mode):  # 临时对象被替换时不能盲目删除。
                        raise ValueError('本次临时路径已变为非普通文件，未删除。')  # 保留异常对象供核查。
                    sftp.remove(partial)  # 单文件删除，不递归删除任何目录。
            except Exception as error:  # 不声称无法确认的临时文件已经清理。
                raise RuntimeError(f'本次临时文件清理未确认：{partial}；{error}') from error  # 回执记录需要核查的确切路径。

def execute_plan(sftp, entries: list[dict]) -> list[dict]:  # 单项失败不撤销其他成功文件。
    results = []  # 收集逐项实际结果。
    for entry in entries:  # 父目录先于子项。
        if context.cancelled.is_set():  # 取消后不开始下一项。
            break  # 已成功内容保留，批次终态明确取消。
        try:  # 网络、权限与内容校验错误都明确记录。
            if entry['kind'] == 'unsupported':  # 本地链接与特殊对象不展开。
                result = {**entry, 'status': 'SkippedUnsupported'}  # 不将跳过误报为上传成功。
            elif entry['kind'] == 'directory':  # 保留空目录并合并已有目录。
                source = Path(entry['local'])  # 使用明确的本地目录路径。
                check_local_path(source)  # 创建前再次检查本地源目录链接。
                if not stat.S_ISDIR(source.lstat().st_mode):  # 目录若在枚举后变为文件，不创建错误的远端层级。
                    raise ValueError(f'本地源目录在枚举后变化：{source}')  # 本项明确失败。
                existed = check_remote_chain(sftp, entry['remote']) is not None  # 判断目标目录是否已经存在。
                ensure_remote_directory(sftp, entry['remote'])  # 只创建缺失目录。
                result = {**entry, 'status': 'DirectoryExists' if existed else 'DirectoryCreated'}  # 不把目录计为上传文件。
            else:  # 处理普通文件。
                result = upload_file(sftp, entry)  # 完整回读校验及无覆盖发布。
        except Exception as error:  # 单项异常不会隐藏已成功内容。
            result = {**entry, 'status': 'Failed', 'error': str(error)}  # 回执不含认证密码。
        context.notify({'event': 'item', 'status': result['status']})  # 只发送逐项状态，不发送文件内容。
        results.append(result)  # 保留本项结果。
        print(f'{result["status"]}: {entry["remote"]}', flush=True)  # 显示批量进度。
    return results  # 返回汇总所需结果。

def run(request: dict, password_provider=None) -> int:  # 单次认证完成整批文件上传。
    username = request.get('username', '').strip()  # 公开版必须使用调用者自己的SSH账号。
    if not username:  # 不猜测或复用原开发者账号。
        raise ValueError('请填写本人的SSH用户名。')  # 缺少账号时在连接前停止。
    if os.name != 'nt':  # 当前入口针对用户现有 Windows 环境。
        raise RuntimeError('此版本仅支持 Windows 本地运行。')  # 不在其他环境猜测本地路径规则。
    import paramiko  # 使用本机已有依赖。
    raw = request['local_paths']  # 本次实际来源路径列表。
    if not isinstance(raw, list):  # 防止字符串被逐字符遍历。
        raise ValueError('local_paths 必须是路径数组。')  # 明确参数要求。
    sources = list(dict.fromkeys(normalize_local(value) for value in raw))  # 保持顺序并去除相同路径。
    destination = normalize_remote(request['remote_directory'])  # 任务目录必须是明确 Linux 绝对路径。
    entries, common = make_plan(sources, destination)  # 先完成本地计划，不读取密码。
    report_root = normalize_local(request['report_root'])  # 本地回执根目录同样使用绝对路径。
    check_local_path(report_root)  # 禁止将回执写入目录联接。
    client = paramiko.SSHClient()  # 不自动信任未知主机。
    client.load_host_keys(str(request['known_hosts']))  # 缺少已确认身份时停止。
    known = client.get_host_keys().lookup(HOST)  # 查找当前服务器的固定身份。
    key = known.get('ssh-ed25519') if known else None  # 只接受批准的 ED25519 公钥。
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=') if key else ''  # 计算记录中的公钥指纹。
    if fingerprint != FINGERPRINT:  # 公钥记录变化时不发送密码。
        raise ValueError('known_hosts 与已批准的服务器指纹不一致。')  # 不自动重新信任。
    client.get_host_keys().clear()  # 不让其他算法或主机记录参与信任。
    client.get_host_keys().add(HOST, 'ssh-ed25519', key)  # 连接仅信任这一把批准密钥。
    client.set_missing_host_key_policy(paramiko.RejectPolicy())  # 未知身份直接拒绝。
    with warnings.catch_warnings():  # 不允许隐藏输入失败后回显密码。
        warnings.simplefilter('error', getpass.GetPassWarning)  # 无交互终端时明确停止。
        password = password_provider() if password_provider else getpass.getpass(f'{username}@{HOST} SSH password: ')  # 每批只读取一次，不保存凭据。
    try:  # 始终关闭本次连接。
        context.check()  # 认证前允许取消。
        client.connect(HOST, port=22, username=username, password=password, look_for_keys=False, allow_agent=False, timeout=15, banner_timeout=20, auth_timeout=30)  # 身份核对先于密码发送。
        del password  # 尽早删除应用层密码变量。
        client.get_transport().set_keepalive(20)  # 保持较长上传会话。
        with client.open_sftp() as sftp:  # 同一会话做全批预检和传输。
            sftp.get_channel().settimeout(60)  # 中断时有界等待。
            preflight_remote(sftp, entries, destination)  # 只读远端预检，冲突时不写入任务目录。
            report_root.mkdir(parents=True, exist_ok=True)  # 仅创建指定本地回执目录。
            check_local_path(report_root)  # 创建后再核对本地位置。
            report_path = report_root / (datetime.now(CHINA_TZ).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex + '.json')  # 不覆盖旧回执。
            with report_path.open('x', encoding='utf-8') as record:  # 先验证回执可写，再上传。
                report = {'server': HOST, 'sources': [str(path) for path in sources], 'common_local_parent': common, 'destination': destination, 'started_at': datetime.now(CHINA_TZ).isoformat(), 'status': 'InProgress', 'results': []}  # 不记录密码。
                json.dump(report, record, ensure_ascii=False, indent=2)  # 保存进行中状态以防突然中断。
                record.flush()  # 让初始回执可见。
                print(f'远端任务目录：{destination}\n计划：{sum(item["kind"] == "file" for item in entries)} 个文件；回执：{report_path}', flush=True)  # 显示确定的传输目的地。
                results = execute_plan(sftp, entries)  # 正式写入仅发生在计划指定位置。
                counts = Counter(item['status'] for item in results)  # 汇总实际上传、跳过和失败数量。
                status = 'Cancelled' if context.cancelled.is_set() else 'PartialFailure' if counts['Failed'] else 'CompletedWithSkips' if counts['SkippedExistingUnverified'] or counts['SkippedUnsupported'] else 'Completed'  # 跳过不等于内容验收。
                report.update(status=status, finished_at=datetime.now(CHINA_TZ).isoformat(), counts=dict(counts), results=results)  # 更新逐项来源、目的地与校验信息。
                try:  # 区分文件已发布和回执未完整保存。
                    record.seek(0)  # 只修改本次独立创建的回执。
                    json.dump(report, record, ensure_ascii=False, indent=2)  # 写入完整内容。
                    record.truncate()  # 删除初始记录多余尾部。
                    record.flush()  # 刷新本地回执。
                    os.fsync(record.fileno())  # 同步回执至存储。
                except OSError as error:  # 不因回执问题删除已上传成功的文件。
                    print(f'文件传输已执行，但完整回执保存失败：{error}；统计：{dict(counts)}', file=sys.stderr)  # 明确已执行的结果。
                    return 2  # 需核查记录但不回滚远端正式内容。
                print(json.dumps({'Status': status, 'RemoteDirectory': destination, 'Counts': dict(counts), 'Receipt': str(report_path)}, ensure_ascii=False, indent=2))  # 输出可检查摘要。
                return 1 if counts['Failed'] or context.cancelled.is_set() else 0  # 存在失败时返回非零状态。
    finally:  # 不删除任何正式源文件或目标文件。
        client.close()  # 释放 SSH/SFTP 会话。

def main() -> int:  # PowerShell 调用入口。
    parser = argparse.ArgumentParser(description=__doc__)  # 提供参数帮助。
    parser.add_argument('--request-file', required=True)  # 只接受非敏感请求文件。
    args = parser.parse_args()  # 不接受密码命令行参数。
    try:  # 输入、认证和预检错误明确失败。
        with open(args.request_file, encoding='utf-8-sig') as stream:  # 兼容有 BOM 的 UTF-8 请求。
            return run(json.load(stream))  # 执行本次上传。
    except (Exception, KeyboardInterrupt) as error:  # 保留已经成功的部分，避免虚假全成功。
        print(f'上传停止：{type(error).__name__}: {error}', file=sys.stderr)  # 不输出密码。
        return 1  # 交由 PowerShell 判断。

if __name__ == '__main__':  # 导入单元测试时不触发认证。
    sys.exit(main())  # 直接运行才开始上传。
