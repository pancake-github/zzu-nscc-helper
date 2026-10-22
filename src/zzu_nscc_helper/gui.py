"""中文统一界面；只展示已选择组件，真实任务必须由用户点击。"""  # 不保存账号密码。
import argparse  # 源码模式也可验收组件组合。
import ctypes  # 接收Windows电源消息。
from ctypes import wintypes  # Windows消息结构。
import json  # 安装组件清单。
import os  # 打开本机回执。
from pathlib import Path  # 校验实际路径。
import sys  # QApplication入口。
from PyQt5.QtCore import QTimer  # 界面状态协调，不产生网络流量。
from PyQt5.QtNetwork import QLocalServer, QLocalSocket  # 本机单实例唤醒。
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QTabWidget, QLineEdit, QPlainTextEdit, QComboBox, QFileDialog, QInputDialog, QMessageBox, QSystemTrayIcon, QMenu, QStyle, QScrollArea  # 原生中文控件。
from .components import COMPONENTS, LABELS, normalize_selection  # 共用安装选择契约。
from .paths import data_root  # 私有数据不进入源码。
from .processes import WorkerTask  # 单独后台进程。
from . import __version__  # 冻结安装包与源码共享候选版本标识。

ERRORS = {'VPN_ROUTE_INVALID': '平台目标未经过已确认的VPN接口。', 'AUTH_FAILED': 'SSH认证失败，请核对自己的SSH账号和密码。', 'HOST_KEY_MISMATCH': '服务器主机密钥不符，已停止认证。', 'CANCELLED_CHECK_RECEIPT': '已取消；已成功文件保留，请查看回执中的临时文件清理结果。', 'CANCELLED_CLEANUP_UNCONFIRMED': '进程已停止；临时文件清理尚未确认，请核对本次回执。', 'TRANSFER_PARTIAL_FAILURE': '部分文件失败，成功内容已保留。', 'RECEIPT_SAVE_FAILED': '文件操作已执行，但完整回执保存失败。', 'CONFIG_CONFLICT': '配置在预览后发生变化，请重新生成预览。', 'CONFIG_CHANGED_ON_EXIT': 'Clash退出时保存了新配置，请重新预览。', 'WAIT_FOR_CLASH_EXIT': 'Clash没有正常退出；请从Clash托盘退出后重新检测。', 'UNSUPPORTED_VERSION': '当前Clash版本未列入自动写入兼容清单。', 'CLASH_NOT_UNIQUE': '没有找到唯一的Clash客户端和配置目录。', 'VPN_NOT_CONNECTED': '请先登录平台VPN，再检测本机环境。', 'PAC_UNSUPPORTED': '当前使用特殊PAC配置，本版只提供检测与导出。', 'FAKE_IP_UNSUPPORTED': '当前DNS模式未通过自动修改适配。', 'BYPASS_DEFAULTS_UNKNOWN': '没有明确的系统代理绕过列表，请先在Clash保存默认绕过配置。', 'SCRIPT_ENTRY_UNSUPPORTED': '增强脚本不是受支持的main入口，本版保留原文件。', 'FailedRestored': '应用失败，已经恢复本次修改前的文件。', 'RecoveryConflict': '恢复遇到配置冲突，原备份已保留，请人工核对。', 'WORKER_FAILED': '后台进程失败，任务未报告成功。', 'TASK_FAILED': '任务失败，请检查路径、网络和本机权限。', 'LOCAL_DETECTION_TIMEOUT': '本机网络信息检测超时，请稍后手动刷新。'}  # 只显示固定错误，不展示认证异常原文。

def error_text(result):  # 所有错误统一中文呈现。
    code = result.get('error', 'TASK_FAILED')  # 失败默认不可用。
    return ERRORS.get(code, '任务未完成（' + str(code)[:80] + '）。')  # 固定代码便于诊断。

ERRORS.update({'WAIT_FOR_CLASH_EXIT': 'Clash没有正常退出；请从Clash托盘退出后再次应用当前预览。', 'CONFIG_LOCATION_UNVERIFIED': '所选目录未与受支持的Clash安装关联验证，本版只提供检测与方案导出。', 'CLASH_IDENTITY_CHANGED': 'Clash进程或版本已改变，请重新检测并生成预览。'})  # 不让用户按错误流程反复尝试。
ERRORS.update({'MANAGED_SCRIPT_CONFLICT': '受管增强脚本发生了人工修改，已保留原文件，请先核对。', 'CONTROLLER_UNAVAILABLE': '无法读取本机核心状态，本版不自动开启控制器或猜测端口。', 'ROUTING_MODE_UNSUPPORTED': '当前不是规则模式，仅提供检测和方案导出。', 'INVALID_PLAN': '本机计划或备份损坏，已在写入前停止，请重新预览并核对备份。'})  # 不以模糊错误掩盖保护条件。
STATUS_LABELS = {'Completed': '全部执行完成', 'CompletedWithSkips': '执行完成，存在未验证同名文件或特殊对象跳过', 'AlreadyVerified': '已有本地文件与给定基准一致（未重新查询远端）', 'Applied': '已应用', 'AppliedPendingVPN': '已应用，等待VPN验证', 'Writing': '应用未完成', 'WritingRollback': '回滚未完成', 'RecoveryConflict': '恢复冲突', 'Unreadable': '记录无法读取'}  # 用户界面以中文描述实际状态。

def button(text, slot):  # 简化统一按钮创建。
    widget = QPushButton(text)  # 原生按钮。
    widget.clicked.connect(slot)  # 只在用户动作时执行。
    return widget  # 交给布局管理。

