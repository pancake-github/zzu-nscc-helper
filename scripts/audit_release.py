"""核对公开资产的清单、哈希、组件边界及常见凭据形式。"""  # 不把压缩包直接视为已经脱敏。
import argparse  # 仅接收实际构建输出目录。
import hashlib  # 完整校验资产。
import json  # 读取构建清单。
from pathlib import Path, PurePosixPath  # 压缩包内路径与本机路径分别处理。
import re  # 二进制也检查未压缩的令牌和私钥标记。
import sys  # 导入源码隐私审核规则。
import zipfile  # 实际读取每个压缩成员。
from audit_public_tree import violations  # 源码与组件采用同一凭据检查。
BAD_BYTES = re.compile(rb'-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{64,}-----END (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b')  # 检查完整密钥材料，避免误判加密库内置的格式标签。

def audit(folder):  # 本机和CI共用，不读取本机用户数据。
    manifest = json.loads((folder / 'payload-manifest.json').read_text(encoding='utf-8'))  # 无凭据元数据。
    errors, files = [], 0  # 只输出类别及计数。
    if set(manifest.get('units', {})) != {'core', 'keepalive', 'routing', 'sftp'}:  # 必须真正按组件分发。
        errors.append('PAYLOAD_UNITS_INVALID')  # 不猜测缺失组件。
    for unit, record in manifest['units'].items():  # 逐一核验实际载荷。
        path = folder / record['file']  # 只能是单层固定ZIP名称。
        if record['file'] != unit + '.zip' or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:  # 不允许清单指向任意私人文件。
            raise ValueError('PAYLOAD_HASH_MISMATCH')  # 立即拒绝。
    for path in folder.iterdir():  # 只扫描实际待上传资产。
        if not path.is_file() or path.suffix not in ('.zip', '.exe', '.json', '.txt'):  # 未审阅资产不能上传。
            errors.append('UNEXPECTED_ASSET')  # 不打印内容。
            continue  # 不能当作已通过。
        if BAD_BYTES.search(path.read_bytes()):  # PE和压缩包外层也检查。
            errors.append('ASSET_CREDENTIAL_PATTERN')  # 不回显认证信息。
        if path.suffix == '.zip':  # 每个成员都检查，不能只检查ZIP名字。
            with zipfile.ZipFile(path) as stream:  # 不解压到用户目录。
                if path.name == 'core.zip':  # 公开安装包必须携带主要运行库的实际完整许可。
                    required = {'LICENSE', 'licenses/Python/LICENSE.txt', 'licenses/PyQt5/LICENSE', 'licenses/PyQt5-Qt5/LICENSE', 'licenses/PyQt5-sip/LICENSE', 'licenses/paramiko/LICENSE', 'corresponding-sources.json', 'build-info.json'}  # 不以外部链接代替包内许可。
                    if not required.issubset(stream.namelist()) or any(len(stream.read(name)) < 100 for name in required if name in stream.namelist()):  # 空文件也不能充数。
                        errors.append('RUNTIME_LICENSE_OR_SOURCE_INDEX_MISSING')  # 阻止保留或上传不完整分发材料。
                for item in stream.infolist():  # 真实成员集合。
                    name = PurePosixPath(item.filename)  # ZIP标准相对路径。
                    if name.is_absolute() or '..' in name.parts or '\\' in item.filename or ':' in item.filename or (item.external_attr >> 16) & 0o170000 == 0o120000:  # 禁止越界路径或符号链接。
                        errors.append('UNSAFE_ARCHIVE_ENTRY')  # 发布前阻止。
                        continue  # 不读危险成员。
                    data = stream.read(item)  # 校验实际内容。
                    files += 1  # 记录真实检查数量。
                    if BAD_BYTES.search(data):  # 二进制成员也检查私钥和令牌。
                        errors.append('ARCHIVE_CREDENTIAL_PATTERN')  # 不打印匹配。
                    if path.name != 'core.zip' and item.filename.endswith(('.py', '.json', '.js', '.cs', '.txt')):  # 组件只包含审计过的公共业务源码。
                        errors.extend(violations(item.filename, data.decode('utf-8-sig')))  # 每个文本成员重验。
                    if path.name == 'core.zip' and '/zzu_nscc_helper/keepalive/' in item.filename:  # 公共运行库不得偷偷包含保活业务包。
                        errors.append('COMPONENT_BOUNDARY_INVALID')  # 独立组件必须真实分离。
    sums = {}  # 安装器的最终字节必须与上传记录一致。
    for line in (folder / 'SHA256SUMS.txt').read_text(encoding='ascii').splitlines():  # 不接受任意路径。
        digest, name = line.split('  ', 1)  # 标准SHA256清单。
        if Path(name).name != name or name in sums:  # 防止目录穿越及重复名称。
            raise ValueError('SUMS_INVALID')  # 不读取其他文件。
        sums[name] = digest  # 固定单层资产。
    expected = {path.name for path in folder.iterdir() if path.is_file() and path.name != 'SHA256SUMS.txt'}  # 所有资产必须有清单。
    if set(sums) != expected:  # 缺少资产或多出未知资产都拒绝。
        errors.append('SUMS_INCOMPLETE')  # 不把部分校验称为全部。
    for name, digest in sums.items():  # 不信任文件扩展名代替哈希。
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:  # 实际完整读取。
            errors.append('ASSET_HASH_MISMATCH')  # 阻止上传。
    return {'passed': not errors, 'archive_members_checked': files, 'assets_checked': len(expected), 'errors': sorted(set(errors))}  # 脱敏摘要。

if __name__ == '__main__':  # 导入可用于离线故障测试。
    parser = argparse.ArgumentParser(description=__doc__)  # 只接受输出目录。
    parser.add_argument('folder', type=Path)  # 不接受账号或认证。
    result = audit(parser.parse_args().folder)  # 审核真实待发布资产。
    print(json.dumps(result, ensure_ascii=False, indent=2))  # 无私人路径或内容。
    raise SystemExit(0 if result['passed'] else 1)  # 失败不继续上传。
