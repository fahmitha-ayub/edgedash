"""
run_cycle.py — entry point.

Usage:
    python run_cycle.py

Loads config from config.yaml at the repo root, then runs one full cycle.
"""
from edgedash.config import load_config
from edgedash.orchestrator import run_cycle

if __name__ == "__main__":
    config = load_config()
    run_cycle(config)
