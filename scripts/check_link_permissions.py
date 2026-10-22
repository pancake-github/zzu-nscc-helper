"""仅补验上传和下载的真实目录符号链接保护；不联网、不修改系统策略。"""  # 专用提权入口。
import argparse  # 输出位置必须由本机启动器明确提供。
import contextlib  # 测试原始路径不写入公共记录。
import ctypes  # 确认本次测试确实获得临时管理员令牌。
from datetime import datetime, timezone  # 保存可核验的UTC时间。
import io  # 暂存在内存中的测试详情。
import json  # 输出仅包含计数及固定类别的记录。
import os  # 记录测试进程身份。
from pathlib import Path  # 限定源码与结果位置。
import sys  # 加载已有融合测试。
import tempfile  # 核验本次临时目录已清理。
import unittest  # 不安装测试依赖。

def main():  # 此入口绝不接收账号、密码或任意测试名称。
    parser = argparse.ArgumentParser(description=__doc__)  # 只允许输出参数。
    parser.add_argument('--output', type=Path, required=True)  # 私有验收记录的实际位置。
    args = parser.parse_args()  # 解析无凭据参数。
    root = Path(__file__).resolve().parents[1]  # 固定为本仓库源码。
    if args.output.resolve().is_relative_to(root):  # 原始本机验收记录不得进入公开仓库。
        raise ValueError('结果必须保存到公开源码目录之外。')  # 写入前拒绝。
    elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())  # 仅检查令牌，不改变权限。
    started = datetime.now(timezone.utc).isoformat()  # 保留真实起点。
    if not elevated:  # 不把再次跳过冒充权限问题已解决。
        result = {'schema': 1, 'started_utc': started, 'elevated': False, 'passed': False, 'error': 'ADMIN_TOKEN_REQUIRED'}  # 明确未补验。
    else:  # 仅管理员子进程运行以下两个固定离线用例。
        sys.path.insert(0, str(root / 'tests'))  # 不安装或修改开发环境。
        import test_stage2 as fixtures  # 已有适配将用例指向活跃融合核心。
        created = []  # 仅追踪本进程自己创建的测试目录。
        original = tempfile.TemporaryDirectory  # 保留标准库原始入口。
        def tracked(*values, **options):  # 不改变测试目录的生命周期。
            item = original(*values, **options)  # 由标准库创建隔离目录。
            created.append(Path(item.name))  # 只在私有进程内保留路径。
            return item  # 原有测试负责清理。
        tempfile.TemporaryDirectory = tracked  # 仅影响本次短命测试进程。
        cases = unittest.TestSuite([fixtures.DOWNLOAD_TESTS.DownloadBehaviorTests('test_local_directory_symlink_is_rejected_when_available'), fixtures.UPLOAD_TESTS.UploadBehaviorTests('test_local_symbolic_directory_link_is_never_followed_when_available')])  # 不允许运行其他测试或任务。
        stream = io.StringIO()  # 路径或异常原文不进入公开摘要。
        try:  # 无论断言结果如何恢复标准库入口。
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):  # 测试不会弹出网络或认证界面。
                outcome = unittest.TextTestRunner(stream=stream, verbosity=2).run(cases)  # 实际创建并拒绝跟随两种目录链接。
        finally:  # 标准库对象不留在改变后的状态。
            tempfile.TemporaryDirectory = original  # 恢复测试进程内入口。
        clean = bool(created) and all(not item.exists() for item in created)  # 核验整个测试根目录确实已删除。
        result = {'schema': 1, 'started_utc': started, 'finished_utc': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(), 'elevated': elevated, 'run': outcome.testsRun, 'failed': len(outcome.failures) + len(outcome.errors), 'skipped': len(outcome.skipped), 'temporary_roots': len(created), 'temporary_roots_cleaned': clean, 'passed': outcome.wasSuccessful() and not outcome.skipped and outcome.testsRun == 2 and clean, 'network_requests': 0, 'system_policy_changed': False}  # 结果不含个人路径或认证信息。
    args.output.parent.mkdir(parents=True, exist_ok=True)  # 只创建已授权的私有验收目录。
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')  # 输出实际结果。
    return 0 if result['passed'] else 1  # 未通过时不能进入已补验状态。

if __name__ == '__main__':  # 导入不会提权或运行测试。
    sys.exit(main())  # 由外部启动器请求一次UAC。
