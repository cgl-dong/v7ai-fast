"""Calculator tool — Day2 example tool (from AI Agent 30-day notes)."""
import logging
from app.services.tools.base import BaseTool

logger = logging.getLogger(__name__)


class CalculatorTool(BaseTool):
    """数学计算器，支持加减乘除。"""

    name = "calculator"
    description = (
        "数学计算器，用于加减乘除四则运算。"
        "仅在用户提出数学计算（如 123+456、2*8、10/3）时使用，"
        "op 仅支持 +、-、*、/ 四种符号。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "num1": {"type": "number", "description": "第一个运算数字"},
            "num2": {"type": "number", "description": "第二个运算数字"},
            "op": {"type": "string", "description": "运算符号，仅支持 +、-、*、/"},
        },
        "required": ["num1", "num2", "op"],
    }

    async def execute(self, num1: float, num2: float, op: str) -> str:
        try:
            if op == "+":
                res = num1 + num2
            elif op == "-":
                res = num1 - num2
            elif op == "*":
                res = num1 * num2
            elif op == "/":
                if num2 == 0:
                    return "计算失败：除数不能为0"
                res = num1 / num2
            else:
                return f"计算失败：不支持的运算符 {op}，仅支持 + - * /"
            # 整数结果去掉 .0 后缀，更友好
            if isinstance(res, float) and res.is_integer():
                res = int(res)
            return f"计算结果：{num1} {op} {num2} = {res}"
        except Exception as e:
            return f"工具执行异常：{str(e)}"


calculator_tool = CalculatorTool()
