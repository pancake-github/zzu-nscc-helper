"""三个冻结程序共用入口，按实际EXE文件名选择固定职责。"""  # 不接收任意模块名。
from pathlib import Path  # 不依赖工作目录。
import sys  # 获取真实安装程序名称。
name = Path(sys.executable).stem.casefold()  # 只允许构建时声明的三个名称。
if name == 'zzu-nscc-worker':  # 网络后台拥有独立进程与私有标准输入。
    from zzu_nscc_helper.worker import main  # 公共任务分发器。
elif name == 'zzu-nscc-maintenance':  # 安装、卸载和离线自检不建立平台连接。
    from zzu_nscc_helper.installation import main  # 固定维护动作。
elif name == 'zzu-nscc-helper':  # 正常桌面入口。
    from zzu_nscc_helper.gui import main  # 用户主动开始任务。
else:  # 被改名的入口不获得其他能力。
    raise SystemExit(2)  # 明确拒绝。
raise SystemExit(main())  # 保留真实退出码。
