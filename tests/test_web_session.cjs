const fs = require('node:fs'); // 实际生产代码测试。
const vm = require('node:vm'); // 隔离浏览器及网络。
const assert = require('node:assert/strict'); // 失败阻止发布。
const {webcrypto} = require('node:crypto'); // 浏览器兼容摘要。
const path = require('node:path'); // 相对仓库路径。
const source = ['daily_file.js', 'session.js'].map(name => fs.readFileSync(path.join(__dirname, '../src/zzu_nscc_helper/keepalive/extension', name), 'utf8')).join('\n'); // 完整事务生产代码。
const url = 'https://172.99.2.7/ac/console3/index.html#/e-file', token = 'ab'.repeat(16); // 无个人资料的合成值。
const flush = () => new Promise(resolve => setImmediate(resolve)); // 推进微任务，无真实等待。
function fixture(shared = {}) { // 内存文件系统和HTTP服务，不连接真实平台。
  const calls = [], sent = [], commits = [], timers = new Map(), injections = [], storage = shared.storage || {}, files = shared.files || new Map(); // 可重用日志以模拟扩展重启。
  const profile = {cluster: '17', home: '/test-home', base: 'https://efile01.v.zzu.edu.cn'}; // 明确的测试材料，不是部署占位符。
  const user = {id: 17, roleId: [], tokenList: [{clusterId: '17', token: 'synthetic-browser-only'}]}; // 检查凭据不出浏览器。
  const state = {now: 10000, body: {code: '0', data: user}, status: 200, type: 'application/json', pages: [{id: 1, url, status: 'complete'}]}; // 合成页面与HTTP状态。
  const window = {app: {$store: {getters: {efileServiceClusterId: 17, clusterIdMap: {17: {clusterUserHomePath: profile.home}}}, state: {user: {userInfo: user}}, dispatch: async () => ({url: profile.base}), commit: (...args) => commits.push(args)}}}; // 真实页面函数的依赖替身。
  let serial = 0; // 定时器编号。
  const context = vm.createContext({URL, URLSearchParams, FormData, Blob, AbortController, TextDecoder, TextEncoder, Uint8Array, crypto: webcrypto, performance, window, Date: {now: () => state.now}, location: {href: url, origin: 'https://172.99.2.7'}, setTimeout: (fn, ms) => {const id = ++serial; timers.set(id, {fn, ms}); return id;}, clearTimeout: id => timers.delete(id), emit: (event, data) => sent.push({event, ...data}), fetch: async (target, options) => { // 全部请求仅执行本函数。
    const u = new URL(target), endpoint = u.pathname.split('/').at(-1), params = options.method === 'POST' && options.body instanceof URLSearchParams ? options.body : u.searchParams; // 按真实接口解析参数。
    calls.push({target, options, endpoint}); // 仅包含合成信息。
    if (state.hang === endpoint || state.hang === true) return new Promise((resolve, reject) => {state.resolveFetch = resolve; options.signal.addEventListener('abort', () => reject(new Error('private network detail')), {once: true});}); // 可以取消的真实网络挂起替身。
    if (state.networkError || state.failEndpoint === endpoint) throw new Error('private network detail'); // 模拟短暂断网。
    let data = null, raw = null; // 文件及JSON分开校验。
    if (endpoint === 'getCurrentUserInfo.action') data = state.body.data; // 当前身份。
    else if (endpoint === 'initInfo.action') data = {userInfo: {homePath: profile.home}}; // 实际主目录。
    else if (endpoint === 'list.action') { const parent = params.get('path'); data = {path: parent, fileList: [...files].filter(([name]) => name.slice(0, name.lastIndexOf('/')) === parent).map(([name, item]) => ({name: name.split('/').at(-1), path: name, isDirectory: item.directory === true, size: item.bytes?.length || 0, permission: item.link ? 'lrwxrwxrwx' : '-rw-r--r--', ...item.extra}))}; } // 列表不展开子目录。
    else if (endpoint === 'mkdir.action') { const name = params.get('path'); assert(!files.has(name)); files.set(name, {directory: true}); data = {}; } // 精确新目录。
    else if (endpoint === 'upload.action') { const name = options.body.get('path') + '/' + options.body.get('file').name; assert(!files.has(name), 'must not overwrite'); const bytes = Buffer.from(await options.body.get('file').arrayBuffer()); files.set(name, {bytes: state.corrupt ? Buffer.alloc(1024) : bytes}); if (state.loseUpload) throw new Error('lost upload response'); data = {}; } // 上传成功后应答丢失。
    else if (endpoint === 'multiDownload.action') { raw = files.get(params.get('paths')).bytes; } // 实际读回当前内容。
    else if (endpoint === 'remove.action') { const name = params.get('paths'); assert(files.has(name)); assert(!files.get(name).directory); assert(!name.includes(',')); assert.match(name, /\/zzu-nscc-helper-daily-[a-f0-9]{32}\/probe-[a-f0-9]{32}\.txt$/); if (!state.refuseDelete) files.delete(name); if (state.loseDelete) throw new Error('lost delete response'); data = {}; } // 确认只删除自己的单个文件。
    else throw new Error('unexpected endpoint'); // 新接口未经测试不得悄悄通过。
    let status = state.status; if (endpoint === 'initInfo.action' && state.authOnce) { status = 401; state.authOnce = false; } // 只模拟第一次文件凭据失效。
    const response = endpoint === 'getCurrentUserInfo.action' ? state.body : {code: '0', data}; // 平台JSON格式。
    const bytes = raw ?? Buffer.from(state.raw ?? JSON.stringify(response)); let read = false; // 流式读取替身。
    return {status, redirected: !!state.redirected, headers: {get: () => raw ? 'application/octet-stream' : state.type}, body: {getReader: () => ({read: async () => {if (read) return {done: true}; read = true; return {done: false, value: bytes};}, cancel: async () => {state.readerCancelled = true;}})}}; // 无真实网络。
  }}); // 完成沙箱。
  context.chrome = {storage: {local: {get: async key => ({[key]: storage[key] && structuredClone(storage[key])}), set: async data => Object.assign(storage, structuredClone(data))}}, tabs: {get: async id => {const tab = state.pages.find(t => t.id === id); if (!tab) throw new Error('closed'); return tab;}, query: async () => state.pages}, scripting: {executeScript: async options => { // 仅模拟本机浏览器API。
    injections.push(options); // 验证不堆积冻结页面注入。
    if (state.hangSync && options.args[3]) return new Promise(resolve => {state.resolveSync = resolve;}); // 页面冻结发生在注入后。
    return [{result: options.args[3] ? {ok: true} : {ok: true, identity: await context.identityHash(user.id), profile, user: state.body.data}}]; // 原始身份不返回桌面。
  }}}; // 完成浏览器替身。
  vm.runInContext(source, context); // 执行生产代码。
  const bind = () => context.webCommand({command: 'web_bind', protocol: 3, token, id: 1, url, related: true}); // 显式新能力授权。
  const request = number => context.webCommand({command: 'web_request', token, request: number}); // 桌面控制轮次。
  const fire = ms => {for (const [id, timer] of timers) if (timer.ms === ms) {timers.delete(id); timer.fn();}}; // 模拟时钟不等待30秒。
  return {context, calls, sent, commits, injections, state, window, timers, storage, files, bind, request, fire}; // 仅合成数据。
} // 结束测试环境。
(async () => { // 验证事务、取消、范围和恢复。
  let f = fixture(); await f.bind(); await f.request(1); await flush(); // 完整首轮。
  assert.equal(f.sent.filter(m => m.event === 'web_success').length, 1); assert.equal(f.storage.dailyFileTransactionV1.stage, 'complete'); // 全部阶段完成。
  assert.equal(f.calls.filter(c => c.endpoint === 'getCurrentUserInfo.action').length, 0); // 正常文件交互没有额外入口IP会话请求。
  assert.equal(f.files.size, 1); assert([...f.files.values()][0].directory); // 仅保留专用目录。
  assert.equal(f.calls.filter(c => c.endpoint === 'upload.action').length, 1); assert.equal(f.calls.filter(c => c.endpoint === 'multiDownload.action').length, 1); // 有实际双向传输。
  assert(!JSON.stringify(f.sent).includes('synthetic-browser-only')); assert(!JSON.stringify(f.sent).includes('/test-home')); assert(!JSON.stringify(f.storage).includes('token')); assert(!JSON.stringify(f.storage).includes('/test-home')); // 桌面消息及恢复记录没有凭据和账号路径。
  const first = structuredClone(f.storage.dailyFileTransactionV1), count = f.calls.length; await f.request(1); await f.context.syncWebPage(1); // 重复轮次和页面同步。
  assert.equal(f.calls.length, count); // 两轮之间无额外平台HTTP。
  f.state.pages[0].frozen = true; await f.request(2); assert.equal(f.sent.filter(m => m.event === 'web_success').length, 2); // 后续冻结页面不阻塞后台。
  assert.equal(f.storage.dailyFileTransactionV1.directory, first.directory); assert.notEqual(f.storage.dailyFileTransactionV1.file, first.file); // 复用目录且每轮新文件。
  const failures = [[{status: 401}, 'WEB_LOGIN_EXPIRED'], [{status: 503}, 'WEB_SERVER_BUSY'], [{type: 'text/html'}, 'WEB_RESPONSE_INVALID'], [{raw: ''}, 'WEB_RESPONSE_EMPTY'], [{raw: 'invalid'}, 'WEB_RESPONSE_INVALID'], [{raw: 'x'.repeat(65537)}, 'WEB_RESPONSE_TOO_LARGE'], [{body: {code: '0', data: {id: 88, roleId: [], tokenList: []}}}, 'WEB_LOGIN_CHANGED'], [{networkError: true}, 'WEB_NETWORK']]; // 身份、结构及网络错误。
  for (const [mutation, code] of failures) { f = fixture(); await f.bind(); Object.assign(f.state, mutation); await f.request(1); assert.equal(f.sent.at(-1).code, code); assert(f.calls.length <= 2); assert.equal(f.sent.at(-1).settled, true); } // 失败不产生文件。
  f = fixture(); await f.bind(); f.state.authOnce = true; await f.request(1); assert.equal(f.calls.filter(c => c.endpoint === 'getCurrentUserInfo.action').length, 1); assert.equal(f.storage.dailyFileTransactionV1.stage, 'complete'); // 仅必要时会话更新，并仍完成原事务。
  f = fixture(); await f.bind(); f.state.loseUpload = true; await f.request(1); assert.equal(f.storage.dailyFileTransactionV1.stage, 'uploading'); f.state.loseUpload = false; await f.request(2); // 应答丢失后先检查同文件。
  assert.equal(f.calls.filter(c => c.endpoint === 'upload.action').length, 1); assert.equal(f.sent.at(-1).event, 'web_success'); // 没有重复上传。
  f = fixture(); await f.bind(); f.state.refuseDelete = true; await f.request(1); assert.equal(f.sent.at(-1).code, 'WEB_CLEANUP_PENDING'); f.state.refuseDelete = false; await f.request(2); // 清理失败后处理原文件。
  assert.equal(f.calls.filter(c => c.endpoint === 'upload.action').length, 1); assert.equal(f.files.size, 1); // 不累积文件。
  f = fixture(); await f.bind(); f.state.loseDelete = true; await f.request(1); assert.equal(f.storage.dailyFileTransactionV1.stage, 'deleting'); const old = f; // 删除生效后丢应答。
  f = fixture({storage: old.storage, files: old.files}); await f.bind(); await f.request(1); // 扩展重启后恢复日志。
  assert.equal(f.calls.filter(c => c.endpoint === 'upload.action').length, 0); assert.equal(f.calls.filter(c => c.endpoint === 'remove.action').length, 0); assert.equal(f.storage.dailyFileTransactionV1.stage, 'complete'); // 确认不存在即可完成，不删其他文件。
  f = fixture(); await f.bind(); f.state.corrupt = true; await f.request(1); assert.equal(f.sent.at(-1).code, 'WEB_FILE_MISMATCH'); assert.equal(f.calls.filter(c => c.endpoint === 'remove.action').length, 0); // 内容不符不可删除。
  const corrupt = f; f = fixture({storage: corrupt.storage, files: corrupt.files}); f.storage.dailyFileTransactionV1.context = 'f'.repeat(64); await f.bind(); await f.request(1); assert.equal(f.sent.at(-1).code, 'WEB_OWNERSHIP_UNCONFIRMED'); assert.equal(f.calls.length, 0); // 跨身份恢复不产生文件操作。
  f = fixture(); await f.bind(); f.state.hang = 'upload.action'; const pending = f.request(1); while (!f.calls.some(c => c.endpoint === 'upload.action')) await flush(); // 上传过程取消。
  await f.request(2); await f.context.webCommand({command: 'web_cancel', token, request: 1}); await pending; assert.equal(f.sent.at(-1).event, 'web_cancelled'); assert.equal(f.storage.dailyFileTransactionV1.stage, 'uploading'); // 保留未确认记录，不虚报清理。
  f.state.hang = false; await f.request(3); assert.equal(f.storage.dailyFileTransactionV1.stage, 'complete'); // 同文件恢复后完整成功。
  f = fixture(); await f.bind(); f.state.hang = true; const timed = f.request(1); while (!f.calls.length) await flush(); f.fire(30000); await timed; assert.equal(f.sent.at(-1).code, 'WEB_TIMEOUT'); // 请求有独立上限。
  f = fixture(); await f.bind(); f.state.hangSync = true; await f.request(1); await flush(); const injected = f.injections.length; f.fire(8000); await flush(); await f.request(2); assert.equal(f.injections.length, injected); // 冻结页面不增加注入或阻塞下一文件轮次。
  const stopCount = f.calls.length; await f.context.webCommand({command: 'web_stop'}); await f.request(3); assert.equal(f.calls.length, stopCount); // 停止无需等待冻结页。
  f = fixture(); const identity = await f.context.pageSessionState(url, f.state.now + 8000); assert.equal(identity.ok, true); assert.equal(f.calls.length, 0); // 页面初始化只是读取当前状态。
  await f.context.pageSessionState(url, f.state.now + 8000, identity.identity, f.state.body.data); assert.equal(f.commits.length, 1); f.state.now += 9000; await f.context.pageSessionState(url, f.state.now - 1000, identity.identity, f.state.body.data); assert.equal(f.commits.length, 1); // 迟到脚本不提交旧状态。
  f = fixture(); await f.context.webCommand({command: 'web_bind', protocol: 2, token, id: 1, url}); await f.request(1); assert.equal(f.calls.length, 0); // 旧扩展协议不能承诺新事务语义。
  for (const bad of ['/home/../research', '/home/a,b', '/home/*', '/home/a\\b']) assert.equal(f.context.dailyPath(bad), false); // 拒绝批量、穿越与通配符。
  assert.throws(() => f.context.dailyService('http://efile01.v.zzu.edu.cn')); assert.throws(() => f.context.dailyService('https://example.invalid')); // 不扩大平台权限。
  console.log('PASS daily file transaction, independent dispatch, resume, cancellation, frozen pages, privacy, identity and exact cleanup'); // 仅输出类别。
})().catch(error => {console.error(error); process.exitCode = 1;}); // 失败阻止发布。
