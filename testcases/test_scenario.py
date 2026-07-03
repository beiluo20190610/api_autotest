import allure
import pytest

from core.scenario_runner import ScenarioRunner
from utils.scenario_data import ScenarioDataHandler

scenario_list = ScenarioDataHandler.get_all_scenarios()

severity_map = {
    "high": allure.severity_level.CRITICAL,
    "medium": allure.severity_level.NORMAL,
    "low": allure.severity_level.MINOR,
}


def build_scenario_params(scenarios):
    params = []
    for scenario in scenarios:
        marks = [pytest.mark.scenario]
        skip_reason = ScenarioRunner.skip_reason(scenario["scenario_id"])
        if skip_reason:
            marks.append(pytest.mark.skip(reason=skip_reason))
        for source in (scenario.get("tags", ""), scenario.get("priority", "")):
            for part in str(source).split(","):
                tag = part.strip()
                if tag in ("high", "medium", "low", "smoke", "positive"):
                    marks.append(getattr(pytest.mark, tag))
        params.append(
            pytest.param(
                scenario,
                id=scenario["scenario_id"],
                marks=marks,
            )
        )
    return params


@allure.feature("业务场景多接口串联")
class TestScenarioChain:
    @pytest.mark.parametrize("scenario", build_scenario_params(scenario_list))
    def test_scenario_chain(self, api_client, scenario):
        allure.dynamic.title(scenario["scenario_name"])
        allure.dynamic.description(
            f"场景 {scenario['scenario_id']}，共 {scenario['step_count']} 步"
        )
        allure.dynamic.severity(
            severity_map.get(scenario.get("priority"), allure.severity_level.NORMAL)
        )
        tag_list = [t.strip() for t in scenario.get("tags", "").split(",") if t.strip()]
        if tag_list:
            allure.dynamic.tag(*tag_list)

        runner = ScenarioRunner(api_client, scenario_id=scenario["scenario_id"])
        runner.run(scenario["steps"], scenario_name=scenario["scenario_name"])
