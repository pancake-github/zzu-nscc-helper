"""区分只读程序资源和本机私有数据；运行数据不进入源码仓库。"""  # 不包含开发者路径。
import os  # 获取当前用户系统目录。
from pathlib import Path  # 以实际位置定位。
import sys  # 识别源码与打包运行。

def data_root():  # 所有私有设置、日志、配置备份使用同一根目录。
    base = os.environ.get('LOCALAPPDATA')  # Windows为当前用户提供的实际位置。
    if not base:  # 不在未知位置保存私有内容。
        raise RuntimeError('未找到当前用户本地数据目录。')  # 不回退到仓库或当前目录。
    return Path(base).resolve() / 'ZZU-NSCC-Helper'  # 不依赖本机用户名或盘符。

def worker_command():  # 使用打包工作程序，源码模式则用同一解释器。
    if getattr(sys, 'frozen', False):  # 安装版不能寻找用户的Python。
        return [str(Path(sys.executable).resolve().parent / 'zzu-nscc-worker.exe')]  # 后续构建的独立后台入口。
    return [sys.executable, '-X', 'utf8', str(Path(__file__).resolve().parents[2] / 'worker_entry.py')]  # 源码入口自行定位src。
