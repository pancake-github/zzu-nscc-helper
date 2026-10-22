"""仅在隔离Windows构建环境生成公共运行库、按需组件和两个安装器。"""  # 不读取开发者AppData。
import argparse  # 构建参数只指定固定工具位置。
import hashlib  # 所有下载和载荷都固定校验。
import importlib.metadata as metadata  # 记录实际构建依赖。
import json  # 版本化构建元数据。
from pathlib import Path  # 构建产物全部限制在仓库dist内。
import shutil  # 从已审计源码白名单复制。
import subprocess  # 不使用shell执行工具。
import sys  # 仅使用CI当前解释器。
import zipfile  # 生成可独立校验的组件包。
ROOT = Path(__file__).resolve().parents[1]  # 独立发布仓库。
SETTINGS = json.loads((ROOT / 'packaging/build-settings.json').read_text(encoding='utf-8'))  # 固定目标仓库及版本。
PARTS = {'keepalive': ('keepalive',), 'routing': ('routing.py', 'controller.py', 'lifecycle.py'), 'sftp': ('transfer',)}  # 未选择组件不进入公共PYZ。

def archive(folder, destination):  # ZIP只包含显式构造的发布树。
    total = 0  # 安装器显示实际解压大小。
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as stream:  # 不遍历整个工作区。
        for path in sorted(folder.rglob('*')):  # 只枚举本次独立构建树。
            if path.is_symlink() or path.is_junction():  # 构建输入也拒绝链接。
                raise ValueError('BUILD_LINK_REJECTED')  # 不打包目录之外的数据。
            if path.is_file():  # 空目录由实际载荷需要决定。
                name = path.relative_to(folder).as_posix()  # 压缩包无绝对路径。
                stream.write(path, name)  # 全部来自已审计源码或CI运行库。
                total += path.stat().st_size  # 使用真实大小。
    return {'file': destination.name, 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(), 'bytes': destination.stat().st_size, 'uncompressed_bytes': total}  # 不记录本机路径。

