let port = null; // 本机 Native Messaging 通道。
let binding = null; // 仅内存保存手动绑定，重启扩展不自动恢复。
let pulse = null; // 本机心跳，不访问超算网络。
let recoveryTimer = null; // 单次恢复截止时间。
let listBusy = false; // 不并发枚举标签页。
function emit(event, data = {}) { // 只向本机桌面程序发送。
  if (port) { try { port.postMessage({event, ...data}); } catch (_) { clearBinding(); } } // 连接错误撤销恢复权限。
} // 结束发送。
function clearBinding() { // 所有停止路径统一撤销。
  binding = null; // 失联后禁止重开网页。
  clearTimeout(recoveryTimer); // 不执行旧恢复回调。
  recoveryTimer = null; // 清空定时器引用。
} // 结束撤销。
function fail(code) { // 单次故障只发送一次。
  const old = binding; // 保存本次会话标识。
  clearBinding(); // 先撤销自动行为。
  if (old) emit('failed', {token: old.token, code}); // 不发送页面正文或密码。
} // 结束失败。
function safeTarget(url) { // 首版仅允许已知超算入口。
  try { const u = new URL(url); return u.origin === 'https://172.99.2.7' && u.pathname === '/ac/console3/index.html' && ['#/e-file', '#/space/dashboard'].includes(u.hash) && !u.username && !u.password; } catch (_) { return false; } // 不恢复任意网址。
} // 结束地址检查。
function compact(tab) { // 只保留桌面选择所需元数据。
  return {id: tab.id, windowId: tab.windowId, title: (tab.title || '无标题').slice(0, 200), url: (tab.url || '').slice(0, 2048), status: tab.status || 'loading', eligible: safeTarget(tab.url || '')}; // 不读取 Cookie。
} // 结束结构转换。
async function listTabs() { // 列出真实标签页而非窗口标题。
  if (!port || listBusy) return; // 无助手则不枚举。
  listBusy = true; // 防止重叠。
  try { // 按小批次发送所有普通标签，避免单帧超大。
    const tabs = (await chrome.tabs.query({})).filter(t => !t.incognito); // 不读取隐私窗口。
    if (!tabs.length) emit('tabs', {version: '0.4.0', tabs: [], total: 0, first: true, final: true}); // 空列表也完成快照。
    for (let i = 0; i < tabs.length; i += 20) emit('tabs', {version: '0.4.0', tabs: tabs.slice(i, i + 20).map(compact), total: tabs.length, first: i === 0, final: i + 20 >= tabs.length}); // 每项都是独立标签。
  } catch (_) { emit('list_error'); } finally { listBusy = false; } // 完整快照更新后释放枚举锁。
} // 结束列表。
async function probe(tabId, expectedUrl) { // 只在绑定或恢复时检查目标页面。
  const tab = await chrome.tabs.get(tabId); // 获取最新真实地址。
  if (tab.status !== 'complete' || tab.url !== expectedUrl || !safeTarget(tab.url)) throw new Error('PAGE_NOT_READY'); // 登录重定向、空白页和错误页不通过。
  const results = await chrome.scripting.executeScript({target: {tabId}, func: () => { // 限定主框架，仅返回布尔值。
    const visible = el => Boolean(el.getClientRects().length); // 隐藏表单不作为登录画面。
    const password = [...document.querySelectorAll('input[type="password"]')].some(visible); // 不读取任何输入值。
    const text = document.body ? document.body.innerText : ''; // 仅在页面内做特征判断。
    const expected = location.hash === '#/e-file' ? /文件/ : /计算服务/; // 已知路由的保守特征。
    return {ready: document.readyState === 'complete' && !password && expected.test(text) && !/登录已过期|会话已过期|请重新登录|证书错误/.test(text)}; // 不向外发送正文。
  }}); // 不能执行时直接失败，不绕过证书。
  if (!results[0]?.result?.ready) throw new Error('PAGE_NOT_READY'); // 不把标签创建成功当恢复成功。
  return compact(tab); // 返回通过检查的标签元数据。
} // 结束检查。
async function recovered(state) { // 恢复完成后重新验证页面。
  if (binding !== state || !state.recovering || state.checking) return; // 防止重复回调。
  state.checking = true; // 一次验证。
  try { const tab = await probe(state.id, state.url); if (binding !== state) return; clearTimeout(recoveryTimer); state.recovering = false; state.checking = false; emit('restored', {token: state.token, tab}); } catch (_) { if (binding === state) fail('RESTORE_PAGE_INVALID'); } // 失败立即停止。
} // 结束恢复检查。
async function command(msg) { // 桌面发出的有限命令。
  if (!msg || typeof msg.command !== 'string') return; // 拒绝无效输入。
  if (msg.command === 'list') { await listTabs(); return; } // 刷新列表。
  if (msg.command === 'stop') { clearBinding(); return; } // 手动停止立即撤销。
  if (msg.command === 'focus' && Number.isInteger(msg.id)) { // 定位真正的标签页。
    try { const t = await chrome.tabs.update(msg.id, {active: true}); await chrome.windows.update(t.windowId, {focused: true}); } catch (_) { emit('focus_error'); } // 不创建新页面。
    return; // 定位不自动绑定。
  } // 结束定位。
  if (msg.command === 'bind') { // 确认目标后进行页面预检。
    clearBinding(); // 撤销上一会话。
    const state = {id: msg.id, token: msg.token, url: msg.url, recovering: false}; // 固定初始地址。
    if (!Number.isInteger(state.id) || typeof state.token !== 'string' || !safeTarget(state.url)) { emit('failed', {token: msg.token, code: 'TARGET_NOT_ALLOWED'}); return; } // 限定目标。
    binding = state; // 保存身份供异步取消判断。
    emit('binding_started', {token: state.token}); // 立即确认命令已收到，避免桌面静默等待。
    try { // 初始绑定只核对真实标签身份，网络可用性由已验证的 HTTPS 请求决定。
      const current = await chrome.tabs.get(state.id); // 不等待标签页内脚本执行。
      if (current.url !== state.url || !safeTarget(current.url)) throw new Error('TARGET_CHANGED'); // 原地址改变则拒绝绑定。
      state.windowId = current.windowId; // 保存原窗口，恢复时不重开浏览器。
      if (binding === state) emit('bound', {token: state.token, tab: compact(current)}); // 绑定完成后桌面立即执行真实交互。
    } catch (_) { if (binding === state) fail('PAGE_NOT_READY'); } // 已关闭或地址不匹配则停止。
    return; // 完成绑定命令。
  } // 结束绑定。
  if (msg.command === 'recover' && binding && msg.token === binding.token) { // 桌面停止计时后才授权重开。
    const state = binding; // 本次恢复对象。
    if (!state.recovering || state.attempted) return; // 同一次关闭只能尝试一次。
    state.attempted = true; // 在异步操作前占用尝试机会。
    try { // 任何错误都停止。
      const windows = await chrome.windows.getAll({windowTypes: ['normal']}); // 不重新启动浏览器。
      if (binding !== state) return; // 已手动停止不创建标签。
      const existing = windows.find(w => w.id === state.windowId); // 只在原窗口恢复。
      if (!existing) { fail('BROWSER_WINDOW_CLOSED'); return; } // 关窗口不重开。
      const tab = await chrome.tabs.create({windowId: existing.id, url: state.url, active: false}); // 仅重开一页，不恢复表单提交。
      if (binding !== state) return; // 创建期间停止后不继续保活。
      state.id = tab.id; // 绑定新的标签标识。
      emit('restoring', {token: state.token, id: tab.id}); // 告知桌面新标识。
      recoveryTimer = setTimeout(() => { if (binding === state) fail('RESTORE_TIMEOUT'); }, 20000); // 二十秒恢复截止。
      if (tab.status === 'complete') await recovered(state); // 快速加载也走同样校验。
    } catch (_) { if (binding === state) fail('RESTORE_FAILED'); } // 不重试。
  } // 结束恢复命令。
} // 结束命令处理。
function connect() { // 连接软件内置桥接进程。
  if (port) return; // 不建立多重连接。
  try { // 桌面未启动时允许失败。
    const current = chrome.runtime.connectNative('cn.zzdx.vpn_tabs'); // Edge 启动已注册本机组件。
    port = current; // 保存当前连接。
    current.onMessage.addListener(msg => { command(msg).catch(() => fail('COMMAND_FAILED')); }); // 捕获异步错误。
    current.onDisconnect.addListener(() => { void chrome.runtime.lastError; if (port !== current) return; port = null; clearBinding(); clearInterval(pulse); pulse = null; }); // 助手退出后停止所有任务。
    emit('hello', {version: '0.4.0'}); // 初次握手。
    listTabs(); // 初次发送列表。
    pulse = setInterval(() => { emit('heartbeat'); }, 2000); // 仅本机心跳。
  } catch (_) { port = null; clearBinding(); } // 不静默恢复旧任务。
} // 结束连接。
chrome.tabs.onRemoved.addListener((id, info) => { // 捕获真实标签关闭。
  if (!binding || binding.id !== id) { listTabs(); return; } // 无关页面不影响绑定。
  if (info.isWindowClosing || binding.recovering) { fail('BROWSER_WINDOW_CLOSED'); return; } // 不反复恢复或重开窗口。
  binding.windowId = info.windowId; binding.recovering = true; binding.attempted = false; // 等待桌面同意单次恢复。
  emit('closed', {token: binding.token}); // 先暂停计时。
}); // 完成关闭监听。
chrome.tabs.onUpdated.addListener((id, change, tab) => { // 页面加载及地址变化。
  if (change.title || change.url || change.status === 'complete') listTabs(); // 更新下拉框。
  const state = binding; // 当前恢复会话。
  if (!state || state.id !== id) return; // 忽略其他标签。
  if (!state.recovering && change.url && change.url !== state.url) { fail('TARGET_NAVIGATED'); return; } // 导航离开绑定页面则停止。
  if (state.recovering && change.status === 'complete') recovered(state); // 完整加载后验证。
}); // 完成更新监听。
chrome.tabs.onCreated.addListener(() => listTabs()); // 新标签出现在列表。
chrome.webNavigation.onErrorOccurred.addListener(info => { if (binding && binding.id === info.tabId && info.frameId === 0) fail('PAGE_LOAD_FAILED'); }); // 主框架失败即停止。
chrome.action.onClicked.addListener(connect); // 扩展图标仅用于手动重连。
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'desktop-connect') connect(); }); // 助手稍后启动时可连接。
chrome.alarms.create('desktop-connect', {periodInMinutes: 0.5}); // 只尝试本机连接，不访问内网。
connect(); // 安装或浏览器启动时连接本机助手。
