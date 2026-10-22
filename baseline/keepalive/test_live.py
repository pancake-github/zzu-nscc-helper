"""真实请求规则的离线测试；不向超算发送数据。"""  # 实际请求另有单次验收记录。
import unittest  # 标准测试框架。
from unittest.mock import patch  # 只替换路由故障，不发网络请求。
from live_request import check_response, perform, MARKERS  # 使用交付代码的响应判据。

class LiveTests(unittest.TestCase):  # 防止把伪响应当保活成功。
    def test_page_validation(self):  # 平台内容必须全部匹配。
        body = b' '.join(MARKERS)  # 不包含真实用户数据的模拟正文。
        self.assertIsNone(check_response(200, 'text/html; charset=UTF-8', body))  # 正确平台页。
        self.assertEqual(check_response(302, 'text/html', body), 'HTTP_STATUS')  # 跳转失败。
        self.assertEqual(check_response(502, 'text/html', body), 'HTTP_STATUS')  # 网关错误失败。
        self.assertEqual(check_response(200, 'text/plain', body), 'CONTENT_TYPE')  # 格式失败。
        self.assertEqual(check_response(200, 'text/html', b''), 'EMPTY_BODY')  # 空响应失败。
        self.assertEqual(check_response(200, 'text/html', b'<html>proxy error</html>'), 'CONTENT_MISMATCH')  # 代理页失败。
        self.assertEqual(check_response(200, 'text/html', b'x' * 65537), 'BODY_TOO_LARGE')  # 大响应失败。

    def test_vpn_route_failure_prevents_connection(self):  # VPN 出口失效不得发请求。
        with patch('live_request.vpn_route_valid', return_value=False), patch('live_request.urllib3.HTTPSConnectionPool') as pool:  # 无真实网络副作用。
            result = perform()  # 实际入口。
            self.assertEqual(result['error'], 'VPN_ROUTE_INVALID')  # 故障类别准确。
            pool.assert_not_called()  # 完全不创建连接。

if __name__ == '__main__':  # 测试入口。
    unittest.main(verbosity=2)  # 逐项显示结果。
