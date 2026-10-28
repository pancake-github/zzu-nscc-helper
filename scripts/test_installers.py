"""在临时Windows构建机器测试两个真实安装器的七种组件组合。"""  # 不测试平台网络。
import argparse  # 接收固定构建产物目录。
import hashlib  # 保证安装器在测试中未改变。
import itertools  # 七个非空组合。
import json  # 脱敏安装验收记录。
import os  # 只修改本测试进程及其子进程的环境。
from pathlib import Path  # 测试安装目录与个人文件隔离。
import subprocess  # 不调用用户Python执行已安装软件。
import tempfile  # 每一轮独立临时安装位置。
from audit_release import extension_payload  # 共用真实载荷版本与哈希核对。

def check_installed_extension(root, expected):  # 确认安装后的文件，而不是仅检查源码或压缩包。
    folder = root / 'modules/zzu_nscc_helper/keepalive/extension'  # 标准安装目录。
    if json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))['version'] != expected['version']:  # 旧组件不能混入新版安装。
        raise ValueError('INSTALLED_EXTENSION_VERSION_MISMATCH')  # 不报告安装矩阵通过。
    if any(hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest for name, digest in expected['sha256'].items()):  # 同版本但旧脚本也必须拒绝。
        raise ValueError('INSTALLED_EXTENSION_CONTENT_MISMATCH')  # 版本号和实际功能同时核验。

def execute(command, **options):  # 超时、失败保留真实错误码。
    completed = subprocess.run(command, capture_output=True, timeout=240, creationflags=subprocess.CREATE_NO_WINDOW, **options)  # 只运行本次安装器或其EXE。
    if completed.returncode:  # 日志只留固定类别，不打印安装目录或原始输出。
        try:  # 本产品维护EXE只有受限JSON输出。
            value = json.loads(completed.stdout.decode('utf-8'))  # 不打印任意安装器文本。
            diagnostic = {key: value[key] for key in ('ok', 'error', 'exception_type', 'missing_module', 'components', 'external_python_modules', 'external_native_libraries', 'frozen', 'tabs', 'workers_running') if key in value}  # 不包含目录、账户或正文。
            print(json.dumps({'command': Path(command[0]).name, 'diagnostic': diagnostic}))  # 保留可修复的技术原因。
        except (ValueError, UnicodeError, TypeError):  # 安装器没有JSON时不回显原始输出。
            pass  # 只由下面固定代码报告。
        raise ValueError('INSTALLER_COMMAND_FAILED_' + str(completed.returncode))  # 不将失败忽略。
    return completed  # 自检结果在内存中解析。

