import os
from typing import Any, Dict, List

import pandas as pd

from utils.common import get_project_root


class DataHandler:
    """CSV 用例加载与按 module 过滤。"""

    @staticmethod
    def load_all_cases(csv_path: str = None) -> pd.DataFrame:
        if csv_path is None:
            csv_path = os.path.join(get_project_root(), "data", "test_cases.csv")
        df = pd.read_csv(csv_path, dtype=str)
        return df.fillna("")

    @staticmethod
    def get_case_by_module(module_name: str) -> List[Dict[str, Any]]:
        df = DataHandler.load_all_cases()
        filter_df = df[df["module"] == module_name]
        return filter_df.to_dict("records")
