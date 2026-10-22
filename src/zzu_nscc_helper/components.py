"""安装组件选择规则；在线与离线安装器共用同一契约。"""  # 此模块完全离线。
COMPONENTS = ('keepalive', 'routing', 'sftp')  # 按固定顺序展示三个可独立安装的功能。
LABELS = {'keepalive': 'VPN保活', 'routing': 'Clash分流', 'sftp': 'SFTP传输'}  # 统一中文名称。

def normalize_selection(values):  # 输入组件编号序列，输出稳定且去重的选择。
    if isinstance(values, (str, bytes)):  # 单个字符串不能误当作字符列表。
        raise ValueError('组件选择必须是列表。')  # 不猜测调用者意图。
    chosen = set(values)  # 对重复选择只保留一次。
    if not chosen:  # 安装器至少需要一项功能。
        raise ValueError('请至少选择一项安装组件。')  # 不产生空安装。
    if not chosen.issubset(COMPONENTS):  # 未知组件不能作为远程加载入口。
        raise ValueError('存在未知安装组件。')  # 仅允许本产品的三个功能。
    return tuple(name for name in COMPONENTS if name in chosen)  # 多种输入顺序得到相同结果。

def download_units(values):  # 计算按需下载集合，不执行下载。
    return ('core',) + normalize_selection(values)  # 公共运行库一次下载，其他组件仅按选择加入。
