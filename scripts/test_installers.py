"""在临时Windows构建机器测试两个真实安装器的七种组件组合。"""  # 不测试平台网络。
import argparse  # 接收固定构建产物目录。
import hashlib  # 保证安装器在测试中未改变。
import itertools  # 七个非空组合。
import json  # 脱敏安装验收记录。
import os  # 只修改本测试进程及其子进程的环境。
from pathlib import Path  # 测试安装目录与个人文件隔离。
import subprocess  # 不调用用户Python执行已安装软件。
import tempfile  # 每一轮独立临时安装位置。

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

def main():  # CI使用一次性机器，不能在个人机器偷偷执行整套安装。
    parser = argparse.ArgumentParser(description=__doc__)  # 不接收凭据。
    parser.add_argument('folder', type=Path)  # 已审计构建输出。
    args = parser.parse_args()  # 实际产物目录。
    if os.environ.get('GITHUB_ACTIONS') != 'true':  # 自动矩阵仅限一次性CI机器。
        raise ValueError('DISPOSABLE_CI_REQUIRED')  # 本机实测另用明确专用流程。
    output = args.folder.resolve()  # 对路径进行归一化。
    version = json.loads((output / 'payload-manifest.json').read_text(encoding='utf-8'))['version']  # 测试实际构建版本。
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
                    records.append({'kind': kind, 'components': list(selected), 'passed': True, 'installer_sha256': digest, 'external_python_modules': 0, 'online_source': 'verified_local_cache' if kind == 'online' else 'embedded_payloads'})  # 不能将缓存测试称为GitHub真实下载测试。
                finally:  # 只卸载本轮实际生成的产品。
                    uninstaller = root / 'unins000.exe'  # 不搜索其他安装。
                    if uninstaller.is_file():  # 即使后置注册失败也尝试撤销。
                        execute([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], env=environment)  # 仅保留本轮私有记录，临时根由标准库清理。
    report = {'schema': 1, 'status': 'component_matrix_passed', 'cases': records, 'real_platform_tested': False, 'clean_windows11_tested': False, 'online_github_download_tested': False}  # 精确声明测试边界。
    (output / 'installer-matrix.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')  # 可公开的计数和哈希。
    sums = [hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name for path in sorted(output.iterdir()) if path.is_file() and path.name != 'SHA256SUMS.txt']  # 新验收摘要也纳入发布清单。
    (output / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='ascii')  # 产物测试后再次固化。
    print(json.dumps({'passed': True, 'installation_cases': len(records)}))  # 不输出本机路径。
    return 0  # 真实平台测试仍在用户本机进行。

if __name__ == '__main__':  # 导入不会执行安装。
    raise SystemExit(main())  # 固定测试入口。
