"""目标仓库专用交付工具；Git认证仅通过现有凭据管理器在内存中取得。"""  # 不读取浏览器Cookie。
import argparse  # 仅公开固定交付动作。
import json  # 输出脱敏状态。
import os  # 禁止无意触发交互认证。
from pathlib import Path  # 固定独立源码目录。
import subprocess  # Git凭据由已有GCM处理。
import sys  # 保留失败退出码。
import requests  # 仅调用GitHub官方API。
ROOT = Path(__file__).resolve().parents[1]  # 不操作其他仓库。
OWNER, NAME = 'pancake-github', 'zzu-nscc-helper'  # 当前会话明确批准的唯一目标。

def session():  # 认证内容不进入参数、环境变量或文件。
    environment = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')  # 缺少认证时返回固定错误。
    result = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n', text=True, capture_output=True, env=environment, timeout=30)  # 输出只在内存解析。
    fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line) if result.returncode == 0 else {}  # 不打印GCM输出。
    if not fields.get('password'):  # 不猜测或抓取网页登录凭据。
        raise ValueError('GITHUB_LOGIN_REQUIRED')  # 请求用户处理现有Git登录。
    client = requests.Session()  # 仅在本次短命进程持有认证。
    client.headers.update({'Authorization': 'Bearer ' + fields.pop('password'), 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})  # 只向GitHubAPI发送。
    fields.clear()  # 释放其他凭据引用。
    who = client.get('https://api.github.com/user', timeout=20)  # 核对登录身份。
    if who.status_code != 200 or who.json().get('login') != OWNER:  # 不在错误账号创建仓库。
        raise ValueError('GITHUB_OWNER_MISMATCH')  # 不回显个人用户信息。
    return client  # 调用者负责关闭会话。

def api(client, method, endpoint, **options):  # 路径只由本工具固定动作生成。
    response = client.request(method, 'https://api.github.com' + endpoint, timeout=30, **options)  # 不接收任意外部主机。
    if response.status_code >= 400:  # 原始正文可能包含内部认证或路径信息。
        raise ValueError('GITHUB_HTTP_' + str(response.status_code))  # 只打印固定状态码。
    return response.json() if response.content else {}  # 安全结构供固定字段读取。

def audit():  # 每次源码上传前必须审查实际工作树、暂存和所有历史。
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/audit_public_tree.py')], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')  # 不上传私人日志。
    value = json.loads(result.stdout) if result.returncode == 0 else {}  # 审核失败原样阻止。
    if not value.get('passed'):  # .gitignore不能替代审核。
        raise ValueError('PRIVACY_AUDIT_FAILED')  # 不执行后续远端修改。
    return value  # 仅计数摘要可公开。

def main():  # 自动化可复用的受限交付接口。
    parser = argparse.ArgumentParser(description=__doc__)  # 不接受账号或令牌参数。
    parser.add_argument('action', choices=('create', 'runs', 'artifacts'))  # 正式Release发布另由验收门槛控制。
    args = parser.parse_args()  # 固定无凭据参数。
    with session() as client:  # 进程退出释放凭据。
        base = '/repos/' + OWNER + '/' + NAME  # 唯一允许的仓库。
        if args.action == 'create':  # 初次源码推送前建立开发仓库。
            checked = audit()  # 先审核，再做任何远端变更。
            existing = client.get('https://api.github.com' + base, timeout=20)  # 不覆盖同名未知项目。
            specification = json.loads((ROOT / 'repository.json').read_text(encoding='utf-8'))  # 已批准的公开介绍和关键词。
            if existing.status_code == 404:  # 首次创建，禁止初始化其他内容。
                repo = api(client, 'POST', '/user/repos', json={'name': NAME, 'description': specification['description'], 'private': False, 'auto_init': False, 'has_issues': True, 'has_wiki': False})  # 明确公开开发仓库。
            elif existing.status_code == 200:  # 重入只读取，不擅自改其他仓库。
                repo = existing.json()  # 后续核对固定身份。
                if repo.get('full_name') != OWNER + '/' + NAME or repo.get('private') or repo.get('size', 0):  # 非空仓库不能自动接管。
                    raise ValueError('EXISTING_REPOSITORY_REQUIRES_REVIEW')  # 留待实际远端对照。
            else:  # 无权限或服务异常。
                raise ValueError('GITHUB_HTTP_' + str(existing.status_code))  # 不猜测创建结果。
            api(client, 'PUT', base + '/topics', json={'names': specification['topics']})  # 可检索的公共技术关键词。
            print(json.dumps({'ok': True, 'repository': repo['html_url'], 'privacy_files_checked': checked['export_files']}))  # 无认证信息。
        else:  # 只读构建跟进。
            endpoint = '/actions/runs?per_page=5' if args.action == 'runs' else '/actions/artifacts?per_page=20'  # 不重复触发构建。
            value = api(client, 'GET', base + endpoint)  # 仅读取现有任务。
            keys = ('id', 'name', 'status', 'conclusion', 'head_sha', 'html_url') if args.action == 'runs' else ('id', 'name', 'size_in_bytes', 'expired')  # 输出限定元数据。
            print(json.dumps([{key: item.get(key) for key in keys} for item in value.get('workflow_runs' if args.action == 'runs' else 'artifacts', [])]))  # 不下载或打印原始日志。
    return 0  # 实际失败由退出码表示。

if __name__ == '__main__':  # 导入不连接远端。
    try:  # 不让凭据或HTTP原文进入终端。
        raise SystemExit(main())  # 执行一个固定动作。
    except Exception as error:  # 仅固定类别向外公开。
        allowed = str(error) if type(error) is ValueError and str(error).startswith(('GITHUB_', 'PRIVACY_', 'EXISTING_')) else 'DELIVERY_FAILED'  # 不打印异常堆栈。
        print(json.dumps({'ok': False, 'error': allowed}))  # 只包含固定代码。
        raise SystemExit(1)  # 后续不得误判成功。
