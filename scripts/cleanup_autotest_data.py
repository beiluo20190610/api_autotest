#!/usr/bin/env python3
"""CLI：清理自动化测试产生的 MySQL 数据。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.test_data_cleanup import cleanup_summary, run_cleanup


def main() -> None:
    print("开始清理自动化测试数据 ...")
    results = run_cleanup()
    print("\n" + cleanup_summary(results))


if __name__ == "__main__":
    main()
