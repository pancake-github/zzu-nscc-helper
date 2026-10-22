"""精确平台分流预览和带冲突检测的本机事务。"""  # 不修改订阅、节点或已有规则内容。
import base64  # 私有备份保存实际原始字节。
from datetime import datetime, timezone  # 私有事务记录使用明确时间。
import hashlib  # 预览与应用之间检查配置变化。
import json  # 私有计划及安全摘要。
import os  # 原子替换本软件负责的文件。
from pathlib import Path  # 限定配置文件范围。
import re  # 识别受支持的增强脚本入口。
import time  # 等待客户端重新生成运行配置。
import uuid  # 每次计划独立身份。
import winreg  # 仅读取系统代理模式。
import yaml  # 本机配置解析，不把原文返回界面。
from .paths import data_root  # 含订阅的备份只能留在用户数据目录。
from .platform import load_platform  # 固定公共平台目标。
from .network import detect_vpn, route_matches  # 稳定接口身份。
from .lifecycle import clients, ClashLifecycle  # 正常退出和重启。
from .controller import query as query_core, ControllerError  # 生效检查读取核心实际状态。

OWNED = ('verge.yaml', 'profiles/Script.js')  # 只允许写这两个文件。
BEGIN, END = '// ZZU-ORIGINAL-BEGIN\n', '// ZZU-ORIGINAL-END\n'  # 无损保留原增强脚本。

class RoutingError(Exception):  # 错误仅允许固定类别。
    pass  # 不把配置正文放入错误信息。

def digest(content):  # 缺失文件与空文件不能混同。
    return hashlib.sha256(content).hexdigest() if content is not None else None  # 用于预览冲突检测。

def safe_path(root, name):  # 不跟随配置目录的重解析点。
    if name not in (*OWNED, 'clash-verge.yaml', 'config.yaml'):  # 拒绝任意文件写入。
        raise RoutingError('UNSUPPORTED_CONFIG_PATH')  # 固定错误类别。
    path = Path(root).absolute() / name  # 在解析前检查每级实际路径。
    if any(node.is_symlink() or node.is_junction() for node in (path, *path.parents)):  # 配置和祖先都拒绝跳转。
        raise RoutingError('REPARSE_POINT')  # 不越过目录边界。
    return path  # 只允许明确的常规路径。

def read(root, name):  # 缺失Script允许稍后新建。
    path = safe_path(root, name)  # 每次读写重新检查边界。
    if not path.exists():  # 只有Script可以不存在。
        if name == 'profiles/Script.js':  # 默认原增强脚本为空逻辑。
            return None  # 备份记为原来不存在。
        raise RoutingError('CONFIG_MISSING')  # 不猜测配置。
    if path.stat().st_size > 16777216:  # 不读取异常巨大配置。
        raise RoutingError('CONFIG_TOO_LARGE')  # 固定上限。
    return path.read_bytes()  # 原始字节留在私有工作进程。

def document(content):  # YAML必须是普通映射。
    value = yaml.safe_load(content) or {}  # 不执行YAML对象。
    if not isinstance(value, dict):  # 数组和标量不是受支持配置。
        raise RoutingError('CONFIG_FORMAT')  # 不输出原内容。
    return value  # 不直接向UI返回此对象。

def controller(runtime):  # 使用实际运行配置，兼容命名管道和HTTP。
    pipe = runtime.get('external-controller-pipe')  # Windows管道不会被错误当作HTTP端口。
    http = runtime.get('external-controller')  # 空字符串不等于启用了HTTP。
    return {'kind': 'pipe' if pipe else 'http' if http else 'disabled', 'endpoint': str(pipe or http or ''), 'secret_present': bool(runtime.get('secret'))}  # 永远不返回secret的值。

def rule_specs():  # 仅平台具体域名和具体IP直连。
    profile = load_platform()  # 经过范围验证的公共预设。
    return ['DOMAIN,' + domain + ',DIRECT' for domain in profile['routing']['dns_domains']] + ['IP-CIDR,' + ip + '/32,DIRECT,no-resolve' for ip in (profile['keepalive']['address'], '172.99.2.103', profile['sftp']['host'], profile['vpn']['gateway'])]  # 不创建宽泛22端口或172网段规则。

