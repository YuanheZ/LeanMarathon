# Slurm Configuration

LeanMarathon uses Slurm for the optional parent `auto` job, both stage
orchestrators, and every agent job.

Resource shape settings are stored per target in:

```text
.leanmarathon-targets/<owner>/<repo>/config.toml
```

Generated target config sections:

```toml
[hpc.auto]
resource = "cpu"
cpus = 1
time = "48:00:00"

[hpc.stage1_orchestrator]
resource = "cpu"
cpus = 1
time = "48:00:00"

[hpc.stage2_orchestrator]
resource = "gpu"
cpus = 42
time = "48:00:00"

[hpc.agent]
resource = "gpu"
cpus = 42
time = "4:00:00"
batch_size = 16
```

Cluster-specific paths and accounts are supplied by `.leanmarathon.local.toml`:

```toml
[paths]
venv_bin = "/absolute/path/to/LeanMarathon/.venv/bin"
node_bin = "/absolute/path/to/node/bin"
elan_bin = "/absolute/path/to/elan/bin"
# Optional full PATH overrides:
# agent_path = "/absolute/path/to/venv/bin:/absolute/path/to/node/bin:/absolute/path/to/elan/bin:/usr/local/bin:/usr/bin:/bin"
# orchestrator_path = "/absolute/path/to/venv/bin:/absolute/path/to/node/bin:/absolute/path/to/elan/bin:/usr/local/bin:/usr/bin:/bin"

[lean]
project_root = "/absolute/path/to/lean-project"

[slurm]
cpu_account = ""
gpu_account = ""
gpu_partition = "gpu"
gpu_gres = "gpu:lovelace_l40:1"
mem_per_cpu = 3850
```

Resource mode `cpu` adds no GPU directives. Resource mode `gpu` adds:

```text
#SBATCH --partition=<slurm.gpu_partition>
#SBATCH --gres=<slurm.gpu_gres>
```

If your cluster does not require `#SBATCH --account`, leave the account fields
empty. Environment variables with matching `LEANMARATHON_*` names override the
local config.

Agent jobs export thread counts from `hpc.agent.cpus`:

```text
VERIFY_BLUEPRINT_LEAN_THREADS
LEAN_LSP_THREADS
DAG_TRACKER_LEAN_THREADS
```

Stage 2 DAG extraction uses the Stage 2 orchestrator CPU count through
`VERIFY_BLUEPRINT_LEAN_THREADS`.
