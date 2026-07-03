"""CRMEB SystemConfigFormVo 表单模板 content 构造。"""
from __future__ import annotations

import json


def default_form_temp_content() -> str:
    """符合 SystemConfigFormVo 的 content JSON（含 __vModel__）。"""
    field = json.dumps(
        {
            "__config__": {"label": "字段1", "tag": "el-input", "required": False},
            "__vModel__": "field1",
        },
        ensure_ascii=False,
    )
    payload = {
        "formRef": "elForm",
        "formModel": "formData",
        "size": "medium",
        "labelPosition": "right",
        "labelWidth": 100,
        "formRules": "rules",
        "gutter": 15,
        "disabled": False,
        "span": 24,
        "formBtns": True,
        "fields": [field],
    }
    return json.dumps(payload, ensure_ascii=False)