def detect(config_root=None):  # 只有本机只读检测，不发平台请求。
    processes = clients()  # 核对真实可执行文件版本。
    candidates = [Path(config_root)] if config_root else [Path(os.environ.get('APPDATA', '')) / 'io.github.clash-verge-rev.clash-verge-rev']  # 可由用户指定便携目录。
    candidates = [path for path in candidates if (path / 'verge.yaml').is_file() and (path / 'clash-verge.yaml').is_file()]  # 不扫描个人订阅目录。
    vpn = detect_vpn()  # 即使Clash未安装仍显示VPN状态。
    result = {'vpn': vpn, 'writable': False, 'clients': processes, 'config_candidates': [str(path) for path in candidates]}  # 不包含配置原文。
    if len(processes) != 1 or len(candidates) != 1:  # 多候选不猜测。
        return {**result, 'error': 'CLASH_NOT_UNIQUE'}  # 仍可导出公共说明。
    root = candidates[0]  # 唯一候选。
    verified_root = Path(os.environ.get('APPDATA', '')) / 'io.github.clash-verge-rev.clash-verge-rev'  # 2.5.8官方app_home_dir使用当前用户data_dir。
    if root.resolve() != verified_root.resolve():  # 自定义目录可能属于旧安装或其他用户。
        return {**result, 'error': 'CONFIG_LOCATION_UNVERIFIED'}  # 可导出说明，但不自动改写未经关联验证的位置。
    runtime, verge = document(read(root, 'clash-verge.yaml')), document(read(root, 'verge.yaml'))  # 仅本进程解析。
    dns = runtime.get('dns') or {}  # 受支持fake-IP配置。
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:  # 不修改系统代理。
        try:  # PAC可能未设置。
            pac = bool(winreg.QueryValueEx(key, 'AutoConfigURL')[0])  # 特殊PAC不自动改写。
        except FileNotFoundError:  # 普通系统代理。
            pac = False  # 无PAC配置。
    error = 'UNSUPPORTED_VERSION' if processes[0]['version'] not in load_platform()['compatibility']['clash_verge_rev_versions'] else 'PAC_UNSUPPORTED' if pac else 'FAKE_IP_UNSUPPORTED' if dns.get('enhanced-mode') != 'fake-ip' or dns.get('fake-ip-filter-mode', 'blacklist') != 'blacklist' else None  # 只接受已知语义。
    if error is None and runtime.get('mode', 'rule') != 'rule':  # 不改变用户选择的全局或直连模式。
        error = 'ROUTING_MODE_UNSUPPORTED'  # 规则模式之外只提供检测和导出。
    if error is None and controller(runtime)['kind'] == 'disabled':  # 无法读取核心状态就不承诺自动生效核验。
        error = 'CONTROLLER_UNAVAILABLE'  # 不擅自开启或改端口。
    return {**result, 'config_root': str(root), 'client': processes[0], 'ports': {key: runtime.get(key) for key in ('mixed-port', 'port', 'socks-port')}, 'controller': controller(runtime), 'system_proxy': verge.get('enable_system_proxy'), 'tun': (runtime.get('tun') or {}).get('enable'), 'writable': error is None, 'error': error}  # 只返回白名单摘要。

