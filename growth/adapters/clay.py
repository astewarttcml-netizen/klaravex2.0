from growth.adapters import not_wired, poc_sandbox
from growth.poc import is_poc_mode


def enrich(*_args, **_kwargs) -> dict:
    if is_poc_mode():
        return poc_sandbox(
            "clay",
            "enrich",
            {"prospects": 3, "domains": ["fixture-co.example", "demo-msp.example"]},
        )
    return not_wired("clay")
