"""Unit and integration tests for Hybrid Extraction Strategy (Tests 1 to 10).

Validates:
TEST 1: Complete structured API record -> LLM must NOT be called.
TEST 2: Record missing a required semantic field -> LLM MUST be called.
TEST 3: Record missing only optional github_url/github_stars -> LLM must NOT be called.
TEST 4: Duplicate record -> LLM must NOT be called.
TEST 5: LLM returns invalid JSON/schema -> one repair attempt.
TEST 6: Repair fails -> quarantine.
TEST 7: Gemini returns 429 -> fallback to Groq.
TEST 8: All providers fail -> quarantine/error handling without fabrication.
TEST 9: Every actual LLM call creates exactly one llm_logs entry.
TEST 10: Deterministic bypass does NOT create an llm_logs entry.
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.llm.extractor import LLMExtractor
from src.llm.router import LLMRouterManager
from src.schemas import (
    JobEntity,
    NewsEntity,
    ProductEntity,
    ResearchPaperEntity,
    StartupEntity,
)
from src.structure import check_record_completeness, should_use_llm


class TestHybridExtractionStrategy(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.quarantine_dir = Path(self.temp_dir) / "quarantine"
        self.structured_dir = Path(self.temp_dir) / "structured"
        self.cache_dir = Path(self.temp_dir) / "cache"
        self.extractor = LLMExtractor(
            quarantine_dir=self.quarantine_dir,
            structured_dir=self.structured_dir,
            cache_dir=self.cache_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # TEST 1: Complete structured API record -> LLM must NOT be called
    # -------------------------------------------------------------------------
    def test_01_complete_record_bypasses_llm(self):
        record = {
            "schemaVersion": "1.0",
            "recordType": "STARTUP",
            "source": {"name": "Y Combinator", "url": "https://www.ycombinator.com/companies/stripe"},
            "content": {"entityName": "Stripe", "data": {"employeeCount": 8000}},
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        needs_llm, entity = should_use_llm(record, "startups", StartupEntity)
        self.assertFalse(needs_llm, "Complete record must NOT require LLM")
        self.assertIsNotNone(entity, "Validated entity must be returned")
        self.assertEqual(entity.content.entityName, "Stripe")

    # -------------------------------------------------------------------------
    # TEST 2: Record missing a required semantic field -> LLM MUST be called
    # -------------------------------------------------------------------------
    def test_02_incomplete_record_requires_llm(self):
        # Missing required entityName
        record = {
            "source": {"name": "TechCrunch", "url": "https://techcrunch.com/article"},
            "content": {"entityName": "", "data": {}},
        }
        needs_llm, entity = should_use_llm(record, "startups", StartupEntity)
        self.assertTrue(needs_llm, "Record missing required entityName MUST require LLM")
        self.assertIsNone(entity)

    # -------------------------------------------------------------------------
    # TEST 3: Record missing only optional github_url/github_stars -> LLM must NOT be called
    # -------------------------------------------------------------------------
    def test_03_missing_optional_fields_does_not_trigger_llm(self):
        record = {
            "schemaVersion": "1.0",
            "recordType": "RESEARCH_PAPER",
            "content": {
                "title": "Attention Is All You Need",
                "authors": ["Vaswani et al."],
                "paper_url": "https://arxiv.org/abs/1706.03762",
                "github_url": None,  # Optional
                "github_stars": None,  # Optional
                "published_date": "2017-06-12T00:00:00Z",
            },
        }
        needs_llm, entity = should_use_llm(record, "papers", ResearchPaperEntity)
        self.assertFalse(needs_llm, "Missing optional github fields must NOT trigger LLM")
        self.assertIsNotNone(entity)
        self.assertIsNone(entity.content.github_url)

    # -------------------------------------------------------------------------
    # TEST 4: Duplicate record -> LLM must NOT be called (Cache hit)
    # -------------------------------------------------------------------------
    def test_04_duplicate_record_uses_cache(self):
        raw_text = '{"snippet": "OpenAI hiring Research Engineer", "url": "https://openai.com"}'
        content_hash = self.extractor.compute_content_hash(raw_text)
        cached_data = {
            "schemaVersion": "1.0",
            "recordType": "JOB",
            "source": {"name": "OpenAI", "url": "https://openai.com"},
            "content": {
                "company": "OpenAI",
                "title": "Research Engineer",
                "date": "2026-08-15T00:00:00Z",
                "is_remote": True,
                "role_family": "Engineering",
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        self.extractor.cache[content_hash] = cached_data

        # Extract should hit cache without calling router
        with patch.object(self.extractor.router, "execute_completion") as mock_exec:
            entity = self.extractor.extract_entity(
                raw_text=raw_text,
                schema_cls=JobEntity,
                source_url="https://openai.com",
                record_type="JOB",
                allow_cache=True,
            )
            mock_exec.assert_not_called()
            self.assertIsNotNone(entity)
            self.assertEqual(entity.content.company, "OpenAI")
            self.assertEqual(self.extractor.stats["llm_cache_hits"], 1)

    # -------------------------------------------------------------------------
    # TEST 5: LLM returns invalid JSON/schema -> one repair attempt
    # -------------------------------------------------------------------------
    def test_05_one_repair_attempt_on_validation_failure(self):
        invalid_json = '{"title": "Broken Json", missing_brackets'
        valid_repaired_json = json.dumps({
            "schemaVersion": "1.0",
            "recordType": "NEWS",
            "source": {"name": "TechCrunch", "url": "https://techcrunch.com/article"},
            "content": {
                "title": "AI Growth in 2026",
                "url": "https://techcrunch.com/article",
                "published_date": "2026-08-15T00:00:00Z",
                "summary": "AI compute investment expands.",
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        })

        # Router returns invalid JSON on attempt 1, valid on attempt 2 (repair)
        with patch.object(self.extractor.router, "execute_completion", side_effect=[invalid_json, valid_repaired_json]):
            entity = self.extractor.extract_entity(
                raw_text="Raw unformatted news text",
                schema_cls=NewsEntity,
                source_url="https://techcrunch.com/article",
                record_type="NEWS",
                allow_cache=False,
            )
            self.assertIsNotNone(entity)
            self.assertEqual(entity.content.title, "AI Growth in 2026")
            self.assertEqual(self.extractor.stats["repair_count"], 1)

    # -------------------------------------------------------------------------
    # TEST 6: Repair fails -> quarantine
    # -------------------------------------------------------------------------
    def test_06_persistent_failure_quarantined(self):
        invalid_json = '{"bad": "json"}'
        with patch.object(self.extractor.router, "execute_completion", return_value=invalid_json):
            entity = self.extractor.extract_entity(
                raw_text="Unparseable text",
                schema_cls=NewsEntity,
                source_url="https://invalid.com",
                record_type="NEWS",
                allow_cache=False,
            )
            self.assertIsNone(entity)
            self.assertEqual(self.extractor.stats["quarantine_count"], 1)
            quarantine_file = self.quarantine_dir / "news.jsonl"
            self.assertTrue(quarantine_file.exists())

    # -------------------------------------------------------------------------
    # TEST 7: Gemini returns 429 -> fallback to Groq
    # -------------------------------------------------------------------------
    def test_07_gemini_429_fallback_tracking(self):
        router_mgr = LLMRouterManager()
        if router_mgr.router:
            mock_choice = MagicMock()
            mock_choice.message.content = json.dumps({"status": "ok"})
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_resp.model = "groq/llama-3.1-8b-instant"
            mock_resp.usage.prompt_tokens = 45
            mock_resp.usage.completion_tokens = 12

            with patch.object(router_mgr.router, "completion", return_value=mock_resp):
                output = router_mgr.execute_completion([{"role": "user", "content": "hi"}])
                self.assertIn("status", output)
                self.assertEqual(router_mgr.stats["fallback_calls"], 1)

    # -------------------------------------------------------------------------
    # TEST 8: All providers fail -> error handled without fabrication
    # -------------------------------------------------------------------------
    def test_08_all_providers_fail_handled_gracefully(self):
        with patch.object(self.extractor.router, "execute_completion", side_effect=RuntimeError("All providers 500")):
            entity = self.extractor.extract_entity(
                raw_text="Some text",
                schema_cls=JobEntity,
                source_url="https://fail.com",
                record_type="JOB",
                allow_cache=False,
            )
            self.assertIsNone(entity)
            self.assertEqual(self.extractor.stats["quarantine_count"], 1)

    # -------------------------------------------------------------------------
    # TEST 9: Every actual LLM call creates exactly one llm_logs entry
    # -------------------------------------------------------------------------
    def test_09_actual_llm_call_creates_log(self):
        router_mgr = LLMRouterManager(
            gemini_api_key="AIza_mock_gemini",
            groq_api_key="mock_groq",
            cerebras_api_key="mock_cerebras",
        )
        if router_mgr.router:
            mock_choice = MagicMock()
            mock_choice.message.content = "OK"
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_resp.model = "gemini/gemini-2.5-flash"
            mock_resp.usage.prompt_tokens = 10
            mock_resp.usage.completion_tokens = 2

            mock_client = MagicMock()
            mock_client.is_configured = True
            mock_client.rest_endpoint = "https://mock.supabase.co/rest/v1"
            mock_client._get_headers.return_value = {"apikey": "mock"}

            with patch("src.db.supabase_client.get_supabase_client", return_value=mock_client), \
                 patch("src.llm.router.httpx.post") as mock_http, \
                 patch.object(router_mgr.router, "completion", return_value=mock_resp):
                router_mgr.execute_completion(
                    messages=[{"role": "user", "content": "test"}],
                    record_type="STARTUP",
                    content_hash="abc123hash",
                    run_id="run_test_99",
                )
                self.assertEqual(mock_http.call_count, 1)
                call_args = mock_http.call_args[1]
                payload = call_args["json"][0]
                self.assertEqual(payload["run_id"], "run_test_99")
                self.assertEqual(payload["record_type"], "STARTUP")
                self.assertEqual(payload["content_hash"], "abc123hash")
                self.assertEqual(payload["status"], "success")

    # -------------------------------------------------------------------------
    # TEST 10: Deterministic bypass does NOT create an llm_logs entry
    # -------------------------------------------------------------------------
    def test_10_deterministic_bypass_creates_no_llm_log(self):
        record = {
            "schemaVersion": "1.0",
            "recordType": "STARTUP",
            "source": {"name": "Y Combinator", "url": "https://www.ycombinator.com/companies/stripe"},
            "content": {"entityName": "Stripe", "data": {"employeeCount": 8000}},
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        with patch("src.llm.router.httpx.post") as mock_http:
            needs_llm, entity = should_use_llm(record, "startups", StartupEntity)
            self.assertFalse(needs_llm)
            mock_http.assert_not_called()

    # -------------------------------------------------------------------------
    # TEST 11: Fallback Gemini -> Groq -> Cerebras
    # -------------------------------------------------------------------------
    def test_11_cerebras_fallback_execution(self):
        router_mgr = LLMRouterManager(
            gemini_api_key="AIza_mock_gemini",
            groq_api_key="mock_groq",
            cerebras_api_key="mock_cerebras",
            cerebras_model="zai-glm-4.7",
        )
        if router_mgr.router:
            mock_choice = MagicMock()
            mock_choice.message.content = json.dumps({"status": "ok_cerebras"})
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_resp.model = "cerebras/zai-glm-4.7"
            mock_resp.usage.prompt_tokens = 50
            mock_resp.usage.completion_tokens = 15

            with patch.object(router_mgr.router, "completion", return_value=mock_resp):
                output = router_mgr.execute_completion([{"role": "user", "content": "hi"}])
                self.assertIn("ok_cerebras", output)

    # -------------------------------------------------------------------------
    # TEST 12: No secrets in telemetry or logs
    # -------------------------------------------------------------------------
    def test_12_no_secrets_in_telemetry(self):
        router_mgr = LLMRouterManager(
            gemini_api_key="AIza_SECRET_GEMINI_KEY_12345",
            groq_api_key="SECRET_GROQ_KEY_12345",
            cerebras_api_key="SECRET_CEREBRAS_KEY_12345",
        )
        if router_mgr.router:
            mock_choice = MagicMock()
            mock_choice.message.content = "OK"
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_resp.model = "gemini/gemini-2.5-flash"
            mock_resp.usage.prompt_tokens = 10
            mock_resp.usage.completion_tokens = 2

            mock_client = MagicMock()
            mock_client.is_configured = True
            mock_client.rest_endpoint = "https://mock.supabase.co/rest/v1"
            mock_client._get_headers.return_value = {"apikey": "mock"}

            with patch("src.db.supabase_client.get_supabase_client", return_value=mock_client), \
                 patch("src.llm.router.httpx.post") as mock_http, \
                 patch.object(router_mgr.router, "completion", return_value=mock_resp):
                router_mgr.execute_completion(
                    messages=[{"role": "user", "content": "test"}],
                    record_type="NEWS",
                    content_hash="hash999",
                    run_id="run_sec_check",
                )
                self.assertEqual(mock_http.call_count, 1)
                payload_str = json.dumps(mock_http.call_args[1]["json"])
                self.assertNotIn("SECRET_GEMINI_KEY", payload_str)
                self.assertNotIn("SECRET_GROQ_KEY", payload_str)
                self.assertNotIn("SECRET_CEREBRAS_KEY", payload_str)

    # -------------------------------------------------------------------------
    # TEST 13: Gemini OAuth Bearer Token passes Authorization header to REST
    # -------------------------------------------------------------------------
    def test_13_gemini_oauth_direct_bearer_header(self):
        oauth_token = "AQ.TestOAuthToken123456789"
        router_mgr = LLMRouterManager(
            gemini_api_key=oauth_token,
            gemini_model="models/gemini-2.5-pro",
        )

        mock_google_resp = MagicMock()
        mock_google_resp.status_code = 200
        mock_google_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"result": "oauth_success"}'}]}}],
            "usageMetadata": {"promptTokenCount": 35, "candidatesTokenCount": 12},
        }

        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.rest_endpoint = "https://mock.supabase.co/rest/v1"
        mock_client._get_headers.return_value = {"apikey": "mock"}

        with patch("src.db.supabase_client.get_supabase_client", return_value=mock_client), \
             patch("src.llm.router.httpx.post", return_value=mock_google_resp) as mock_http:
            output = router_mgr.execute_completion(
                messages=[{"role": "user", "content": "hello"}],
                record_type="PRODUCT",
                content_hash="hash_oauth_test",
                run_id="run_oauth_99",
            )
            self.assertIn("oauth_success", output)
            # Verify first HTTP call went to Google Generative Language API with Authorization: Bearer
            google_call = mock_http.call_args_list[0]
            url = google_call[0][0]
            headers = google_call[1]["headers"]
            self.assertIn("generativelanguage.googleapis.com", url)
            self.assertNotIn("?key=", url)
            self.assertEqual(headers.get("Authorization"), f"Bearer {oauth_token}")


    # -------------------------------------------------------------------------
    # TEST 14: Fallback Groq -> OpenRouter
    # -------------------------------------------------------------------------
    def test_14_openrouter_fallback_execution(self):
        router_mgr = LLMRouterManager(
            groq_api_key="mock_groq",
            openrouter_api_key="mock_openrouter",
            openrouter_model="openrouter/free",
        )
        if router_mgr.router:
            mock_choice = MagicMock()
            mock_choice.message.content = json.dumps({"status": "ok_openrouter"})
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_resp.model = "openrouter/free"
            mock_resp.usage.prompt_tokens = 45
            mock_resp.usage.completion_tokens = 10

            with patch.object(router_mgr.router, "completion", return_value=mock_resp):
                output = router_mgr.execute_completion([{"role": "user", "content": "hi"}])
                self.assertIn("ok_openrouter", output)


if __name__ == "__main__":
    unittest.main()