def patch_bypass(content, targets):  # 只改一个标量的字符区间，保留其余配置原文。
    text = content.decode('utf-8-sig')  # 支持已有UTF8 BOM。
    tree = yaml.compose(text)  # 获取源文件的准确字符位置。
    if not isinstance(tree, yaml.MappingNode):  # 不支持复杂顶层。
        raise RoutingError('CONFIG_FORMAT')  # 不重写整份YAML。
    matches = [value for key, value in tree.value if key.value == 'system_proxy_bypass']  # 重复键必须拒绝。
    if len(matches) > 1:  # YAML重复键语义不确定。
        raise RoutingError('DUPLICATE_BYPASS')  # 请用户先整理。
    if matches:  # 在原值基础上精确追加。
        node = matches[0]  # 唯一标量。
        if not isinstance(node, yaml.ScalarNode) or node.style in ('|', '>') or '\n' in node.value:  # 不覆盖特殊多行配置。
            raise RoutingError('BYPASS_FORMAT_UNSUPPORTED')  # 仅导出说明。
        existing = node.value.split(';') if node.value else []  # 保留原顺序和所有原条目。
    else:  # 没有用户自定义绕过列表时保留客户端默认规则。
        raise RoutingError('BYPASS_DEFAULTS_UNKNOWN')  # 不假设未知默认值并覆盖。
    missing = [item for item in targets if item.casefold() not in {entry.casefold() for entry in existing}]  # 精确匹配不重复。
    if not missing:  # 已完整包含时不改变字节格式。
        return content, []  # 幂等。
    replacement = json.dumps(';'.join(existing + missing), ensure_ascii=False)  # JSON字符串同样是合法YAML双引号标量。
    updated = text[:node.start_mark.index] + replacement + text[node.end_mark.index:]  # 其他字段包括secret保持原文。
    return updated.encode('utf-8'), missing  # 实际内容仅存私有计划。

def managed_script(content, vpn):  # 将原main放入闭包再调用，不删除原来的逻辑。
    alias = vpn.get('alias', '')  # 来自实际目的接口，不靠固定网卡名。
    if not alias or any(char in alias for char in '#&\r\n'):  # Mihomo绑定语法不能有歧义。
        raise RoutingError('VPN_ALIAS_UNSUPPORTED')  # 不生成无效策略。
    text = content.decode('utf-8-sig') if content is not None else 'function main(config) { return config; } // 原文件不存在，保留默认行为。\n'  # 真实默认入口。
    if '// ZZU-MANAGED-' in text and not text.startswith('// ZZU-MANAGED-2\n'):  # 换行或前缀被修改也不能偷偷套第二层包装。
        raise RoutingError('MANAGED_SCRIPT_CONFLICT')  # 保留整个现有文件。
    if text.startswith('// ZZU-MANAGED-1\n'):  # 重复应用先取回原始逻辑。
        raise RoutingError('MANAGED_SCRIPT_CONFLICT')  # 未发布旧格式缺少完整性信息，不猜测重写。
    if text.startswith('// ZZU-MANAGED-2\n'):  # 新格式明确核对整个受管内容。
        fields = text.split('\n', 2)  # 分离完整性声明和实际代码。
        if len(fields) != 3:  # 截断记录必须明确拒绝。
            raise RoutingError('MANAGED_SCRIPT_CONFLICT')  # 不猜测丢失内容。
        header, signature, body = fields  # 完整三段格式。
        if signature != '// ZZU-SHA256:' + digest(body.encode('utf-8')):  # 人工修改不能被重新生成时丢弃。
            raise RoutingError('MANAGED_SCRIPT_CONFLICT')  # 先供用户人工核对。
        if text.count(BEGIN) != 1 or text.count(END) != 1:  # 被人工修改的包裹层不猜测。
            raise RoutingError('MANAGED_SCRIPT_CONFLICT')  # 需要人工审查。
        text = text.split(BEGIN, 1)[1].split(END, 1)[0]  # 精确保留原主脚本。
    if BEGIN in text or END in text or not re.search(r'\bfunction\s+main\s*\(', text) or re.search(r'\b(?:import|export)\s|\basync\s+function\s+main', text):  # 仅支持客户端正常同步main入口。
        raise RoutingError('SCRIPT_ENTRY_UNSUPPORTED')  # 不擅自替换特殊脚本。
    profile = load_platform()  # 固定精确目标。
    domains = profile['routing']['dns_domains']  # 五个服务域名。
    rules = rule_specs()  # 生成和验收使用同一精确目标集合。
    parameters = json.dumps({'domains': domains, 'dns': 'udp://' + profile['vpn']['dns'] + ':53#' + alias, 'exclude': profile['routing']['tun_exclusions'], 'rules': rules}, ensure_ascii=False)  # 只含平台目标和本机接口别名。
    suffix = [  # 每行脚本同样附带中文说明。
        'return main; // 返回原增强脚本入口。',
        '})(); // 原脚本变量留在自己的闭包内。',
        'function main(config, profileName) { // Clash正常增强脚本入口。',
        '  const c = __zzu_previous(config, profileName); // 先执行原逻辑。',
        '  if (!c || typeof c !== "object") throw new Error("ZZU_ORIGINAL_RESULT"); // 拒绝无效原结果。',
        '  const p = ' + parameters + '; // 当前平台精确增量。',
        '  c.dns = c.dns || {}; // 保留已有DNS字段。',
        '  if ((c.dns["enhanced-mode"] && c.dns["enhanced-mode"] !== "fake-ip") || (c.dns["fake-ip-filter-mode"] || "blacklist") !== "blacklist") throw new Error("ZZU_DNS_MODE"); // 原脚本改变模式时拒绝误配。',
        '  for (const value of [c.dns["fake-ip-filter"], c.tun && c.tun["route-exclude-address"], c.rules]) if (value !== undefined && !Array.isArray(value)) throw new Error("ZZU_LIST_FORMAT"); // 不把标量错误展开为字符。',
        '  c.dns["fake-ip-filter"] = Array.from(new Set([...(c.dns["fake-ip-filter"] || []), ...p.domains])); // 只追加五个域名。',
        '  c.dns["nameserver-policy"] = c.dns["nameserver-policy"] || {}; // 保留其他DNS策略。',
        '  for (const domain of p.domains) c.dns["nameserver-policy"][domain] = p.dns; // 绑定检测到的VPN接口。',
        '  c.tun = c.tun || {}; // 不改变TUN开关。',
        '  c.tun["route-exclude-address"] = Array.from(new Set([...(c.tun["route-exclude-address"] || []), ...p.exclude])); // 仅追加VPN公网入口。',
        '  c.rules = [...p.rules, ...(c.rules || []).filter(rule => !p.rules.includes(rule))]; // 精确规则在前，其他规则原样保留。',
        '  return c; // 不修改本机代理端口、节点或订阅。',
        '} // 完成本平台增量。',
        '// ZZU-MANAGED-END-1',
    ]  # 包裹结构固定，方便复核。
    body = 'const __zzu_previous = (() => { // 隔离原脚本作用域。\n' + BEGIN + text.rstrip('\n') + '\n' + END + '\n'.join(suffix) + '\n'  # 原脚本和增量一并校验。
    return ('// ZZU-MANAGED-2\n// ZZU-SHA256:' + digest(body.encode('utf-8')) + '\n' + body).encode('utf-8')  # 不执行脚本。

