"""Arithmetic for answers: the model asks for a calculation instead of doing it in its head.

An expression is parsed with ``ast`` and evaluated by an allow-list walker (numbers, + - * / // % **, parentheses, whitelisted functions and constants) --
never ``eval``. Size, depth and exponent limits keep a hostile or careless expression from costing more than a few milliseconds.
The tool result is part of the run's evidence, so a number the answer takes from it counts as "from tool data" in the grounding check.
"""
from __future__ import annotations

import ast
import math
import operator
import statistics
from typing import Any, Callable

MAX_CHARS = 300
MAX_NODES = 120
MAX_EXPONENT = 400
MAX_ARGS = 200

_BINARY: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _mean(*xs: float) -> float:
    return statistics.fmean(xs)


# name -> (function, description shown to the model). Wi-Fi helpers first: dB arithmetic is where hand calculation goes wrong.
FUNCTIONS: dict[str, tuple[Callable[..., float], str]] = {
    "dbm_to_mw": (lambda x: 10 ** (x / 10), "dBm → mW"),
    "mw_to_dbm": (lambda x: 10 * math.log10(x), "mW → dBm"),
    "db_to_ratio": (lambda x: 10 ** (x / 10), "dB → 倍數"),
    "ratio_to_db": (lambda x: 10 * math.log10(x), "倍數 → dB"),
    "mbps_to_mbyte": (lambda x: x / 8, "Mbps → MB/s"),
    "mbyte_to_mbps": (lambda x: x * 8, "MB/s → Mbps"),
    "pct": (lambda part, whole: 100 * part / whole, "pct(部分, 整體)＝百分比"),
    "change_pct": (lambda old, new: 100 * (new - old) / old, "change_pct(舊, 新)＝變化百分比"),
    "abs": (abs, "絕對值"), "round": (round, "round(x, 位數)"), "sqrt": (math.sqrt, "平方根"),
    "log10": (math.log10, "以 10 為底的對數"), "ln": (math.log, "自然對數"), "exp": (math.exp, "e 的次方"),
    "min": (min, "最小值"), "max": (max, "最大值"), "sum": (lambda *xs: math.fsum(xs), "加總"),
    "mean": (_mean, "平均"), "median": (lambda *xs: statistics.median(xs), "中位數"),
}
CONSTANTS = {"pi": math.pi, "e": math.e}


class CalculationError(ValueError):
    pass


def _eval(node: ast.AST, depth: int = 0) -> float:
    if depth > 30:
        raise CalculationError("運算式巢狀太深")
    if isinstance(node, ast.Expression):
        return _eval(node.body, depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalculationError("只能使用數字")
        return node.value
    if isinstance(node, ast.Name):
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise CalculationError(f"未知的名稱：{node.id}")
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, depth + 1))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left, depth + 1), _eval(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and (abs(right) > MAX_EXPONENT or abs(left) > 1e6 and abs(right) > 50):
            raise CalculationError("次方過大")
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
        if len(node.args) > MAX_ARGS:
            raise CalculationError("引數過多")
        return FUNCTIONS[node.func.id][0](*[_eval(a, depth + 1) for a in node.args])
    raise CalculationError("不支援的運算式")


def calculate(expression: str, digits: int = 6) -> dict[str, Any]:
    """{"expression", "result"} or {"error"}; never raises."""
    text = str(expression or "").strip()
    if not text:
        return {"error": "請提供運算式"}
    if len(text) > MAX_CHARS:
        return {"error": f"運算式超過 {MAX_CHARS} 字"}
    try:
        tree = ast.parse(text.replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", ", "), mode="eval")
        if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
            raise CalculationError("運算式太複雜")
        value = _eval(tree)
        if isinstance(value, complex) or value != value or value in (math.inf, -math.inf):
            raise CalculationError("結果不是有限的實數")
    except CalculationError as exc:
        return {"error": str(exc), "expression": text}
    except SyntaxError:
        return {"error": "運算式語法錯誤", "expression": text}
    except (ZeroDivisionError, ValueError, OverflowError, TypeError) as exc:
        return {"error": f"無法計算：{type(exc).__name__}", "expression": text}
    digits = max(0, min(int(digits), 12))
    shown = int(value) if float(value).is_integer() and abs(value) < 1e15 else round(float(value), digits)
    return {"expression": text, "result": shown}


CALC_TOOL = {"type": "function", "function": {
    "name": "calculate",
    "description": "計算數值：加減乘除、次方、百分比、單位換算（dBm↔mW、dB↔倍數、Mbps↔MB/s）、平均與加總。回答中任何自己算出的數字都要先用這個工具算，不要心算。"
                   "可用函式：" + "；".join(f"{name}（{desc}）" for name, (_, desc) in FUNCTIONS.items()) + "。常數：pi、e。例：dbm_to_mw(20)、pct(1201, 2402)、mean(332.5, 444.05)。",
    "parameters": {"type": "object", "properties": {
        "expression": {"type": "string", "description": "運算式，例如 (2402 * 0.5) 或 change_pct(332.5, 444.05)；只能用數字、運算符號與上述函式"},
        "digits": {"type": "integer", "minimum": 0, "maximum": 12, "description": "小數位數，預設 6"}}, "required": ["expression"]}}}

CALC_PROMPT = """
計算（本次已啟用計算工具）：回答中的百分比、差值、平均、單位換算與其他自己推算的數字，一律先用 calculate 計算；算式用到的數字必須來自工具回傳的文件內容，並在句末註明該數字的來源 [S#]。計算結果要寫出算式（例如「1201 ÷ 2402 = 50%」）。"""
