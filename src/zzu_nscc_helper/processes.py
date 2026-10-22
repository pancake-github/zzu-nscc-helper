"""GUI与后台工作进程之间使用私有匿名管道，不把凭据放进命令行。"""  # 不记录任务正文。
import json  # 有界JSON消息。
from PyQt5.QtCore import QObject, QProcess, QTimer, pyqtSignal  # Qt异步进程和信号。
from .paths import worker_command  # 源码与安装版共用启动方式。

def prepare_process(process, request):  # 创建者负责start，便于保留已有保活状态机。
    command = worker_command()  # 命令行只有入口，没有账户密码。
    process.setProgram(command[0])  # 不经shell。
    process.setArguments(command[1:])  # 私有任务另走stdin。
    packet = bytearray(json.dumps(request, ensure_ascii=True).encode() + b'\n')  # 只在内存中编码。
    def deliver():  # 不把密码留在长期信号闭包中。
        process.write(bytes(packet))  # 写入Qt专属匿名管道。
        packet[:] = b'\0' * len(packet)  # 尽早覆盖本程序的可变副本。
        packet.clear()  # 不声称能覆盖解释器或Qt内部全部副本。
        process.started.disconnect(deliver)  # 释放一次性闭包。
    process.started.connect(deliver)  # 进程建立后交付一次。

class WorkerTask(QObject):  # SFTP和分流各有一个控制器，不互相取消。
    progress_event = pyqtSignal(dict)  # 进度和逐项结果。
    completed = pyqtSignal(dict)  # 固定终态，不返回原始异常。
    changed = pyqtSignal(bool)  # 主界面用于互斥控制。
    def __init__(self, parent=None):  # 初始没有后台进程。
        super().__init__(parent)  # 跟随GUI生命周期。
        self.process = None  # 单任务运行。
        self.buffer = b''  # 有界输出缓冲。
        self.result = None  # 等工作进程退出再发布终态。
        self.cancelled = False  # 区分手动取消。
        self.protocol_failed = False  # 无效输出不能被之前的成功结果掩盖。
        self.deadline = QTimer(self)  # 不阻塞GUI。
        self.deadline.setSingleShot(True)  # 每个任务只有一个截止。
        self.deadline.timeout.connect(self.force_stop)  # 工作进程异常时可清理。

    @property  # GUI读取任务状态。
    def busy(self):  # 以实际进程引用为准。
        return self.process is not None  # 不靠按钮状态判断。

    def start(self, task, payload, auth=None, timeout_ms=0):  # 密码只存在本次请求内存中。
        if self.busy:  # 禁止同一控制器并发。
            raise RuntimeError('任务仍在运行。')  # 不创建第二个工作进程。
        self.buffer, self.result, self.cancelled = b'', None, False  # 不复用上次数据。
        self.protocol_failed = False  # 每批独立协议状态。
        process = QProcess(self)  # Windows Qt默认不创建可见控制台。
        self.process = process  # 固定信号身份。
        request = {'task': task, 'payload': payload}  # 普通任务参数。
        if auth is not None:  # 只对SFTP提供当次认证。
            request['auth'] = auth  # 不保存为设置或日志。
        prepare_process(process, request)  # 私有标准输入。
        process.readyReadStandardOutput.connect(lambda: self.read(process))  # 持续读取小事件。
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())  # 丢弃原始错误，避免凭据回显。
        process.finished.connect(lambda code, status: self.finish(process, code))  # 必须核对实际退出。
        process.errorOccurred.connect(lambda error: self.finish(process, -1) if error == QProcess.FailedToStart else None)  # 启动失败也有终态。
        if timeout_ms:  # SFTP由网络超时和取消控制，短任务可设硬截止。
            self.deadline.start(timeout_ms)  # 从启动前开始计时。
        self.changed.emit(True)  # 让其他功能检查互斥。
        process.start()  # 异步启动。

    def read(self, process):  # 每条消息最大256KiB。
        if process is not self.process:  # 不处理旧进程信号。
            return  # 不污染新任务。
        self.buffer += bytes(process.readAllStandardOutput())  # 子进程标准输出不进入日志。
        while b'\n' in self.buffer:  # 允许分批消息。
            line, self.buffer = self.buffer.split(b'\n', 1)  # 提取完整帧。
            if len(line) > 262144:  # 防止异常输出拖垮界面。
                self.protocol_failed = True  # 丢弃可能已保存的成功终态。
                self.force_stop()  # 终止本控制器拥有的进程。
                return  # 不读取超长内容。
            try:  # 只接受JSON对象。
                item = json.loads(line)  # 不执行输出内容。
                if not isinstance(item, dict):  # 固定协议。
                    raise ValueError()  # 统一失败。
            except ValueError:  # 不展示原始内容。
                self.protocol_failed = True  # 无效JSON不能接受为成功。
                self.force_stop()  # 协议错误即停止。
                return  # 避免把调试输出当成功。
            if item.get('event') == 'result':  # 最终结果仍等进程退出。
                if self.result is not None or type(item.get('ok')) is not bool:  # 终态只能一个且成功必须是布尔值。
                    self.protocol_failed = True  # 拒绝模糊结果。
                    self.force_stop()  # 清理本工作进程。
                    return  # 不覆盖先前结果。
                self.result = item  # 不依赖退出前短暂状态。
            else:  # 进度只交给本机GUI。
                self.progress_event.emit(item)  # 不保存账户或任务正文。
        if len(self.buffer) > 262144:  # 残帧也有上限。
            self.protocol_failed = True  # 不能忽略异常尾部。
            self.force_stop()  # 不无限积累。

    def finish(self, process, code):  # 最多发出一次终态。
        if process is not self.process:  # 旧进程不能完成新任务。
            return  # 防止重复提醒。
        self.read(process)  # 取走退出前最后一批数据。
        self.process = None  # 已退出才能允许新任务。
        self.deadline.stop()  # 清除截止计时。
        result = self.result if self.result is not None and code == 0 and not self.protocol_failed and not self.buffer.strip() else {'event': 'result', 'ok': False, 'error': 'CANCELLED_CLEANUP_UNCONFIRMED' if self.cancelled else 'WORKER_FAILED'}  # 不误报取消清理或无效协议成功。
        process.deleteLater()  # 清理Qt对象。
        self.changed.emit(False)  # 解除本任务占用。
        self.completed.emit(result)  # 只发一次。

    def cancel(self):  # 先协作式取消，保留清理临时文件机会。
        if self.process is not None:  # 空闲不产生动作。
            self.cancelled = True  # 明确手动停止。
            self.process.write(b'{"command":"cancel"}\n')  # 不包含凭据。
            self.deadline.start(7000)  # 清理超时后只结束本进程。

    def force_stop(self):  # 异常超时不会遗留网络进程。
        if self.process is not None:  # 只结束自己拥有的后台任务。
            self.process.kill()  # 最终终态会说明清理未确认。
