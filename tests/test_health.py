from __future__ import annotations

import unittest

from futonhub_auto import health
from futonhub_auto.health import FAIL, OK, UNKNOWN, WARN, build_checks, build_report, problem_headline, worst_status


def by_key(checks):
    return {check.key: check for check in checks}


class ChecksTests(unittest.TestCase):
    def test_token_failure_offers_token_action_and_keeps_internet_ok(self) -> None:
        checks = by_key(build_checks("token", installation_ready=True, env_present=True, installed_version="0.6.4"))
        self.assertEqual(checks["network"].status, OK)
        self.assertEqual(checks["github"].status, FAIL)
        self.assertEqual(checks["github"].action, health.ACTION_TOKEN)
        self.assertEqual(checks["update"].status, UNKNOWN)
        self.assertEqual(checks["erp"].status, OK)
        self.assertIn("0.6.4", checks["erp"].message)

    def test_missing_token_before_start_is_a_token_failure(self) -> None:
        checks = by_key(build_checks("no_token", installation_ready=False, env_present=True))
        self.assertEqual(checks["github"].action, health.ACTION_TOKEN)
        self.assertEqual(checks["erp"].status, FAIL)

    def test_network_failure_marks_only_connection(self) -> None:
        checks = by_key(build_checks("network", installation_ready=True, env_present=True))
        self.assertEqual(checks["network"].status, FAIL)
        self.assertEqual(checks["github"].status, UNKNOWN)

    def test_rate_limit_is_a_warning_not_a_failure(self) -> None:
        checks = build_checks("rate_limit", installation_ready=True, env_present=True)
        self.assertEqual(by_key(checks)["github"].status, WARN)
        self.assertEqual(worst_status(checks), WARN)

    def test_not_found_has_no_user_action(self) -> None:
        github = by_key(build_checks("not_found", installation_ready=True, env_present=True))["github"]
        self.assertEqual(github.status, FAIL)
        self.assertIsNone(github.action)

    def test_missing_env_offers_env_action_even_without_remote_failure(self) -> None:
        checks = by_key(build_checks(None, installation_ready=True, env_present=False))
        self.assertEqual(checks["env"].action, health.ACTION_ENV)
        self.assertEqual(checks["update"].status, OK)

    def test_all_good_has_no_problem(self) -> None:
        self.assertEqual(worst_status(build_checks(None, installation_ready=True, env_present=True)), OK)

    def test_erp_crash_marks_the_erp(self) -> None:
        erp = by_key(build_checks("erp_crash", installation_ready=True, env_present=True, detail="código 1"))["erp"]
        self.assertEqual(erp.status, FAIL)
        self.assertIn("código 1", erp.message)

    def test_headline_depends_on_whether_erp_can_open(self) -> None:
        self.assertIn("Puedes abrir", problem_headline("token", True)[0])
        self.assertIn("No se pudo preparar", problem_headline("token", False)[0])


class ReportTests(unittest.TestCase):
    def test_report_has_technical_data_and_never_leaks_the_token(self) -> None:
        checks = build_checks("token", installation_ready=True, env_present=True)
        report = build_report(
            launcher_version="0.14.3", channel="test", title="t", kind="token",
            message="401 con ghp_SECRET123", status_text="s", installed="0.6.4", available="—",
            checks=checks, activity=["a", "b ghp_SECRET123"], extra="traza", secret="ghp_SECRET123",
        )
        self.assertNotIn("ghp_SECRET123", report)
        for expected in ("v0.14.3 [test]", "Tipo de fallo: token", "[FAIL   ] Acceso a GitHub", "Actividad reciente", "traza"):
            self.assertIn(expected, report)


if __name__ == "__main__":
    unittest.main()
