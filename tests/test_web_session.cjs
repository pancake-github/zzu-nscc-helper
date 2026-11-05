const fs = require('node:fs'); // 读取实际扩展模块。
const vm = require('node:vm'); // 离线执行，无浏览器、VPN或平台请求。
const assert = require('node:assert/strict'); // 核对安全边界和真实响应判据。
const path = require('node:path'); // 使用仓库相对路径。
const source = fs.readFileSync(path.join(__dirname, '../src/zzu_nscc_helper/keepalive/extension/session.js'), 'utf8'); // 被测生产代码。
const url = 'https://172.99.2.7/ac/console3/index.html#/e-file'; // 合成无身份参数的页面。
const token = 'ab'.repeat(16); // 本地授权随机值的离线替身，不是账号凭据。
function fixture() { // 每例独立网页与扩展状态。
  const calls = [], sent = [], commits = [], timers = []; // 仅保存合成测试数据。
  const user = {id: 17, roleId: [], tokenList: []}; // 最小合成平台结构。
  const state = {body: {code: '0', data: user}, status: 200, type: 'application/json', redirected: false, pages: [{id: 1, url, status: 'complete'}]}; // 可注入故障。
  const window = {app: {$store: {state: {user: {userInfo: user}}, commit: (...args) => commits.push(args)}}}; // 不导出或读取实际登录态。
  const context = vm.createContext({URL, AbortController, TextDecoder, performance, window, location: {href: url, origin: 'https://172.99.2.7'}, setTimeout: fn => {timers.push(fn); return timers.length;}, clearTimeout: () => {}, emit: (event, data) => sent.push({event, ...data}), fetch: async (target, options) => { // 真实网络入口完全替换。
    calls.push({target, options}); // 检查请求地址、Cookie策略和只读方法。
    if (state.networkError) throw new Error('private error must not escape'); // 模拟敏感原文不能透传。
    let read = false; // 模拟有界流。
    return {status: state.status, redirected: state.redirected, headers: {get: () => state.type}, body: {getReader: () => ({read: async () => { if (state.timeout) { timers.at(-1)(); throw new Error(); } if (read) return {done: true}; read = true; return {done: false, value: Buffer.from(state.raw ?? JSON.stringify(state.body))}; }, cancel: async () => {state.cancelled = true;}})}}; // 无网络数据。
  }}); // 完成页面沙箱。
  context.chrome = {tabs: {get: async id => {const item = state.pages.find(t => t.id === id); if (!item) throw new Error(); return item;}, query: async () => state.pages}, scripting: {executeScript: async options => { if (options.func.name === 'pageSessionRequest') { state.requests = (state.requests || 0) + 1; return [{result: state.summary || {ok: true, status: 200, bytes: 40, elapsed: 0.1}}]; } state.aborted = true; return []; }}}; // 扩展调用也完全离线。
  vm.runInContext(source, context); // 同一实际源代码。
  return {context, state, calls, sent, commits, timers, window}; // 不接触用户浏览器。
} // 结束沙箱构造。
(async () => { // 覆盖正文判据、并发、取消与绑定边界。
  let f = fixture(); const result = await f.context.pageSessionRequest(url); // 完整成功读取与网页状态刷新。
  assert.equal(result.ok, true); assert.equal(f.commits.length, 1); assert.equal(f.calls[0].target, '/ac/api/user/getCurrentUserInfo.action?includeToken=true&refresh=true'); // 不能退化成静态页面GET。
  assert.equal(f.calls[0].options.method, 'GET'); assert.equal(f.calls[0].options.credentials, 'same-origin'); assert.equal(f.calls[0].options.redirect, 'error'); assert.equal(f.calls[0].options.cache, 'no-store'); // 不发送命令、不绕过认证或缓存命中。
  assert.deepEqual(Object.keys(result).sort(), ['bytes', 'elapsed', 'ok', 'status']); assert.equal(f.window.__zzuNsccSessionRequestV1, undefined); // 摘要不含账户/令牌且清理句柄。
  for (const mutation of [{status: 401}, {status: 503}, {type: 'text/html'}, {redirected: true}, {raw: ''}, {raw: 'invalid'}, {raw: 'x'.repeat(65537)}, {body: {code: '401'}}, {body: {code: '0', data: {id: 88, roleId: [], tokenList: []}}}, {body: {code: '0', data: {id: 17}}}, {networkError: true}, {timeout: true}]) { // 各种不真实成功。
    f = fixture(); Object.assign(f.state, mutation); const response = await f.context.pageSessionRequest(url); assert.equal(response.ok, false); assert.equal(f.commits.length, 0); assert.equal(f.calls.length, 1); assert(!JSON.stringify(response).includes('private')); // 不重试、不写网页身份，不泄漏原文。
  } // 完成失败矩阵。
  f = fixture(); f.window.__zzuNsccSessionRequestV1 = new AbortController(); assert.equal((await f.context.pageSessionRequest(url)).error, 'WEB_BUSY'); assert.equal(f.calls.length, 0); // 并发不多发请求。
  f = fixture(); f.context.location.href = 'https://example.invalid'; assert.equal((await f.context.pageSessionRequest(url)).ok, false); assert.equal(f.calls.length, 0); // 导航后不向其他站点发送。
  f = fixture(); assert.equal(f.context.sessionTarget(url.replace('#/e-file', '#/space/shell')), true); assert.equal(f.context.sessionTarget(url.replace('https:', 'http:')), false); assert.equal(f.context.sessionTarget(url.replace('172.99.2.7', '172.99.2.70')), false); // 允许命令行网页但不扩大站点。
  f.state.pages.push({id: 2, url: url.replace('#/e-file', '#/space/shell'), status: 'complete'}, {id: 3, url: 'https://example.invalid', status: 'complete'}); // 相关与无关标签。
  await f.context.webCommand({command: 'web_bind', id: 1, url, token, related: true}); assert.equal(f.sent.at(-1).pages, 2); // 只纳入同会话的已知业务页。
  await f.context.webCommand({command: 'web_request', token, request: 1}); assert.equal(f.state.requests, 2); assert.equal(f.sent.at(-1).event, 'web_success'); // 每页确实调用一次网页交互。
  await f.context.webCommand({command: 'web_request', token, request: 1}); assert.equal(f.state.requests, 2); // 重复消息不发请求。
  await f.context.webCommand({command: 'web_request', token, request: 2}); await f.context.webCommand({command: 'web_request', token, request: 1}); assert.equal(f.state.requests, 4); // 旧编号不能在新轮后重新执行。
  f.state.pages.pop(); f.state.pages.pop(); await f.context.webCommand({command: 'web_request', token, request: 3}); assert.equal(f.sent.at(-1).event, 'web_failed'); const count = f.state.requests; await f.context.webCommand({command: 'web_request', token, request: 4}); assert.equal(f.state.requests, count); // 关闭标签失败后授权撤销，无自动恢复请求。
  f = fixture(); await f.context.webCommand({command: 'web_bind', id: 1, url, token}); f.state.summary = {ok: false, error: 'WEB_LOGIN_EXPIRED'}; await f.context.webCommand({command: 'web_request', token, request: 1}); assert.equal(f.sent.at(-1).code, 'WEB_LOGIN_EXPIRED'); // 不把业务失效误判成功。
  f = fixture(); await f.context.webCommand({command: 'web_bind', id: 1, url, token}); await f.context.webCommand({command: 'web_stop'}); await f.context.webCommand({command: 'web_request', token, request: 1}); assert.equal(f.state.requests, undefined); // 手动停止后绝无发送。
  console.log('PASS authenticated web request, private summary, 12 failures, per-page refresh, scope, cancellation and duplicate suppression'); // 只输出测试类别。
})().catch(error => {console.error(error); process.exitCode = 1;}); // 失败阻止发布。
