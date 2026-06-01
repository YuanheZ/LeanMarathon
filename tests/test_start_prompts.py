from __future__ import annotations

import importlib.util
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from leanmarathon import cli


ROOT = Path(__file__).resolve().parents[1]
PWL_PATH = ROOT / ".scripts" / "per_node_worker_loop.py"
SPEC = importlib.util.spec_from_file_location("per_node_worker_loop_prompt_test", PWL_PATH)
assert SPEC is not None and SPEC.loader is not None
pwl = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pwl
SPEC.loader.exec_module(pwl)


class StartPromptTests(unittest.TestCase):
    def test_write_project_config_omits_prompt_section_when_no_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli.write_project_config(
                root,
                owner="Owner",
                repo="Repo",
                lean_file="LeanMarathon/Main.lean",
                problem_file="inputs/problem.txt",
                proof_file="inputs/proof",
                auto_resource="cpu",
                auto_cpus=1,
                auto_time="48:00:00",
                stage1_orchestrator_resource="cpu",
                stage1_orchestrator_cpus=1,
                stage1_orchestrator_time="48:00:00",
                orchestrator_resource="gpu",
                orchestrator_cpus=42,
                orchestrator_time="48:00:00",
                agent_resource="gpu",
                agent_cpus=42,
                agent_time="4:00:00",
                batch_size=16,
                max_rounds=100,
                max_review_rounds=20,
                lean_project_root=root,
                numeric_tools=[],
                agent_prompts={},
            )
            config = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
            self.assertNotIn("agents", config)

    def test_script_command_forwards_configured_stage1_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli.write_project_config(
                root,
                owner="Owner",
                repo="Repo",
                lean_file="LeanMarathon/Main.lean",
                problem_file="inputs/problem.txt",
                proof_file="inputs/proof",
                auto_resource="cpu",
                auto_cpus=1,
                auto_time="48:00:00",
                stage1_orchestrator_resource="cpu",
                stage1_orchestrator_cpus=1,
                stage1_orchestrator_time="48:00:00",
                orchestrator_resource="gpu",
                orchestrator_cpus=42,
                orchestrator_time="48:00:00",
                agent_resource="gpu",
                agent_cpus=42,
                agent_time="4:00:00",
                batch_size=16,
                max_rounds=100,
                max_review_rounds=20,
                lean_project_root=root,
                numeric_tools=[],
                agent_prompts={
                    "blueprinter": "Start blueprint",
                    "target_reviewer": "Begin the work.",
                    "refiner": "Repair\nnow",
                    "worker": "Worker prompt",
                },
            )
            old_target_state_root = cli.target_state_root
            try:
                cli.target_state_root = lambda _owner, _repo: root
                command, _env = cli.script_command_from_config(
                    owner="Owner",
                    repo="Repo",
                    script_name="stage1_blueprint_loop.py",
                    extra_args=[],
                    submit=True,
                )
            finally:
                cli.target_state_root = old_target_state_root
            self.assertIn("--blueprinter-prompt", command)
            self.assertIn("Start blueprint", command)
            self.assertIn("--target-reviewer-prompt", command)
            self.assertIn("Begin the work.", command)
            self.assertIn("--refiner-prompt", command)
            self.assertIn("Repair\nnow", command)
            self.assertNotIn("--worker-prompt", command)

    def test_script_command_forwards_configured_stage2_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli.write_project_config(
                root,
                owner="Owner",
                repo="Repo",
                lean_file="LeanMarathon/Main.lean",
                problem_file="inputs/problem.txt",
                proof_file="inputs/proof",
                auto_resource="cpu",
                auto_cpus=1,
                auto_time="48:00:00",
                stage1_orchestrator_resource="cpu",
                stage1_orchestrator_cpus=1,
                stage1_orchestrator_time="48:00:00",
                orchestrator_resource="gpu",
                orchestrator_cpus=42,
                orchestrator_time="48:00:00",
                agent_resource="gpu",
                agent_cpus=42,
                agent_time="4:00:00",
                batch_size=16,
                max_rounds=100,
                max_review_rounds=20,
                lean_project_root=root,
                numeric_tools=[],
                agent_prompts={"refiner": "Repair", "worker": "Prove"},
            )
            old_target_state_root = cli.target_state_root
            try:
                cli.target_state_root = lambda _owner, _repo: root
                command, _env = cli.script_command_from_config(
                    owner="Owner",
                    repo="Repo",
                    script_name="per_node_worker_loop.py",
                    extra_args=[],
                    submit=True,
                )
            finally:
                cli.target_state_root = old_target_state_root
            self.assertIn("--worker-prompt", command)
            self.assertIn("Prove", command)
            self.assertIn("--refiner-prompt", command)
            self.assertIn("Repair", command)
            self.assertNotIn("--blueprinter-prompt", command)
            self.assertNotIn("--target-reviewer-prompt", command)

    def test_materialize_start_prompt_skips_agent_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(pwl.materialize_start_prompt(root, None))
            self.assertIsNone(
                pwl.materialize_start_prompt(
                    root,
                    "Begin the work.",
                    default_prompt="Begin the work.",
                )
            )
            prompt_file = pwl.materialize_start_prompt(root, "Line 1\nLine 2")
            assert prompt_file is not None
            self.assertEqual("Line 1\nLine 2", prompt_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
