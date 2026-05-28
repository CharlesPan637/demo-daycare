import importlib
import os
import unittest


class P0RegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("API_KEY", "test-key")
        cls.mod = importlib.import_module("bot.app")
        cls.app = cls.mod.app

    def setUp(self):
        self.mod.API_KEY = "test-key"
        self.mod.API_KEY_NEXT = ""
        self.mod.API_KEY_NEXT_ACTIVE_UNTIL = ""
        self.mod.RATE_LIMIT_ENABLED = False
        with self.mod._IDEMPOTENCY_LOCK:
            self.mod._IDEMPOTENCY_STORE.clear()
        with self.mod._RATE_LIMIT_LOCK:
            self.mod._RATE_LIMIT_STORE.clear()
        self.mod.get_waitlist = lambda status=None: []
        self.client = self.app.test_client()

    def _auth_headers(self):
        return {"X-API-Key": "test-key"}

    def _assert_error_code(self, response, expected_status, expected_code):
        self.assertEqual(response.status_code, expected_status)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("error", {}).get("code"), expected_code)
        self.assertTrue(payload.get("error", {}).get("request_id"))

    def test_auth_gate_401_and_200(self):
        denied = self.client.get("/waitlist")
        self._assert_error_code(denied, 401, "unauthorized")

        self.mod.get_waitlist = lambda status=None: [{"id": 1, "fields": {"status": "new"}}]
        ok = self.client.get("/waitlist", headers=self._auth_headers())
        self.assertEqual(ok.status_code, 200)
        payload = ok.get_json()
        self.assertEqual(payload.get("count"), 1)
        self.assertIn("entries", payload)

    def test_pickup_verify_and_events_denied_and_override(self):
        self.mod.get_child_guardian_links = lambda child_id_val: [
            {"id": 77, "fields": {"guardian": 12, "legal_status": "custodial", "pickup_allowed": True, "pickup_password": "1234"}}
        ]
        verify = self.client.post(
            "/pickup/verify",
            json={"child_id": 1, "guardian_id": 12, "pickup_password": "1234"},
            headers=self._auth_headers(),
        )
        self.assertEqual(verify.status_code, 200)
        self.assertEqual(verify.get_json().get("allowed"), True)

        self.mod.add_pickup_event = lambda **kwargs: {"id": 101}
        denied = self.client.post(
            "/pickup/events",
            json={"child_id": 1, "approved": False, "denial_code": "pickup_not_allowed", "denial_reason": "Policy"},
            headers=self._auth_headers(),
        )
        self.assertEqual(denied.status_code, 200)
        self.assertEqual(denied.get_json().get("status"), "logged")

        override = self.client.post(
            "/pickup/events",
            json={
                "child_id": 1,
                "approved": True,
                "override_used": True,
                "override_reason": "Manual ID verified",
                "override_approved_by": 1,
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(override.status_code, 200)
        self.assertEqual(override.get_json().get("status"), "logged")

    def test_invoice_allocation_and_autopay_attempts(self):
        invoice = {"id": 5, "fields": {"account": 10, "total_due": 100, "status": "issued"}}
        parties = [{
            "id": 1,
            "fields": {
                "account": 10,
                "guardian": 3,
                "payer_label": "Primary",
                "share_pct": 100,
                "fixed_amount": 0,
                "priority": 1,
                "auto_debit": True,
                "status": "active",
            },
        }]
        self.mod.get_invoice = lambda invoice_id_val: invoice
        self.mod.get_billing_account_parties = lambda account_id_val=None, status=None: parties
        self.mod.get_payments = lambda invoice_id_val=None: []
        self.mod.create_autopay_attempt = lambda payload: {"id": 901, "fields": payload}
        self.mod.update_invoice = lambda invoice_id_val, fields: {"ok": True}

        alloc = self.client.post("/billing/invoices/5/allocate", headers=self._auth_headers())
        self.assertEqual(alloc.status_code, 200)
        alloc_payload = alloc.get_json()
        self.assertEqual(alloc_payload.get("allocation_count"), 1)
        self.assertEqual(alloc_payload.get("allocations", [{}])[0].get("allocated_amount"), 100.0)

        autopay = self.client.post(
            "/billing/invoices/5/autopay/run",
            json={"dry_run": True},
            headers=self._auth_headers(),
        )
        self.assertEqual(autopay.status_code, 200)
        auto_payload = autopay.get_json()
        self.assertEqual(auto_payload.get("attempt_count"), 1)
        self.assertEqual(auto_payload.get("attempts", [{}])[0].get("status"), "simulated")

    def test_subsidy_claim_reconcile_and_summary(self):
        created_claim = {}

        def _create_claim(fields):
            created_claim.update(fields)
            return {"id": 7, "fields": fields}

        def _claims(claim_month=None, status=None, program=None):
            return [
                {"id": 7, "fields": {"claim_month": "2026-05", "program": "state", "child": 1, "expected_amount": 100, "received_amount": 90, "status": "variance"}},
                {"id": 8, "fields": {"claim_month": "2026-05", "program": "state", "child": 2, "expected_amount": 100, "received_amount": 100, "status": "paid"}},
            ]

        updated = {}

        def _update_claim(claim_id_val, fields):
            updated.update(fields)
            return {"ok": True}

        self.mod.create_subsidy_claim = _create_claim
        self.mod.get_subsidy_claims = _claims
        self.mod.update_subsidy_claim = _update_claim

        create = self.client.post(
            "/subsidy/claims",
            json={"claim_month": "2026-05", "child": 1, "program": "state", "expected_amount": 100, "received_amount": 90},
            headers=self._auth_headers(),
        )
        self.assertEqual(create.status_code, 201)
        self.assertEqual(create.get_json().get("status"), "created")
        self.assertEqual(created_claim.get("status"), "variance")

        reconcile = self.client.post(
            "/subsidy/reconcile/7",
            json={"received_amount": 100},
            headers=self._auth_headers(),
        )
        self.assertEqual(reconcile.status_code, 200)
        self.assertEqual(updated.get("status"), "paid")
        self.assertEqual(updated.get("variance"), 0.0)

        summary = self.client.get("/subsidy/reconciliation/summary", headers=self._auth_headers())
        self.assertEqual(summary.status_code, 200)
        payload = summary.get_json()
        self.assertEqual(payload.get("count"), 2)
        self.assertEqual(payload.get("variance_buckets", {}).get("overpaid"), 0)
        self.assertEqual(payload.get("variance_buckets", {}).get("exact"), 1)

    def test_waitlist_create_advance_and_list(self):
        captured_create = {}
        captured_patch = {}

        def _add_waitlist(fields):
            captured_create.update(fields)
            return {"id": 11, "fields": fields}

        def _patch_waitlist(entry_id_val, fields):
            captured_patch.update(fields)
            return {"ok": True}

        entries = [
            {"id": 11, "fields": {"status": "new", "last_contact_at": "2026-05-01T10:00:00", "priority_score": 3}},
            {"id": 12, "fields": {"status": "contacted", "last_contact_at": "2026-05-02T10:00:00", "priority_score": 4}},
        ]
        self.mod.add_waitlist_entry = _add_waitlist
        self.mod.update_waitlist_entry = _patch_waitlist
        self.mod.get_waitlist = lambda status=None: entries if not status else [e for e in entries if e["fields"].get("status") == status]

        create = self.client.post(
            "/waitlist",
            json={"child_first_name": "Ava", "child_last_name": "Lee", "desired_start_date": "2026-06-01", "status": "new"},
            headers=self._auth_headers(),
        )
        self.assertEqual(create.status_code, 201)
        self.assertEqual(create.get_json().get("status"), "created")
        self.assertEqual(captured_create.get("desired_start_date"), "2026-06-01")

        advance = self.client.post("/waitlist/11/advance", json={}, headers=self._auth_headers())
        self.assertEqual(advance.status_code, 200)
        self.assertEqual(advance.get_json().get("new_status"), "contacted")
        self.assertEqual(captured_patch.get("status"), "contacted")

        listed = self.client.get("/waitlist?limit=1&offset=0&sort_by=id&sort_dir=asc", headers=self._auth_headers())
        self.assertEqual(listed.status_code, 200)
        list_payload = listed.get_json()
        self.assertEqual(list_payload.get("count"), 2)
        self.assertEqual(len(list_payload.get("entries", [])), 1)

    def test_marketing_attribution_summary(self):
        self.mod.get_marketing_leads = lambda channel=None, status=None: [
            {"id": 1, "fields": {"family_name": "Ng", "channel": "google", "campaign": "summer", "status": "converted"}},
            {"id": 2, "fields": {"family_name": "Diaz", "channel": "google", "campaign": "summer", "status": "lost"}},
            {"id": 3, "fields": {"family_name": "Ali", "channel": "facebook", "campaign": "referral", "status": "converted"}},
        ]
        self.mod.get_review_requests = lambda platform=None, status=None: [
            {"id": 11, "fields": {"family_name": "Ng", "status": "received", "rating": 5}},
            {"id": 12, "fields": {"family_name": "Ali", "status": "received", "rating": 4}},
            {"id": 13, "fields": {"family_name": "Diaz", "status": "requested", "rating": 0}},
        ]

        resp = self.client.get("/marketing/attribution/summary", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload.get("lead_count"), 3)
        self.assertEqual(payload.get("review_count"), 3)

        channels = {row["channel"]: row for row in payload.get("channels", [])}
        self.assertAlmostEqual(channels["google"]["conversion_rate"], 0.5, places=4)
        self.assertEqual(channels["google"]["reviews_received_count"], 1)
        self.assertAlmostEqual(channels["google"]["average_review_rating"], 5.0, places=2)
        self.assertAlmostEqual(channels["facebook"]["conversion_rate"], 1.0, places=4)

        campaigns = {row["campaign"]: row for row in payload.get("campaigns", [])}
        self.assertEqual(campaigns["summer"]["lead_count"], 2)
        self.assertAlmostEqual(campaigns["summer"]["conversion_rate"], 0.5, places=4)

    def test_marketing_seo_summary(self):
        self.mod.get_marketing_leads = lambda channel=None, status=None: [
            {"id": 1, "fields": {"family_name": "Ng", "channel": "google", "campaign": "summer", "status": "converted", "inquiry_date": "2026-04-10T09:00:00"}},
            {"id": 2, "fields": {"family_name": "Diaz", "channel": "google", "campaign": "summer", "status": "lost", "inquiry_date": "2026-04-11T09:00:00"}},
            {"id": 3, "fields": {"family_name": "Ali", "channel": "facebook", "campaign": "fall", "status": "converted", "inquiry_date": "2026-05-01T09:00:00"}},
        ]
        self.mod.get_review_requests = lambda platform=None, status=None: [
            {"id": 11, "fields": {"family_name": "Ng", "status": "received", "rating": 5, "received_at": "2026-04-22T12:00:00"}},
            {"id": 12, "fields": {"family_name": "Ali", "status": "received", "rating": 4, "received_at": "2026-05-15T12:00:00"}},
            {"id": 13, "fields": {"family_name": "Diaz", "status": "requested", "rating": 0, "requested_at": "2026-05-10T12:00:00"}},
        ]

        resp = self.client.get("/marketing/seo/summary", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload.get("lead_count"), 3)
        self.assertEqual(payload.get("review_count"), 3)

        lead_trend = {row["month"]: row["count"] for row in payload.get("lead_trend_by_month", [])}
        self.assertEqual(lead_trend.get("2026-04"), 2)
        self.assertEqual(lead_trend.get("2026-05"), 1)

        review_trend = {row["month"]: row["count"] for row in payload.get("received_review_trend_by_month", [])}
        self.assertEqual(review_trend.get("2026-04"), 1)
        self.assertEqual(review_trend.get("2026-05"), 1)

        campaigns = {row["campaign"]: row for row in payload.get("campaign_performance", [])}
        self.assertAlmostEqual(campaigns["summer"]["conversion_rate"], 0.5, places=4)
        self.assertAlmostEqual(campaigns["fall"]["conversion_rate"], 1.0, places=4)

    def test_marketing_spend_summary(self):
        self.mod.get_marketing_leads = lambda channel=None, status=None: [
            {"id": 1, "fields": {"channel": "google", "campaign": "summer", "status": "converted", "inquiry_date": "2026-04-10T09:00:00"}},
            {"id": 2, "fields": {"channel": "google", "campaign": "summer", "status": "lost", "inquiry_date": "2026-04-11T09:00:00"}},
            {"id": 3, "fields": {"channel": "facebook", "campaign": "fall", "status": "converted", "inquiry_date": "2026-04-15T09:00:00"}},
        ]
        self.mod.get_marketing_channel_spend = lambda channel=None, campaign=None, period_month=None: [
            {"id": 10, "fields": {"channel": "google", "campaign": "summer", "period_month": "2026-04", "spend_amount": 300, "currency": "USD"}},
            {"id": 11, "fields": {"channel": "facebook", "campaign": "fall", "period_month": "2026-04", "spend_amount": 120, "currency": "USD"}},
        ]

        resp = self.client.get("/marketing/attribution/spend-summary?period_month=2026-04", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload.get("count"), 2)
        self.assertAlmostEqual(payload.get("totals", {}).get("spend_amount"), 420.0, places=2)
        self.assertEqual(payload.get("totals", {}).get("lead_count"), 3)
        self.assertEqual(payload.get("totals", {}).get("converted_count"), 2)
        self.assertAlmostEqual(payload.get("totals", {}).get("blended_cpl"), 140.0, places=2)
        self.assertAlmostEqual(payload.get("totals", {}).get("blended_cpa"), 210.0, places=2)

        items = {f"{row['channel']}:{row['campaign']}": row for row in payload.get("items", [])}
        self.assertAlmostEqual(items["google:summer"]["cpl"], 150.0, places=2)
        self.assertAlmostEqual(items["google:summer"]["cpa"], 300.0, places=2)
        self.assertAlmostEqual(items["facebook:fall"]["cpl"], 120.0, places=2)
        self.assertAlmostEqual(items["facebook:fall"]["cpa"], 120.0, places=2)

    def test_marketing_spend_trend(self):
        self.mod.get_marketing_leads = lambda channel=None, status=None: [
            {"id": 1, "fields": {"channel": "google", "campaign": "summer", "status": "converted", "inquiry_date": "2026-03-10T09:00:00"}},
            {"id": 2, "fields": {"channel": "google", "campaign": "summer", "status": "lost", "inquiry_date": "2026-03-11T09:00:00"}},
            {"id": 3, "fields": {"channel": "google", "campaign": "summer", "status": "converted", "inquiry_date": "2026-04-15T09:00:00"}},
        ]
        self.mod.get_marketing_channel_spend = lambda channel=None, campaign=None, period_month=None: [
            {"id": 10, "fields": {"channel": "google", "campaign": "summer", "period_month": "2026-03", "spend_amount": 200}},
            {"id": 11, "fields": {"channel": "google", "campaign": "summer", "period_month": "2026-04", "spend_amount": 300}},
        ]

        resp = self.client.get("/marketing/attribution/spend-trend", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload.get("count"), 2)
        items = payload.get("items", [])
        self.assertEqual(items[0]["period_month"], "2026-03")
        self.assertAlmostEqual(items[0]["blended_cpl"], 100.0, places=2)
        self.assertAlmostEqual(items[1]["blended_cpl"], 300.0, places=2)
        self.assertAlmostEqual(items[1]["mom_cpl_change"], 200.0, places=2)

    def test_marketing_multi_touch(self):
        self.mod.get_marketing_leads = lambda channel=None, status=None: [
            {"id": 1, "fields": {"channel": "google", "campaign": "summer", "status": "converted", "inquiry_date": "2026-05-10T09:00:00"}},
            {"id": 2, "fields": {"channel": "facebook", "campaign": "fall", "status": "converted", "inquiry_date": "2026-05-12T09:00:00"}},
            {"id": 3, "fields": {"channel": "google", "campaign": "spring", "status": "converted", "inquiry_date": "2026-04-05T09:00:00"}},
        ]
        self.mod.get_marketing_touchpoints = lambda lead_id=None, channel=None: [
            {"id": 10, "fields": {"lead_id": 1, "channel": "google", "occurred_at": "2026-05-01T09:00:00"}},
            {"id": 11, "fields": {"lead_id": 1, "channel": "facebook", "occurred_at": "2026-05-08T09:00:00"}},
            {"id": 12, "fields": {"lead_id": 2, "channel": "facebook", "occurred_at": "2026-05-02T09:00:00"}},
            {"id": 13, "fields": {"lead_id": 3, "channel": "google", "occurred_at": "2026-04-02T09:00:00"}},
        ]
        def _spend_rows(channel=None, campaign=None, period_month=None):
            rows = [
                {"id": 20, "fields": {"channel": "google", "period_month": "2026-05", "spend_amount": 300}},
                {"id": 21, "fields": {"channel": "facebook", "period_month": "2026-05", "spend_amount": 200}},
                {"id": 22, "fields": {"channel": "google", "period_month": "2026-04", "spend_amount": 150}},
            ]
            if period_month:
                rows = [r for r in rows if r["fields"].get("period_month") == period_month]
            return rows
        self.mod.get_marketing_channel_spend = _spend_rows

        resp = self.client.get(
            "/marketing/attribution/multi-touch?period_month=2026-05&model=position_based",
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload.get("model"), "position_based")
        items = {row["channel"]: row for row in payload.get("items", [])}
        self.assertAlmostEqual(items["google"]["weighted_conversions"], 0.5, places=4)
        self.assertAlmostEqual(items["facebook"]["weighted_conversions"], 1.5, places=4)
        self.assertAlmostEqual(items["facebook"]["weighted_cpa"], 133.33, places=2)
        self.assertAlmostEqual(payload.get("totals", {}).get("weighted_cpa"), 250.0, places=2)
        self.assertAlmostEqual(payload.get("totals", {}).get("weighted_cpa_change_vs_prior_month"), 100.0, places=2)

    def test_marketing_attribution_weights(self):
        get_resp = self.client.get("/marketing/attribution/weights", headers=self._auth_headers())
        self.assertEqual(get_resp.status_code, 200)
        original = get_resp.get_json()
        self.assertAlmostEqual(original.get("sum"), 1.0, places=4)

        bad_resp = self.client.post(
            "/marketing/attribution/weights",
            json={"first_touch": 0.5, "middle_touch_total": 0.5, "last_touch": 0.5},
            headers=self._auth_headers(),
        )
        self.assertEqual(bad_resp.status_code, 400)

        ok_resp = self.client.post(
            "/marketing/attribution/weights",
            json={"first_touch": 0.3, "middle_touch_total": 0.4, "last_touch": 0.3},
            headers=self._auth_headers(),
        )
        self.assertEqual(ok_resp.status_code, 200)
        updated = ok_resp.get_json()
        self.assertEqual(updated.get("status"), "updated")
        self.assertAlmostEqual(updated.get("sum"), 1.0, places=4)

    def test_staffing_risk_summary(self):
        self.mod.get_room_ratios = lambda: [
            {"id": 1, "fields": {"room_name": "Infant", "staff_child_ratio": "1:4", "current_enrolled": 12, "scheduled_staff": 3}},
            {"id": 2, "fields": {"room_name": "Toddler", "staff_child_ratio": "1:6", "current_enrolled": 12, "scheduled_staff": 2}},
        ]
        self.mod.find_substitutes = lambda day_of_week, room_qual: (
            [{"name": "Alex Sub", "phone": "555-0101", "rooms_qualified": room_qual, "is_on_call": True}]
            if room_qual == "Infant"
            else []
        )

        resp = self.client.get("/staffing/risk-summary?callout_rate=0.2", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload.get("total_rooms"), 2)
        self.assertEqual(payload.get("coverage_gap_rooms"), 0)
        self.assertEqual(payload.get("predicted_gap_rooms"), 2)
        self.assertEqual(payload.get("risk_buckets", {}).get("high"), 0)
        self.assertEqual(payload.get("risk_buckets", {}).get("medium"), 2)
        self.assertEqual(payload.get("recommended_substitutes_total"), 1)
        self.assertEqual(payload.get("unresolved_predicted_gap_rooms"), 1)

        rooms = {row["room_name"]: row for row in payload.get("rooms", [])}
        self.assertEqual(rooms["Infant"]["recommended_substitute_count"], 1)
        self.assertEqual(rooms["Infant"]["remaining_gap_after_recommendations"], 0.0)
        self.assertEqual(rooms["Toddler"]["recommended_substitute_count"], 0)

        bad = self.client.get("/staffing/risk-summary?callout_rate=1.5", headers=self._auth_headers())
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
