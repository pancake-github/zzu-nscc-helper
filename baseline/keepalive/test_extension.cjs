const fs = require('node:fs'); // 读取内置扩展源码。
const vm = require('node:vm'); // 在模拟 Edge API 中执行，无真实浏览器访问。
const assert = require('node:assert/strict'); // 验收断言。
const source = fs.readFileSync(__dirname + '/extension/background.js', 'utf8'); // 与交付版本相同源码。
const target = 'https://172.99.2.7/ac/console3/index.html#/space/dashboard'; // 虚拟目标。
function event() { const listeners = []; return {listeners, addListener(fn) { listeners.push(fn); }}; } // 模拟事件注册。
function fixture() { // 每项测试有独立扩展状态。
  const sent = [], tabs = new Map([[17, {id:17, windowId:3, title:'计算服务', url:target, status:'complete'}]]); // 虚拟标签列表。
  const state = {sent, tabs, creates:0, ready:true, open:true, loadComplete:true}; // 可注入失败。
  const port = {postMessage: x => sent.push(x), onMessage:event(), onDisconnect:event()}; // 不接网络。
  const chrome = { // 有限的 Edge API 替身。
    tabs: {query: async () => [...tabs.values()], get:async id => { if (!tabs.has(id)) throw Error(); return tabs.get(id); }, update:async id => tabs.get(id), create:async opts => { state.creates++; const tab={id:18,windowId:3,url:opts.url,status:state.loadComplete?'complete':'loading'};tabs.set(18,tab);return tab; }, onRemoved:event(),onUpdated:event(),onCreated:event()}, // 标签操作。
    windows:{getAll:async () => state.open?[{id:3}]:[], update:async () => {}}, // 原窗口存在性。
    scripting:{executeScript:async () => [{result:{ready:state.ready}}]}, // 页面检查返回布尔值。
    runtime:{connectNative:() => port,lastError:null}, // 本机连接替身。
    alarms:{create:() => {},onAlarm:event()}, action:{onClicked:event()}, webNavigation:{onErrorOccurred:event()} // 事件注册替身。
  }; // 结束 API。
  const timers = []; // 可手动触发截止时间。
  const context = vm.createContext({chrome,URL,setInterval:()=>1,clearInterval:()=>{},setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:()=>{}}); // 不启动真实计时。
  vm.runInContext(source,context); // 扩展仅在本机虚拟上下文运行。
  state.call = msg => context.command(msg); // 驱动桌面命令。
  state.remove = (id,closing=false) => chrome.tabs.onRemoved.listeners[0](id,{windowId:3,isWindowClosing:closing}); // 模拟用户关闭。
  state.disconnect = () => port.onDisconnect.listeners[0](); // 模拟助手退出。
  state.timers = timers; // 注入恢复超时。
  state.bind = () => state.call({command:'bind',id:17,url:target,token:'session-a'}); // 手动绑定命令。
  return state; // 返回测试工具。
} // 结束测试环境。
(async () => { // 顺序执行，避免异步事件互相影响。
  let f=fixture();await f.bind();assert(f.sent.some(x=>x.event==='bound'));f.remove(17);assert(f.sent.some(x=>x.event==='closed'));await f.call({command:'recover',token:'session-a'});assert.equal(f.creates,1);assert(f.sent.some(x=>x.event==='restored'));await f.call({command:'recover',token:'session-a'});assert.equal(f.creates,1);console.log('PASS close restores once and updates identity'); // 不重复恢复。
  f=fixture();await f.bind();f.ready=false;f.remove(17);await f.call({command:'recover',token:'session-a'});assert(f.sent.some(x=>x.event==='failed'&&x.code==='RESTORE_PAGE_INVALID'));await f.call({command:'recover',token:'session-a'});assert.equal(f.creates,1);console.log('PASS login or page validation failure stops without retry'); // 页面失败。
  f=fixture();await f.bind();f.remove(17,true);await f.call({command:'recover',token:'session-a'});assert.equal(f.creates,0);console.log('PASS whole-window close never opens a window'); // 不重启浏览器。
  f=fixture();await f.bind();f.remove(17);await f.call({command:'stop'});await f.call({command:'recover',token:'session-a'});assert.equal(f.creates,0);console.log('PASS manual stop revokes recovery'); // 手动停止。
  f=fixture();await f.bind();f.remove(17);f.disconnect();await f.call({command:'recover',token:'session-a'});assert.equal(f.creates,0);console.log('PASS desktop disconnect revokes recovery'); // 失联停止。
  f=fixture();await f.bind();f.remove(999);assert(!f.sent.some(x=>x.event==='closed'));console.log('PASS unrelated tab close does not trigger recovery'); // 无关标签不影响。
  f=fixture();await f.bind();f.loadComplete=false;f.remove(17);await f.call({command:'recover',token:'session-a'});f.timers.at(-1)();assert(f.sent.some(x=>x.event==='failed'&&x.code==='RESTORE_TIMEOUT'));assert.equal(f.creates,1);console.log('PASS recovery deadline stops without reopening again'); // 截止时间。
  f=fixture();await f.call({command:'bind',id:17,url:'https://example.com/',token:'session-a'});assert(f.sent.some(x=>x.event==='failed'&&x.code==='TARGET_NOT_ALLOWED'));console.log('PASS unrelated origin cannot be bound or restored'); // 站点边界。
})().catch(error => { console.error(error);process.exitCode=1; }); // 测试失败返回非零。
