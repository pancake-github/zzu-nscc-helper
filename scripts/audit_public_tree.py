"""审核实际Git导出集合，而非仅依赖.gitignore避免敏感文件发布。"""  # 不联网、不读取凭据。
import argparse  # 接收实际仓库和原工作区路径。
import ast  # 检查Python中写死的账号或口令常量。
import hashlib  # 核对来源与公开副本。
import json  # 读取来源清单并输出检查摘要。
from pathlib import Path  # 限定文件边界。
import re  # 检查私钥、令牌形式及个人路径。
import subprocess  # 只读枚举Git将导出的文件。
import sys  # 加载新仓库的共享资源。

TOP_LEVEL = frozenset(('.gitignore', '.gitattributes', 'AGENTS.md', 'LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md', 'pyproject.toml', 'repository.json', 'observed-dependencies.json', 'source-inventory.json', 'launcher.py', 'worker_entry.py'))  # 明确可公开的根文件。
PROJECT_FILES = frozenset(('src/zzu_nscc_helper/__init__.py', 'src/zzu_nscc_helper/components.py', 'src/zzu_nscc_helper/platform.py', 'src/zzu_nscc_helper/data/known_hosts', 'src/zzu_nscc_helper/data/zzdx-nscc.json', 'tests/test_contracts.py', 'tests/test_public_credentials.py', 'tests/test_export_audit.py', 'scripts/audit_public_tree.py', 'docs/ARCHITECTURE.md', 'docs/PLATFORM.md', 'docs/PRIVACY.md', 'docs/STAGES.md', 'docs/stage1-validation.json'))  # 第一阶段新增文件的精确白名单。
PROJECT_FILES |= frozenset('src/zzu_nscc_helper/' + name for name in ('paths.py', 'network.py', 'processes.py', 'instance.py', 'lifecycle.py', 'routing.py', 'worker.py', 'gui.py', 'transfer/__init__.py', 'transfer/context.py', 'transfer/nscc_download.py', 'transfer/nscc_upload.py', 'keepalive/__init__.py', 'keepalive/app.py', 'keepalive/engine.py', 'keepalive/instance_guard.py', 'keepalive/live_request.py', 'keepalive/native_setup.py', 'keepalive/tab_app.py', 'keepalive/tab_bridge.py', 'keepalive/windows.py', 'keepalive/NativeHost.cs', 'keepalive/extension-id.txt', 'keepalive/extension/background.js', 'keepalive/extension/manifest.json'))  # 第二阶段每个活跃源码文件逐个列入。
PROJECT_FILES |= frozenset(('tests/test_stage2.py', 'tests/test_keepalive_fusion.py', 'tests/test_routing_script.cjs', 'tests/test_extension_fusion.cjs', 'docs/SOURCE_USAGE.md', 'docs/stage2-validation.json'))  # 仅脱敏文档及离线用例可公开。
PROJECT_FILES |= frozenset(('src/zzu_nscc_helper/controller.py', 'tests/test_regression_stage3.py', 'docs/stage3-validation.json'))  # 第三阶段的只读核心验证与离线回归。
PROJECT_FILES |= frozenset(('scripts/check_link_permissions.py', 'src/zzu_nscc_helper/installation.py', 'packaging/requirements-build.txt', 'packaging/frozen_entry.py', 'packaging/helper.spec', 'packaging/build-settings.json', 'packaging/setup.iss', 'scripts/build_release.py', 'scripts/github_delivery.py', 'scripts/audit_release.py', 'scripts/test_installers.py', '.github/workflows/build.yml', 'tests/test_packaging.py', 'docs/INSTALLATION.md'))  # 第四阶段公开构建脚本；私人原始验收仍排除。
PROJECT_FILES |= frozenset(('scripts/lock_build.py', 'packaging/requirements-build.lock'))  # 构建依赖的公开固定版本与官方轮子哈希。
PRIVATE_KEY = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')  # 不将公开SSH公钥误判为私钥。
GITHUB_TOKEN = re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b')  # 只检测形式，不输出匹配内容。
PERSONAL_PATH = re.compile(r'[A-Za-z]:[\\/](?:Users[\\/][^\\/\s\"\']+|ANACONDA3)(?:[\\/]|\b)', re.IGNORECASE)  # 排除用户目录和本机环境根路径。
CREDENTIAL_FIELDS = frozenset(('user', 'username', 'password', 'passwd', 'secret', 'api_key', 'access_token', 'subscription_url'))  # 公共配置不能包含实际认证值。
URL_AUTH = re.compile(r'https?://[^/\s:@]+:[^/\s@]+@', re.IGNORECASE)  # URL中也不能夹带用户名密码。

def structured_credentials(value):  # 递归检查公共JSON中的实际值。
    if isinstance(value, dict):  # 只检查字段，不把说明文档当认证。
        return any((str(key).casefold() in CREDENTIAL_FIELDS and bool(item)) or structured_credentials(item) for key, item in value.items())  # 空输入框默认值允许。
    if isinstance(value, list):  # 组件清单也可能含嵌套配置。
        return any(structured_credentials(item) for item in value)  # 不输出匹配值。
    return False  # 普通标量不单独猜测。

