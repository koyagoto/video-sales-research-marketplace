import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sales_list.py"


class SalesListScriptTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name) / "営業管理"

    def tearDown(self):
        self.temporary.cleanup()

    def run_script(self, *arguments, expected_code=0):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, expected_code, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_full_pipeline_and_deduplication(self):
        initialized = self.run_script("init", "--dir", str(self.data_dir))
        self.assertEqual(initialized["result"], "initialized")

        created = self.run_script(
            "upsert",
            "--dir",
            str(self.data_dir),
            "--company",
            "サンプル株式会社",
            "--official-url",
            "https://example.com/",
            "--opportunity-url",
            "https://example.com/partners",
            "--checked-date",
            "2026-08-16",
            "--score",
            "92",
            "--evidence",
            "83",
            "--decision",
            "暫定推薦",
            "--next-action",
            "応募条件を確認",
        )
        self.assertEqual(created["result"], "created")

        updated = self.run_script(
            "upsert",
            "--dir",
            str(self.data_dir),
            "--company",
            "サンプル株式会社",
            "--official-url",
            "https://example.com/?tracking=1",
            "--checked-date",
            "2026-08-17",
            "--score",
            "94",
            "--evidence",
            "90",
            "--decision",
            "暫定推薦",
        )
        self.assertEqual(updated["result"], "updated")
        self.assertEqual(created["company_id"], updated["company_id"])

        for event_type, event_date in [
            ("送信", "2026-08-18"),
            ("返信", "2026-08-19"),
            ("面談", "2026-08-20"),
            ("提案", "2026-08-21"),
            ("受注", "2026-08-22"),
        ]:
            recorded = self.run_script(
                "event",
                "--dir",
                str(self.data_dir),
                "--company",
                "サンプル株式会社",
                "--type",
                event_type,
                "--date",
                event_date,
            )
            self.assertEqual(recorded["result"], "recorded")

        summary = self.run_script("summary", "--dir", str(self.data_dir))
        self.assertEqual(summary["counts"]["登録企業数"], 1)
        self.assertEqual(summary["counts"]["送信済み企業数"], 1)
        self.assertEqual(summary["counts"]["面談企業数"], 1)
        self.assertEqual(summary["counts"]["受注企業数"], 1)
        self.assertEqual(summary["rates_percent"]["受注率"], 100.0)

        listed = self.run_script("list", "--dir", str(self.data_dir))
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["prospects"][0]["進捗状態"], "受注")

        validated = self.run_script("validate", "--dir", str(self.data_dir))
        self.assertEqual(validated, {"result": "valid", "issues": []})

    def test_rejects_invalid_score_and_missing_exclusion_reason(self):
        invalid = self.run_script(
            "upsert",
            "--dir",
            str(self.data_dir),
            "--company",
            "サンプル株式会社",
            "--score",
            "101",
            expected_code=2,
        )
        self.assertEqual(invalid["result"], "error")

        self.run_script(
            "upsert",
            "--dir",
            str(self.data_dir),
            "--company",
            "サンプル株式会社",
        )
        exclusion = self.run_script(
            "event",
            "--dir",
            str(self.data_dir),
            "--company",
            "サンプル株式会社",
            "--type",
            "除外",
            expected_code=2,
        )
        self.assertEqual(exclusion["result"], "error")

    def test_saved_profile_survives_sales_list_initialization_and_updates(self):
        profile_path = self.data_dir / "プロフィール.md"

        self.run_script("init", "--dir", str(self.data_dir))
        self.assertFalse(profile_path.exists())

        profile_text = """# 保存済みプロフィール

- 屋号・会社名：サンプル映像事業
- 主な活動拠点：関西
- 希望する発注元：広告代理店、Web制作会社、一般企業
- 顧客業種を限定するか：限定しない
"""
        profile_path.write_text(profile_text, encoding="utf-8")
        original_bytes = profile_path.read_bytes()

        self.run_script(
            "upsert",
            "--dir",
            str(self.data_dir),
            "--company",
            "移行テスト株式会社",
            "--official-url",
            "https://migration.example.invalid/",
            "--checked-date",
            "2026-08-24",
            "--score",
            "90",
            "--evidence",
            "80",
            "--decision",
            "暫定推薦",
        )
        self.run_script(
            "event",
            "--dir",
            str(self.data_dir),
            "--company",
            "移行テスト株式会社",
            "--type",
            "送信",
            "--date",
            "2026-08-24",
        )

        self.assertEqual(profile_path.read_bytes(), original_bytes)
        self.assertIn("希望する発注元", profile_path.read_text(encoding="utf-8"))
        validated = self.run_script("validate", "--dir", str(self.data_dir))
        self.assertEqual(validated, {"result": "valid", "issues": []})


if __name__ == "__main__":
    unittest.main()
