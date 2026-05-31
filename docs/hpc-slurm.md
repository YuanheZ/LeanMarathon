# Slurm Configuration

LeanMarathon uses Slurm for the orchestrator and every agent job.

LeanMarathon stores resource shape settings in the local runtime config:
`.leanmarathon-targets/<owner>/<repo>/config.toml`.

```toml
[hpc.orchestrator]
resource = "gpu"
cpus = 42
time = "48:00:00"

[hpc.agent]
resource = "gpu"
cpus = 42
time = "4:00:00"
batch_size = 16
```

Cluster-specific paths and accounts are supplied by environment variables:

- `LEANMARATHON_VENV_BIN`: Python virtual environment `bin` directory.
- `LEANMARATHON_NODE_BIN`: Node.js `bin` directory containing Codex and Node MCP tools.
- `LEANMARATHON_ELAN_BIN`: Lean/Elan `bin` directory.
- `LEANMARATHON_SLURM_CPU_ACCOUNT`: optional CPU Slurm account.
- `LEANMARATHON_SLURM_GPU_ACCOUNT`: optional GPU Slurm account.
- `LEANMARATHON_SLURM_GPU_PARTITION`: GPU partition, default `gpu`.
- `LEANMARATHON_SLURM_GPU_GRES`: GPU GRES request, default `gpu:lovelace_l40:1`.
- `LEANMARATHON_SLURM_MEM_PER_CPU`: memory per CPU in MB, default `3850`.

If your cluster does not require `#SBATCH --account`, leave the account
variables unset.
