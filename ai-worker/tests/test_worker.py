import unittest

from worker import Opportunity, money_from_text, score_task


class WorkerTests(unittest.TestCase):
    def test_money_parser_handles_usdc(self):
        self.assertEqual(money_from_text("Prize: 25 USDC"), (25.0, "USDC"))

    def test_money_parser_handles_dollars(self):
        self.assertEqual(money_from_text("Reward $12.50"), (12.5, "USD"))

    def test_unknown_reward_does_not_become_paid(self):
        task = Opportunity(
            source="test", source_id="1", title="Example", url="https://example.com",
            description="", paid_status="unknown", eligibility="unverified"
        )
        self.assertLess(score_task(task), 0)

    def test_unverified_github_lead_scores_below_confirmed_paid_task(self):
        lead = Opportunity(
            source="GitHub issue lead", source_id="1", title="Issue", url="https://github.com",
            description="", reward_text="10 USDC", reward_usd=10,
            token="USDC", paid_status="unverified", eligibility="unverified",
            risk_flags=["not_a_verified_bounty"]
        )
        confirmed = Opportunity(
            source="BasedAgents", source_id="2", title="Task", url="https://basedagents.ai",
            description="", reward_text="10 USDC", reward_usd=10,
            token="USDC", paid_status="paid", eligibility="unverified",
            risk_flags=[]
        )
        self.assertGreater(score_task(confirmed), score_task(lead))


if __name__ == "__main__":
    unittest.main()
