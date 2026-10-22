"""从PyPI官方发行元数据生成固定版本、固定轮子哈希的CI依赖锁。"""  # 不执行pip安装。
import json  # 解析公开软件包元数据。
from pathlib import Path  # 只更新本仓库构建锁。
import urllib.request  # 仅访问PyPI官方HTTPS入口。
ROOT = Path(__file__).resolve().parents[1]  # 固定源码目录。

def main():  # 更新锁后必须重新审查及回归。
    lines = ['# 由scripts/lock_build.py生成；CI使用--require-hashes及--only-binary=:all:。']  # 不允许隐式安装未锁定依赖。
    count = 0  # 只输出包数。
    for line in (ROOT / 'packaging/requirements-build.txt').read_text(encoding='utf-8').splitlines():  # 人工审核过的精确版本。
        line = line.strip()  # 忽略空白和注释。
        if not line or line.startswith('#'):  # 无安装内容。
            continue  # 不访问其他地址。
        name, version = line.split('==')  # 不接受URL或非固定版本。
        if not all(character.isalnum() or character in '._-' for character in name + version):  # 不拼接任意URL路径。
            raise ValueError('INVALID_PIN')  # 写锁前拒绝。
        with urllib.request.urlopen('https://pypi.org/pypi/' + name + '/' + version + '/json', timeout=20) as response:  # 证书校验使用系统Python默认配置。
            info = json.load(response)  # 仅公开发行信息。
        digests = sorted({entry['digests']['sha256'] for entry in info['urls'] if entry['packagetype'] == 'bdist_wheel'})  # CI不执行源代码包构建。
        if not digests:  # Windows构建不能退回未知源码安装。
            raise ValueError('NO_BINARY_WHEELS')  # 不生成半份锁。
        lines.append(line + ' \\')  # pip标准带哈希格式。
        lines.extend('    --hash=sha256:' + digest + (' \\' if index < len(digests) - 1 else '') for index, digest in enumerate(digests))  # 只允许官方发行的固定字节。
        count += 1  # 不收录本机环境。
    (ROOT / 'packaging/requirements-build.lock').write_text('\n'.join(lines) + '\n', encoding='utf-8')  # 全部成功后一次写入。
    print(json.dumps({'locked_packages': count}))  # 无认证或私人路径。

if __name__ == '__main__':  # 导入不访问网络。
    main()  # 手动更新构建锁时调用。
