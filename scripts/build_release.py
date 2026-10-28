"""仅在隔离Windows构建环境生成公共运行库、按需组件和两个安装器。"""  # 不读取开发者AppData。
import argparse  # 构建参数只指定固定工具位置。
import hashlib  # 所有下载和载荷都固定校验。
import importlib.metadata as metadata  # 记录实际构建依赖。
import io  # 只在内存读取经过哈希校验的上游源码包。
import json  # 版本化构建元数据。
from pathlib import Path  # 构建产物全部限制在仓库dist内。
import shutil  # 从已审计源码白名单复制。
import subprocess  # 不使用shell执行工具。
import sys  # 仅使用CI当前解释器。
import tarfile  # 读取固定许可证成员，不解压任意路径。
import urllib.request  # 获取固定版本的公开对应源码索引。
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
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'  # 使用官方构建解释器自带的完整许可与版权声明。
    if not python_license.is_file():  # 不以项目GPL代替Python许可。
        raise ValueError('PYTHON_LICENSE_MISSING')  # 缺少分发材料时阻止打包。
    (licenses / 'Python').mkdir(exist_ok=True)  # 与第三方发行包分开命名。
    shutil.copy2(python_license, licenses / 'Python/LICENSE.txt')  # 原样附带全部解释器许可。
    dependencies = []  # 按实际安装版本生成物料清单。
    source_index = json.loads((ROOT / 'packaging/runtime-sources.json').read_text(encoding='utf-8'))  # 已独立核验的Python及Qt对应源码。
    for dist in sorted(metadata.distributions(), key=lambda item: item.metadata['Name'].casefold()):  # CI为此项目的隔离环境。
        distribution = dist.metadata['Name']  # 公开软件包名。
        dependencies.append({'name': distribution, 'version': dist.version})  # 不收录环境变量或镜像凭据。
        if distribution.casefold().replace('_', '-') != 'pyqt5-qt5':  # Qt运行库使用官方Qt完整源码，不误认为只有包装轮子。
            with urllib.request.urlopen('https://pypi.org/pypi/' + distribution + '/' + dist.version + '/json', timeout=30) as response:  # 官方固定发行元数据。
                info = json.load(response)  # 不执行第三方代码。
            sources = [{'url': entry['url'], 'sha256': entry['digests']['sha256']} for entry in info['urls'] if entry['packagetype'] == 'sdist']  # 对应版本实际源代码归档与哈希。
            if sources:  # 没有源码归档的包装轮子由明确运行库源代码条目覆盖。
                source_index['sources'].append({'name': distribution, 'version': dist.version, 'archives': sources})  # 不包含个人路径或认证。
            if distribution.casefold() == 'pyqt5':  # 此版本Windows轮子未携带LICENSE文件，必须从同版源码补齐。
                source = sources[0]  # 同版官方PyPI元数据确定的源码与SHA256。
                if not source['url'].startswith('https://files.pythonhosted.org/'):  # 不将元数据当任意下载指令。
                    raise ValueError('PYQT_SOURCE_HOST_INVALID')  # 只允许官方包分发主机。
                with urllib.request.urlopen(source['url'], timeout=30) as response:  # 构建时下载，不影响用户现有Python。
                    body = response.read(64 * 1024 * 1024 + 1)  # 有界读取，避免异常大小。
                if len(body) > 64 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != source['sha256']:  # 对照官方同版源码哈希。
                    raise ValueError('PYQT_SOURCE_HASH_FAILED')  # 不接受未知许可材料。
                with tarfile.open(fileobj=io.BytesIO(body), mode='r:*') as archive_source:  # 不向磁盘解压源码树。
                    member = archive_source.getmember('PyQt5-' + dist.version + '/LICENSE')  # 只读取明确根目录许可。
                    if not member.isfile() or member.size > 1024 * 1024:  # 不跟随链接或读取异常材料。
                        raise ValueError('PYQT_LICENSE_INVALID')  # 阻止发布缺失许可的包。
                    (licenses / 'PyQt5').mkdir(exist_ok=True)  # 实际分发包专属目录。
                    (licenses / 'PyQt5/LICENSE').write_bytes(archive_source.extractfile(member).read())  # 保留上游原始GPL全文。
        for item in dist.files or ():  # 只复制许可证和版权文件。
            if Path(item).name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):  # 不复制包缓存或其他项目数据。
                source = Path(dist.locate_file(item))  # 来自已安装发行包。
                if source.is_file():  # 部分元数据可能引用缺失文件。
                    target = licenses / distribution / Path(item).name  # 文件名限定在各软件包目录。
                    target.parent.mkdir(parents=True, exist_ok=True)  # 不包含用户名。
                    if not target.exists():  # 不覆盖同一包已有版权文件。
                        shutil.copy2(source, target)  # 原文保留。
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()  # 固定产物与实际公开源码的对应关系。
    (core / 'build-info.json').write_text(json.dumps({'schema': 1, 'version': SETTINGS['version'], 'source_commit': commit, 'dependencies': dependencies}, indent=2), encoding='utf-8')  # 可公开、无本机账号。
    (core / 'corresponding-sources.json').write_text(json.dumps(source_index, ensure_ascii=False, indent=2), encoding='utf-8')  # 安装目录提供确切版本和源码获取位置。
    extension_version = json.loads((ROOT / 'src/zzu_nscc_helper/keepalive/extension/manifest.json').read_text(encoding='utf-8'))['version']  # 从实际扩展读取版本。
    if extension_version != SETTINGS['extension_version']:  # 打包目标与源码不一致必须阻止。
        raise ValueError('EXTENSION_VERSION_MISMATCH')  # 不将旧扩展混入新安装器。
    manifest = {'schema': 1, 'version': SETTINGS['version'], 'tag': SETTINGS['tag'], 'extension_version': extension_version, 'units': {}}  # 两种安装器共用明确组件版本。
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
    parser.add_argument('--iscc', type=Path)  # 完整构建需要已校验的Inno编译器。
    parser.add_argument('--native-only', action='store_true')  # 回归前仅编译同一连接程序。
    args = parser.parse_args()  # 不接收任意源码目录。
    native = ROOT / 'src/zzu_nscc_helper/keepalive/native_host.exe'  # 此文件被Git忽略。
    subprocess.run([str(Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')), '/nologo', '/target:exe', '/debug-', '/out:' + str(native), str(native.with_name('NativeHost.cs'))], check=True)  # 原生主机从本次源码编译。
    if args.native_only:  # 源码回归不需要先安装打包工具。
        return 0  # 使用相同的绝对Windows路径，避免旧csc误解析正斜杠。
    if args.iscc is None:  # 不猜测本机安装的编译器。
        parser.error('完整构建必须指定--iscc。')  # 不启动不完整的构建。
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', str(ROOT / 'packaging/helper.spec')], cwd=ROOT, check=True)  # 使用隔离CI环境。
    output, manifest = payloads()  # 不扫描开发者目录。
    compile_installers(output, manifest, args.iscc)  # 每个下载哈希嵌入安装器。
    return 0  # 后续隐私审核和测试独立判定。

if __name__ == '__main__':  # 导入可独立测试载荷规则。
    raise SystemExit(main())  # 构建失败立即中止。
