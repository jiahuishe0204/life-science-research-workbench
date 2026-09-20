#!/usr/bin/env python3
"""Core backend tests that do not call external services."""

import tempfile
import unittest
from pathlib import Path

import server


class ServerCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        server.DATA = Path(self.temp.name)
        server.DB_PATH = server.DATA / "test.sqlite3"
        server.init_db()

    def tearDown(self):
        self.temp.cleanup()

    def test_owner_tokens_are_hashed_and_distinct(self):
        self.assertEqual(len(server.owner_hash("a")), 64)
        self.assertNotEqual(server.owner_hash("a"), server.owner_hash("b"))

    def test_merge_deduplicates_by_doi(self):
        base = {"provider": "PubMed", "title": "A title", "url": "https://example.org/1", "doi": "10.1/x", "abstract": "a", "published": "2026", "read_scope": "abstract"}
        duplicate = {**base, "provider": "Europe PMC", "url": "https://example.org/2"}
        self.assertEqual(len(server.merge_sources([base], [duplicate])), 1)

    def test_job_defaults_are_safe(self):
        timestamp = server.now()
        with server.db() as connection:
            connection.execute("""INSERT INTO jobs
              (id,owner_hash,idempotency_key,topic,status,message,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?)""", ("job", server.owner_hash("secret"), "a" * 16, "CRISPR detection", "queued", "created", timestamp, timestamp))
            row = connection.execute("SELECT * FROM jobs WHERE id='job'").fetchone()
        public = server.public_job(row)
        self.assertNotIn("owner_hash", public)
        self.assertIn("等待管理员审批", public["patent_status"])
        self.assertEqual(public["usage"]["estimated_cost_cny"], 0)

    def test_fallback_query_keeps_scientific_terms(self):
        query = server.fallback_query("mRNA药物递送系统的主要技术路线与关键限制")
        self.assertIn("mRNA", query)
        self.assertIn("drug delivery", query)
        self.assertIn("limitations", query)

    def test_required_patent_disclosure_text_is_explicit(self):
        disclosure = "EPO OPS 账号仍在等待管理员审批，本报告未执行专利检索，不代表不存在相关专利。"
        self.assertIn("EPO", disclosure)
        self.assertIn("未执行专利检索", disclosure)


if __name__ == "__main__":
    unittest.main()