def store_path(identity):  # 用户输入不能变成任意私有文件读取。
    if str(uuid.UUID(identity)) != identity:  # 严格规范UUID。
        raise RoutingError('INVALID_PLAN')  # 固定失败。
    return data_root() / 'routing' / (identity + '.json')  # 不位于源码仓库。

def save_plan(plan):  # 备份可能含用户配置，绝不作为公开验收附件。
    path = store_path(plan['id'])  # 自己创建的事务文件。
    path.parent.mkdir(parents=True, exist_ok=True)  # 当前用户数据目录。
    temporary = path.with_name('.plan-' + uuid.uuid4().hex + '.tmp')  # 排他随机文件避免跟随残留链接。
    try:  # 完整写入备份后才允许修改配置。
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:  # 不覆盖其他临时文件。
            json.dump(plan, stream, ensure_ascii=False, indent=2)  # 只在本机留存。
            stream.flush()  # 刷新Python缓冲。
            os.fsync(stream.fileno())  # 原子发布前同步备份。
        os.replace(temporary, path)  # 终态原子写入。
    finally:  # 仅清理本次文件。
        temporary.unlink(missing_ok=True)  # 不删除其他事务材料。

def preview(snapshot):  # 需要当前检测结果，预览不写Clash配置。
    if not snapshot.get('writable'):  # 未知环境不得放行。
        raise RoutingError(snapshot.get('error') or 'READ_ONLY_ENVIRONMENT')  # 不猜测。
    vpn = snapshot['vpn']  # 当前稳定身份。
    if not vpn.get('connected'):  # 必须先检测到接口才能生成绑定DNS策略。
        raise RoutingError('VPN_NOT_CONNECTED')  # 可阅读平台方案，不能应用猜测网卡名。
    root = snapshot['config_root']  # 唯一确认目录。
    original = {name: read(root, name) for name in OWNED}  # 精确白名单。
    bypass, missing = patch_bypass(original['verge.yaml'], load_platform()['routing']['system_proxy_bypass'])  # 仅追加缺少项。
    updates = {'verge.yaml': bypass, 'profiles/Script.js': managed_script(original['profiles/Script.js'], vpn)}  # 保留原脚本逻辑。
    identity = str(uuid.uuid4())  # 每次预览独立。
    files = [{'name': name, 'before': base64.b64encode(original[name]).decode() if original[name] is not None else None, 'before_hash': digest(original[name]), 'after': base64.b64encode(updates[name]).decode(), 'after_hash': digest(updates[name])} for name in OWNED if original[name] != updates[name]]  # 只备份实际改动文件。
    plan = {'schema': 1, 'id': identity, 'created': datetime.now(timezone.utc).isoformat(), 'root': root, 'client': snapshot['client'], 'vpn': vpn, 'switches': {'system_proxy': snapshot['system_proxy'], 'tun': snapshot['tun']}, 'ports': snapshot.get('ports', {}), 'files': files, 'status': 'Previewed'}  # 全文只保存在本机。
    save_plan(plan)  # 此步骤不写Clash。
    return {'id': identity, 'changes': [item['name'] for item in files], 'bypass_added': missing, 'dns_domains': load_platform()['routing']['dns_domains'], 'vpn_alias': vpn['alias'], 'resolver': 'udp://' + load_platform()['vpn']['dns'] + ':53#' + vpn['alias'], 'tun_exclusions': load_platform()['routing']['tun_exclusions'], 'rules': '五个域名与平台、工单、SFTP、VPN入口的精确DIRECT规则', 'restart_required': bool(files)}  # UI只显示自己的增量。

