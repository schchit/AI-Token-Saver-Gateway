import json
import threading
import time
import unittest
import urllib.error
import urllib.request

import gateway
from gateway import KeywordHeuristicStrategy, apply_safe_fallback, evaluate_cost_saving, gateway_transform


class GatewayTests(unittest.TestCase):
    def test_gateway_transform_schema(self):
        payload = {"target": "release", "message": "Fact: outage fixed. Next step: monitor."}
        out = gateway_transform(payload)
        self.assertEqual(out["target"], "release")
        self.assertIn("compressed", out)
        self.assertIn("metrics", out)

    def test_target_aware_strategy(self):
        strategy = KeywordHeuristicStrategy()
        out = gateway_transform({"target": "deploy_decision", "message": "Deploy ready. Risk: high latency."}, strategy=strategy)
        self.assertEqual(out["compressed"]["strategy"], "keyword_heuristic")

    def test_safe_fallback_triggered(self):
        message = "hello"
        compressed = KeywordHeuristicStrategy().compress(message)
        fixed = apply_safe_fallback(message, compressed, min_confidence=0.95)
        self.assertTrue(fixed.fallback_used)

    def test_cost_metrics(self):
        msg = "Fact: outage fixed. Next step: monitor. Risk: latency spike."
        compressed = KeywordHeuristicStrategy().compress(msg)
        metrics = evaluate_cost_saving(msg, compressed)
        self.assertIn("tokens_before", metrics)
        self.assertIn("saving_ratio", metrics)

    def test_http_smoke(self):
        th = threading.Thread(target=gateway.run_server, kwargs={"host": "127.0.0.1", "port": 18081}, daemon=True)
        th.start()
        time.sleep(0.3)

        health = urllib.request.urlopen("http://127.0.0.1:18081/health", timeout=2).read().decode()
        self.assertIn("ok", health)

        req = urllib.request.Request(
            "http://127.0.0.1:18081/transform",
            data=json.dumps({"target": "deploy_decision", "message": "Fact: x. Next step: y. Risk: z."}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        body = urllib.request.urlopen(req, timeout=2).read().decode()
        self.assertIn("compressed", body)


if __name__ == "__main__":
    unittest.main()
