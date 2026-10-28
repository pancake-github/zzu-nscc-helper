const fs = require('node:fs'); // 读取仓库内已有离线场景。
const path = require('node:path'); // 以当前仓库位置定位。
const root = path.resolve(__dirname, '..'); // 不包含开发者固定路径。
const scenarios = fs.readFileSync(path.join(root, 'baseline', 'keepalive', 'test_extension.cjs'), 'utf8'); // 已有模拟Edge用例。
const execute = new Function('require', '__dirname', scenarios); // 仅执行本仓库测试，场景内不连接真实Edge。
execute(require, path.join(root, 'src', 'zzu_nscc_helper', 'keepalive')); // 将真实被测扩展切换为融合组件。
const vm = require('node:vm'); // 会话地址用例使用独立模拟上下文，不操作实际Edge。
const assert = require('node:assert/strict'); // 对资格、绑定身份和停止行为作断言。
const source = fs.readFileSync(path.join(root, 'src/zzu_nscc_helper/keepalive/extension/background.js'), 'utf8'); // 测试实际修复源码。
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'src/zzu_nscc_helper/keepalive/extension/manifest.json'), 'utf8')); // 核对扩展修订号与权限。
const base = 'https://172.99.2.7/ac/console3/index.html'; // 固定公开平台入口，不包含会话。
const suffix = ';jsessionid=' + 'Ab12'.repeat(8); // 仅生成合成会话标识，不复制用户地址。
function eventHook() { const listeners = []; return {listeners, addListener(fn) { listeners.push(fn); }}; } // 记录模拟浏览器事件。
function sessionFixture(url) { // 每个用例独占状态，禁止调用真实浏览器。
  const sent = [], tabs = new Map([[17, {id:17, windowId:3, title:'E-File', url, status:'complete'}]]); // 合成标签元数据。
  const state = {sent, tabs, ready:true, created:[]}; // 记录恢复请求与页面预检结果。
  const port = {postMessage: message => sent.push(message), onMessage:eventHook(), onDisconnect:eventHook()}; // 本机管道替身。
  const chrome = { // 仅实现扩展需要的离线API。
    tabs:{query:async () => [...tabs.values()], get:async id => tabs.get(id), create:async options => { state.created.push(options); const tab={id:18, windowId:3, url:options.url, status:'complete'}; tabs.set(18,tab); return tab; }, onRemoved:eventHook(), onUpdated:eventHook(), onCreated:eventHook()}, // 重开只写入内存。
    windows:{getAll:async () => [{id:3}]}, // 原窗口存在，不允许模拟新窗口启动。
    scripting:{executeScript:async () => [{result:{ready:state.ready}}]}, // 仍必须通过原页面预检。
    runtime:{connectNative:() => port, lastError:null}, // 不访问本机宿主。
    alarms:{create:() => {}, onAlarm:eventHook()}, action:{onClicked:eventHook()}, webNavigation:{onErrorOccurred:eventHook()} // 不创建真实计时器或流量。
  }; // 结束浏览器替身。
  const context = vm.createContext({chrome, URL, setInterval:() => 1, clearInterval:() => {}, setTimeout:() => 1, clearTimeout:() => {}}); // 时间相关动作均离线。
  vm.runInContext(source, context); // 装载完整实际扩展。
  state.allowed = value => context.safeTarget(value); // 直接测试同一个目标校验器。
  state.call = value => context.command(value); // 通过真实命令入口验证完整流程。
  state.bind = () => state.call({command:'bind', id:17, url, token:'offline-binding'}); // 初始绑定保留完整合成会话地址。
  state.remove = () => chrome.tabs.onRemoved.listeners[0](17, {windowId:3, isWindowClosing:false}); // 模拟单标签关闭。
  state.navigate = value => chrome.tabs.onUpdated.listeners[0](17, {url:value}, {id:17, url:value}); // 模拟已绑定页面地址改变。
  return state; // 不向调用者暴露真实用户数据。
} // 结束会话测试环境。
(async () => { // 与历史回归分离，完整验证会话地址兼容边界。
  assert.equal(manifest.version, '0.4.1'); // 修复版本应在Edge扩展管理页可辨认。
  assert.deepEqual(manifest.host_permissions, ['https://172.99.2.7/*']); // 不扩大站点访问权限。
  let f = sessionFixture(base + suffix + '#/e-file'); // 首个虚拟E-File标签。
  const accepted = [base + '#/e-file', base + '#/space/dashboard', base + suffix + '#/e-file', base + suffix.toLowerCase() + '#/space/dashboard']; // 新旧入口及会话大小写均支持。
  for (const url of accepted) assert.equal(f.allowed(url), true); // 只验证合成或公开地址。
  const rejected = [ // 检查放宽路径规则不会放行其他目标。
    base + ';jsessionid=#/e-file', base + ';jsessionid=' + 'A'.repeat(31) + '#/e-file', base + ';jsessionid=' + 'A'.repeat(33) + '#/e-file', // 空、过短和过长参数均拒绝。
    base + ';jsessionid=' + 'G'.repeat(32) + '#/e-file', base + suffix + suffix + '#/e-file', base + suffix + ';other=x#/e-file', // 非十六进制、重复和额外参数均拒绝。
    base + suffix + '/other#/e-file', base + '%3Bjsessionid=' + 'A'.repeat(32) + '#/e-file', base + suffix + '#/space/shell', // 不接受附加路径、编码参数或命令行页面。
    base + suffix + '#/login', base.replace('https:', 'http:') + suffix + '#/e-file', base.replace('172.99.2.7', '172.99.2.70') + suffix + '#/e-file', // 登录页面、不安全协议和其他IP均拒绝。
    base.replace('172.99.2.7', '172.99.2.7:444') + suffix + '#/e-file', base.replace('https://', 'https://sample@') + suffix + '#/e-file', 'invalid-url' // 其他端口、嵌入身份和无效URL均拒绝。
  ]; // 所有会话值仅在本次离线测试中合成。
  for (const url of rejected) assert.equal(f.allowed(url), false); // 拒绝列表必须全部保持失败。
  await f.call({command:'list'}); // 验证下拉框实际收到的资格字段。
  assert(f.sent.some(message => message.event === 'tabs' && message.version === '0.4.0' && message.tabs.some(tab => tab.eligible && tab.url === base + suffix + '#/e-file'))); // 新修订保持现有桌面通信协议兼容。
  await f.bind(); // 通过真实绑定命令进入已绑定状态。
  assert(f.sent.some(message => message.event === 'bound' && message.tab.url === base + suffix + '#/e-file')); // 不删除参数，也不替换会话地址。
  f.remove(); await f.call({command:'recover', token:'offline-binding'}); // 验证关闭后的单次恢复使用原地址。
  assert.equal(f.created.length, 1); assert.equal(f.created[0].url, base + suffix + '#/e-file'); assert(f.sent.some(message => message.event === 'restored')); // 完整URL与页面预检都必须保留。
  f = sessionFixture(base + suffix + '#/e-file'); await f.bind(); f.ready = false; f.remove(); // 模拟恢复后落入登录失效页面。
  await f.call({command:'recover', token:'offline-binding'}); await f.call({command:'recover', token:'offline-binding'}); // 失败后不能通过重复命令再次重开。
  assert.equal(f.created.length, 1); assert(f.sent.some(message => message.code === 'RESTORE_PAGE_INVALID')); // 会话参数不绕过恢复页面检查。
  f = sessionFixture(base + suffix + '#/e-file'); await f.bind(); f.navigate(base + ';jsessionid=' + 'B'.repeat(32) + '#/e-file'); // 会话身份变化仍按导航停止。
  assert.equal(f.sent.filter(message => message.code === 'TARGET_NAVIGATED').length, 1); // 不把新会话当作原绑定。
  f = sessionFixture(base + suffix + '#/e-file'); f.tabs.get(17).url = base + '#/e-file'; await f.bind(); // 选择后地址已改变，不能仅凭标准化路径绑定。
  assert(!f.sent.some(message => message.event === 'bound')); assert(f.sent.some(message => message.code === 'PAGE_NOT_READY')); // 仍需匹配选中的完整真实地址。
  for (const url of rejected) { const invalid = sessionFixture(url); await invalid.bind(); assert(invalid.sent.some(message => message.code === 'TARGET_NOT_ALLOWED')); } // 从绑定入口再次检查拒绝路径。
  console.log('PASS session URL eligibility, binding, recovery, navigation and 15 rejected URL cases'); // 只打印测试类别，不输出任何会话值。
})().catch(error => { console.error(error); process.exitCode = 1; }); // 任一回归失败阻止交付。
