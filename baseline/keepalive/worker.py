"""隔离的单次请求进程；真实 HTTPS 与模拟模式明确区分。"""  # GUI 默认使用真实模式。
import json  # 输出不含敏感内容的结果。
import sys  # 读取模拟模式参数。
import time  # 模拟请求延迟。

def validate_response(status, body, marker):  # 供将来正式请求与当前测试共享。
    if status != 200:  # 首版不允许重定向或错误状态。
        return 'HTTP_STATUS'  # 不接受代理错误页。
    if not body:  # 必须确实读取数据。
        return 'EMPTY_BODY'  # 空响应不算成功。
    if len(body) > 65536:  # 响应体大小限制。
        return 'BODY_TOO_LARGE'  # 避免意外大文件传输。
    if not marker or marker not in body:  # 必须有平台确认的内容特征。
        return 'CONTENT_MISMATCH'  # 不接受任意二百响应。
    return None  # 验证成功。

def run(mode):  # 参数仅允许固定模拟场景。
    started = time.monotonic()  # 记录耗时。
    if mode == 'live':  # 明确选择才发送真实只读请求。
        from live_request import perform  # 模拟测试不导入或发送网络请求。
        return perform()  # 真实请求通过后才报告成功。
    if mode == 'timeout':  # 测试父进程硬超时和清理。
        time.sleep(60)  # 父进程应在二十秒内终止本进程。
    elif mode == 'success':  # 成功模拟完全不访问网络。
        time.sleep(0.2)  # 保持异步界面行为可见。
        return {'ok': True, 'bytes': 32, 'elapsed': time.monotonic() - started}  # 明确为模拟数据。
    elif mode == 'failure':  # 模拟网络异常。
        return {'ok': False, 'error': 'SIMULATED_FAILURE'}  # 不输出异常原文。
    return {'ok': False, 'error': 'INVALID_MODE'}  # 未知参数不执行。

if __name__ == '__main__':  # 独立进程入口。
    print(json.dumps(run(sys.argv[1] if len(sys.argv) == 2 else ''), ensure_ascii=True))  # 输出单条机器可读结果。
