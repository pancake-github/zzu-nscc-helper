const DAILY_KEY = 'dailyFileTransactionV1'; // 仅保存随机标识、摘要和阶段，不保存账号、路径或令牌。
const DAILY_HOSTS = new Set(['efile01.v.zzu.edu.cn', 'efile02.v.zzu.edu.cn']); // 只允许本平台已经确认的两台文件服务。
const DAILY_STAGES = new Set(['directory', 'creating', 'ready', 'uploading', 'uploaded', 'verified', 'deleting', 'complete']); // 恢复状态必须属于明确的阶段。
function dailyError(code) { throw new Error(code); } // 错误原文永不进入桌面或日志。
function dailyPath(path) { // 平台实际主目录只能在浏览器内使用。
  return typeof path === 'string' && path.startsWith('/') && !path.includes('//') && !/[\\\x00-\x1f,?*\[\]]/.test(path) && !path.split('/').some(part => part === '.' || part === '..') && !path.endsWith('/'); // 拒绝批量分隔符、通配符和路径穿越。
} // 结束路径约束。
function dailyService(raw) { // 服务地址来源于当前页面已经选择的集群。
  const url = new URL(raw); // 仅在浏览器内解析。
  if (url.protocol !== 'https:' || !DAILY_HOSTS.has(url.hostname) || url.port || url.username || url.password || url.search || url.hash || !/^\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_-]*$/.test(url.pathname)) dailyError('WEB_SERVICE_UNSUPPORTED'); // 不猜测或降级HTTP服务。
  return url.href.replace(/\/$/, ''); // 保留实际服务上下文路径。
} // 结束服务地址检查。
function dailyRandom() { return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join(''); } // 每轮128位随机标识。
function dailyPayload(id) { return new TextEncoder().encode(('ZZU-NSCC-HELPER-DAILY-V1\n' + id + '\n').repeat(20).slice(0, 1024)); } // 可恢复的1KiB无个人信息内容。
async function dailyDigest(bytes) { return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join(''); } // 完整读回摘要。
function dailyActive(state) { if (webBinding !== state || state.cancelled) dailyError('WEB_CANCELLED'); } // 每个副作用之前重新核对当前授权。
async function dailySave(state, record) { // 先记阶段，再发送可能产生副作用的请求。
  dailyActive(state); // 停止不能创建新事务。
  await chrome.storage.local.set({[DAILY_KEY]: record}); // 所有字段均为恢复所需的非凭据数据。
  dailyActive(state); // 存储期间取消则不继续网络请求。
} // 结束原子记录更新。
async function dailyFetch(state, url, options = {}, limit = 65536, json = true) { // 所有后台请求统一有界、无缓存、禁止跳转。
  dailyActive(state); // 取消后不排队新请求。
  state.diagnostic = 'fetch'; // 固定诊断位置，不记录地址。
  const controller = new AbortController(); state.controller = controller; // 只保留当前网络任务。
  const timer = setTimeout(() => controller.abort(), 30000); // 每个请求包括正文读取最多30秒。
  try { // 不读取或导出Cookie。
    const response = await fetch(url, {...options, credentials: 'include', cache: 'no-store', redirect: 'error', headers: {'Cache-Control': 'no-cache', ...options.headers}, signal: controller.signal}); // 浏览器正常发送现有认证。
    if ([401, 403].includes(response.status)) dailyError('WEB_LOGIN_EXPIRED'); // 明确认证失败不无限重试。
    if (response.status === 429 || response.status >= 500) dailyError('WEB_SERVER_BUSY'); // 平台忙允许退避。
    if (response.status !== 200 || response.redirected || !response.body || json && !/application\/json/i.test(response.headers.get('content-type') || '')) dailyError('WEB_RESPONSE_INVALID'); // 登录页不能冒充文件。
    state.diagnostic = 'body'; // 读取阶段与连接失败分开。
    const reader = response.body.getReader(), chunks = []; let length = 0; // 仅在浏览器内暂存有界响应。
    while (true) { const item = await reader.read(); if (item.done) break; length += item.value.byteLength; if (length > limit) { await reader.cancel(); dailyError('WEB_RESPONSE_TOO_LARGE'); } chunks.push(item.value); } // 逐块核验大小。
    if (!length) dailyError('WEB_RESPONSE_EMPTY'); // 没有实际数据不成功。
    const data = new Uint8Array(length); let offset = 0; // 合并完整响应进行校验。
    for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.byteLength; } // 不输出正文。
    if (controller.signal.aborted) dailyError('WEB_TIMEOUT'); // 迟到结果不算成功。
    dailyActive(state); // 取消结果不推进事务。
    if (!json) return data; // 原始文件必须完整哈希。
    let result; try { result = JSON.parse(new TextDecoder().decode(data)); } catch (_) { dailyError('WEB_RESPONSE_INVALID'); } // 不记录解析异常原文。
    if (['401', '403'].includes(String(result.code))) dailyError('WEB_LOGIN_EXPIRED'); // 平台业务认证码。
    if (String(result.code) !== '0') dailyError('WEB_SERVICE_REJECTED'); // 不把业务拒绝当上传成功。
    return result.data; // 业务数据只留在扩展。
  } catch (error) { if (controller.signal.aborted && !state.cancelled) dailyError('WEB_TIMEOUT'); throw error; } finally { clearTimeout(timer); if (state.controller === controller) state.controller = null; } // 完成后立即释放定时器。
} // 结束有界请求。
async function dailyApi(state, profile, endpoint, params = {}, method = 'GET', raw = false) { // 只由下面固定操作调用。
  const url = new URL(profile.base + endpoint), headers = {token: profile.token}; // 服务令牌不经过桌面。
  let body; // 表单按平台原有规则编码。
  if (method === 'GET') { for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value)); } else { body = new URLSearchParams(params); headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'; } // 删除路径只允许单个值。
  if (raw) url.searchParams.set('token', profile.token); // 平台原下载入口需要token参数，仅在浏览器请求内使用。
  return dailyFetch(state, url.href, {method, headers, body}, raw ? 1024 : 65536, !raw); // 测试文件严格限制1KiB。
} // 结束文件服务请求。
async function dailyList(state, profile, path) { // 精确查询当前事务目录，不搜索其他文件夹。
  const data = await dailyApi(state, profile, '/list.action', {path, limit: -1, orderBy: 'name', start: 0, keyWord: '', lockFileName: '', nonToHome: true}); // 禁止服务端静默回退主目录。
  if (!data || data.path !== path || !Array.isArray(data.fileList)) dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 返回路径必须完全一致。
  return data.fileList; // 列表内容不发给桌面。
} // 结束精确列表。
function dailyEntry(entries, name, path, directory) { // 只识别唯一精确名称。
  const matches = entries.filter(entry => entry.name === name); // 不使用前缀匹配删除。
  if (matches.length > 1) dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 重复身份不猜测。
  const item = matches[0]; // 不存在是明确的可恢复状态。
  if (item && (item.path !== path || item.isDirectory !== directory || item.isSymbolicLink === true || item.isLink === true || item.linkTarget || /^l/.test(item.permission || '') || item.type === 'link')) dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 拒绝目录冒充文件或符号链接。
  return item; // 调用方仍需文件内容哈希。
} // 结束条目检查。
async function dailyTransaction(state, request, user) { // 一轮完整业务写入与清理，不设置自己的循环计时。
  state.diagnostic = 'profile'; // 当前固定处理位置。
  const source = state.profile; // 来自首次手动绑定页面的集群元数据。
  if (!source || !dailyPath(source.home) || !source.cluster) dailyError('WEB_SERVICE_UNSUPPORTED'); // 缺少真实参数不使用占位符。
  const base = dailyService(source.base), item = user.tokenList.find(entry => String(entry.clusterId) === String(source.cluster)); // 每轮使用当前身份返回的服务令牌。
  if (!item?.token || typeof item.token !== 'string') dailyError('WEB_LOGIN_EXPIRED'); // 不复用旧令牌。
  const profile = {base, home: source.home, token: item.token}; // 只保存在当前浏览器内存。
  const context = await identityHash(JSON.stringify([state.identity, String(source.cluster), base, source.home])); // 磁盘只记不可逆上下文摘要。
  state.diagnostic = 'journal'; // 本机存储与平台连接错误分开。
  let record = (await chrome.storage.local.get(DAILY_KEY))[DAILY_KEY]; // 浏览器扩展重启后可以恢复同一事务。
  if (record && (record.version !== 1 || !/^[a-f0-9]{32}$/.test(record.directory || '') || !DAILY_STAGES.has(record.stage) || !/^[a-f0-9]{32}$/.test(record.file || '') || !/^[a-f0-9]{64}$/.test(record.sha256 || '') || record.context !== context)) dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 不能跨身份、集群或损坏记录清理。
  const progress = stage => { dailyActive(state); emit('web_progress', {token: state.token, request, stage}); }; // 固定阶段不含路径。
  progress('identity'); // 初始化也计入本轮，轮次之间没有此请求。
  const info = await dailyApi(state, profile, '/initInfo.action', {pathList: encodeURIComponent('[]')}); // 沿用平台初始化接口。
  if (info?.userInfo?.homePath !== profile.home) dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 实际服务器个人主目录必须与所选集群一致。
  if (!record || record.stage === 'complete') { // 完整成功后下一轮才创建新的随机文件。
    const file = dailyRandom(); // 不使用任何个人资料生成文件名。
    record = {version: 1, context, directory: record?.directory || dailyRandom(), file, sha256: await dailyDigest(dailyPayload(file)), stage: record ? 'ready' : 'directory'}; // 保留专用目录复用。
    await dailySave(state, record); // 首次副作用之前落盘。
  } // 未完成记录保持原来的文件标识。
  const directoryName = 'zzu-nscc-helper-daily-' + record.directory, directory = profile.home + '/' + directoryName, name = 'probe-' + record.file + '.txt', path = directory + '/' + name; // 所有远端路径只在浏览器内存构造。
  if (!dailyPath(path) || record.sha256 !== await dailyDigest(dailyPayload(record.file))) dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 损坏内容记录禁止任何写入。
  progress('directory'); // 新目录创建或已有专用目录核验。
  const homeEntries = await dailyList(state, profile, profile.home); // 不递归扫描主目录。
  let folder = dailyEntry(homeEntries, directoryName, directory, true); // 只查询自己保存的随机目录名。
  if (folder && record.stage === 'directory') dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 初次创建前已存在的随机目录不自动接管。
  if (!folder) { // 专用目录丢失只允许在尚未上传阶段重新创建。
    if (!['directory', 'creating', 'ready'].includes(record.stage)) dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 不用新目录掩盖未完成文件。
    record.stage = 'creating'; await dailySave(state, record); // 先确认目录缺失再记录创建意图。
    await dailyApi(state, profile, '/mkdir.action', {path: directory}, 'POST'); // 一次精确目录创建。
    folder = dailyEntry(await dailyList(state, profile, profile.home), directoryName, directory, true); // 确认创建真实生效。
    if (!folder) dailyError('WEB_SERVICE_REJECTED'); // 不在未确认目录上传。
  } // 目录始终保留，不调用删除目录。
  if (record.stage === 'creating' && (await dailyList(state, profile, directory)).length) dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 创建恢复只接受空的专用目录。
  if (['directory', 'creating'].includes(record.stage)) { record.stage = 'ready'; await dailySave(state, record); } // 确认目录后进入文件阶段。
  let entry = dailyEntry(await dailyList(state, profile, directory), name, path, false); // 上传结果丢失时先核对同一个文件。
  if (!entry && record.stage === 'deleting') { record.stage = 'complete'; await dailySave(state, record); progress('complete'); return; } // 删除应答丢失但文件已经不存在，完整事务可以结束。
  if (!entry) { // 仅确认缺失时才允许发送上传。
    if (record.stage === 'verified') dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 已校验文件突然消失不猜测原因。
    progress('upload'); record.stage = 'uploading'; await dailySave(state, record); // 写前日志保留同一随机文件。
    const form = new FormData(); form.append('file', new Blob([dailyPayload(record.file)], {type: 'text/plain'}), name); form.append('path', directory); // 完全沿用普通网页上传参数。
    await dailyFetch(state, profile.base + '/upload.action', {method: 'POST', headers: {token: profile.token}, body: form}); // 浏览器自动生成multipart边界。
    record.stage = 'uploaded'; await dailySave(state, record); // 上传应答本身不算整轮成功。
    entry = dailyEntry(await dailyList(state, profile, directory), name, path, false); // 上传后必须看到普通文件。
    if (!entry) dailyError('WEB_SERVICE_REJECTED'); // 不凭应答猜测文件存在。
  } // 已有同名文件只能校验，不重复覆盖。
  if (Number(entry.size) !== 1024) dailyError('WEB_FILE_MISMATCH'); // 非预期大小不删除。
  progress('readback'); // 必须实际通过E-File读回完整文件。
  const bytes = await dailyApi(state, profile, '/multiDownload.action', {paths: path}, 'GET', true); // 单文件下载，不触发浏览器保存窗口。
  if (bytes.byteLength !== 1024 || await dailyDigest(bytes) !== record.sha256) dailyError('WEB_FILE_MISMATCH'); // 内容不符时保留文件并暂停，禁止越界清理。
  record.stage = 'verified'; await dailySave(state, record); // 文件身份由路径、随机内容和摘要共同确认。
  progress('delete'); // 此处只允许单个已校验普通文件。
  entry = dailyEntry(await dailyList(state, profile, directory), name, path, false); // 删除前再次核对类型和路径。
  if (!entry || Number(entry.size) !== 1024) dailyError('WEB_OWNERSHIP_UNCONFIRMED'); // 状态改变停止副作用。
  record.stage = 'deleting'; await dailySave(state, record); // 删除应答不明确时可以确认不存在。
  await dailyApi(state, profile, '/remove.action?recursive=true', {paths: path}, 'POST'); // 平台虽通用递归接口，实际参数只有这个普通文件，没有目录、逗号或通配符。
  progress('absence'); // 完整成功必须再确认文件已不存在。
  if (dailyEntry(await dailyList(state, profile, directory), name, path, false)) dailyError('WEB_CLEANUP_PENDING'); // 清理失败只处理原文件，不开始新轮。
  record.stage = 'complete'; await dailySave(state, record); progress('complete'); // 仅完整成功后交回桌面开始86400秒计时。
} // 结束每日事务。
