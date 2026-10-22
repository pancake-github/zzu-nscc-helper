"""郑州超算助手共享入口；组件代码按安装选择加载。"""  # 正式可用性以发布验收为准。
from pathlib import Path  # 已安装组件只从本安装目录加载。
import sys  # 区分源码与冻结程序。
__version__ = '0.5.0b1'  # 候选测试版编号；通过全部验收才发布Release。
if getattr(sys, 'frozen', False):  # 冻结公共运行库不包含未选组件的业务实现。
    __path__.append(str(Path(sys.executable).resolve().parent / 'modules' / 'zzu_nscc_helper'))  # 不查询任意环境路径或用户Python。