def violations(name, text):  # 只返回类别，绝不把疑似口令写入报告。
    errors = []  # 每个文件独立结果。
    if PRIVATE_KEY.search(text):  # 私钥不能随源码发布。
        errors.append('PRIVATE_KEY')  # 固定类别。
    if GITHUB_TOKEN.search(text):  # GitHub认证令牌不能入库。
        errors.append('GITHUB_TOKEN')  # 不输出令牌本身。
    if PERSONAL_PATH.search(text):  # 公开源码不能依赖个人安装位置。
        errors.append('PERSONAL_ABSOLUTE_PATH')  # 只报告类别。
    if URL_AUTH.search(text):  # 禁止将认证信息嵌入URL。
        errors.append('URL_CREDENTIAL')  # 不回显URL。
    if name.endswith('.json'):  # 公共资源和构建清单必须是无凭据JSON。
        try:  # 损坏配置也不能放行。
            if structured_credentials(json.loads(text)):  # 只检查实际值。
                errors.append('CONFIG_CREDENTIAL')  # 固定错误类别。
        except ValueError:  # 需要修复源文件。
            errors.append('JSON_SYNTAX')  # 不输出内容。
    if name.endswith('.py'):  # 对Python进行语法与固定身份检查。
        try:  # 无法解析也应使发布审核失败。
            tree = ast.parse(text, filename=name)  # 不执行源码。
            for node in ast.walk(tree):  # 同时检查模块和函数内部。
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):  # 忽略其他语法节点。
                    continue  # 不把说明文字当认证配置。
                value = node.value  # 赋值表达式。
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]  # 兼容带注解常量。
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:  # 只有非空固定字面量存在泄漏风险。
                    if any(isinstance(target, ast.Name) and target.id.casefold() in ('user', 'username', 'password', 'api_key', 'access_token') for target in targets):  # 不允许写死账户或口令。
                        errors.append('HARDCODED_CREDENTIAL')  # 不输出固定值。
        except SyntaxError:  # 发布副本不能含损坏代码。
            errors.append('PYTHON_SYNTAX')  # 供修正后重新审计。
    return sorted(set(errors))  # 去重后稳定输出。

def inside(root, relative):  # 清单本身也不能让审核越过指定目录。
    candidate = root / relative  # 在解析链接前保留实际路径。
    if any(part.is_symlink() or part.is_junction() for part in (candidate, *candidate.parents) if part != root and part.is_relative_to(root)):  # 同时拒绝祖先目录联接。
        raise ValueError('清单路径不能是链接或目录联接。')  # 不把目标文件误认为原路径。
    path = candidate.resolve()  # 解析绝对边界。
    if not path.is_relative_to(root):  # 拒绝越界路径和链接资源。
        raise ValueError('清单路径不在允许边界内。')  # 不读取其他私人文件。
    return path  # 仅返回已核对路径。

def audit_git_objects(root, allowed):  # 暂存区和历史与当前磁盘文件分别检查。
    def git(*arguments):  # 所有命令只读，不请求认证。
        return subprocess.run(['git', '-C', str(root), *arguments], capture_output=True, check=True).stdout  # 二进制内容不打印。
    objects = {}  # 相同blob只检查一次，但保留实际路径。
    errors = []  # 仅保存类别。
    for record in git('ls-files', '--stage', '-z').split(b'\0'):  # 暂存区可能仍含旧凭据。
        if record:  # 跳过结束帧。
            metadata, name = record.split(b'\t', 1)  # 不按空格拆路径。
            mode, oid, stage = metadata.decode().split()  # 获取实际blob身份。
            relative = name.decode('utf-8')  # Git文件名。
            if mode not in ('100644', '100755') or stage != '0':  # 拒绝链接、子模块或未解决冲突。
                errors.append({'file': relative, 'error': 'INDEX_UNSAFE_ENTRY'})  # 不读取链接目标。
            objects[(oid, relative)] = 'index'  # 扫描实际暂存内容。
    for record in git('rev-list', '--objects', '--all').decode('utf-8').splitlines():  # 无提交仓库返回空集合。
        fields = record.split(' ', 1)  # 历史对象名可包含空格。
        if len(fields) == 2 and git('cat-file', '-t', fields[0]).strip() == b'blob':  # 只检查实际文件。
            objects[(fields[0], fields[1])] = 'history'  # 删除过的文件也保留在历史中。
    for (oid, name), source in objects.items():  # 不依赖当前工作目录文件。
        if name not in allowed:  # 历史中未获准公开的文件也阻止发布。
            errors.append({'file': name, 'error': source.upper() + '_NOT_ALLOWLISTED'})  # 仅报告路径和类别。
            continue  # 不打印私人内容。
        try:  # 源码仓库当前只允许UTF8文本。
            content = git('cat-file', 'blob', oid).decode('utf-8-sig')  # 读取对象本身。
            errors.extend({'file': name, 'error': source.upper() + '_' + error} for error in violations(name, content))  # 分清泄漏位置。
        except UnicodeError:  # 发布二进制另行核验。
            errors.append({'file': name, 'error': source.upper() + '_UNREVIEWED_BINARY'})  # 不猜测内容。
    return errors, len(objects)  # 提供实际扫描数量。