def public_online_smoke(output):  # 发布后从真实GitHub地址下载组件，不使用本地载荷缓存。
    manifest = json.loads((output / 'payload-manifest.json').read_text(encoding='utf-8'))  # 工作流已验证整个公开资产集合。
    extension = extension_payload(output, manifest)  # 本轮必须安装的真实扩展字节。
    installer = output / ('zzu-nscc-helper-online-' + manifest['version'] + '-x64.exe')  # 与公开发布完全相同的安装器。
    with tempfile.TemporaryDirectory(prefix='zzu-public-online-') as temporary:  # 不访问任何真实用户配置。
        root = Path(temporary) / 'program'  # 一次性CI安装路径。
        environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONHOME='', PYTHONPATH='', LOCALAPPDATA=str(Path(temporary) / 'local-data'))  # 隔离运行数据。
        environment['PATH'] = str(Path(os.environ['WINDIR']) / 'System32')  # 不通过PATH借用Python。
        try:  # 任何失败都清理本轮注册。
            execute([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/DIR=' + str(root), '/COMPONENTS=keepalive,routing,sftp', '/TASKS='], env=environment)  # 故意不传PAYLOADDIR，实际访问安装器内嵌GitHub链接。
            check_installed_extension(root, extension)  # 真实下载后核对0.4.1及完整脚本。
            result = json.loads(execute([str(root / 'zzu-nscc-maintenance.exe'), 'self-test'], env=environment).stdout.decode('utf-8'))  # 验证下载运行库可独立启动。
            if not result['ok'] or result['components'] != ['keepalive', 'routing', 'sftp'] or result['external_python_modules']: raise ValueError('PUBLIC_ONLINE_SELF_TEST_FAILED')  # 不能只看安装器退出码。
            execute([str(root / 'zzu-nscc-helper.exe'), '--preview', '--smoke-test'], env=environment)  # 只启动预览，不请求平台。
        finally:  # 仅卸载本轮临时软件。
            if (root / 'unins000.exe').is_file(): execute([str(root / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], env=environment)  # 不影响用户主安装。
    report = {'passed':True, 'version':manifest['version'], 'extension_version':extension['version'], 'installer_sha256':hashlib.sha256(installer.read_bytes()).hexdigest(), 'online_source':'public_github_release', 'components':['keepalive', 'routing', 'sftp'], 'uninstalled':True, 'real_platform_tested':False, 'clean_windows11_tested':False}  # Windows云机器不是用户干净Win11。
    (output / 'public-online-installation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')  # 独立报告，不改已发布SHA清单。
    print(json.dumps(report))  # 不输出路径、凭据或网络正文。
    return 0  # 公网下载和安装流程实际通过。

def main():  # CI使用一次性机器，不能在个人机器偷偷执行整套安装。
    parser = argparse.ArgumentParser(description=__doc__)  # 不接收凭据。
    parser.add_argument('folder', type=Path)  # 已审计构建输出。
    parser.add_argument('--public-online', action='store_true')  # 发布后独立验收真实在线下载路径。
    args = parser.parse_args()  # 实际产物目录。
    if os.environ.get('GITHUB_ACTIONS') != 'true':  # 自动矩阵仅限一次性CI机器。
        raise ValueError('DISPOSABLE_CI_REQUIRED')  # 本机实测另用明确专用流程。
    output = args.folder.resolve()  # 对路径进行归一化。
    if args.public_online: return public_online_smoke(output)  # 不重复十四轮缓存矩阵或修改发布资产。
    manifest = json.loads((output / 'payload-manifest.json').read_text(encoding='utf-8'))  # 测试实际构建清单。
    version = manifest['version']  # 本轮软件版本。
    extension = extension_payload(output, manifest)  # 固定安装后必须匹配的组件。
    combinations = [part for count in (1, 2, 3) for part in itertools.combinations(('keepalive', 'routing', 'sftp'), count)]  # 七种组合完整覆盖。
    records = []  # 只公开技术结果，不公开机器用户目录。
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONHOME='', PYTHONPATH='')  # 清空外部Python导入配置。
    environment['PATH'] = str(Path(os.environ['WINDIR']) / 'System32')  # 已安装EXE无法通过PATH寻找Python。
    for kind in ('offline', 'online'):  # 测试与最终发布相同字节的两个安装器。
        installer = output / ('zzu-nscc-helper-' + kind + '-' + version + '-x64.exe')  # 固定文件名。
        digest = hashlib.sha256(installer.read_bytes()).hexdigest()  # 与发布清单相同。
        for selected in combinations:  # 每轮全新目录，避免其他组件掩盖缺失依赖。
            with tempfile.TemporaryDirectory(prefix='zzu-install-') as temporary:  # 不放入用户个人资料。
                root = Path(temporary) / 'program'  # 确定的测试安装位置。
                private = Path(temporary) / 'local-data'  # 注册迁移备份只在此轮保存。
                environment['LOCALAPPDATA'] = str(private)  # 仅影响本次子进程。
                command = [str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/DIR=' + str(root), '/COMPONENTS=' + ','.join(selected), '/TASKS=']  # 不创建桌面入口。
                if kind == 'online':  # Release未发布前，用固定哈希缓存验证同一个在线安装器。
                    command.append('/PAYLOADDIR=' + str(output))  # 不关闭TLS或篡改目标地址。
                installed = False  # 失败时也尝试撤销自己的注册。
                try:  # 不留下影响下一个组合的注册状态。
                    execute(command, env=environment)  # 安装器执行真实解压和迁移逻辑。
                    installed = True  # 卸载程序此时应已存在。
                    result = execute([str(root / 'zzu-nscc-maintenance.exe'), 'self-test'], env=environment)  # 使用真正冻结EXE启动GUI控件。
                    value = json.loads(result.stdout.decode('utf-8'))  # 不依赖外部解释器。
                    if not value['ok'] or tuple(value['components']) != selected or value['external_python_modules']:  # 必须真实加载所选模块。
                        raise ValueError('FROZEN_SELF_TEST_FAILED')  # 不误报无依赖。
                    actual = json.loads((root / 'components.json').read_text(encoding='utf-8'))  # 核对落盘选择。
                    if actual != {'schema': 1, 'components': list(selected)}:  # 不接受默认全部。
                        raise ValueError('INSTALLED_COMPONENTS_MISMATCH')  # 明确失败。
                    execute([str(root / 'zzu-nscc-helper.exe'), '--preview', '--smoke-test'], env=environment)  # 真正运行GUI EXE并验证正常退出。
                    for component, relative in {'keepalive': 'keepalive', 'routing': 'routing.py', 'sftp': 'transfer'}.items():  # 未选组件必须实际不存在。
                        if (root / 'modules/zzu_nscc_helper' / relative).exists() != (component in selected):  # 不靠隐藏标签页冒充组件安装。
                            raise ValueError('UNSELECTED_COMPONENT_INSTALLED')  # 阻止发布。
                    if 'keepalive' in selected: check_installed_extension(root, extension)  # 每种含保活的组合都验证实际安装的扩展。
                    records.append({'kind': kind, 'components': list(selected), 'passed': True, 'installer_sha256': digest, 'extension_version': extension['version'] if 'keepalive' in selected else None, 'external_python_modules': 0, 'online_source': 'verified_local_cache' if kind == 'online' else 'embedded_payloads'})  # 不能将缓存测试称为GitHub真实下载测试。
                finally:  # 只卸载本轮实际生成的产品。
                    uninstaller = root / 'unins000.exe'  # 不搜索其他安装。
                    if uninstaller.is_file():  # 即使后置注册失败也尝试撤销。
                        execute([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], env=environment)  # 仅保留本轮私有记录，临时根由标准库清理。
    safety = []  # 升级、保留用户资料和坏载荷分别记录。
    for kind in ('offline', 'online'):  # 单独验证覆盖旧扩展时无需额外补丁。
        with tempfile.TemporaryDirectory(prefix='zzu-extension-upgrade-') as temporary:  # 仅使用一次性CI目录。
            root = Path(temporary) / 'program'  # 本轮唯一测试安装。
            environment['LOCALAPPDATA'] = str(Path(temporary) / 'local-data')  # 私有数据隔离。
            installer = output / ('zzu-nscc-helper-' + kind + '-' + version + '-x64.exe')  # 相同待发布字节。
            command = [str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/DIR=' + str(root), '/COMPONENTS=keepalive', '/TASKS=']  # 只测保活升级。
            if kind == 'online': command.append('/PAYLOADDIR=' + str(output))  # 发布前仍使用校验缓存。
            try:  # 无论成功失败都清理本轮注册。
                execute(command, env=environment)  # 建立一个正常旧组件测试容器。
                folder = root / 'modules/zzu_nscc_helper/keepalive/extension'  # 确定的组件目录。
                old = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))  # 仅改模拟目录中的版本。
                old['version'] = '0.4.0'  # 合成旧组件，不借用用户浏览器。
                (folder / 'manifest.json').write_text(json.dumps(old), encoding='utf-8')  # 模拟安装目录仍有旧manifest。
                (folder / 'background.js').write_text('// synthetic older extension\n', encoding='utf-8')  # 模拟旧脚本内容。
                execute(command, env=environment)  # 原位安装必须覆盖旧组件。
                check_installed_extension(root, extension)  # 版本和脚本完整哈希同时一致才通过。
                safety.append({'kind': kind, 'case': 'replace_synthetic_legacy_extension', 'passed': True, 'extension_version': extension['version']})  # 不冒充完整旧版到新版迁移实测。
            finally:  # 不留下本轮Native Messaging注册。
                if (root / 'unins000.exe').is_file(): execute([str(root / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], env=environment)  # 仅卸载本轮临时产品。
    for kind in ('offline', 'online'):  # 两种安装器都必须能添加组件。
        with tempfile.TemporaryDirectory(prefix='zzu-upgrade-') as temporary:  # 与十四轮新装隔离。
            root = Path(temporary) / 'program'  # 本轮唯一安装目录。
            private = Path(temporary) / 'local-data'  # 本轮私有数据。
            environment['LOCALAPPDATA'] = str(private)  # 仅传给受控子进程。
            installer = output / ('zzu-nscc-helper-' + kind + '-' + version + '-x64.exe')  # 相同被测字节。
            common = [str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/DIR=' + str(root), '/TASKS=']  # 不启动GUI或平台请求。
            if kind == 'online':  # 发布前使用同一固定哈希缓存。
                common.append('/PAYLOADDIR=' + str(output))  # 不换包、不重新编译测试版。
            try:  # 成功或失败都回收本轮安装。
                execute(common + ['/COMPONENTS=routing'], env=environment)  # 首次仅装分流。
                marker = private / 'ZZU-NSCC-Helper/backups/preserve-user-data.txt'  # 合成本机备份材料。
                marker.parent.mkdir(parents=True, exist_ok=True)  # 只创建测试私有目录。
                marker.write_bytes(b'preserve synthetic local data')  # 不是真实用户配置。
                execute(common + ['/COMPONENTS=routing,sftp'], env=environment)  # 升级添加SFTP。
                checked = json.loads(execute([str(root / 'zzu-nscc-maintenance.exe'), 'self-test'], env=environment).stdout.decode('utf-8'))  # 加载真实冻结组件。
                if not checked['ok'] or checked['components'] != ['routing', 'sftp'] or marker.read_bytes() != b'preserve synthetic local data':  # 不丢组件或私有资料。
                    raise ValueError('UPGRADE_ADD_COMPONENT_FAILED')  # 不发布半通过结果。
                before = (root / 'components.json').read_bytes()  # 被拒绝的静默移除不得改变既有清单。
                refused = subprocess.run(common + ['/COMPONENTS=routing'], capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW, env=environment)  # 只操作本次临时安装。
                if refused.returncode == 0 or (root / 'components.json').read_bytes() != before or not (root / 'modules/zzu_nscc_helper/transfer/nscc_download.py').is_file():  # 不能只隐藏仍在磁盘的组件。
                    raise ValueError('SILENT_COMPONENT_REMOVAL_NOT_BLOCKED')  # 静默路径必须和交互路径一致。
            finally:  # 不遗留注册和卸载项。
                if (root / 'unins000.exe').is_file():  # 仅运行自己的卸载器。
                    execute([str(root / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], env=environment)  # 不删除私有备份。
            if marker.read_bytes() != b'preserve synthetic local data':  # 卸载也必须保留资料。
                raise ValueError('UNINSTALL_REMOVED_PRIVATE_DATA')  # 明确失败。
            safety.append({'kind': kind, 'case': 'upgrade_add_component_and_preserve_private_data', 'passed': True, 'silent_component_removal_blocked': True})  # 无私人路径。
    with tempfile.TemporaryDirectory(prefix='zzu-broken-payload-') as temporary:  # 模拟下载不完整或缓存损坏。
        root = Path(temporary) / 'program'  # 不影响任何已安装软件。
        cache = Path(temporary) / 'cache'  # 本轮故障材料。
        cache.mkdir()  # 不复制其他项目数据。
        (cache / 'core.zip').write_bytes(b'incomplete synthetic payload')  # 故意不符合内嵌SHA-256。
        environment['LOCALAPPDATA'] = str(Path(temporary) / 'local-data')  # 只影响子进程。
        installer = output / ('zzu-nscc-helper-online-' + version + '-x64.exe')  # 同一在线安装器。
        failed = subprocess.run([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/DIR=' + str(root), '/COMPONENTS=routing', '/TASKS=', '/PAYLOADDIR=' + str(cache)], capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW, env=environment)  # 校验失败应在写入程序之前停止。
        if failed.returncode == 0 or (root / 'components.json').exists() or (root / 'zzu-nscc-helper.exe').exists():  # 不允许损坏载荷变成有效安装。
            raise ValueError('INVALID_PAYLOAD_NOT_BLOCKED')  # 明确阻止发布。
        safety.append({'kind': 'online', 'case': 'incomplete_or_corrupt_payload_rejected_before_install', 'passed': True})  # 不将此项冒充强制断电验收。
    report = {'schema': 1, 'status': 'component_matrix_passed', 'cases': records, 'safety_cases': safety, 'real_platform_tested': False, 'clean_windows11_tested': False, 'online_github_download_tested': False, 'abrupt_power_loss_tested': False}  # 精确声明测试边界。
    (output / 'installer-matrix.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')  # 可公开的计数和哈希。
    sums = [hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name for path in sorted(output.iterdir()) if path.is_file() and path.name != 'SHA256SUMS.txt']  # 新验收摘要也纳入发布清单。
    (output / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='ascii')  # 产物测试后再次固化。
    print(json.dumps({'passed': True, 'installation_cases': len(records)}))  # 不输出本机路径。
    return 0  # 真实平台测试仍在用户本机进行。

if __name__ == '__main__':  # 导入不会执行安装。
    raise SystemExit(main())  # 固定测试入口。
