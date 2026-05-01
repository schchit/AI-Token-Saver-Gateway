import unittest
from fastapi.testclient import TestClient
import gateway
from gateway import app, TransformRequest, transform_impl, TOKEN_COUNTER

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        r = self.client.get('/health')
        self.assertEqual(r.status_code, 200)

    def test_transform(self):
        payload = {
            "target": "deploy_decision",
            "message": "Fact: stable. Next step: deploy.",
            "strategy": "hybrid"
        }
        r = self.client.post('/transform', json=payload)
        self.assertEqual(r.status_code, 200)
        self.assertIn('metrics', r.json())

    def test_tokenizer(self):
        self.assertGreaterEqual(TOKEN_COUNTER.count('hello world'), 1)

    def test_transform_impl(self):
        out = transform_impl(
            TransformRequest(message='email a@b.com Fact: done. Next step: deploy.'),
            tenant='t1'
        )
        self.assertEqual(out['version'], 'v2.1')

if __name__ == '__main__':
    unittest.main()
