let webBinding = null; // 网页会话独立于旧版标签恢复，不持久保存授权。
function sessionTarget(raw) { // 仅允许三种已核对的超算业务页面。
  try { const u = new URL(raw); return u.origin === 'https://172.99.2.7' && !u.username && !u.password && !u.search && /^\/ac\/console3\/index\.html(?:;jsessionid=[a-fA-F0-9]{32})?$/.test(u.pathname) && ['#/e-file', '#/space/dashboard', '#/space/shell'].includes(u.hash); } catch (_) { return false; } // 不扩大到登录页、工单或其他网站。
} // 结束目标检查。
async function pageSessionRequest(expectedUrl) { // 此函数整体在目标网页主上下文执行，敏感响应留在网页内。
  const started = performance.now(); // 单调时钟记录本次耗时。
  const controller = new AbortController(); // 同时支持二十秒超时与桌面取消。
  const key = '__zzuNsccSessionRequestV1'; // 仅在当前页面保存取消句柄。
  if (window[key]) return {ok: false, error: 'WEB_BUSY'}; // 不并发访问会话接口。
  window[key] = controller; // 只有本次控制器能提交返回的数据。
  const timer = setTimeout(() => controller.abort(), 20000); // 包括响应读取的总期限。
  let bytes = 0; // 只允许将响应长度传给桌面。
  try { // 任何未知页面、认证或解析错误都不算成功。
    if (location.href !== expectedUrl || location.origin !== 'https://172.99.2.7') throw new Error('WEB_TARGET_CHANGED'); // 注入前后的地址必须完全相同。
    const store = window.app?.$store; // 使用平台自身现有状态容器，不读取 Cookie 或存储中的令牌。
    const previous = store?.state?.user?.userInfo; // 只在页面内确认当前用户身份未切换。
    if (!previous?.id || !Array.isArray(previous.roleId) || typeof store.commit !== 'function') throw new Error('WEB_PAGE_NOT_READY'); // 登录页或未初始化页面不能发请求。
    const response = await fetch('/ac/api/user/getCurrentUserInfo.action?includeToken=true&refresh=true', {method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: {'Accept': 'application/json', 'Cache-Control': 'no-cache'}, signal: controller.signal}); // 复用平台前端真实只读接口，让浏览器自行携带本网站登录态。
    if ([401, 403].includes(response.status)) throw new Error('WEB_LOGIN_EXPIRED'); // HTTP 认证失败单独分类。
    if (response.status !== 200 || response.redirected || !/application\/json/i.test(response.headers.get('content-type') || '') || !response.body) throw new Error('WEB_RESPONSE_INVALID'); // 登录 HTML、空响应和非预期重定向一律失败。
    const reader = response.body.getReader(); // 分块读取，限制响应体而非无限制 JSON 读取。
    const decoder = new TextDecoder(); // 正确处理 UTF-8 多字节边界。
    let text = ''; // 原始响应只存在本网页本次调用的内存中。
    while (true) { const chunk = await reader.read(); if (chunk.done) break; bytes += chunk.value.byteLength; if (bytes > 65536) { await reader.cancel(); throw new Error('WEB_RESPONSE_TOO_LARGE'); } text += decoder.decode(chunk.value, {stream: true}); } // 读取上限64KiB。
    text += decoder.decode(); // 完成字符解码。
    if (!bytes) throw new Error('WEB_RESPONSE_EMPTY'); // 空响应不能续期成功。
    const result = JSON.parse(text); // 不将正文或服务端错误文本输出到控制台或桌面。
    if (['401', '403'].includes(String(result.code))) throw new Error('WEB_LOGIN_EXPIRED'); // 同时核对平台业务认证码。
    const user = result.data; // 此对象可能包含令牌，只能留在网页内。
    if (String(result.code) !== '0' || !user || String(user.id) !== String(previous.id) || !Array.isArray(user.roleId) || !Array.isArray(user.tokenList)) throw new Error('WEB_RESPONSE_INVALID'); // 成功码、当前用户及平台实际结构都必须匹配。
    if (controller.signal.aborted || window[key] !== controller || location.href !== expectedUrl) throw new Error('WEB_CANCELLED'); // 取消或导航后不更新页面状态。
    store.commit('SET_USER_INFO', user); // 与平台初始化相同的状态更新，使该页后续 E-File/E-Shell 请求采用返回的当前令牌。
    return {ok: true, status: 200, bytes, elapsed: (performance.now() - started) / 1000}; // 只返回无账号、无令牌的技术摘要。
  } catch (error) { // 不透传浏览器或服务端原始报错文本。
    const known = ['WEB_BUSY', 'WEB_TARGET_CHANGED', 'WEB_PAGE_NOT_READY', 'WEB_LOGIN_EXPIRED', 'WEB_RESPONSE_INVALID', 'WEB_RESPONSE_TOO_LARGE', 'WEB_RESPONSE_EMPTY', 'WEB_CANCELLED']; // 有限错误类别。
    return {ok: false, error: controller.signal.aborted ? 'WEB_CANCELLED_OR_TIMEOUT' : known.includes(error?.message) ? error.message : 'WEB_NETWORK_OR_PARSE', bytes, elapsed: (performance.now() - started) / 1000}; // 失败不自动重试。
  } finally { clearTimeout(timer); if (window[key] === controller) delete window[key]; } // 保证取消句柄和定时器清理。
} // 结束页面内真实交互。
async function clearWebBinding() { // 停止只取消本软件正在进行的网页请求。
  const previous = webBinding; webBinding = null; // 先撤销授权，迟到的结果不能恢复任务。
  if (!previous?.busy) return; // 未发请求无需注入取消函数。
  try { await chrome.scripting.executeScript({target: {tabId: previous.busy}, world: 'MAIN', func: () => { window.__zzuNsccSessionRequestV1?.abort(); }}); } catch (_) { /* 标签关闭时其请求已经随文档退出。 */ } // 不关闭标签或网页自身的其他请求。
} // 结束取消。
async function webCommand(msg) { // 网页交互仅由桌面授权命令触发，不在扩展内自动循环。
  if (!['web_bind', 'web_request', 'web_stop'].includes(msg.command)) return false; // 保留旧版标签协议兼容。
  if (msg.command === 'web_stop') { await clearWebBinding(); return true; } // 幂等停止。
  if (msg.command === 'web_bind') { // 每次重新绑定都需要用户在助手内点击。
    await clearWebBinding(); // 取消旧请求后才接纳新目标。
    if (!Number.isInteger(msg.id) || !/^[a-f0-9]{32}$/.test(msg.token || '') || !sessionTarget(msg.url)) { emit('web_failed', {token: msg.token, code: 'WEB_TARGET_CHANGED'}); return true; } // 限定标签与本地随机授权标识。
    const state = {token: msg.token, tabs: [], busy: null, running: false, lastRequest: 0}; webBinding = state; // 只在内存保存目标，不保存返回令牌。
    try { // 精确核对选中的页面以及用户允许的同会话页面。
      const selected = await chrome.tabs.get(msg.id); // 不依赖旧列表。
      if (selected.incognito || selected.url !== msg.url || !sessionTarget(selected.url)) throw new Error(); // 拒绝过期选择。
      const path = new URL(selected.url).pathname; // 会话参数仅用于当前浏览器内的同会话分组。
      const all = msg.related === true ? await chrome.tabs.query({}) : [selected]; // 只有勾选同会话页面才加入其他业务标签。
      state.tabs = all.filter(t => !t.incognito && sessionTarget(t.url) && new URL(t.url).pathname === path).map(t => ({id: t.id, url: t.url})); // 不接纳不同会话或其他站点。
      if (!state.tabs.length || state.tabs.length > 10) throw new Error(); // 十个页面上限避免一次交互持续过久。
      if (webBinding === state) emit('web_bound', {token: state.token, pages: state.tabs.length}); // 不把绑定成功当真实请求成功。
    } catch (_) { if (webBinding === state) { await clearWebBinding(); emit('web_failed', {token: state.token, code: 'WEB_TARGET_CHANGED'}); } } // 不重试不自动打开标签。
    return true; // 完成绑定命令。
  } // 结束绑定分支。
  const state = webBinding; // 固定本轮授权身份。
  if (!state || msg.token !== state.token || state.running || !Number.isSafeInteger(msg.request) || msg.request <= state.lastRequest) return true; // 并发、旧消息和重复编号全部忽略。
  state.lastRequest = msg.request; state.running = true; // 单调编号去重，不积累历史集合。
  let pages = 0, bytes = 0, elapsed = 0; // 仅累计无敏感信息的摘要。
  try { // 每页实际交互一次；任一失败停止本轮网页维护。
    for (const target of state.tabs) { // 所有页面顺序执行，不发送并发会话刷新。
      if (webBinding !== state) return true; // 桌面取消后不发下一请求。
      const tab = await chrome.tabs.get(target.id); // 导航、关闭和休眠未加载页面都不冒充在线。
      if (tab.url !== target.url || tab.status !== 'complete' || !sessionTarget(tab.url)) throw new Error('WEB_TARGET_CHANGED'); // 不采用新登录态自动重绑。
      state.busy = target.id; // 取消命令只针对当前这页的专用请求。
      const results = await chrome.scripting.executeScript({target: {tabId: target.id}, world: 'MAIN', func: pageSessionRequest, args: [target.url]}); // 浏览器原有 TLS 与认证处理，不关闭证书检查。
      state.busy = null; // 本页请求已结束。
      if (webBinding !== state) return true; // 丢弃停止后迟到结果。
      const result = results[0]?.result; // 只接受函数返回的最小摘要。
      if (result?.ok !== true || result.status !== 200 || !(result.bytes > 0 && result.bytes <= 65536)) throw new Error(result?.error || 'WEB_RESPONSE_INVALID'); // 不把执行脚本成功当网络成功。
      pages += 1; bytes += result.bytes; elapsed += result.elapsed; // 汇总真实成功页面。
    } // 结束逐页交互。
    if (webBinding === state) emit('web_success', {token: state.token, request: msg.request, pages, bytes, elapsed}); // 不发送响应正文、帐号或令牌。
  } catch (error) { // 失败只通知一次，后续必须用户重新绑定。
    if (webBinding === state) { await clearWebBinding(); emit('web_failed', {token: state.token, code: /^WEB_[A-Z_]+$/.test(error?.message || '') ? error.message : 'WEB_TARGET_CLOSED', pages}); } // 有限错误且不透传网址。
  } finally { state.running = false; } // 释放本轮状态。
  return true; // 命令已消费。
} // 结束网页命令处理。
async function webTargetChanged(id, newUrl) { // 标签关闭或导航立即撤销网页授权，不影响桌面VPN。
  const state = webBinding; // 固定旧授权以免异步撤销新任务。
  const target = state?.tabs.find(tab => tab.id === id); // 只检查用户本次选中的页面集合。
  if (!target || newUrl === target.url) return; // 标题变化与无关标签不影响。
  await clearWebBinding(); // 先取消本次专用请求，不自动刷新或重开。
  emit('web_failed', {token: state.token, code: newUrl ? 'WEB_TARGET_CHANGED' : 'WEB_TARGET_CLOSED'}); // 返回固定类别即可。
} // 结束页面生命周期处理。
