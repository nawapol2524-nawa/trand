"""
Unit Tests for Gate 25: GitHub CI/CD, Security Hardening & Dockerization
========================================================================
Tests:
- Tracked secret file detection
- Credential signature scanning
- .env.example placeholder hygiene
- .gitignore completeness
- Dockerfile non-root & security hardening
- docker-compose decoupled architecture & least privilege mounts
- GitHub Actions CI workflow structure
"""

import os
import unittest
from pathlib import Path
import yaml

from ai_forex_bot.config.settings import settings
from scripts.security_scan import (
    run_git_ls_files,
    audit_tracked_files,
    audit_code_secrets,
    audit_env_example,
    audit_gitignore,
    audit_governance_invariants
)

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent


class TestGate25SecurityAndHygiene(unittest.TestCase):
    def test_security_scanner_zero_tracked_secrets(self):
        """Verify no .env, private keys, or credentials files are tracked in git."""
        tracked = run_git_ls_files()
        self.assertTrue(len(tracked) > 0, "Git tracked files should not be empty")
        passed, violations = audit_tracked_files(tracked)
        self.assertTrue(passed, f"Forbidden tracked secret files detected: {violations}")

    def test_code_secrets_zero_violations(self):
        """Verify tracked source code contains zero unmasked API keys or private keys."""
        tracked = run_git_ls_files()
        passed, violations = audit_code_secrets(tracked)
        self.assertTrue(passed, f"Real secret signatures found in code: {violations}")

    def test_env_example_hygiene(self):
        """Verify .env.example contains only safe placeholders and no real secrets."""
        passed, reason = audit_env_example()
        self.assertTrue(passed, reason)

    def test_gitignore_completeness(self):
        """Verify .gitignore includes critical exclusions for secrets, models, and cache."""
        passed, missing = audit_gitignore()
        self.assertTrue(passed, f"Missing critical .gitignore entries: {missing}")

    def test_governance_invariants(self):
        """Verify LIVE_TRADING and AUTO_PROMOTION are hardcoded to False."""
        passed, violations = audit_governance_invariants()
        self.assertTrue(passed, f"Governance invariant violations: {violations}")

    def test_dockerfile_security_specifications(self):
        """Verify Dockerfile uses multi-stage build, non-root user, and safe defaults."""
        dockerfile_path = WORKSPACE_ROOT / "Dockerfile"
        self.assertTrue(dockerfile_path.exists(), "Dockerfile must exist")
        content = dockerfile_path.read_text(encoding="utf-8")

        self.assertIn("AS builder", content, "Dockerfile must use multi-stage builder")
        self.assertIn("AS runtime", content, "Dockerfile must define runtime stage")
        self.assertIn("USER appuser", content, "Container must execute as unprivileged appuser")
        self.assertIn("LIVE_TRADING=false", content, "LIVE_TRADING must default to false")
        self.assertIn("AUTO_PROMOTION=false", content, "AUTO_PROMOTION must default to false")

    def test_docker_compose_decoupled_services(self):
        """Verify docker-compose defines decoupled trading and retraining services."""
        dc_path = WORKSPACE_ROOT / "docker-compose.yml"
        self.assertTrue(dc_path.exists(), "docker-compose.yml must exist")

        with open(dc_path, "r", encoding="utf-8") as f:
            dc_data = yaml.safe_load(f)

        services = dc_data.get("services", {})
        self.assertIn("trading-bot", services, "Must define trading-bot service")
        self.assertIn("training-worker", services, "Must define training-worker service")

        # Security checks on services
        for sname in ["trading-bot", "training-worker"]:
            s_cfg = services[sname]
            sec_opts = s_cfg.get("security_opt", [])
            self.assertIn("no-new-privileges:true", sec_opts, f"{sname} must set no-new-privileges:true")

            env = s_cfg.get("environment", [])
            self.assertIn("LIVE_TRADING=false", env, f"{sname} must enforce LIVE_TRADING=false")
            self.assertIn("AUTO_PROMOTION=false", env, f"{sname} must enforce AUTO_PROMOTION=false")

        # Trading bot must have read-only access to models
        trading_vols = services["trading-bot"].get("volumes", [])
        has_ro_models = any("artifacts/models" in v and ":ro" in v for v in trading_vols)
        self.assertTrue(has_ro_models, "Trading bot must mount artifacts/models as read-only (:ro)")

    def test_ci_pipeline_workflow_integrity(self):
        """Verify .github/workflows/ci.yml defines all required audit and testing stages."""
        ci_path = WORKSPACE_ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci_path.exists(), ".github/workflows/ci.yml must exist")

        with open(ci_path, "r", encoding="utf-8") as f:
            ci_data = yaml.safe_load(f)

        jobs = ci_data.get("jobs", {})
        expected_jobs = [
            "lint-and-syntax",
            "security-hygiene-scan",
            "test-suite",
            "ast-oos-audit"
        ]
        for ej in expected_jobs:
            self.assertIn(ej, jobs, f"CI workflow missing expected job: {ej}")


if __name__ == "__main__":
    unittest.main()