class TransferPanel(QWidget):  # 路径式批量传输，不做远程文件浏览器。
    def __init__(self, owner):  # 统一窗口管理任务互斥。
        super().__init__(owner)  # Qt生命周期。
        self.owner, self.receipt = owner, None  # 回执只留在本机。
        self.task = WorkerTask(self)  # 不与保活共用进程。
        self.task.progress_event.connect(self.progress)  # 脱敏进度。
        self.task.completed.connect(self.finished)  # 实际进程退出后更新终态。
        layout = QVBoxLayout(self)  # 表单和结果纵向排列。
        note = QLabel('仅连接本平台 172.99.1.100:22。使用自己的 SSH 账号；每批密码隐藏输入一次，不保存。\n已有同名文件保留。上传完整回读 SHA-256 校验；下载无独立基准时只留存本地哈希。')  # 明确传输与验证语义。
        note.setWordWrap(True)  # 适应窗口宽度。
        layout.addWidget(note)  # 常驻说明。
        form = QFormLayout()  # 清楚标注实际参数。
        self.direction = QComboBox()  # 下载或上传。
        self.direction.addItem('下载到本机', 'download')  # 默认不执行。
        self.direction.addItem('上传到超算', 'upload')  # 用户选择实际方向。
        form.addRow('传输方向', self.direction)  # 参数标签。
        self.username = QLineEdit()  # 初始空白，不载入开发者账号。
        form.addRow('本人 SSH 用户名', self.username)  # 不混淆网页密码。
        self.sources = QPlainTextEdit()  # 一行一个真实路径。
        self.sources.setMaximumHeight(120)  # 保留结果显示空间。
        form.addRow('来源路径（每行一个）', self.sources)  # 上传为Windows路径，下载为Linux路径。
        self.target = QLineEdit()  # 明确的实际目的目录，默认留空。
        form.addRow('目标目录', self.target)  # 不猜用户研究目录。
        self.category = QLineEdit()  # 下载任务分类由用户输入。
        form.addRow('下载任务名称', self.category)  # 上传时禁用。
        self.expected = QLineEdit()  # 可选独立单文件SHA256。
        form.addRow('下载基准 SHA-256（可选）', self.expected)  # 不把本地留存哈希当独立验证。
        layout.addLayout(form)  # 完成主表单。
        row = QHBoxLayout()  # 本地选择器只读用户选择。
        self.add_files = button('添加上传文件', self.select_files)  # 支持多选。
        self.add_folder = button('添加上传文件夹', self.select_folder)  # 保留目录层级。
        self.target_folder = button('选择下载根目录', self.select_target)  # 不改变浏览器下载设置。
        for widget in (self.add_files, self.add_folder, self.target_folder):  # 平行按钮。
            row.addWidget(widget)  # 进入同一行。
        layout.addLayout(row)  # 选择器行。
        controls = QHBoxLayout()  # 任务按钮。
        self.start_button = button('开始本批传输', self.start)  # 密码在参数检查后才请求。
        self.cancel_button = button('取消本批传输', self.task.cancel)  # 不取消保活。
        self.receipt_button = button('打开本次回执', self.open_receipt)  # 私有本机文件。
        for widget in (self.start_button, self.cancel_button, self.receipt_button):  # 平行操作。
            controls.addWidget(widget)  # 添加按钮。
        layout.addLayout(controls)  # 结束按钮行。
        self.status = QLabel('未启动；没有建立 SSH 连接。')  # 不把界面打开当连接成功。
        self.status.setWordWrap(True)  # 错误说明可换行。
        layout.addWidget(self.status)  # 展示状态。
        self.stats = QLabel('成功：0　跳过：0　失败：0')  # 逐项状态统计。
        layout.addWidget(self.stats)  # 不显示密码。
        layout.addStretch()  # 避免字段拉伸。
        self.counts = {}  # 本批状态数量。
        self.direction.currentIndexChanged.connect(self.update_controls)  # 方向改变同步表单。
        self.task.changed.connect(self.update_controls)  # 运行中锁定参数。
        self.update_controls()  # 初始按钮状态。

    def update_controls(self, unused=None):  # 不靠按钮状态作为后台授权依据。
        busy, download = self.task.busy, self.direction.currentData() == 'download'  # 当前实际状态。
        for widget in (self.direction, self.username, self.sources, self.target):  # 批次中不可更改参数。
            widget.setEnabled(not busy)  # 结束后恢复。
        self.category.setEnabled(download and not busy)  # 上传不自动添加日期任务名。
        self.expected.setEnabled(download and not busy)  # 仅下载单文件可用。
        self.add_files.setEnabled(not download and not busy)  # 本地来源选择。
        self.add_folder.setEnabled(not download and not busy)  # 文件夹来源选择。
        self.target_folder.setEnabled(download and not busy)  # 下载根目录选择。
        self.start_button.setEnabled(not busy and not self.owner.preview_mode and not self.owner.mutating())  # 预览和分流写入期间禁用。
        self.cancel_button.setEnabled(busy)  # 只取消本批工作进程。
        self.receipt_button.setEnabled(bool(self.receipt))  # 无回执不打开未知路径。

    def append_sources(self, values):  # 不把文件选择立即当上传授权。
        current = self.sources.toPlainText().splitlines()  # 保留已有来源。
        self.sources.setPlainText('\n'.join(dict.fromkeys(current + values)))  # 精确去重。

    def select_files(self):  # 用户主动选择上传来源。
        paths, unused = QFileDialog.getOpenFileNames(self, '选择本批上传文件')  # 不指定个人默认目录。
        self.append_sources(paths)  # 只填表。

    def select_folder(self):  # 支持整个文件夹。
        path = QFileDialog.getExistingDirectory(self, '选择本批上传文件夹')  # 用户实际选择。
        if path:  # 取消对话框不改变参数。
            self.append_sources([path])  # 不马上读取远端。

    def select_target(self):  # 下载目标由用户指定。
        path = QFileDialog.getExistingDirectory(self, '选择下载根目录')  # 不改变浏览器设置。
        if path:  # 只有有效选择才写入。
            self.target.setText(path)  # 后续仍会验证绝对路径。

    def start(self):  # 在隐藏输入密码前先完成明确参数检查。
        if self.task.busy or self.owner.preview_mode or self.owner.mutating():  # 不可绕过互斥。
            return  # 不创建后台任务。
        from .transfer.nscc_download import normalize_remote, validate_name, check_local_path  # 共享原核心参数规则。
        from .transfer.nscc_upload import normalize_local  # 上传本地路径规则。
        vpn = self.owner.environment.get('vpn', {})  # 之前实际检测结果。
        try:  # 参数错误只显示中文，不询问密码。
            if not vpn.get('connected'):  # 无VPN身份不能认证。
                raise ValueError('请先登录VPN并点击顶部“检测本机环境”。')  # 明确下一步。
            username = self.username.text().strip()  # 用户本次填写。
            if not username or any(char.isspace() for char in username):  # 防止无效账号。
                raise ValueError('请填写自己的 SSH 用户名，不能包含空白。')  # 不回显账号。
            paths = [line.strip() for line in self.sources.toPlainText().splitlines() if line.strip()]  # 实际来源。
            if not paths:  # 不扫描默认目录。
                raise ValueError('请填写本批来源路径。')  # 不生成占位路径。
            payload = {'direction': self.direction.currentData(), 'username': username, 'vpn_guid': vpn['guid']}  # 账户只走私有管道。
            if payload['direction'] == 'download':  # 明确本地根、任务、日期布局。
                sources = [normalize_remote(path) for path in paths]  # 拒绝模糊远端路径。
                root = normalize_local(self.target.text().strip())  # 实际Windows绝对根目录。
                category = self.category.text().strip()  # 界面要求明确任务名称。
                validate_name(category)  # 不猜分类。
                check_local_path(root)  # 拒绝目录联接。
                expected = self.expected.text().strip()  # 独立基准可空。
                if expected and (len(sources) != 1 or len(expected) != 64 or any(char not in '0123456789abcdefABCDEF' for char in expected)):  # 验证参数组合。
                    raise ValueError('基准 SHA-256 仅用于一个文件，必须为64位十六进制。')  # 不错用整批哈希。
                payload.update(remote_paths=sources, download_root=str(root), category=category, expected_sha256=expected)  # 固定核心接口。
            else:  # 上传目标不追加任务名或日期。
                sources = [normalize_local(path) for path in paths]  # 用户实际本地来源。
                if any(not path.exists() for path in sources):  # 来源必须存在。
                    raise ValueError('至少一个上传来源不存在，请核对路径。')  # 不自动创建来源。
                for path in sources:  # 提前检查链接边界。
                    check_local_path(path)  # 传输核心还会复核。
                payload.update(local_paths=[str(path) for path in sources], remote_directory=normalize_remote(self.target.text().strip()), report_root=str(data_root() / 'transfer-reports'))  # 回执在本机私有目录。
        except (ValueError, OSError) as error:  # 参数错误不包含口令。
            QMessageBox.warning(self, '参数未完整', str(error))  # 用户补充真实信息。
            return  # 不认证。
        dialog = QInputDialog(self)  # 口令只在此次输入窗口存在。
        dialog.setWindowTitle('本批 SSH 认证')  # 不混淆平台网页密码。
        dialog.setLabelText('输入自己的 SSH 密码；本批只认证一次，不保存密码。')  # 明确用途。
        dialog.setTextEchoMode(QLineEdit.Password)  # 隐藏输入。
        accepted = dialog.exec_()  # 用户主动输入。
        password = dialog.textValue() if accepted else ''  # 不从任何其他地方读密码。
        dialog.setTextValue('')  # 立即清空输入控件。
        dialog.deleteLater()  # 释放对话框。
        if not accepted or not password:  # 取消和空密码均不连接。
            return  # 不产生后台网络任务。
        self.counts, self.receipt = {}, None  # 新批次清除旧统计。
        self.status.setText('正在连接并核对主机密钥；尚未报告传输成功。')  # 主机身份核对先于密码认证。
        self.task.start('sftp', payload, auth={'password': password})  # 匿名管道，不放参数或环境变量。
        password = ''  # 清除GUI长期引用，不声称能擦除解释器内部所有副本。

    def progress(self, event):  # 后台只发字节和结果类别。
        if event.get('event') == 'progress':  # 不返回数据正文。
            self.status.setText(f"本批已处理 {event.get('bytes', 0):,} 字节（上传包含完整回读校验）。")  # 不将字节进度当完成。
        elif event.get('event') == 'item':  # 单项真实完成或失败。
            key = event.get('status', 'Failed')  # 固定核心状态。
            self.counts[key] = self.counts.get(key, 0) + 1  # 累计状态数量。
            self.show_counts()  # 即时显示。

    def show_counts(self):  # 未验证同名跳过不能列为成功。
        success = sum(self.counts.get(key, 0) for key in ('Downloaded', 'UploadedVerified', 'AlreadyVerified'))  # 不把目录计为文件成功。
        skipped = sum(self.counts.get(key, 0) for key in ('SkippedExistingUnverified', 'SkippedUnsupported'))  # 明确跳过。
        self.stats.setText(f"成功：{success}　跳过：{skipped}　失败：{self.counts.get('Failed', 0)}\n已有文件跳过表示未验证；上传成功表示完整回读校验通过。")  # 原结果语义。

    def finished(self, result):  # 进程清理完成后才允许下一批。
        summary = result.get('summary', {})  # 固定白名单摘要。
        self.receipt = summary.get('Receipt')  # 仅本机实际回执。
        self.counts = summary.get('Counts', self.counts)  # 用最终完整统计校准。
        if summary.get('Status') == 'AlreadyVerified':  # 旧核心可能在认证前完成本地独立校验。
            self.counts = {'AlreadyVerified': 1}  # 单文件独立基准验证计入已验证数量。
        self.show_counts()  # 显示实际结果。
        self.status.setText(('本批结果：' + STATUS_LABELS.get(summary.get('Status', 'Completed'), '执行完成')) if result.get('ok') else error_text(result))  # 跳过和完整成功仍有区别。
        self.update_controls()  # 更新回执按钮。

    def open_receipt(self):  # 不上传或自动分享回执。
        if self.receipt and Path(self.receipt).is_file():  # 不猜文件路径。
            os.startfile(self.receipt)  # 用本机默认查看器打开。

