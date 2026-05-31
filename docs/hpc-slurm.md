# Slurm Configuration

LeanMarathon uses Slurm for the orchestrator and every agent job.

LeanMarathon stores resource shape settings in the local runtime config:
`.leanmarathon-targets/<owner>/<repo>/config.toml`.

```toml
[hpc.auto]
resource = "cpu"
cpus = 1
time = "48:00:00"

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

Cluster-specific paths and accounts are normally supplied by
`.leanmarathon.local.toml`:

```toml
[paths]
venv_bin = "/absolute/path/to/LeanMarathon/.venv/bin"
node_bin = "/absolute/path/to/node/bin"
elan_bin = "/absolute/path/to/elan/bin"

[lean]
project_root = "/absolute/path/to/lean-project"

[slurm]
cpu_account = ""
gpu_account = ""
gpu_partition = "gpu"
gpu_gres = "gpu:lovelace_l40:1"
mem_per_cpu = 3850
```

Environment variables with matching `LEANMARATHON_*` names override the local
config.

If your cluster does not require `#SBATCH --account`, leave the account fields
empty.
