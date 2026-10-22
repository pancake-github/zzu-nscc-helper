"""当前用户限定的本机命名管道，不开放网络监听端口。"""  # 桌面与 Edge 桥接。
import json  # 帧内容为 JSON。
import time  # 心跳时间。
import os  # 测试进程可使用独立命名管道。
from PyQt5.QtCore import QObject, pyqtSignal  # UI 线程信号。
from PyQt5.QtNetwork import QLocalServer  # Windows 命名管道。

class TabBridge(QObject):  # 只接受一个 Edge 配置文件连接。
    message = pyqtSignal(dict)  # 已验证大小的消息。
    lost = pyqtSignal()  # 扩展断线后停止任务。
    connected = pyqtSignal()  # 本机通道接入不等于已收到标签。
    def __init__(self, parent=None):  # 随主窗口创建。
        super().__init__(parent)  # Qt 生命周期。
        self.peer = None  # 未连接。
        self.buffer = b''  # 每连接独立缓冲。
        self.last_seen = 0.0  # 初始无心跳。
        self.server = QLocalServer(self)  # IPC 服务。
        self.server.setSocketOptions(QLocalServer.UserAccessOption)  # 当前用户权限。
        override = os.environ.get('ZZDX_VPN_TEST_PIPE', '')  # 仅测试子进程传入。
        self.name = override if override.startswith('ZZDX-VPN-Test-') else 'ZZDX-VPN-Tabs-v1'  # 正常软件始终使用正式管道。
        self.listening = self.server.listen(self.name)  # 测试不会占用真实 Edge 通道。
        self.server.newConnection.connect(self.accept)  # 处理扩展连接。

    def accept(self):  # 主线程接收连接。
        peer = self.server.nextPendingConnection()  # 取待接入通道。
        if self.peer is not None:  # 不混合不同浏览器配置文件。
            peer.abort()  # 拒绝第二来源。
            peer.deleteLater()  # 清理对象。
            return  # 保持原连接。
        self.peer = peer  # 保存唯一连接。
        self.buffer = b''  # 清空旧连接缓冲。
        self.last_seen = time.monotonic()  # 开始心跳窗口。
        peer.readyRead.connect(lambda: self.read(peer))  # 绑定实际连接身份。
        peer.disconnected.connect(lambda: self.disconnect(peer))  # 断连清理。
        self.connected.emit()  # 告知界面真实连接阶段。
        self.send('list')  # 主动握手，避免单向等待。
        if peer.bytesAvailable():  # 接入前已到达的数据也要读取。
            self.read(peer)  # 不只依赖后续 readyRead 信号。

    def disconnect(self, peer):  # 只有当前连接能改变状态。
        if self.peer is peer:  # 避免旧信号影响新连接。
            self.peer = None  # 立即置为失联。
            self.buffer = b''  # 清除半帧。
            self.lost.emit()  # 提醒控制器停止。
        peer.deleteLater()  # 释放连接。

    def read(self, peer):  # 解析换行 JSON 帧。
        if peer is not self.peer:  # 拒绝旧连接数据。
            return  # 不改变当前状态。
        self.buffer += bytes(peer.readAll())  # 增量读取。
        while b'\n' in self.buffer:  # 允许多个小帧。
            line, self.buffer = self.buffer.split(b'\n', 1)  # 拆分一帧。
            if len(line) > 262144:  # 限制单帧，不误拒多个正常批次。
                peer.abort()  # 拒绝超长单帧。
                return  # 不处理剩余数据。
            try:  # 错误 JSON 不可传到 UI。
                item = json.loads(line)  # 仅数据解析，不执行代码。
                if not isinstance(item, dict) or not isinstance(item.get('event'), str):  # 最小协议校验。
                    raise ValueError()  # 统一拒绝。
            except (ValueError, UnicodeError):  # 编码或结构错误。
                peer.abort()  # 断开连接。
                return  # 停止处理。
            self.last_seen = time.monotonic()  # 正常消息证明连接存活。
            self.message.emit(item)  # 交给 UI 状态机。
        if len(self.buffer) > 262144:  # 不完整帧也有上限。
            peer.abort()  # 不允许无限缓存。

    def send(self, command, **values):  # 发送固定桌面命令。
        if self.peer is None:  # 扩展未连接。
            return False  # 不静默丢弃成功状态。
        packet = json.dumps({'command': command, **values}, ensure_ascii=True).encode() + b'\n'  # 编码帧。
        return self.peer.write(packet) == len(packet)  # 仅表示已入本机发送队列。

    def close(self):  # 助手退出时断开扩展。
        if self.peer:  # 有连接才撤销。
            self.peer.abort()  # 扩展立即清除恢复权限。
        self.server.close()  # 释放本机管道。
