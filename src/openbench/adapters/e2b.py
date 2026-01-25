"""
E2B sandbox adapter for OpenBench.

Allows running custom Python code in isolated sandboxed environments.
"""

import json
from typing import Any, Optional, List
from openbench.core import FrameworkAdapter


class E2BAdapter(FrameworkAdapter):
    """
    Adapter for running custom code in E2B sandboxes.

    Perfect for:
    - User-provided custom transforms
    - Untrusted code execution
    - Isolated environments with specific dependencies

    Example:
        ```python
        from openbench.adapters.e2b import E2BAdapter
        from openbench import Workflow
        from openbench.data import CSVSource
        from openbench.output import PDFGenerator

        # Custom data transformation in sandbox
        custom_transform = E2BAdapter(
            code='''
import pandas as pd

# input_data is automatically available
df = pd.DataFrame(input_data)

# Perform analysis
summary = df.describe().to_dict()
top_items = df.nlargest(10, 'value').to_dict('records')

# Must assign to 'result'
result = {
    "summary": summary,
    "top_items": top_items
}
''',
            packages=["pandas"]
        )

        # Use in workflow
        workflow = Workflow(
            name="custom-analysis",
            chain=(
                CSVSource("data.csv")
                | custom_transform  # Runs in isolated sandbox
                | PDFGenerator()
            )
        )

        result = workflow.run({})
        ```
    """

    @property
    def framework_name(self) -> str:
        return "e2b"

    def __init__(
        self,
        code: str,
        template: str = "python-data-science",
        packages: Optional[List[str]] = None
    ):
        """
        Initialize the E2B adapter.

        Args:
            code: Python code to execute (must assign output to 'result' variable)
            template: E2B template to use (default: "python-data-science")
            packages: List of pip packages to install
        """
        self.code = code
        self.template = template
        self.packages = packages or []

    def invoke(self, input: Any, config: Optional[Any] = None) -> Any:
        """
        Execute code in E2B sandbox.

        Args:
            input: Input data (will be available as 'input_data' in the code)
            config: Optional configuration

        Returns:
            Value of 'result' variable from executed code
        """
        try:
            from e2b import Sandbox
        except ImportError:
            raise ImportError(
                "E2B is not installed. Install it with: pip install e2b"
            )

        with Sandbox(template=self.template) as sandbox:
            # Install additional packages if needed
            for pkg in self.packages:
                sandbox.process.start(f"pip install {pkg}")

            # Inject input and run user code
            sandbox.filesystem.write("/tmp/input.json", json.dumps(input))

            result = sandbox.process.start(
                cmd="python",
                args=["-c", f"""
import json
with open('/tmp/input.json') as f:
    input_data = json.load(f)

# User's code
{self.code}

# Output must be assigned to 'result'
print(json.dumps(result))
"""]
            )

            return json.loads(result.stdout)
