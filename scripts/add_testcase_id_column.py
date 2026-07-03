"""修复并填充 scenario_test_cases.csv 的 testcase_id 列。"""
import csv
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "data" / "scenario_test_cases.csv"

with path.open("r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    raw_fields = reader.fieldnames or []
    fieldnames = [name.lstrip("\ufeff").strip() for name in raw_fields]
    rows: list[dict] = []
    for raw in reader:
        row = {}
        for old_key, new_key in zip(raw_fields, fieldnames):
            row[new_key] = raw.get(old_key, "")
        rows.append(row)

if "scenario_id" not in fieldnames:
    raise SystemExit("缺少 scenario_id 列")

scenario_ids = sorted({row["scenario_id"] for row in rows if row.get("scenario_id")})
scenario_to_no = {sid: str(i) for i, sid in enumerate(scenario_ids, start=1)}

for row in rows:
    row["testcase_id"] = scenario_to_no.get(row.get("scenario_id", ""), "")

# 列顺序：scenario_id 后接 testcase_id
ordered = [c for c in fieldnames if c not in ("testcase_id",)]
if "scenario_id" in ordered:
    idx = ordered.index("scenario_id") + 1
    ordered.insert(idx, "testcase_id")
else:
    ordered.insert(0, "testcase_id")

with path.open("w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=ordered, lineterminator="\n")
    writer.writeheader()
    writer.writerows({k: row.get(k, "") for k in ordered} for row in rows)

print(f"testcase_id 已填充：{len(scenario_ids)} 个场景，{len(rows)} 行")
