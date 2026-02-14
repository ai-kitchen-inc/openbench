"""
Mock agent for demo purposes -- no API key needed.

Returns different content types based on keyword detection:
  - "chart" / "sales"    -> bar chart
  - "pie"                -> pie chart
  - "line" / "trend"     -> line chart
  - "form" / "register"  -> form fields
  - "file" / "download"  -> file card
  - anything else        -> markdown text
"""

from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult


class MockAgent(Agent):
    """Deterministic mock agent that returns rich content based on keywords."""

    @property
    def agent_type(self) -> str:
        return "mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        goal = (context.goal or "").lower()
        content = self._route(goal, context.goal or "")
        return ExecutionResult(
            output=content,
            status="success",
            metadata={"model": "mock-agent"},
            tokens_used=0,
            cost=0.0,
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0

    def _route(self, lower: str, original: str):
        if "pie" in lower:
            return self._pie_chart()
        if "line" in lower or "trend" in lower:
            return self._line_chart()
        if "chart" in lower or "sales" in lower:
            return self._bar_chart()
        if "form" in lower or "register" in lower:
            return self._form()
        if "file" in lower or "download" in lower:
            return self._file()
        return self._text(original)

    # ── Content generators ──

    @staticmethod
    def _bar_chart():
        return {
            "type": "bar",
            "title": "Q4 Sales by Region",
            "data": [
                {"label": "North America", "value": 4200},
                {"label": "Europe", "value": 3100},
                {"label": "Asia Pacific", "value": 2800},
                {"label": "Latin America", "value": 1500},
            ],
        }

    @staticmethod
    def _pie_chart():
        return {
            "type": "pie",
            "title": "Market Share",
            "data": [
                {"label": "Product A", "value": 45},
                {"label": "Product B", "value": 30},
                {"label": "Product C", "value": 15},
                {"label": "Others", "value": 10},
            ],
        }

    @staticmethod
    def _line_chart():
        return {
            "type": "line",
            "title": "Monthly Revenue",
            "data": [
                {"label": "Jan", "value": 12000},
                {"label": "Feb", "value": 15000},
                {"label": "Mar", "value": 13500},
                {"label": "Apr", "value": 18000},
                {"label": "May", "value": 21000},
                {"label": "Jun", "value": 19500},
            ],
        }

    @staticmethod
    def _form():
        return {
            "fields": [
                {"name": "name", "type": "text", "label": "Full Name", "required": True},
                {"name": "email", "type": "email", "label": "Email Address", "required": True},
                {"name": "role", "type": "choice", "label": "Role", "required": False,
                 "options": ["Developer", "Designer", "Manager", "Other"]},
                {"name": "agree", "type": "checkbox", "label": "I agree to the terms",
                 "required": True},
            ],
            "submitLabel": "Register",
        }

    @staticmethod
    def _file():
        return {
            "name": "Report.pdf",
            "url": "/files/report.pdf",
            "size": 2_048_000,
            "mimeType": "application/pdf",
        }

    @staticmethod
    def _text(original: str):
        return (
            f"**Echo:** {original}\n\n"
            "I'm a mock agent running locally -- no API key required.\n\n"
            "Try these commands:\n"
            "- **chart** or **sales** -- bar chart\n"
            "- **pie** -- pie chart\n"
            "- **line** or **trend** -- line chart\n"
            "- **form** or **register** -- interactive form\n"
            "- **file** or **download** -- file card"
        )