def atomic_write(root, name, content):  # 只写允许文件，同目录原子替换。
    path = safe_path(root, name)  # 每次写入都检查链接。
    path.parent.mkdir(parents=True, exist_ok=True)  # Script目录可能原来不存在。
    if content is None:  # 回滚原来不存在的文件。
        path.unlink(missing_ok=True)  # 只能删除本软件新建且已核对哈希的Script。
        return  # 不删除任何其他文件。
    temporary = path.with_name('.zzu-' + uuid.uuid4().hex + '.tmp')  # 同目录随机临时文件。
    try:  # 写入完成后再替换。
        with temporary.open('xb') as stream:  # 拒绝覆盖已有临时文件。
            stream.write(content)  # 不重序列化其他配置。
            stream.flush()  # 刷新Python缓冲。
            os.fsync(stream.fileno())  # 同步文件内容。
        os.replace(temporary, path)  # 单文件原子发布。
    finally:  # 失败仅清理本次随机文件。
        temporary.unlink(missing_ok=True)  # 不碰其他临时文件。

def decode(value):  # 备份数据保持精确原字节。
    return base64.b64decode(value, validate=True) if value is not None else None  # 损坏备份直接失败。

def load_plan(identity):  # 任何写入前核对完整备份和计划结构。
    try:  # 损坏信息不带入GUI或启动参数。
        plan = json.loads(store_path(identity).read_text(encoding='utf-8'))  # 私有本机记录。
        files = plan['files']  # 两个受支持目标。
        if plan.get('id') != identity or plan.get('schema') != 1 or not isinstance(files, list) or len(files) > len(OWNED) or len({item['name'] for item in files}) != len(files):  # 禁止重复或越界目标。
            raise ValueError()  # 统一损坏类别。
        for item in files:  # 每份字节备份必须匹配自己的摘要。
            if item['name'] not in OWNED or digest(decode(item['before'])) != item['before_hash'] or digest(decode(item['after'])) != item['after_hash'] or item['after'] is None:  # 不写入损坏内容。
                raise ValueError()  # 停止在任何进程动作之前。
        if not Path(plan['root']).is_absolute() or plan['client']['version'] not in load_platform()['compatibility']['clash_verge_rev_versions']:  # 拒绝未知客户端备份或相对位置。
            raise ValueError()  # 不能用旧计划启动不受支持程序。
        return plan  # 完整核对后使用。
    except (OSError, ValueError, KeyError, TypeError):  # 不尝试修复缺失备份。
        raise RoutingError('INVALID_PLAN') from None  # 原始内容不进入日志。

