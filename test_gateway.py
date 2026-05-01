import unittest

from gateway import KeywordHeuristicStrategy, apply_safe_fallback, evaluate_cost_saving, gateway_transform


class GatewayTests(unittest.TestCase):
    def test_gateway_transform_schema(self):
        payload = {"target": "release", "message": "Fact: outage fixed. Next step: monitor."}
        out = gateway_transform(payload)
        self.assertEqual(out["target"], "release")
        self.assertIn("compressed", out)
        self.assertIn("metrics", out)
        self.assertIn("facts", out["compressed"])

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


if __name__ == "__main__":
    unittest.main()