class RoutingPanel(QWidget):  # 应用前显示具体平台增量。
    def __init__(self, owner):  # 共用环境检测和任务互斥。
        super().__init__(owner)  # Qt生命周期。
        self.owner, self.plan, self.applied = owner, None, None  # 私有计划只保存身份。
        self.recovery_pending = False  # 未完成事务需要先人工核对。
        self.task = WorkerTask(self)  # 分流任务独立。
        self.operation = None  # 区分预览和实际写入。
        self.task.completed.connect(self.finished)  # 终态处理。
        layout = QVBoxLayout(self)  # 简洁分流页面。
        notice = QLabel('检测 → 预览 → 点击应用 → 备份 → 正常退出 Clash → 写入并重启 → 生效检查。\n连接可能短暂中断；保活或 SFTP 运行时不能应用或回滚。原始配置备份只保存在本机。')  # 用户需要知道的影响。
        notice.setWordWrap(True)  # 自动换行。
        layout.addWidget(notice)  # 常驻说明。
        self.summary = QPlainTextEdit()  # 仅展示自己新增内容。
        self.summary.setReadOnly(True)  # 用户不直接编辑原配置。
        self.summary.setPlainText('先点击顶部“检测本机环境”，再生成分流预览。')  # 不假报已应用。
        layout.addWidget(self.summary)  # 预览主区域。
        row = QHBoxLayout()  # 明确独立操作。
        self.preview_button = button('生成分流预览', self.preview)  # 只读Clash。
        self.apply_button = button('应用此预览', self.apply)  # 实际写入授权入口。
        self.rollback_button = button('回滚本次应用', self.rollback)  # 不恢复其他备份。
        self.export_button = button('导出平台分流说明', self.export)  # 无个人配置的公共说明。
        for widget in (self.preview_button, self.apply_button, self.rollback_button, self.export_button):  # 平行按钮。
            row.addWidget(widget)  # 添加操作。
        layout.addLayout(row)  # 结束按钮行。
        history_row = QHBoxLayout()  # 重启软件后仍可找到私有回滚记录。
        self.history_box = QComboBox()  # 只显示时间、状态和短编号。
        self.history_box.addItem('尚未读取本机回滚记录', None)  # 不默认选择未知事务。
        self.history_box.currentIndexChanged.connect(self.select_history)  # 用户选择实际回滚范围。
        history_row.addWidget(self.history_box)  # 私有记录选择器。
        self.history_button = button('刷新本机回滚记录', self.refresh_history)  # 不向网络上传。
        history_row.addWidget(self.history_button)  # 读取自己的备份摘要。
        layout.addLayout(history_row)  # 放在操作和状态之间。
        self.status = QLabel('尚未应用任何分流修改。')  # 真实状态。
        self.status.setWordWrap(True)  # 容纳错误说明。
        layout.addWidget(self.status)  # 显示结果。
        self.update_controls()  # 初始禁用应用。
        if not owner.preview_mode:  # 界面预览不读取个人备份。
            QTimer.singleShot(0, self.refresh_history)  # 正常启动恢复回滚入口。

    def update_controls(self):  # 运行中保持互斥。
        idle = not self.task.busy and not self.owner.preview_mode  # 界面预览不能修改机器。
        unlocked = idle and not self.owner.network_busy() and not self.recovery_pending  # 未完成恢复不能叠加新写入。
        self.preview_button.setEnabled(idle and bool(self.owner.environment.get('writable')))  # 已支持的环境才生成可应用计划。
        self.apply_button.setEnabled(unlocked and self.plan is not None)  # 必须先预览。
        self.rollback_button.setEnabled(unlocked and self.applied is not None)  # 只回滚本软件已应用事务。
        self.history_button.setEnabled(idle)  # 读取备份不与本组件其他任务并发。

    def select_history(self, unused=None):  # 记录选择不执行回滚。
        row = self.history_box.currentData()  # 实际安全摘要。
        self.applied = row['id'] if row and row['status'] in ('Applied', 'AppliedPendingVPN') else None  # 只允许合法终态。
        if row and row['status'] not in ('Applied', 'AppliedPendingVPN'):  # 崩溃或恢复冲突记录需人工核对。
            self.status.setText('发现未完成或损坏的分流事务，请先核对本机私有备份；不会自动继续或覆盖配置。')  # 不重启旧事务。
        self.update_controls()  # 选择合法范围后才启用回滚。

    def refresh_history(self):  # 本机只读任务。
        if self.task.busy or self.owner.preview_mode:  # 不能与写入并发。
            return  # 等当前操作结束。
        self.operation = 'history'  # 终态只更新选择器。
        self.task.start('routing_history', {}, timeout_ms=15000)  # 不含配置正文。

    def preview(self):  # 预览只保存在当前用户私有目录。
        if self.task.busy or self.owner.preview_mode:  # 不并发预览。
            return  # 不覆盖当前任务。
        self.operation, self.plan = 'preview', None  # 新预览使旧计划失效。
        self.task.start('routing_preview', {'config_root': self.owner.config_root}, timeout_ms=30000)  # 后台重新检测源文件。
        self.status.setText('正在读取本机配置并生成精确增量；尚未修改 Clash。')  # 明确阶段。

    def apply(self):  # 用户必须确认可见改动。
        if not self.plan or self.task.busy or self.owner.network_busy() or self.owner.preview_mode:  # 二次检查真实任务状态。
            return  # 不依赖按钮禁用。
        answer = QMessageBox.question(self, '应用预览中的分流', '将备份并应用上方列出的改动，正常退出并重启 Clash，连接可能短暂中断。是否应用此预览？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)  # 正式产品中的写入授权。
        if answer == QMessageBox.Yes:  # 只有用户点击才写。
            self.operation = 'apply'  # 主窗口将禁止新网络任务。
            self.task.start('routing_apply', {'id': self.plan['id']})  # 不硬杀写入事务。
            self.status.setText('正在应用并检查；请等待完成。')  # 不误报成功。

    def rollback(self):  # 只恢复本软件新增且尚未被改动的内容。
        if not self.applied or self.task.busy or self.owner.network_busy() or self.owner.preview_mode:  # 互斥检查。
            return  # 不影响正在传输的文件。
        if QMessageBox.question(self, '回滚本次分流', '将正常退出并重启 Clash。若配置已被后来修改，会停止并报告冲突。是否回滚本次应用？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:  # 明确范围。
            self.operation = 'rollback'  # 防止新任务启动。
            self.task.start('routing_rollback', {'id': self.applied})  # 本机私有事务身份。

    def finished(self, result):  # 后台进程已退出。
        if not result.get('ok'):  # 不保留失败预览作为可用计划。
            self.status.setText(error_text(result))  # 固定中文错误。
            safe_errors = ('WAIT_FOR_CLASH_EXIT', 'CONFIG_CONFLICT', 'CONFIG_CHANGED_ON_EXIT', 'CLASH_IDENTITY_CHANGED', 'INVALID_PLAN', 'PLAN_STATE', 'FailedRestored', 'TRANSACTION_FAILED')  # 这些失败已确认没有未恢复写入。
            if self.operation in ('apply', 'rollback') and result.get('error') not in safe_errors:  # 进程崩溃或恢复冲突不能继续叠加修改。
                self.recovery_pending = True  # 等核对私有备份。
                self.status.setText(self.status.text() + '\n配置结果需要核对，请先查看本机备份记录。')  # 不自动重新执行。
            if self.operation == 'preview':  # 错误预览没有应用入口。
                self.plan = None  # 等用户重新检测。
            elif self.operation == 'apply' and result.get('error') != 'WAIT_FOR_CLASH_EXIT':  # 已改变或失败的计划不能再次应用。
                self.plan = None  # 必须重新预览。
        elif self.operation == 'history':  # 恢复本机回滚选择，不自动回滚。
            self.recovery_pending = any(row['status'] in ('Writing', 'WritingRollback', 'RecoveryConflict', 'Unreadable') for row in result['history'])  # 不能把未完成事务静默忽略。
            self.history_box.blockSignals(True)  # 原子更新列表。
            self.history_box.clear()  # 删除过期摘要。
            self.history_box.addItem('选择需要回滚的本机应用记录', None)  # 用户明确选择。
            for row in result['history']:  # 只展示仍有处理意义的记录。
                if row['status'] in ('Applied', 'AppliedPendingVPN', 'Writing', 'WritingRollback', 'RecoveryConflict', 'Unreadable'):  # 已回滚记录不再次回滚。
                    self.history_box.addItem(row['created'] + ' · ' + STATUS_LABELS.get(row['status'], row['status']) + ' · ' + row['id'][:8], row)  # 不展示原配置。
            self.history_box.blockSignals(False)  # 恢复用户选择。
            self.select_history()  # 默认仍不绑定回滚目标。
            if self.recovery_pending:  # 不等用户点到异常条目才提醒。
                self.status.setText('发现未完成或损坏的分流事务，应用和回滚已暂停；请先核对本机私有备份。')  # 不自动重做旧事务。
        elif self.operation == 'preview':  # 只展示具体增量。
            self.plan = result['plan']  # 不含原配置正文。
            plan = self.plan  # 简化展示。
            self.summary.setPlainText('将改动文件：' + '、'.join(plan['changes']) + '\n系统代理绕过新增：' + ('、'.join(plan['bypass_added']) or '已包含，无新增') + '\nDNS 与 fake-IP 排除：\n' + '\n'.join(plan['dns_domains']) + '\nDNS 服务器：' + plan.get('resolver', '') + '\nVPN 网卡：' + plan['vpn_alias'] + '\nTUN 精确排除：' + '、'.join(plan['tun_exclusions']) + '\n核心规则：' + plan['rules'] + '\n其余节点、订阅、端口和开关保留。')  # 只包含本方案字段。
            self.status.setText('预览已生成，尚未应用。')  # 用户决定下一步。
        else:  # 实际应用或回滚完成。
            transaction = result['transaction']  # 固定终态。
            self.status.setText({'Applied': '配置已应用并通过本机生效检查；仍需联网验收。', 'AppliedPendingVPN': '配置已应用；VPN未连接，等待联网验证。', 'RolledBack': '本次修改已回滚。', 'NoChanges': '当前配置已包含相同改动，无需重启。'}.get(transaction['status'], transaction['status']))  # 不把本机检查当VPN连续验收。
            self.applied = transaction['id'] if self.operation == 'apply' and transaction['status'] in ('Applied', 'AppliedPendingVPN') else None  # 只允许回滚真实应用。
            self.plan = None  # 应用后旧预览作废。
        self.operation = None  # 解除事务锁。
        self.update_controls()  # 更新按钮。
        self.owner.coordinate()  # 同步其他组件。

    def export(self):  # 导出内容没有本机路径或账户。
        from .platform import load_platform  # 公共固定预设。
        path, unused = QFileDialog.getSaveFileName(self, '导出平台分流方案', '郑州超算分流方案.json', 'JSON 文件 (*.json)')  # 用户选择保存位置。
        if path:  # 取消不写文件。
            profile = load_platform()  # 公共配置没有凭据。
            Path(path).write_text(json.dumps({'scope': profile['scope'], 'routing': profile['routing'], 'vpn_dns': profile['vpn']['dns'], 'sftp_host': profile['sftp']['host'], 'note': '仅为平台方案；实际网卡与端口须由本机检测，不能直接作为Clash完整配置。'}, ensure_ascii=False, indent=2), encoding='utf-8')  # 绝不导出原订阅或secret。

class MainWindow(QMainWindow):  # 三组件共用一个托盘和生命周期。
    def __init__(self, components=COMPONENTS, preview=False):  # 构造不启动保活或传输。
        super().__init__()  # 原生主窗口。
        self.components = normalize_selection(components)  # 至少一个组件。
        self.preview_mode, self.environment, self.config_root = preview, {}, None  # 预览严格无实际任务。
        self.keepalive = self.transfer = self.routing = None  # 未安装组件不创建。
        self.exiting = False  # X默认收起托盘。
        self.setWindowTitle('郑州超算助手 · ' + __version__ + ' 测试版')  # 不把候选测试版称为稳定正式版。
        self.resize(980, 800)  # 适配主要表单。
        self.setStyleSheet('QWidget {font-family: Microsoft YaHei; font-size: 13px;} QPushButton {padding: 7px;} QLabel {padding: 3px;}')  # 保持原生中文易读。
        central = QWidget(self)  # 主布局容器。
        self.setCentralWidget(central)  # QMainWindow标准结构。
        layout = QVBoxLayout(central)  # 顶部状态和组件页。
        scope = QLabel('郑州超算平台专用 · 非官方项目 · 请先安装并登录自己的 SSL VPN\n' + ('界面预览：所有联网和配置写入均禁用。' if preview else '当前为测试版，请依据发布页的验收记录核对适用环境。'))  # 不以界面文本冒充全部环境已通过。
        scope.setStyleSheet('background:#fff2ce;padding:10px;')  # 常驻状态提示。
        layout.addWidget(scope)  # 顶部说明。
        row = QHBoxLayout()  # 环境检测入口。
        self.detect_button = button('检测本机环境', self.detect)  # 只读本机状态。
        self.directory_button = button('指定 Clash 配置目录', self.select_config)  # 便携安装需要明确路径。
        row.addWidget(self.detect_button)  # 统一检测。
        if 'routing' in self.components:  # 只安装传输或保活无需分流配置选择。
            row.addWidget(self.directory_button)  # 仅分流组件显示。
        else:  # 不显示无关入口。
            self.directory_button.hide()  # 不要求安装Clash。
        layout.addLayout(row)  # 完成顶部操作。
        self.environment_label = QLabel('尚未检测本机环境。')  # 不猜VPN是否连接。
        self.environment_label.setWordWrap(True)  # 长摘要自动换行。
        layout.addWidget(self.environment_label)  # 展示安全字段。
        self.tabs = QTabWidget()  # 已安装组件页。
        layout.addWidget(self.tabs)  # 主功能区域。
        if 'keepalive' in self.components:  # 仅此组件需要Edge连接器。
            from .keepalive.tab_app import TabWindow  # 懒加载保活模块。
            self.keepalive = TabWindow(connect=not preview)  # 预览不注册原生组件。
            self.keepalive.can_start = lambda: not self.preview_mode and not self.mutating()  # 源码模式同样执行真实互斥。
            self.keepalive.tray.hide()  # 使用统一托盘。
            self.keepalive.reveal = self.reveal  # 提醒回到统一窗口。
            self.keepalive.quit = self.quit  # 不单独退出子组件。
            area = QScrollArea()  # 较小屏幕也能访问全部控件。
            area.setWidgetResizable(True)  # 保持宽度自适应。
            area.setWidget(self.keepalive)  # 嵌入既有标签页保活。
            self.tabs.addTab(area, LABELS['keepalive'])  # 组件标签。
        if 'routing' in self.components:  # 按安装选择创建。
            self.routing = RoutingPanel(self)  # 此时不读取配置。
            self.tabs.addTab(self.routing, LABELS['routing'])  # 分流页。
        if 'sftp' in self.components:  # 不依赖浏览器扩展。
            self.transfer = TransferPanel(self)  # 不读取或保存账号。
            self.tabs.addTab(self.transfer, LABELS['sftp'])  # 传输页。
        self.detector = WorkerTask(self)  # 环境检测也放后台。
        self.detector.completed.connect(self.detected)  # 安全摘要返回主界面。
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ComputerIcon), self)  # 单一托盘图标。
        menu = QMenu(self)  # 所有常用后台操作。
        menu.addAction('显示主界面', self.reveal)  # 唤回统一窗口。
        if self.keepalive:  # 没安装不提供空操作。
            menu.addAction('停止保活', lambda: self.keepalive.stop())  # 不取消SFTP。
        if self.transfer:  # 可独立取消本批传输。
            menu.addAction('取消本批 SFTP', self.transfer.task.cancel)  # 保留成功文件。
        menu.addSeparator()  # 区分退出。
        menu.addAction('退出郑州超算助手', self.quit)  # 统一清理。
        self.tray.setContextMenu(menu)  # 绑定菜单。
        self.tray.activated.connect(lambda reason: self.reveal() if reason == QSystemTrayIcon.DoubleClick else None)  # 双击显示。
        if not preview:  # 测试预览不留下托盘。
            self.tray.show()  # 正常应用驻留。
        self.timer = QTimer(self)  # 仅协调本地UI状态。
        self.timer.timeout.connect(self.coordinate)  # 检查任务互斥。
        self.timer.start(500)  # 不产生网络流量。
        self.detect_button.setEnabled(not preview)  # 预览不启动本机检测进程。
        self.directory_button.setEnabled(not preview)  # 预览也不更改待检测目录。
        self.coordinate()  # 初始化组合状态。
        if not preview:  # 正常启动自动进行本机只读检测。
            QTimer.singleShot(0, self.detect)  # 不自动开始保活、认证或分流写入。

    def network_busy(self):  # 两项网络任务独立判断。
        keep = self.keepalive  # 可能没有安装。
        return bool(keep and (keep.engine.active or keep.awaiting or keep.recovering or keep.worker is not None) or self.transfer and self.transfer.task.busy)  # 不只判断倒计时阶段。

    def mutating(self):  # 分流写入及回滚期间禁止启动网络任务。
        return bool(self.routing and self.routing.task.busy and self.routing.operation in ('apply', 'rollback'))  # 只读预览不影响已有任务。

    def coordinate(self):  # 不取消用户已运行的独立任务。
        if self.routing:  # 更新互斥按钮。
            self.routing.update_controls()  # 保活/SFTP运行时禁用应用。
        if self.transfer:  # 同步启动限制。
            self.transfer.update_controls()  # 已运行批次保留。
        if self.keepalive and (self.preview_mode or self.mutating()):  # 预览或写配置时不能开始保活。
            self.keepalive.start_button.setEnabled(False)  # 还会由真实VPN身份和连接检查。
        elif self.keepalive and not (self.keepalive.engine.active or self.keepalive.awaiting or self.keepalive.recovering):  # 分流结束后恢复真实启动资格。
            self.keepalive.selection_changed()  # 不要求用户反复刷新扩展。
        self.tray.setToolTip('郑州超算助手 · ' + ('任务运行中' if self.network_busy() or self.mutating() else '未运行网络任务'))  # 单一托盘显示真实摘要。

    def detect(self):  # 不自动发平台HTTPS或SSH请求。
        if self.detector.busy or self.preview_mode or self.network_busy() or self.mutating():  # 运行中不改变绑定的VPN身份。
            return  # 用户先完成或停止任务。
        self.detect_button.setEnabled(False)  # 防止并发检测。
        self.environment_label.setText('正在只读检测 VPN 路由、Clash 版本及实际端口…')  # 真实阶段。
        self.detector.start('detect', {'config_root': self.config_root}, timeout_ms=30000)  # 本机检查有截止。

    def detected(self, result):  # 只接收脱敏环境摘要。
        self.detect_button.setEnabled(not self.preview_mode)  # 检测完成。
        if not result.get('ok'):  # 失败清除旧身份。
            self.environment = {}  # 不能沿用旧VPN判断。
            self.environment_label.setText(error_text(result))  # 固定错误。
        else:  # 显示实际端口和控制器类型。
            self.environment = result['environment']  # 无控制器secret值。
            vpn = self.environment.get('vpn', {})  # 单组件也可检测VPN。
            ports = self.environment.get('ports', {})  # 未发现Clash可为空。
            self.environment_label.setText(('VPN：已确认，网卡 ' + vpn.get('alias', '') if vpn.get('connected') else 'VPN：尚未确认') + '\nClash：' + str(self.environment.get('client', {}).get('version') or '未找到唯一受支持客户端') + '；实际端口：' + (', '.join(f'{key}={value}' for key, value in ports.items()) or '无') + '；控制器：' + self.environment.get('controller', {}).get('kind', '未检测'))  # 不显示认证配置。
        if self.keepalive:  # 只有下次手动开始才使用新身份。
            vpn = self.environment.get('vpn', {})  # 当前结果。
            self.keepalive.vpn_guid = vpn.get('guid') if vpn.get('connected') else None  # 不猜固定接口名。
            self.keepalive.selection_changed()  # 重新核对候选启动资格。
        self.coordinate()  # 更新分流入口。

    def select_config(self):  # 明确便携客户端配置目录。
        if self.network_busy() or self.mutating():  # 不在运行期换环境。
            return  # 保持当前绑定。
        path = QFileDialog.getExistingDirectory(self, '选择包含 verge.yaml 和 clash-verge.yaml 的目录')  # 不猜多个候选。
        if path:  # 只保存本次窗口内存。
            self.config_root = path  # 不写入公开预设。
            self.detect()  # 重新只读核对。

    def reveal(self):  # 单实例和托盘统一唤醒。
        self.showNormal()  # 恢复窗口。
        self.raise_()  # 前置本应用。
        self.activateWindow()  # 请求焦点。

    def nativeEvent(self, event_type, message):  # 嵌入子控件后由顶层接收电源通知。
        msg = wintypes.MSG.from_address(int(message))  # 不读取其他应用消息。
        if msg.message == 0x218 and self.keepalive:  # WM_POWERBROADCAST。
            if msg.wParam == 4 and (self.keepalive.engine.active or self.keepalive.awaiting or self.keepalive.recovering):  # 睡眠前停止。
                self.keepalive.stop('POWER_SUSPEND')  # 撤销恢复授权并清理网络进程。
                self.keepalive.deferred_notice = '电脑睡眠前已停止保活，请检查后手动重新开始。'  # 唤醒后只提醒一次。
            elif msg.wParam in (7, 18) and self.keepalive.deferred_notice:  # 唤醒通知。
                notice, self.keepalive.deferred_notice = self.keepalive.deferred_notice, None  # 清除后再展示。
                QTimer.singleShot(0, lambda: self.keepalive.alert(notice))  # 不自动重启。
        return super().nativeEvent(event_type, message)  # 其他消息交给Qt。

    def closeEvent(self, event):  # X按钮收起至托盘。
        if self.exiting or self.preview_mode:  # 预览窗口可直接清理。
            self.cleanup()  # 释放本机测试资源。
            event.accept()  # 允许关闭。
        elif QSystemTrayIcon.isSystemTrayAvailable():  # 托盘可用才隐藏。
            self.hide()  # 任务继续后台运行。
            event.ignore()  # 不关闭浏览器。
        else:  # 无托盘不能失去控制界面。
            event.ignore()  # 走完整退出清理。
            self.quit()  # 处理运行任务。

    def quit(self):  # 退出前统一协调任务。
        if self.mutating():  # 不在配置写入中间强杀事务。
            QMessageBox.information(self, '请等待分流事务完成', '当前正在应用或回滚分流，请等待终态后再退出。')  # 防止半写配置。
            return  # 保持界面可见。
        if self.transfer and self.transfer.task.busy:  # 取消传输需要保留清理机会。
            if QMessageBox.question(self, '结束本批传输并退出', '退出将取消本批 SFTP，已成功文件保留。是否继续？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:  # 用户明确选择。
                return  # 不影响当前任务。
            self.transfer.task.completed.connect(lambda unused: self.finish_quit())  # 等实际进程退出。
            self.transfer.task.cancel()  # 有界清理，本进程结束后再退出GUI。
            return  # 不立即销毁QProcess。
        self.finish_quit()  # 无传输时直接结束。

    def cleanup(self):  # 测试和正常退出共用清理。
        self.timer.stop()  # 不再协调控件。
        self.tray.hide()  # 移除统一托盘。
        if self.keepalive:  # 撤销扩展权限与网络请求。
            self.keepalive.stop()  # 保活停止不取消传输。
            self.keepalive.timer.stop()  # 不保留轮询。
            if self.keepalive.bridge:  # 预览没有正式管道。
                self.keepalive.bridge.close()  # 浏览器不关闭。
            for handler in tuple(self.keepalive.logger.handlers):  # 退出后释放自己的日志句柄。
                handler.close()  # Windows文件可正常清理或轮转。
                self.keepalive.logger.removeHandler(handler)  # 不留下指向已关闭文件的处理器。
        for task in (self.detector, self.routing.task if self.routing else None):  # 退出时剩余只有只读任务。
            if task and task.busy:  # 不遗留自己的后台检测。
                task.force_stop()  # 只结束本程序持有的进程。
                task.process.waitForFinished(2000)  # 确认退出。

    def finish_quit(self):  # 网络进程已退出后执行。
        self.exiting = True  # closeEvent允许关闭。
        self.cleanup()  # 清理IPC和托盘。
        QApplication.instance().quit()  # 不影响Edge或其他应用。

def installed_components(override=None):  # 安装器后续写入同一组件契约。
    if override is not None:  # 显式空选择不能偷偷回退到全部组件。
        return normalize_selection(override.split(','))  # 不允许空安装或任意模块。
    manifest = Path(sys.executable).parent / 'components.json' if getattr(sys, 'frozen', False) else None  # 安装版位置固定。
    if manifest is not None:  # 安装版必须有实际安装清单。
        value = json.loads(manifest.read_text(encoding='utf-8'))  # 缺失或损坏不能假装全部安装。
        if value.get('schema') != 1:  # 版本化格式。
            raise ValueError('安装组件清单版本不受支持。')  # 停止启动。
        return normalize_selection(value['components'])  # 至少一项。
    return COMPONENTS  # 源码仓库包含三个组件。

def main():  # 无开机自启、无任务自动恢复。
    parser = argparse.ArgumentParser(description='郑州超算助手')  # 不接受凭据参数。
    parser.add_argument('--components')  # 源码组件组合验收。
    parser.add_argument('--preview', action='store_true')  # 安全界面验收模式。
    parser.add_argument('--smoke-test', action='store_true')  # 明确离线预览时验证真实GUI EXE入口后自动退出。
    args = parser.parse_args()  # 不读取环境口令。
    if args.smoke_test and not args.preview:  # 自检不能自动启动真实检测或任务。
        parser.error('--smoke-test必须与--preview一起使用。')  # 不进入正式会话。
    application = QApplication(sys.argv[:1])  # 不把应用参数交Qt解析。
    application.setQuitOnLastWindowClosed(False)  # 正常收起到托盘。
    from .instance import InstanceGuard  # 共享组件单实例，不依赖Edge。
    guard = InstanceGuard()  # 内核自动回收锁。
    name = 'ZZU-NSCC-Helper-v1'  # 本机当前用户通道。
    if not guard.primary:  # 重复启动只唤回现有实例。
        peer = QLocalSocket()  # 不访问网络。
        peer.connectToServer(name)  # 连接同用户通道。
        if peer.waitForConnected(2000):  # 启动中允许短暂等待。
            peer.write(b'SHOW\n')  # 只唤醒，不创建任务。
            peer.waitForBytesWritten(1000)  # 确保送达。
        guard.close()  # 释放本次锁引用。
        return 0  # 不创建第二界面。
    legacy_guard = InstanceGuard(prefix='ZZDXVPNKeepalive-')  # 升级期也禁止与原独立助手同时控制网络。
    if not legacy_guard.primary:  # 原助手可能仍有未结束任务。
        QMessageBox.information(None, '旧版助手仍在运行', '请先停止并退出旧版 SSL VPN 保活助手，再打开统一版；当前未关闭旧任务或浏览器。')  # 不自动抢占通道。
        legacy_guard.close()  # 释放本次旧互斥引用。
        guard.close()  # 不占用新软件入口。
        return 1  # 等用户完成旧任务。
    server = QLocalServer()  # 当前用户单实例唤醒。
    server.setSocketOptions(QLocalServer.UserAccessOption)  # 限制用户访问。
    if not server.listen(name):  # 锁和通道必须同时成功。
        legacy_guard.close()  # 同时释放兼容锁。
        guard.close()  # 不留下第二控制器。
        return 1  # 明确启动失败。
    try:  # 安装清单异常要有可见中文反馈。
        selected = installed_components(args.components)  # 拒绝空选择或未知清单版本。
    except (OSError, ValueError, KeyError, TypeError):  # 不输出本机配置正文。
        QMessageBox.critical(None, '安装组件配置异常', '组件清单缺失、损坏或版本不受支持，请修复本软件安装。')  # 不寻找用户Python或猜测安装内容。
        server.close()  # 启动失败释放专用通道。
        guard.close()  # 释放主互斥。
        legacy_guard.close()  # 释放兼容互斥。
        return 1  # 不创建半套界面。
    window = MainWindow(selected, preview=args.preview)  # 不自动开始保活或传输。
    def awaken():  # 重复启动只显示主窗口。
        peer = server.nextPendingConnection()  # 取本机请求。
        window.reveal()  # 不恢复停止任务。
        if peer:  # 及时清理短连接。
            peer.disconnectFromServer()  # 不建立长期控制通道。
            peer.deleteLater()  # 释放对象。
    server.newConnection.connect(awaken)  # 唤醒入口。
    application.aboutToQuit.connect(window.cleanup)  # 最终清理保障。
    window.show()  # 用户选择组件内的实际动作。
    if args.smoke_test:  # CI启动真正无控制台GUI EXE，而非只导入控件。
        QTimer.singleShot(1500, window.finish_quit)  # 正常事件循环后释放锁、托盘和所有子对象。
    result = application.exec_()  # Qt事件循环。
    server.close()  # 释放唤醒通道。
    guard.close()  # 释放单实例锁。
    legacy_guard.close()  # 允许旧版在统一助手退出后再启动。
    return result  # 正常退出状态。