def history():  # 重启后仍可回滚已完成事务，只返回安全摘要。
    rows = []  # 不返回原始配置或控制器密钥。
    folder = data_root() / 'routing'  # 当前用户私有计划目录。
    if folder.is_dir():  # 首次使用没有历史。
        for path in folder.glob('*.json'):  # 仅本软件UUID文件。
            try:  # 单份损坏记录不能当成功。
                if store_path(path.stem) != path or path.is_symlink() or path.is_junction():  # 拒绝不属于事务的文件。
                    continue  # 不读取任意外部内容。
                plan = load_plan(path.stem)  # 损坏备份也要在历史列表中标记，而非仅检查JSON语法。
                if plan.get('schema') == 1 and plan.get('id') == path.stem:  # 版本与身份必须一致。
                    rows.append({'id': plan['id'], 'created': plan.get('created', ''), 'status': plan.get('status', 'Unknown')})  # 不包含原文。
            except (OSError, ValueError, TypeError, RoutingError):  # 损坏文件显式标识，不覆盖。
                rows.append({'id': path.stem, 'created': '', 'status': 'Unreadable'})  # 用户需要核对本机记录。
    return sorted(rows, key=lambda item: item['created'], reverse=True)  # 最新事务在前。

def validate_effect(plan):  # 本机生效检查，不额外访问内网。
    if plan.get('runtime_before_mtime') is not None and safe_path(plan['root'], 'clash-verge.yaml').stat().st_mtime_ns == plan['runtime_before_mtime']:  # 旧文件不能充当重启后证据。
        return False  # 等待Clash生成新运行配置。
    runtime = document(read(plan['root'], 'clash-verge.yaml'))  # Clash重启后生成的真实配置。
    dns, tun = runtime.get('dns') or {}, runtime.get('tun') or {}  # 仅核对本方案负责字段。
    domains = load_platform()['routing']['dns_domains']  # 固定五个域名。
    resolver = 'udp://' + load_platform()['vpn']['dns'] + ':53#' + plan['vpn']['alias']  # 当前计划绑定接口。
    verge = document(read(plan['root'], 'verge.yaml'))  # 核对客户端开关和绕过配置。
    bypass = set(str(verge.get('system_proxy_bypass') or '').split(';'))  # 精确条目检查。
    required = set(load_platform()['routing']['system_proxy_bypass'])  # 不把通配规则当精确成功。
    proxy_ok = verge.get('enable_system_proxy') == plan['switches']['system_proxy'] and required.issubset(bypass)  # 保留原系统代理开关。
    if plan['switches']['system_proxy']:  # 启用系统代理时还检查实际WinINET状态。
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:  # 仅读取实际生效结果。
            enabled = winreg.QueryValueEx(key, 'ProxyEnable')[0]  # 不能把配置写入当开关生效。
            active_bypass = winreg.QueryValueEx(key, 'ProxyOverride')[0]  # 不读密码或订阅。
        proxy_ok = proxy_ok and bool(enabled) and required.issubset(set(active_bypass.split(';')))  # 精确核对系统层。
    running = clients()  # 重启后必须确实有对应GUI进程。
    process_ok = len(running) == 1 and Path(running[0]['exe']) == Path(plan['client']['exe'])  # 不接受其他Clash程序。
    file_ok = process_ok and proxy_ok and runtime.get('mode', 'rule') == 'rule' and dns.get('enhanced-mode') == 'fake-ip' and dns.get('fake-ip-filter-mode', 'blacklist') == 'blacklist' and all(runtime.get(key) == value for key, value in plan.get('ports', {}).items()) and runtime.get('rules', [])[:len(rule_specs())] == rule_specs() and set(domains).issubset(dns.get('fake-ip-filter') or []) and all((dns.get('nameserver-policy') or {}).get(domain) in (resolver, [resolver]) for domain in domains) and '222.22.12.2/32' in (tun.get('route-exclude-address') or []) and tun.get('enable') == plan['switches']['tun']  # 各配置层分别核对。
    if not file_ok:  # 文件条件不满足时不发送无意义核心查询。
        return False  # 等待新配置或进入失败恢复。
    general, rules = query_core(runtime, '/configs'), query_core(runtime, '/rules').get('rules', [])  # 只读本机API，不访问超算。
    expected_rules = [('Domain', domain) for domain in domains] + [('IPCIDR', rule.split(',')[1]) for rule in rule_specs()[len(domains):]]  # 与生成器独立核对核心规则类型和值。
    core_tun = general.get('tun') or {}  # API返回的实际TUN配置。
    return general.get('mode', 'rule') == 'rule' and all((general.get(key) or 0) == (value or 0) for key, value in plan.get('ports', {}).items()) and core_tun.get('enable', False) == bool(plan['switches']['tun']) and (not plan['switches']['tun'] or '222.22.12.2/32' in (core_tun.get('route-exclude-address') or [])) and len(rules) >= len(expected_rules) and all(row.get('type') == kind and row.get('payload') == payload and row.get('proxy') == 'DIRECT' and not (row.get('extra') or {}).get('disabled', False) for row, (kind, payload) in zip(rules, expected_rules))  # 核心实际加载内容、开关和规则启用状态也必须匹配。

