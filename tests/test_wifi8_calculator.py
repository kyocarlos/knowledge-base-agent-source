import json

import pytest

from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools, run_agent
from src.wifi8.calculator import CALC_PROMPT, FUNCTIONS, calculate
from tests.test_wifi8_agent import call, reply
from tests.test_wifi8_search import engine  # noqa: F401  (fixture)


@pytest.mark.parametrize("expression, expected", [
    ("1201 / 2402 * 100", 50), ("2402 * 0.5", 1201), ("dbm_to_mw(20)", 100), ("mw_to_dbm(100)", 20), ("db_to_ratio(3)", 1.995262),
    ("pct(1201, 2402)", 50), ("change_pct(332.5, 444.05)", 33.548872), ("mean(1, 2, 3, 4)", 2.5), ("median(5, 1, 3)", 3), ("sum(0.1, 0.2)", 0.3),
    ("mbps_to_mbyte(800)", 100), ("(2 + 3) * 4 ^ 2", 80), ("max(3, 9, 4) - min(3, 9, 4)", 6), ("-5 + abs(-8)", 3), ("2 × 3 ÷ 4", 1.5),
])
def test_arithmetic_and_wifi_conversions(expression, expected):
    assert calculate(expression) == {"expression": expression, "result": expected}


def test_digits_control_rounding():
    assert calculate("1 / 3", digits=3)["result"] == 0.333 and calculate("1 / 3", digits=99)["result"] == round(1 / 3, 12)


@pytest.mark.parametrize("expression", [
    "__import__('os').system('id')", "open('/etc/passwd')", "().__class__", "[1, 2][0]", "'a' * 5", "x + 1", "lambda: 1", "1 if True else 2",
    "2 ** 100000", "9999999 ** 99", "1 / 0", "sqrt(-1)", "log10(0)", "(1 +", "", "   ", "1" * 301, "max()", "round('a')", "-" * 40 + "1",
])
def test_anything_else_is_an_error_not_an_exception(expression):
    out = calculate(expression)
    assert "error" in out and "result" not in out


def test_every_function_is_described_to_the_model():
    from src.wifi8.calculator import CALC_TOOL
    description = CALC_TOOL["function"]["description"]
    assert all(name in description for name in FUNCTIONS)


def make(search, calc):
    settings = AgentSettings(calc=calc, grounding=False)
    return WifiTools(search, settings, CitationRegistry()), settings


def test_tool_and_prompt_exist_only_when_enabled(engine):  # noqa: F811
    search, *_ = engine
    for calc in (False, True):
        tools, settings = make(search, calc)
        seen = {}

        def llm(*, messages, tools, tool_choice):
            seen["names"] = [t["function"]["name"] for t in tools]
            seen["system"] = messages[0]["content"]
            return reply("ok")
        run_agent("q", llm=llm, tools=tools, settings=settings)
        assert ("calculate" in seen["names"]) is calc and (CALC_PROMPT in seen["system"]) is calc
        assert (tools.call("calculate", {"expression": "1+1"}).get("result") == 2) is calc


def test_a_calculation_result_is_evidence_for_the_numbers_in_the_answer(engine):  # noqa: F811
    search, *_ = engine
    tools, settings = make(search, True)

    def llm(*, messages, tools, tool_choice):
        if not any(m.get("role") == "tool" for m in messages):
            return reply(calls=[call("calculate", {"expression": "1201 / 2402 * 100"})])
        return reply("門檻 1201 是理論速率 2402 的 50%。")
    out = run_agent("q", llm=llm, tools=tools, settings=settings)
    assert out["trace"][0]["tool"] == "calculate" and any('"result": 50' in e for e in tools.evidence)
    assert tools.call("calculate", {"expression": "1/0"})["error"]
    assert "參數錯誤" in tools.call("calculate", {"wrong": 1})["error"]
