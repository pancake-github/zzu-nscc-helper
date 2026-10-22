"""源码模式的独立工作进程入口，不接受命令行凭据。"""  # 安装版使用独立EXE。
from pathlib import Path  # 不依赖当前目录。
import sys  # 仅修改当前子进程的导入路径。
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))  # 源码与GUI共用实际模块。
from zzu_nscc_helper.worker import main  # 不在导入前读取任务或密码。
if __name__ == '__main__':  # 测试导入时不运行。
    sys.exit(main())  # 任务从私有标准输入读取。
