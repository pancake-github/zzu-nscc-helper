"""无网络副作用的计时状态机；可用虚拟时钟测试。"""  # 模块用途。
INTERVAL = 780.0  # 正式与界面模拟均保持十三分钟。
GRACE = 30.0  # 超过计划时刻三十秒后不补发。

class Engine:  # 管理一次保活会话。
    def __init__(self):  # 初始化停止状态。
        self.stop()  # 不自动开始。
        self.count = 0  # 成功次数。

    def start(self, now):  # 启动第一次请求前调用。
        self.active = True  # 标记会话有效。
        self.pending = True  # 首次请求尚未成功。
        self.deadline = now + 20  # 整次请求最大二十秒。
        self.due = None  # 首次成功前没有下次时间。
        self.count = 0  # 新会话重新计数。
        self.last_tick = now  # 记录本地轮询时刻。

    def success(self, now):  # 仅在响应已验证后调用。
        if not self.active or not self.pending:  # 拒绝停止后迟到的结果。
            return False  # 不恢复会话。
        if now >= self.deadline:  # 边界处也不能接受超时结果。
            return False  # 交由控制器停止。
        self.pending = False  # 本次请求完成。
        self.count += 1  # 增加真实或模拟成功次数。
        self.due = now + INTERVAL  # 从成功时刻计算十三分钟。
        return True  # 通知界面更新。

    def poll(self, now):  # 每秒使用单调时钟调用。
        if not self.active:  # 停止时不发请求。
            return None  # 无事件。
        gap = now - self.last_tick  # 检测事件循环长时间停顿。
        self.last_tick = now  # 更新轮询基准。
        if gap > GRACE:  # 保守处理睡眠或严重阻塞。
            return 'SUSPEND_OR_DELAY'  # 不自动补发。
        if self.pending:  # 请求执行期间。
            return 'TIMEOUT' if now >= self.deadline else None  # 硬截止时间。
        if now > self.due + GRACE:  # 已错过发送窗口。
            return 'MISSED_DEADLINE'  # 停止而不是追赶。
        if now >= self.due:  # 到达正常发送时间。
            self.pending = True  # 防止重复启动进程。
            self.deadline = now + 20  # 设置整次请求截止时间。
            return 'SEND'  # 控制器创建一个工作进程。
        return None  # 继续安静等待。

    def stop(self):  # 同步撤销所有未来请求。
        self.active = False  # 停止会话。
        self.pending = False  # 不接受迟到结果。
        self.due = None  # 清空计划。
