from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("suffix", [".whl", ".tar.gz"])
def test_built_distribution_exposes_public_api(tmp_path: Path, suffix: str) -> None:
    output = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(output)],
        check=True,
        cwd=Path(__file__).parents[1],
    )
    artifact = next(output.glob(f"*{suffix}"))
    environment = tmp_path / suffix.removeprefix(".").replace(".", "-")
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = environment / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", str(artifact)],
        check=True,
    )
    subprocess.run(
        [
            str(python),
            "-c",
            "from agent_squad_aerospike import AerospikeChatStorage, AerospikeConfig, "
            "AgentSquadAerospikeError",
        ],
        check=True,
    )