def transact(identity, rollback=False, lifecycle_factory=ClashLifecycle, validator=validate_effect, validation_timeout=20):  # 可注入离线生命周期测试，不接触实际Clash。
    plan = load_plan(identity)  # 备份损坏时先停止，不请求退出Clash。
    if plan['status'] not in (('Applied', 'AppliedPendingVPN') if rollback else ('Previewed',)):  # 事务不可重复或错序执行。
        raise RoutingError('PLAN_STATE')  # 重新预览才可再次应用。
    expected, target = ('after_hash', 'before') if rollback else ('before_hash', 'after')  # 回滚只接受本软件写入的当前内容。
    def unchanged():  # 退出客户端前后都检查。
        return all(digest(read(plan['root'], item['name'])) == item[expected] for item in plan['files'])  # 人工修改不能被覆盖。
    if not unchanged():  # 预览后已发生变化。
        raise RoutingError('CONFIG_CONFLICT')  # 保留当前内容。
    if not plan['files']:  # 幂等重用同一配置时不重启Clash。
        return {'id': identity, 'status': 'NoChanges'}  # 没有真实修改就没有回滚范围。
    running = clients()  # 每次应用或回滚重新核对当前进程，不能复用重启前PID。
    if len(running) > 1 or running and (Path(running[0]['exe']).resolve() != Path(plan['client']['exe']).resolve() or running[0]['version'] != plan['client']['version']):  # 其他安装或已升级版本不能沿用旧计划。
        raise RoutingError('CLASH_IDENTITY_CHANGED')  # 不请求退出或写入。
    life = lifecycle_factory(running[0] if running else plan['client'])  # 没有运行进程时按原路径恢复启动。
    if not life.stop():  # 正常退出失败绝不强杀。
        raise RoutingError('WAIT_FOR_CLASH_EXIT')  # 请用户退出后重新检测。
    written = []  # 精确记录本次写入范围。
    try:  # 无论成功失败都尝试重启原程序。
        if not unchanged():  # Clash退出时可能保存内存配置。
            raise RoutingError('CONFIG_CHANGED_ON_EXIT')  # 重新预览避免丢改动。
        runtime_path = safe_path(plan['root'], 'clash-verge.yaml')  # 记录旧运行文件的身份。
        plan['runtime_before_mtime'] = runtime_path.stat().st_mtime_ns if runtime_path.is_file() else None  # 测试夹具可注入验证器，不依赖真实核心。
        plan['status'] = 'WritingRollback' if rollback else 'Writing'  # 写入前保存原始备份及事务状态。
        save_plan(plan)  # 崩溃后仍有可核对的证据。
        for item in plan['files']:  # 只修改预览确认的文件。
            if digest(read(plan['root'], item['name'])) != item[expected]:  # 写每个文件前也防止外部并发修改。
                raise RoutingError('CONFIG_CONFLICT')  # 已写项目会按事务边界恢复。
            atomic_write(plan['root'], item['name'], decode(item[target]))  # 精确原字节写入。
            written.append(item)  # 失败恢复仅针对实际写入文件。
        life.restart()  # 客户端重新生成配置。
        if not rollback:  # 应用后检查自己新增的运行规则。
            deadline = time.monotonic() + validation_timeout  # 不无限等待。
            while True:  # 重启初期运行配置可能短暂不可读。
                try:  # 等待生成完整运行配置。
                    if validator(plan):  # 全部本机条件通过。
                        break  # 完成验证。
                except (OSError, ValueError, yaml.YAMLError, RoutingError, ControllerError):  # 核心启动暂未就绪也需等待。
                    pass  # 到期限再报告失败。
                if time.monotonic() >= deadline:  # 超过等待期限。
                    raise RoutingError('EFFECT_VALIDATION_FAILED')  # 不假报成功。
                time.sleep(0.5)  # 后台进程等待，不阻塞GUI。
        plan['status'] = 'RolledBack' if rollback else 'Applied' if route_matches(plan['vpn']['guid']) else 'AppliedPendingVPN'  # VPN退出不伪造联网成功。
        save_plan(plan)  # 保存实际终态。
        return {'id': identity, 'status': plan['status']}  # 不返回配置原文。
    except Exception as error:  # 部分写入不能留成成功状态。
        if not written:  # 退出时外部保存了新配置，不能谎称已经恢复原文件。
            plan['status'] = 'Rejected'  # 当前内容完全保留。
            save_plan(plan)  # 该计划不能再次应用。
            raise RoutingError(str(error) if isinstance(error, RoutingError) else 'TRANSACTION_FAILED') from None  # 只保留固定错误码。
        conflicts = []  # 后续人工修改不得被恢复覆盖。
        if written and not life.stopped:  # 已重启时必须再次正常退出才恢复。
            current = clients()  # 新进程具有新的身份。
            if len(current) != 1 or Path(current[0]['exe']) != Path(plan['client']['exe']):  # 不能确认就保留现场。
                conflicts = [item['name'] for item in written]  # 明确恢复未确认。
            else:  # 使用新身份再次正常退出。
                life = lifecycle_factory(current[0])  # 不复用已退出的PID。
                if not life.stop():  # 拒绝强杀。
                    conflicts = [item['name'] for item in written]  # 留给人工恢复。
        for item in reversed(written):  # 只回退尚未发生后续变更的文件。
            if conflicts or digest(read(plan['root'], item['name'])) != digest(decode(item[target])):  # 不覆盖外部改动。
                conflicts.append(item['name'])  # 记录冲突文件名。
            else:  # 仍是本事务写入内容。
                try:  # 恢复也可能遇到磁盘或权限错误。
                    atomic_write(plan['root'], item['name'], decode(item['after'] if rollback else item['before']))  # 恢复事务前内容。
                except OSError:  # 不声称实际失败的恢复已经完成。
                    conflicts.append(item['name'])  # 原备份留待人工核对。
        plan['status'] = 'RecoveryConflict' if conflicts else 'FailedRestored'  # 不误报失败恢复成功。
        save_plan(plan)  # 保留备份供核查。
        raise RoutingError(plan['status']) from None  # 不把原异常中的配置带到UI。
    finally:  # 退出失败之外，尽力恢复客户端运行。
        life.restart()  # 此方法只在确实停止后启动一次。
