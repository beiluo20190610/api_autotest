"""清理 Allure 历史结果目录。"""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRS = ("allure-results", "allure-report")


def clean_allure(*dirs: str) -> None:
    targets = dirs or DEFAULT_DIRS
    for name in targets:
        path = ROOT / name
        if path.exists():
            shutil.rmtree(path)
            print(f"已删除: {path}")
        else:
            print(f"跳过（不存在）: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理 Allure 报告目录")
    parser.add_argument(
        "dirs",
        nargs="*",
        help="要清理的目录名，默认 allure-results allure-report",
    )
    args = parser.parse_args()
    clean_allure(*args.dirs)
