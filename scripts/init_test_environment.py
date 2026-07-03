#!/usr/bin/env python3
"""CLI：完整初始化测试环境（seed + 全局上下文 + 共享 ApiClient）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.environment_init import initialize_test_environment

if __name__ == "__main__":
    initialize_test_environment(flush_redis=False)
    print("test environment initialized")
