#!/usr/bin/env python3
"""
Detect GPU hardware and generate docker-compose compute overrides.
Run before first `docker compose up` to auto-configure for best performance.

Detects: NVIDIA > AMD (ROCm) > Intel (XPU) > Apple Silicon (ARM64) > CPU fallback
Also detects host RAM and sets ComfyUI memory limit (GPU+lowvram needs more for LTX offload).
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


def get_host_ram_gb() -> float:
    """Return host RAM in GB. Uses psutil if available, else /proc/meminfo on Linux, else wmic on Windows."""
    try:
        import psutil
        return psutil.virtual_memory().total / (1024**3)
    except ImportError:
        pass
    if platform.system() == "Linux" and Path("/proc/meminfo").exists():
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb / (1024 * 1024)
        except (ValueError, OSError):
            pass
    if platform.system() == "Windows":
        code, out = run(["wmic", "computersystem", "get", "TotalPhysicalMemory", "/format:value"])
        if code == 0 and "TotalPhysicalMemory=" in out:
            try:
                for line in out.splitlines():
                    if line.strip().startswith("TotalPhysicalMemory="):
                        return int(line.split("=", 1)[1]) / (1024**3)
            except (ValueError, IndexError):
                pass
    return 16.0


def comfyui_memory_limit(mode: str, total_ram_gb: float) -> str:
    """
    Compute ComfyUI container memory limit from mode and host RAM.
    GPU+lowvram offloads weights to RAM (LTX needs ~12–16GB); CPU mode uses less.
    """
    max_safe = max(1, int(total_ram_gb * 0.85))  # leave 15% for host
    if mode in ("nvidia", "amd", "intel"):
        target = max(12, min(24, int(total_ram_gb * 0.6)))
    else:
        target = max(4, min(16, int(total_ram_gb * 0.5)))
    result = min(target, max_safe)
    return f"{result}G"


def run(cmd: list[str], check: bool = False) -> tuple[int, str]:
    """Run command, return (returncode, stdout+stderr)."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, ""


def detect_nvidia() -> bool:
    """Check for NVIDIA GPU via nvidia-smi."""
    code, out = run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    return code == 0 and bool(out)


def detect_amd() -> bool:
    """Check for AMD GPU (ROCm)."""
    if platform.system() != "Linux":
        return False
    # ROCm: rocm-smi or /dev/kfd
    if shutil.which("rocm-smi"):
        code, _ = run(["rocm-smi", "--showproductname"])
        return code == 0
    return Path("/dev/kfd").exists()


def detect_intel() -> bool:
    """Check for Intel GPU (XPU)."""
    if platform.system() != "Linux":
        return False
    # Intel oneAPI / level-zero
    return Path("/dev/dri").exists() and any(
        p.name.startswith("renderD") for p in Path("/dev/dri").iterdir()
    )


def detect_apple_silicon() -> bool:
    """Check for Apple Silicon (M1/M2/M3) on macOS."""
    if platform.system() != "Darwin":
        return False
    machine = platform.machine().lower()
    return machine in ("arm64", "aarch64")


def detect() -> str:
    """Return: nvidia | amd | intel | apple_silicon | cpu."""
    if detect_nvidia():
        return "nvidia"
    if detect_amd():
        return "amd"
    if detect_intel():
        return "intel"
    if detect_apple_silicon():
        return "apple_silicon"
    return "cpu"


