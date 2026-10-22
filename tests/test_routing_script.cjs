const fs = require('node:fs'); // 只读取父测试通过stdin提供的合成配置。
const vm = require('node:vm'); // 在隔离上下文执行实际生成的增强脚本。
const assert = require('node:assert/strict'); // 独立检查行为，不连接Clash。
const input = JSON.parse(fs.readFileSync(0, 'utf8')); // 测试数据不含订阅和真实凭据。
const sandbox = vm.createContext({}); // 不提供文件、网络或进程接口。
vm.runInContext(input.script, sandbox, {timeout: 1000}); // 检查真实脚本语法与入口。
sandbox.fixture = JSON.parse(JSON.stringify(input.config)); // 独立副本避免断言被输入修改干扰。
vm.runInContext('result = main(fixture, "offline-profile")', sandbox, {timeout: 1000}); // 执行真实main组合。
const result = JSON.parse(JSON.stringify(sandbox.result)); // 跨上下文转换普通数据。
assert.equal(result.custom, 'preserved'); // 原增强逻辑必须实际执行。
assert.equal(result['mixed-port'], 11789); // 本地代理端口保持检测值。
assert.equal(result.tun.enable, false); // 不能自动开启TUN。
assert.deepEqual(result.proxies, input.config.proxies); // 节点内容完整保留。
assert.equal(result.dns['nameserver-policy']['existing.invalid'], '1.1.1.1'); // 原DNS策略保留。
assert.equal(result.dns['nameserver-policy']['hpc01.v.zzu.edu.cn'], 'udp://172.99.2.11:53#VPN 测试接口 9'); // 绑定实际VPN别名。
assert(result.dns['fake-ip-filter'].includes('existing.invalid')); // 原fake-IP排除保留。
assert(result.tun['route-exclude-address'].includes('192.0.2.1/32')); // 原TUN排除保留。
assert(result.tun['route-exclude-address'].includes('222.22.12.2/32')); // 仅新增精确VPN公网入口。
assert(result.rules.includes('MATCH,ExistingGroup')); // 原规则顺序尾部保留。
assert.equal(result.rules.filter(rule => rule === 'DOMAIN,hpc01.v.zzu.edu.cn,DIRECT').length, 1); // 重复应用不重复追加规则。
assert(!result.rules.some(rule => rule.startsWith('DST-PORT,22,'))); // 不将所有SSH流量放行。
process.stdout.write('ROUTING_SCRIPT_PASSED\n'); // 只输出检查结果。
