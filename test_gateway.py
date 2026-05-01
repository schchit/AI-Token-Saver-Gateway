import json
import unittest

from gateway import compress_message, gateway_transform


class GatewayTests(unittest.TestCase):
    def test_compress_message_has_intent(self):
        msg = "Need to ship patch today. Fact: bug reproduced on v2. Risk: tests are flaky."
        result = compress_message(msg)
        self.assertIn("Need to ship patch", result.intent)
        self.assertGreaterEqual(result.confidence, 0.4)

    def test_gateway_transform_schema(self):
        payload = {"target": "release", "message": "Fact: outage fixed. Next step: monitor."}
        out = gateway_transform(payload)
        self.assertEqual(out["target"], "release")
        self.assertIn("compressed", out)
        self.assertIn("facts", out["compressed"])
        json.dumps(out)


if __name__ == "__main__":
    unittest.main()