def main() -> int:
    base = Path(os.environ.get("BASE_PATH", ".")).resolve()
    repo_root = Path(__file__).resolve().parent.parent
    if base == Path(".").resolve():
        base = repo_root

    mode = detect()
    ram_gb = get_host_ram_gb()
    env_path = base / ".env"
    env_override = None
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("COMFYUI_MEMORY_LIMIT="):
                env_override = line.split("=", 1)[1].strip().strip('"\'')
                break
    comfyui_mem = env_override if env_override else comfyui_memory_limit(mode, ram_gb)
    print(f"Detected compute: {mode}, host RAM: {ram_gb:.1f} GB, ComfyUI limit: {comfyui_mem}")

    # Compose override content per mode
    overrides = {
        "nvidia": {
            "ollama": {
                "deploy": {
                    "resources": {
                        "reservations": {
                            "devices": [
                                {"driver": "nvidia", "count": "all", "capabilities": ["gpu"]}
                            ]
                        }
                    }
                }
            },
            "comfyui": {
                "image": "yanwk/comfyui-boot:cu128-slim",
                "environment": {
                    "CLI_ARGS": "--disable-xformers --lowvram",
                    "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True,pinned_use_cuda_host_register:True",
                },
                "deploy": {
                    "resources": {
                        "reservations": {
                            "devices": [
                                {"driver": "nvidia", "count": "all", "capabilities": ["gpu"]}
                            ]
                        }
                    }
                },
            },
        },
        "amd": {
            "ollama": {
                "image": "ollama/ollama:rocm",
                "devices": ["/dev/kfd", "/dev/dri"],
                "security_opt": ["seccomp:unconfined"],
            },
            "comfyui": {
                "image": "yanwk/comfyui-boot:rocm",
                "environment": {"CLI_ARGS": "--disable-xformers --lowvram"},
                "devices": ["/dev/kfd", "/dev/dri"],
                "security_opt": ["seccomp:unconfined"],
            },
        },
        "intel": {
            "ollama": {},  # CPU; Intel XPU not in standard Ollama image
            "comfyui": {
                "image": "yanwk/comfyui-boot:xpu",
                "environment": {"CLI_ARGS": "--disable-xformers --lowvram"},
                "devices": ["/dev/dri"],
            },
        },
        "apple_silicon": {
            "ollama": {},
            "comfyui": {
                "image": "thiagoin/comfyui:arm64",
                "platform": "linux/arm64",
                "environment": {"CLI_ARGS": "--cpu"},
            },
        },
        "cpu": {
            "ollama": {},
            "comfyui": {
                "image": "yanwk/comfyui-boot:cpu",
                "environment": {"CLI_ARGS": "--cpu"},
            },
        },
    }

    # Inject ComfyUI memory limit (from host RAM) into each mode's comfyui override
    for svc_cfg in overrides.values():
        comfyui = svc_cfg.get("comfyui")
        if not comfyui:
            continue
        deploy = comfyui.setdefault("deploy", {})
        resources = deploy.setdefault("resources", {})
        resources.setdefault("limits", {})["memory"] = comfyui_mem

    def format_override(cfg: dict) -> str:
        lines = ["# Auto-generated by scripts/detect_hardware.py", "services:"]
        for svc, opts in cfg.items():
            if not opts:
                continue
            lines.append(f"  {svc}:")
            for k, v in opts.items():
                if v is None:
                    continue
                if k == "image":
                    lines.append(f"    image: {v}")
                elif k == "platform":
                    lines.append(f"    platform: {v}")
                elif k == "environment":
                    lines.append("    environment:")
                    for ek, ev in v.items():
                        lines.append(f"      - {ek}={ev}")
                elif k == "deploy":
                    lines.append("    deploy:")
                    lines.append("      resources:")
                    res = v.get("resources", {})
                    if "limits" in res:
                        lines.append("        limits:")
                        for lk, lv in res["limits"].items():
                            lines.append(f"          {lk}: {lv}")
                    if "reservations" in res and "devices" in res["reservations"]:
                        lines.append("        reservations:")
                        lines.append("          devices:")
                        for d in res["reservations"]["devices"]:
                            lines.append("            - driver: " + d["driver"])
                            lines.append("              count: " + str(d["count"]))
                            lines.append("              capabilities: " + str(d["capabilities"]))
                elif k == "devices":
                    lines.append("    devices:")
                    for d in v:
                        lines.append(f"      - {d}")
                elif k == "security_opt":
                    lines.append("    security_opt:")
                    for s in v:
                        lines.append(f"      - {s}")
        return "\n".join(lines)

    cfg = overrides[mode]
    override_content = format_override(cfg)
    override_path = base / "overrides" / "compute.yml"
    override_path.parent.mkdir(exist_ok=True)

    override_path.write_text(override_content, encoding="utf-8")
    print(f"Wrote {override_path}")

    # Append COMPOSE_FILE to .env so docker compose up uses the compute override
    # Windows uses ; as path separator, Linux/Mac use :
    sep = ";" if platform.system() == "Windows" else ":"
    env_path = base / ".env"
    compute_vars = f"""
# Auto-generated by scripts/detect_hardware.py
COMPUTE_MODE={mode}
COMPOSE_FILE=docker-compose.yml{sep}overrides/compute.yml
"""
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        new_compose_file = f"COMPOSE_FILE=docker-compose.yml{sep}overrides/compute.yml"
        if re.search(r"COMPOSE_FILE=", content):
            content = re.sub(r"COMPOSE_FILE=.*", new_compose_file, content)
        else:
            content = content.rstrip() + "\n" + new_compose_file + "\n"
        if re.search(r"COMPUTE_MODE=", content):
            content = re.sub(r"COMPUTE_MODE=.*", f"COMPUTE_MODE={mode}", content)
        else:
            content = content.rstrip() + f"\nCOMPUTE_MODE={mode}\n"
        env_path.write_text(content, encoding="utf-8")
        print(f"Updated {env_path} (COMPOSE_FILE, COMPUTE_MODE)")
    else:
        env_compute = base / ".env.compute"
        env_compute.write_text(f"# Auto-generated\nCOMPUTE_MODE={mode}\nCOMPOSE_FILE=docker-compose.yml{sep}overrides/compute.yml\n", encoding="utf-8")
        print(f"Wrote {env_compute} (create .env from .env.example, then re-run detect)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
