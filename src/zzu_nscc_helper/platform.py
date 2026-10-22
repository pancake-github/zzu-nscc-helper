"""加载郑州超算的公开平台资源，禁止混入用户凭据或其他平台配置。"""  # 不查询系统、不发网络请求。
import base64  # 校验公开主机密钥。
import hashlib  # 独立计算SSH指纹。
import json  # 读取版本化平台预设。
from pathlib import Path  # 源码及打包资源均以模块位置定位。

DATA = Path(__file__).resolve().parent / 'data'  # 不依赖盘符、用户名或当前工作目录。
DOMAINS = frozenset(('eshell01.v.zzu.edu.cn', 'ai01.v.zzu.edu.cn', 'hpc01.v.zzu.edu.cn', 'efile02.v.zzu.edu.cn', 'efile01.v.zzu.edu.cn'))  # 首版限定五个已核对服务。
FORBIDDEN = frozenset(('user', 'username', 'password', 'secret', 'token', 'subscription', 'interface_alias', 'interface_guid', 'local_proxy_port'))  # 本机状态与账户不得嵌入公共平台资源。

def validate_profile(profile):  # 对仓库自带预设进行严格校验。
    if not isinstance(profile, dict) or profile.get('schema_version') != 1 or profile.get('id') != 'zzdx-nscc':  # 首版只有一个实际支持的平台。
        raise ValueError('不支持的平台预设或资源版本。')  # 不冒充通用超算工具。
    def check_keys(value):  # 递归检查所有嵌套字段。
        if isinstance(value, dict):  # JSON对象可以携带意外凭据。
            if FORBIDDEN.intersection(value):  # 检查固定敏感字段。
                raise ValueError('公共平台预设不得包含账户或本机配置。')  # 在任何调用前拒绝。
            for item in value.values():  # 检查下层对象。
                check_keys(item)  # 不遗漏列表中的对象。
        elif isinstance(value, list):  # 检查数组内数据。
            for item in value:  # 顺序不影响验证。
                check_keys(item)  # 保持相同字段边界。
    check_keys(profile)  # 先确保资源没有个人信息。
    vpn, ssh, live, routing = (profile[name] for name in ('vpn', 'sftp', 'keepalive', 'routing'))  # 需要真实、完整的四类配置。
    if vpn['gateway'] != '222.22.12.2' or vpn['gateway_port'] != 6443 or vpn['dns'] != '172.99.2.11':  # 固定本平台接入身份。
        raise ValueError('VPN入口与本平台预设不一致。')  # 不自动扩展其他入口。
    if ssh['host'] != '172.99.1.100' or ssh['port'] != 22 or ssh['host_key_resource'] != 'known_hosts':  # 传输入口和资源名必须确定。
        raise ValueError('SFTP入口与本平台预设不一致。')  # 不接受凭据目标替换。
    if live['address'] != '172.99.2.7' or live['tls_name'] != 'v.zzu.edu.cn' or live['resource'] != '/ac/console3/index.html':  # 沿用已真实核验的HTTPS目标。
        raise ValueError('HTTPS目标与已核验平台不一致。')  # 不接受任意URL。
    if (live['interval_seconds'], live['connect_timeout_seconds'], live['total_timeout_seconds'], live['body_limit_bytes']) != (780, 5, 20, 65536):  # 固定已约定频率和上限。
        raise ValueError('保活参数不符合首版约定。')  # 不因安装组件选择改变频率。
    if live['status'] != 200 or live['content_markers'] != ['ac-ui', 'id="app"', '/sso/themes/sso/favicon.ico']:  # 不能把任意响应计为成功。
        raise ValueError('响应判据与已核验内容不一致。')  # 保持真实验证边界。
    if set(routing['dns_domains']) != DOMAINS or set(routing['fake_ip_exclusions']) != DOMAINS:  # 仅允许五个完整域名。
        raise ValueError('域名分流范围与本平台不一致。')  # 不接受通配扩大。
    bypass = set(routing['system_proxy_bypass'])  # 系统代理层使用自己的精确目标。
    if bypass != DOMAINS | {'172.99.2.7', '172.99.2.103', '222.22.12.2'} or routing['tun_exclusions'] != ['222.22.12.2/32']:  # 不把系统代理绕过与TUN排除混为一谈。
        raise ValueError('代理绕过或TUN排除范围不正确。')  # 拒绝宽泛172网段规则。
    return profile  # 已校验内容仍是普通JSON对象，方便后续跨进程传输。

def verify_host_key(profile):  # 本地独立校验公钥与固定指纹。
    path = DATA / profile['sftp']['host_key_resource']  # 资源名经过上面的严格校验。
    lines = path.read_text(encoding='ascii').splitlines()  # 仅读取平台公钥，不读取个人known_hosts。
    if len(lines) != 1:  # 不允许捎带其他主机记录。
        raise ValueError('主机公钥资源必须只包含本平台一个身份。')  # 明确拒绝多余记录。
    parts = lines[0].split()  # OpenSSH公钥格式。
    if len(parts) != 3 or parts[:2] != [profile['sftp']['host'], 'ssh-ed25519']:  # 只接受指定主机及算法。
        raise ValueError('主机公钥格式或服务器身份不匹配。')  # 不自动信任新算法。
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(parts[2], validate=True)).digest()).decode().rstrip('=')  # 按SSH标准计算指纹。
    if fingerprint != profile['sftp']['host_key_fingerprint']:  # 与公开预设核对。
        raise ValueError('主机公钥指纹不一致。')  # 密钥变化需要人工核对平台。
    return path  # 交给后续SSH客户端的本应用专用公钥资源。

def load_platform():  # 正式默认预设入口。
    profile = validate_profile(json.loads((DATA / 'zzdx-nscc.json').read_text(encoding='utf-8')))  # 不从网络更新预设。
    verify_host_key(profile)  # 资源不一致时不返回可连接配置。
    return profile  # 用户名、密码、网卡与端口由运行时另行获取。
