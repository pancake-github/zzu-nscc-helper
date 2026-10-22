const fs = require('node:fs'); // 读取仓库内已有离线场景。
const path = require('node:path'); // 以当前仓库位置定位。
const root = path.resolve(__dirname, '..'); // 不包含开发者固定路径。
const scenarios = fs.readFileSync(path.join(root, 'baseline', 'keepalive', 'test_extension.cjs'), 'utf8'); // 已有模拟Edge用例。
const execute = new Function('require', '__dirname', scenarios); // 仅执行本仓库测试，场景内不连接真实Edge。
execute(require, path.join(root, 'src', 'zzu_nscc_helper', 'keepalive')); // 将真实被测扩展切换为融合组件。
