let webBinding = null; // 绑定与响应仅在扩展内存保存，停止即释放。
const webPageJobs = new Map(); // 冻结页面最多一个待执行脚本，不堆积注入。
const WEB_API = 'https://172.99.2.7/ac/api/user/getCurrentUserInfo.action?includeToken=true&refresh=true'; // 平台自身的固定只读接口。
const WEB_TRANSIENT = new Set(['WEB_TIMEOUT', 'WEB_NETWORK', 'WEB_SERVER_BUSY', 'WEB_RESPONSE_EMPTY', 'WEB_PAGE_NOT_READY', 'WEB_CLEANUP_PENDING', 'WEB_SERVICE_REJECTED']); // 暂态问题由桌面退避恢复。
function sessionTarget(raw) { // 只接纳已核对的三个业务路由。
  try { const u = new URL(raw); return u.origin === 'https://172.99.2.7' && !u.username && !u.password && !u.search && /^\/ac\/console3\/index\.html(?:;jsessionid=[a-fA-F0-9]{32})?$/.test(u.pathname) && ['#/e-file', '#/space/dashboard', '#/space/shell'].includes(u.hash); } catch (_) { return false; } // 不扩大到其他网站或登录页面。
} // 结束目标检查。
async function identityHash(value) { // 账户校验使用摘要，不经本机消息传输。
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(value))); // 不读取密码或Cookie。
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join(''); // 摘要只留在浏览器内存。
} // 结束摘要。
async function pageSessionState(expectedUrl, deadline, expectedIdentity = null, user = null) { // 页面内仅检查与同步状态，绝不启动网络请求。
  if (Date.now() >= deadline || location.href !== expectedUrl || location.origin !== 'https://172.99.2.7') return {ok: false}; // 冻结后迟到脚本不能应用旧结果。
  const store = window.app?.$store, current = store?.state?.user?.userInfo; // 使用平台原有状态，不读取浏览器存储。
  if (!current?.id || !Array.isArray(current.roleId) || typeof store.commit !== 'function') return {ok: false}; // 未登录页面不参与。
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(current.id))); // 不从页面导出原账号。
  const identity = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join(''); // 固定长度身份摘要。
  if (Date.now() >= deadline || location.href !== expectedUrl || String(store.state.user.userInfo?.id) !== String(current.id)) return {ok: false}; // 异步计算后再次核对。
  if (expectedIdentity && identity !== expectedIdentity) return {ok: false, changed: true}; // 不把其他账户的数据写入本页。
  if (user) store.commit('SET_USER_INFO', user); // 与平台初始化逻辑一致，服务令牌仅在浏览器内使用。
  if (user) return {ok: true}; // 同步时不再读取集群元数据。
  const cluster = store.getters?.efileServiceClusterId, home = store.getters?.clusterIdMap?.[cluster]?.clusterUserHomePath; // 用户实际选择集群对应的个人主目录。
  if (!cluster || !home || typeof store.dispatch !== 'function') return {ok: false}; // 必要参数缺失不能猜测。
  const service = await store.dispatch('GetServiceUrl', {clusterId: cluster, type: 'efileUrl'}); // E-File使用平台已选择服务地址，不触发文件操作。
  if (Date.now() >= deadline || location.href !== expectedUrl || String(store.state.user.userInfo?.id) !== String(current.id)) return {ok: false}; // 等待期间改变身份则拒绝。
  return {ok: true, identity, profile: {cluster: String(cluster), home, base: service.url}, user: current}; // 该结果只返回浏览器扩展，不返回桌面。
} // 结束页面函数。
async function boundedPage(target, state, user = null) { // 页面卡顿不阻塞后台HTTP。
  const tab = await chrome.tabs.get(target.id); // 核实真实标签身份。
  if (tab.url !== target.url || !sessionTarget(tab.url)) return {ok: false}; // 导航后不注入旧结果。
  if (tab.frozen || tab.discarded || tab.status !== 'complete' || webPageJobs.has(target.id)) return {ok: false, deferred: true}; // 不强行激活或刷新业务页。
  if (webBinding !== state) return {ok: false}; // 停止后不新增脚本。
  const deadline = Date.now() + 8000; // 扩展赋予绝对期限，迟到执行也能识别。
  const job = chrome.scripting.executeScript({target: {tabId: target.id}, world: 'MAIN', func: pageSessionState, args: [target.url, deadline, state.identity || null, user]}); // 请求不再依赖网页计时器。
  webPageJobs.set(target.id, job); // 一个页面最多一个挂起注入。
  const settled = job.then(results => results[0]?.result || {ok: false}, () => ({ok: false})).finally(() => { if (webPageJobs.get(target.id) === job) webPageJobs.delete(target.id); }); // 正常、失败均释放占用。
  let timer; // 超时在扩展侧执行。
  try { return await Promise.race([settled, new Promise(resolve => { timer = setTimeout(() => resolve({ok: false, deferred: true}), 8000); })]); } finally { clearTimeout(timer); } // 同步延期不冒充认证失败。
} // 结束有界注入。
async function syncWebPage(id) { // 页面恢复响应时应用最近服务器结果，不增加平台请求。
  const state = webBinding, target = state?.tabs.find(tab => tab.id === id); // 仅授权集合。
  if (!target || !state.latest || Date.now() - state.latest.at > 900000) return; // 不应用过期结果。
  const latest = state.latest; // 当前唯一缓存，不写磁盘。
  try { const result = await boundedPage(target, state, latest.user); if (webBinding === state && state.latest === latest && result.ok) { state.synced.add(id); emit('web_sync', {token: state.token, request: latest.request, pages: state.tabs.length, synced: state.synced.size}); } } catch (_) { /* 页面关闭或冻结留待下一轮，不记录原文。 */ } // 唤醒后的同步也即时更新桌面摘要。
} // 结束唤醒同步。
async function clearWebBinding() { // 取消不再依赖被冻结网页内的脚本。
  const old = webBinding; webBinding = null; // 先撤销权限，迟到结果立即失效。
  if (!old) return; // 幂等退出。
  old.latest = null; old.controller?.abort(); // 清除缓存并取消扩展自己的fetch。
  if (old.task) await old.task; // 旧网络任务结束后才允许重新绑定，不等待页面同步。
} // 结束停止。
async function runWebRequest(state, request) { // 每轮完整文件交互，桌面独立安排24小时间隔。
  const started = performance.now(); // 单调时钟记录整轮耗时。
  try { // 所有响应与凭据只留在浏览器内存。
    if (!state.identity) { // 手动绑定时先确认当前页面身份和集群。
      const result = await boundedPage(state.selected, state); // 页面冻结时有界等待后退避。
      if (!result.ok || !/^[a-f0-9]{64}$/.test(result.identity || '') || !result.profile) throw new Error('WEB_PAGE_NOT_READY'); // 参数不明不发写请求。
      state.identity = result.identity; state.profile = result.profile; state.user = result.user; // 后续请求不等待冻结页面渲染器。
    } else { // 后续优先核对响应中的页面身份；冻结页不阻塞文件服务自己的认证。
      const current = await boundedPage(state.selected, state); // 此处只有本地页面状态读取，没有HTTP。
      if (current.changed || current.ok && current.identity !== state.identity) throw new Error('WEB_LOGIN_CHANGED'); // 页面明确换号立即停止。
      if (current.ok) { if (JSON.stringify(current.profile) !== JSON.stringify(state.profile)) throw new Error('WEB_TARGET_CHANGED'); state.user = current.user; } // 不悄悄切换集群或目录。
    } // 结束初次授权信息解析。
    dailyActive(state); // 初始化期间停止则不联网。
    emit('web_progress', {token: state.token, request, stage: 'identity'}); // 固定阶段无敏感资料。
    let user = state.user; // 使用当前网页已经取得的服务凭据，绝不传给桌面。
    if (!user?.id || !Array.isArray(user.roleId) || !Array.isArray(user.tokenList)) throw new Error('WEB_RESPONSE_INVALID'); // 不把登录HTML当数据。
    if (await identityHash(user.id) !== state.identity) throw new Error('WEB_LOGIN_CHANGED'); // 当前登录身份变化不自动接管遗留文件。
    try { await dailyTransaction(state, request, user); } catch (error) { // 文件服务初始化实际验证身份，不把静态页面当认证成功。
      if (error?.message !== 'WEB_LOGIN_EXPIRED') throw error; // 普通失败由事务恢复，不刷新登录凭据。
      try { user = await dailyFetch(state, WEB_API); } catch (_) { throw new Error('WEB_LOGIN_EXPIRED'); } // 仅必要时尝试平台原会话接口，TLS或认证失败不绕过。
      if (!user?.id || !Array.isArray(user.roleId) || !Array.isArray(user.tokenList) || await identityHash(user.id) !== state.identity) throw new Error('WEB_LOGIN_CHANGED'); // 新凭据仍必须属于原身份。
      state.user = user; await dailyTransaction(state, request, user); // 同一事务记录继续，不生成第二个文件。
    } // 上传、完整读回、删除与确认不存在全部完成才成功。
    dailyActive(state); // 取消中的成功不续期。
    state.latest = {user, at: Date.now(), request}; state.synced = new Set(); // 页面恢复响应后同步，不再发网络请求。
    emit('web_success', {token: state.token, request, pages: state.tabs.length, bytes: 1024, elapsed: (performance.now() - started) / 1000, synced: 0, daily: true, cleanup: 'confirmed'}); // 桌面仅接收明确的完整事务摘要。
    void Promise.all(state.tabs.map(tab => syncWebPage(tab.id))); // 页面同步与服务器文件事务分开执行。
  } catch (error) { // 不透传异常原文、账号、路径或令牌。
    if (webBinding !== state || state.cancelled) return; // 取消由单独事件确认。
    const known = ['WEB_PAGE_NOT_READY', 'WEB_LOGIN_EXPIRED', 'WEB_LOGIN_CHANGED', 'WEB_TARGET_CHANGED', 'WEB_SERVER_BUSY', 'WEB_RESPONSE_INVALID', 'WEB_RESPONSE_TOO_LARGE', 'WEB_RESPONSE_EMPTY', 'WEB_TIMEOUT', 'WEB_SERVICE_UNSUPPORTED', 'WEB_OWNERSHIP_UNCONFIRMED', 'WEB_FILE_MISMATCH', 'WEB_CLEANUP_PENDING', 'WEB_SERVICE_REJECTED']; // 固定错误类型。
    const code = known.includes(error?.message) ? error.message : 'WEB_NETWORK'; // 未知网络错误不泄漏网址。
    state.controller?.abort(); // 先结束当前请求，再由桌面退避。
    if (!WEB_TRANSIENT.has(code)) { state.latest = null; webBinding = null; } // 明确身份或归属不符需要手动处理。
    emit('web_failed', {token: state.token, request, code, settled: true, diagnostic: ['fetch', 'body', 'profile', 'journal'].includes(state.diagnostic) ? state.diagnostic : 'binding', errorKind: ['TypeError', 'ReferenceError', 'RangeError', 'SyntaxError', 'Error'].includes(error?.name) ? error.name : 'Other'}); // 未完成文件日志保留用于下次核对。
  } finally { state.controller = null; } // 单轮结束释放当前网络句柄。
} // 结束每日请求。
async function webCommand(msg) { // 桌面统一安排所有实际请求时刻。
  if (!['web_bind', 'web_request', 'web_cancel', 'web_stop'].includes(msg.command)) return false; // 兼容原基础协议。
  if (msg.command === 'web_stop') { await clearWebBinding(); return true; } // 停止后不自动恢复。
  if (msg.command === 'web_cancel') { // 桌面总截止时先确认旧请求取消。
    const state = webBinding; // 不影响其他绑定或后续轮次。
    if (state && state.token === msg.token && state.lastRequest === msg.request) { state.cancelled = true; state.controller?.abort(); if (state.task) await state.task; if (webBinding === state) emit('web_cancelled', {token: state.token, request: msg.request}); } // 不等待冻结页面取消脚本。
    return true; // 完成取消确认。
  } // 结束取消分支。
  if (msg.command === 'web_bind') { // 仅用户显式绑定才接纳新页面。
    await clearWebBinding(); // 旧网络任务终止后再接纳新请求。
    if (msg.protocol !== 3 || !Number.isInteger(msg.id) || !/^[a-f0-9]{32}$/.test(msg.token || '') || !sessionTarget(msg.url)) { emit('web_failed', {token: msg.token, code: 'WEB_TARGET_CHANGED'}); return true; } // 老桌面不能误判新版成功含义。
    const state = {token: msg.token, tabs: [], selected: null, identity: null, latest: null, synced: new Set(), controller: null, task: null, lastRequest: 0, cancelled: false}; webBinding = state; // 不保存账号配置。
    try { // 使用当前实际标签，非旧列表。
      const selected = await chrome.tabs.get(msg.id); // 核对用户选择。
      if (selected.incognito || selected.url !== msg.url || !sessionTarget(selected.url)) throw new Error(); // 拒绝已导航或隐私窗口。
      const all = msg.related === true ? await chrome.tabs.query({}) : [selected]; // 只有勾选后才加入相关业务页。
      state.tabs = all.filter(tab => !tab.incognito && sessionTarget(tab.url) && new URL(tab.url).pathname === new URL(selected.url).pathname).map(tab => ({id: tab.id, url: tab.url})); // 同登录路径，不跨会话。
      state.selected = state.tabs.find(tab => tab.id === msg.id); // 初次验证以用户选择页为准。
      if (!state.selected || state.tabs.length > 10) throw new Error(); // 十页范围上限。
      if (webBinding === state) emit('web_bound', {token: state.token, pages: state.tabs.length}); // 绑定并非实际网络成功。
    } catch (_) { if (webBinding === state) { webBinding = null; emit('web_failed', {token: state.token, code: 'WEB_TARGET_CHANGED'}); } } // 无合法目标不联网。
    return true; // 完成绑定。
  } // 结束绑定分支。
  const state = webBinding; // 当前授权。
  if (!state || state.token !== msg.token || state.task || !Number.isSafeInteger(msg.request) || msg.request <= state.lastRequest) return true; // 拒绝重复、过期或并发指令。
  state.lastRequest = msg.request; state.cancelled = false; // 本轮拥有独立编号。
  const task = runWebRequest(state, msg.request); state.task = task; // 保存真实任务供取消等待。
  try { await task; } finally { if (state.task === task) state.task = null; } // 确认结束后才接受重试。
  return true; // 完成请求命令。
} // 结束网页调度。
async function webTargetChanged(id, newUrl) { // 只移除关闭的页面，不连带停止其他已绑定页。
  const state = webBinding, target = state?.tabs.find(tab => tab.id === id); // 仅授权集合。
  if (!target || newUrl === target.url) return; // 标题变化不影响。
  if (newUrl && sessionTarget(newUrl) && new URL(newUrl).pathname === new URL(target.url).pathname) { target.url = newUrl; return; } // 同会话业务路由切换继续维护。
  state.tabs = state.tabs.filter(tab => tab.id !== id); state.synced.delete(id); // 只撤销离开的页。
  if (!state.tabs.length) { await clearWebBinding(); emit('web_failed', {token: state.token, code: newUrl ? 'WEB_TARGET_CHANGED' : 'WEB_TARGET_CLOSED'}); } // 最后一页关闭才停止网页通道。
  else { if (state.selected.id === id) state.selected = state.tabs[0]; emit('web_targets', {token: state.token, pages: state.tabs.length}); } // 其他页面继续，不重开旧地址。
} // 结束目标生命周期。