def audit(root, workspace=None):  # 核对将被Git公开的完整集合。
    root = root.resolve()  # 固定仓库根目录。
    inventory = json.loads((root / 'source-inventory.json').read_text(encoding='utf-8'))['files']  # 来源清单已经可人工复核。
    imported = {item['target'] for item in inventory}  # 所有基线副本都有来源哈希。
    allowed = TOP_LEVEL | PROJECT_FILES | imported  # 文件须满足精确白名单。
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-c', '-o', '--exclude-standard', '-z'], check=True, capture_output=True)  # 不枚举.git内部或忽略的运行数据。
    names = sorted(set(name for name in result.stdout.decode('utf-8').split('\0') if name))  # 保留实际Git文件名。
    errors = []  # 全部问题统一留到最后报告。
    errors.extend({'file': name, 'error': 'REQUIRED_FILE_MISSING'} for name in sorted((TOP_LEVEL | imported) - set(names)))  # 许可证或基线缺失也必须失败。
    for name in names:  # 每个实际待导出文件都检查。
        if name not in allowed:  # 忽略规则不等于导出授权。
            errors.append({'file': name, 'error': 'NOT_ALLOWLISTED'})  # 不接受额外文件。
            continue  # 不读取未经白名单授权的内容。
        path = inside(root, name)  # 防止清单路径越界。
        if path.is_dir():  # 不允许嵌入另一个仓库或目录链接。
            errors.append({'file': name, 'error': 'NOT_REGULAR_FILE'})  # 只导出实际源码文件。
            continue  # 不递归扫描其内容。
        try:  # 所有第一阶段公开文件都应是文本。
            text = path.read_text(encoding='utf-8-sig')  # 同时兼容原UTF8 BOM。
        except UnicodeError:  # 未审阅的二进制不应进入源文件仓库。
            errors.append({'file': name, 'error': 'UNREVIEWED_BINARY'})  # 构建二进制应属于后续Release。
            continue  # 不尝试解码或输出内容。
        errors.extend({'file': name, 'error': error} for error in violations(name, text))  # 只保存类别。
    object_errors, object_count = audit_git_objects(root, allowed)  # 检查真实Git导出及历史。
    errors.extend(object_errors)  # 任一层失败均不能发布。
    unchanged = 0  # 有实际工作区参数时才核对原件。
    for item in inventory:  # 确认公开副本与已记录的变更一致。
        path = inside(root, item['target'])  # 只核对已授权副本。
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['target_sha256']:  # 整理后出现额外变更需要复核。
            errors.append({'file': item['target'], 'error': 'BASELINE_COPY_CHANGED'})  # 不用旧清单掩盖改动。
        if workspace is not None:  # 本机验收还要证明原件未修改。
            source = inside(workspace.resolve(), item['source'])  # 真实来源必须位于原工作区。
            if hashlib.sha256(source.read_bytes()).hexdigest() != item['source_sha256']:  # 源文件已变时不能声称原件保留。
                errors.append({'file': item['source'], 'error': 'ORIGINAL_CHANGED'})  # 只输出相对来源名。
            else:  # 原件仍与导出前一致。
                unchanged += 1  # 统计实际核对数量。
    sys.path.insert(0, str(root / 'src'))  # 只影响当前审核进程。
    from zzu_nscc_helper.platform import load_platform  # 不安装项目或依赖。
    load_platform()  # 同时独立验证平台公钥与限定目标。
    return {'passed': not errors, 'export_files': len(names), 'git_objects_checked': object_count, 'imported_sources': len(inventory), 'originals_hash_checked': unchanged, 'host_key_verified': True, 'errors': errors}  # 不输出个人路径、凭据或内容。

def main():  # 本机与后续CI共用入口。
    parser = argparse.ArgumentParser(description=__doc__)  # 明确只读审核用途。
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])  # 默认仅限此独立仓库。
    parser.add_argument('--workspace', type=Path)  # 本机可额外核对来源，CI不需要个人工作区。
    args = parser.parse_args()  # 参数不包含密码或令牌。
    result = audit(args.root, args.workspace)  # 执行只读检查。
    print(json.dumps(result, ensure_ascii=False, indent=2))  # 输出脱敏结果。
    return 0 if result['passed'] else 1  # 有任何问题就阻止下一阶段。

if __name__ == '__main__':  # 导入测试时不自动运行。
    sys.exit(main())  # 正常命令行入口。
