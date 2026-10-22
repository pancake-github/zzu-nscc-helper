"""源码入口；安装版由PyInstaller使用相同main函数。"""  # 不写个人解释器路径。
from pathlib import Path  # 根据实际源码位置加载。
import sys  # 同一运行环境。
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))  # 只影响当前进程。
from zzu_nscc_helper.gui import main  # 导入不启动传输。
if __name__ == '__main__':  # 避免测试导入自动弹窗。
    sys.exit(main())  # 正常应用入口。
