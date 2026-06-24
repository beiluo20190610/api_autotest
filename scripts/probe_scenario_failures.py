#!/usr/bin/env python3
"""批量探测场景失败原因。"""
import traceback

from core.api_client import ApiClient
from core.scenario_runner import ScenarioRunner
from utils.scenario_data import ScenarioDataHandler

scenarios = ScenarioDataHandler.get_all_scenarios()
results = {"pass": [], "fail": []}

for sc in scenarios:
    if sc["scenario_id"] in ScenarioRunner.SKIP_SCENARIO_IDS:
        continue
    client = ApiClient()
    runner = ScenarioRunner(client)
    try:
        runner.run(sc["steps"])
        results["pass"].append(sc["scenario_id"])
    except Exception as exc:
        msg = str(exc)
        if "响应:" in msg:
            msg = msg.split("响应:")[-1][:200]
        else:
            msg = msg[:200]
        results["fail"].append((sc["scenario_id"], msg))

print(f"PASS {len(results['pass'])}")
for x in results["pass"]:
    print("  OK", x)
print(f"\nFAIL {len(results['fail'])}")
for sid, msg in results["fail"]:
    print(f"  {sid}: {msg}")
