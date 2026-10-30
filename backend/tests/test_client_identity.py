import hashlib
import hmac
import os
import time
import unittest
from unittest.mock import patch
from starlette.requests import Request
from http_boundary import client_host


class ClientIdentityTests(unittest.TestCase):
    def request(self, ip='203.0.113.1', age=0, signed=True, path='/api/v1/auth/login'):
        stamp = str(int(time.time()) - age)
        message = '\n'.join((stamp, ip, 'POST', path))
        signature = hmac.new(b'test-secret', message.encode(), hashlib.sha256).hexdigest() if signed else 'forged'
        headers = {'x-care-proxy-ip': ip, 'x-care-proxy-time': stamp,
                   'x-care-proxy-signature': signature, 'x-forwarded-for': '1.1.1.1'}
        return Request({'type': 'http', 'method': 'POST', 'path': '/api/v1/auth/login',
                        'headers': [(k.encode(), v.encode()) for k, v in headers.items()],
                        'client': ('127.0.0.1', 5000), 'server': ('backend', 80), 'scheme': 'http'})

    @patch.dict(os.environ, {'PROXY_IDENTITY_SECRET': 'test-secret'})
    def test_distinct_clients_and_ipv6(self):
        for ip in ['203.0.113.1', '203.0.113.2', '2001:db8::1']:
            self.assertEqual(client_host(self.request(ip)), ip)

    @patch.dict(os.environ, {'PROXY_IDENTITY_SECRET': 'test-secret'})
    def test_forged_expired_malformed_and_cross_path_fall_back(self):
        for options in [{'signed': False}, {'age': 90}, {'age': -90},
                        {'ip': '1.1.1.1, 2.2.2.2'}, {'path': '/api/v1/auth/register'}]:
            self.assertEqual(client_host(self.request(**options)), '127.0.0.1')

    @patch.dict(os.environ, {'PROXY_IDENTITY_SECRET': ''})
    def test_disabled_does_not_trust_headers(self):
        self.assertEqual(client_host(self.request()), '127.0.0.1')
