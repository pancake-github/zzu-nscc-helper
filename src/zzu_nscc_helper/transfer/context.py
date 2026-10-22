"""单工作进程的取消和进度上下文；不保存认证信息。"""  # 默认离线测试没有副作用。
import threading  # 取消标志跨stdin接收线程共享。
import time  # 限制进度消息频率。

class Cancelled(Exception):  # 清理逻辑仍由每个文件事务的finally执行。
    pass  # 不含密码或路径。

cancelled = threading.Event()  # 一个进程只执行一个批次。
notify = lambda message: None  # 命令行调用不要求GUI接收器。
last_progress = 0.0  # 避免每个小块都刷界面。
total_bytes = 0  # 当前批次实际处理字节。

def check():  # 在枚举、数据块和发布之前检查。
    if cancelled.is_set():  # 不继续写下一项。
        raise Cancelled('CANCELLED')  # 不把取消当成功。

def advance(count):  # 仅发送数量，不发送文件内容。
    global total_bytes, last_progress  # 状态仅存在本工作进程。
    check()  # 每个块都能响应取消。
    total_bytes += count  # 上传回读也计入处理流量。
    now = time.monotonic()  # 墙上时间变更不影响频率。
    if now - last_progress >= 0.25:  # 每秒最多四条。
        notify({'event': 'progress', 'bytes': total_bytes})  # 不包含账号或口令。
        last_progress = now  # 下一次进度基准。

class Output:  # 下载时包装已排他创建的临时文件。
    def __init__(self, stream):  # 不按路径再次打开文件。
        self.stream = stream  # 保留原始文件对象。
    def write(self, block):  # Paramiko通过此处写入数据。
        check()  # 写入前可以停止。
        written = self.stream.write(block)  # 保持原有写入语义。
        advance(written)  # 记录实际写入字节。
        return written  # 与原始流接口相同。
    def __getattr__(self, name):  # flush、tell等接口继续转发。
        return getattr(self.stream, name)  # 不复制文件内容。