def payloads():  # 已完成PyInstaller构建后拆分载荷。
    output = ROOT / 'dist/release'  # 只维护本产品的构建目录。
    output.mkdir(parents=True, exist_ok=True)  # 不删除现有未知目录。
    core = ROOT / 'dist/zzu-nscc-helper'  # PyInstaller固定输出。
    for name in ('LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md'):  # 用户安装后可查看许可证和说明。
        shutil.copy2(ROOT / name, core / name)  # 不复制个人文档。
    licenses = core / 'licenses'  # 安装包自带第三方版权说明。
    licenses.mkdir(exist_ok=True)  # 构建目录内可重复生成。
    dependencies = []  # 按实际安装版本生成物料清单。
    for dist in sorted(metadata.distributions(), key=lambda item: item.metadata['Name'].casefold()):  # CI为此项目的隔离环境。
        distribution = dist.metadata['Name']  # 公开软件包名。
        dependencies.append({'name': distribution, 'version': dist.version})  # 不收录环境变量或镜像凭据。
        for item in dist.files or ():  # 只复制许可证和版权文件。
            if Path(item).name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):  # 不复制包缓存或其他项目数据。
                source = Path(dist.locate_file(item))  # 来自已安装发行包。
                if source.is_file():  # 部分元数据可能引用缺失文件。
                    target = licenses / distribution / Path(item).name  # 文件名限定在各软件包目录。
                    target.parent.mkdir(parents=True, exist_ok=True)  # 不包含用户名。
                    if not target.exists():  # 不覆盖同一包已有版权文件。
                        shutil.copy2(source, target)  # 原文保留。
    (core / 'build-info.json').write_text(json.dumps({'schema': 1, 'version': SETTINGS['version'], 'dependencies': dependencies}, indent=2), encoding='utf-8')  # 可公开、无本机账号。
    manifest = {'schema': 1, 'version': SETTINGS['version'], 'tag': SETTINGS['tag'], 'units': {}}  # 安装器的固定版本清单。
    manifest['units']['core'] = archive(core, output / 'core.zip')  # 公共运行库只打包一次。
    module_root = ROOT / 'src/zzu_nscc_helper'  # 唯一业务源码输入。
    for name, entries in PARTS.items():  # 三个可独立下载的组件。
        staging = ROOT / 'build/payloads' / name  # 构建暂存与源码隔离。
        if staging.exists():  # 不递归删除可能来自其他运行的目录。
            raise ValueError('PAYLOAD_STAGING_EXISTS')  # 需要新干净构建任务。
        target = staging / 'modules/zzu_nscc_helper'  # 固定命名空间。
        target.mkdir(parents=True)  # 只创建本次暂存树。
        for entry in entries:  # 不靠任意glob打包工作区。
            source = module_root / entry  # 固定组件源。
            if source.is_dir():  # 保留包相对层级。
                shutil.copytree(source, target / entry, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pdb'))  # 不复制缓存或调试路径。
            else:  # 分流由三个明确模块组成。
                shutil.copy2(source, target / entry)  # 保留公共已审计代码。
        manifest['units'][name] = archive(staging, output / (name + '.zip'))  # 组件校验独立。
    extension = ROOT / 'build/extension-package'  # 用户手动加载一次的公开扩展。
    shutil.copytree(module_root / 'keepalive/extension', extension)  # 不包含浏览器个人配置。
    archive(extension, output / ('zzu-nscc-helper-edge-' + SETTINGS['version'] + '.zip'))  # 独立扩展资产。
    (output / 'payload-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')  # SHA256固化到安装器。
    return output, manifest  # 安装器只消费这些产物。

def compile_installers(output, manifest, compiler):  # 在线和离线版来自相同载荷与源码。
    entries = []  # 给Inno生成无凭据的文件声明。
    for unit, item in manifest['units'].items():  # 固定四个载荷。
        component = '' if unit == 'core' else '; Components: ' + unit  # 公共运行库必需，其他按选择。
        entries.extend(['#ifndef Online', 'Source: "' + str(output / item['file']) + '"; Flags: dontcopy', '#endif', 'Source: "{tmp}\\' + item['file'] + '"; DestDir: "{app}"; ExternalSize: ' + str(item['uncompressed_bytes']) + '; Hash: "' + item['sha256'] + '"; Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs' + component])  # 校验通过后才解压。
    generated = ROOT / 'build/payloads.iss'  # 构建路径不进入公开源码。
    generated.write_text('\n'.join(entries) + '\n', encoding='utf-8')  # 使用真实换行。
    constants = ['#define Payload_' + unit + ' "' + item['sha256'] + '"' for unit, item in manifest['units'].items()]  # 每次构建独立哈希。
    (ROOT / 'build/hashes.iss').write_text('\n'.join(constants) + '\n', encoding='utf-8')  # 不使用占位校验值。
    for online in (False, True):  # 两种安装器均编译和后续实测。
        command = [str(compiler), '/Qp', '/DReleaseVersion=' + SETTINGS['version'], '/DReleaseTag=' + SETTINGS['tag'], '/DOutputFolder=' + str(output)]  # 不含用户凭据。
        if online:  # 在线版不内嵌任何载荷。
            command.append('/DOnline=1')  # 仅运行时下载选中组件。
        subprocess.run(command + [str(ROOT / 'packaging/setup.iss')], check=True)  # 无shell、保留退出码。
    sums = [hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name for path in sorted(output.iterdir()) if path.is_file() and path.name != 'SHA256SUMS.txt']  # 包括安装器与组件。
    (output / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='ascii')  # 发布后逐项回读核验。

def main():  # 仅CI调用，不安装到开发者环境。
    parser = argparse.ArgumentParser(description=__doc__)  # 固定构建流程。
    parser.add_argument('--iscc', type=Path, required=True)  # 已校验的Inno编译器。
    args = parser.parse_args()  # 不接收任意源码目录。
    native = ROOT / 'src/zzu_nscc_helper/keepalive/native_host.exe'  # 此文件被Git忽略。
    subprocess.run([str(Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')), '/nologo', '/target:exe', '/debug-', '/out:' + str(native), str(native.with_name('NativeHost.cs'))], check=True)  # 原生主机从本次源码编译。
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', str(ROOT / 'packaging/helper.spec')], cwd=ROOT, check=True)  # 使用隔离CI环境。
    output, manifest = payloads()  # 不扫描开发者目录。
    compile_installers(output, manifest, args.iscc)  # 每个下载哈希嵌入安装器。
    return 0  # 后续隐私审核和测试独立判定。

if __name__ == '__main__':  # 导入可独立测试载荷规则。
    raise SystemExit(main())  # 构建失败立即中止。
