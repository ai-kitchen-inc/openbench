"""
OpenBench Framework Adapters Demo

Demonstrates how OpenBench serves as a universal control plane for multiple
AI agent frameworks. Shows how to wrap existing agents from LangChain, AG2,
CrewAI, and custom code (E2B) in OpenBench workflows.

Key Concepts:
- FrameworkAdapter: Minimal interface for integrating any framework
- Mixed workflows: Combine agents from different frameworks
- Zero migration: Use existing agents without rewriting
- Universal orchestration: Same workflow syntax regardless of framework
"""

from datetime import datetime

from openbench.core import (
    DataLayer,
    DataSource,
    FrameworkAdapter,
    GeneratedOutput,
    IntelligenceLayer,
    OutputGenerator,
    OutputLayer,
    RawData,
)
from openbench.workflows import Workflow

# ============================================================================
# Mock Framework Adapters (for demo without installing external frameworks)
# ============================================================================


class MockLangChainRunnable:
    """Mock LangChain Runnable for demo."""

    def invoke(self, input):
        return f"[LangChain Agent] Analyzed: {input}"


class MockAG2Agent:
    """Mock AG2 Agent for demo."""

    def __init__(self, name):
        self.name = name


class MockUserProxy:
    """Mock AG2 UserProxyAgent for demo."""

    def __init__(self):
        self._last_message = None

    def initiate_chat(self, agent, message):
        self._last_message = {"content": f"[AG2 Agent: {agent.name}] Processed: {message}"}

    def last_message(self):
        return self._last_message


class MockCrewAICrew:
    """Mock CrewAI Crew for demo."""

    def kickoff(self, inputs):
        return f"[CrewAI Crew] Completed: {inputs}"


# ============================================================================
# Demo Adapter Implementations
# ============================================================================


class DemoLangChainAdapter(FrameworkAdapter):
    """Demo LangChain adapter."""

    framework_name = "langchain"

    def __init__(self, runnable):
        self.runnable = runnable

    def invoke(self, input, config=None):
        return self.runnable.invoke(input)


class DemoAG2Adapter(FrameworkAdapter):
    """Demo AG2 adapter."""

    framework_name = "ag2"

    def __init__(self, agent):
        self.agent = agent
        self.user_proxy = MockUserProxy()

    def invoke(self, input, config=None):
        message = str(input)
        self.user_proxy.initiate_chat(self.agent, message)
        return self.user_proxy.last_message()["content"]


class DemoCrewAIAdapter(FrameworkAdapter):
    """Demo CrewAI adapter."""

    framework_name = "crewai"

    def __init__(self, crew):
        self.crew = crew

    def invoke(self, input, config=None):
        inputs = {"data": input}
        return self.crew.kickoff(inputs)


class DemoE2BAdapter(FrameworkAdapter):
    """Demo E2B sandbox adapter (simulated)."""

    framework_name = "e2b"

    def __init__(self, code):
        self.code = code

    def invoke(self, input, config=None):
        # Simulate sandboxed execution
        return f"[E2B Sandbox] Executed custom code on: {input}"


# ============================================================================
# Demo Components
# ============================================================================


class DemoDataSource(DataSource):
    """Demo data source."""

    source_type = "demo"
    source_id = "demo-source"

    def get_metadata(self):
        return {"name": "Demo Source"}

    def extract(self):
        return RawData(
            content="Sample data from demo source",
            content_type="text",
            metadata={},
            source=self,
        )

    def validate(self):
        return True


class DemoOutputGenerator(OutputGenerator):
    """Demo output generator."""

    output_format = "demo"

    def generate(self, content, template=None, **options):
        content_str = str(content)
        return GeneratedOutput(
            file_path=f"outputs/demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            format="txt",
            size_bytes=len(content_str),
            metadata={"content": content_str},
        )

    def validate(self, content):
        return True


# ============================================================================
# Demo Scenarios
# ============================================================================


def demo_1_single_framework_adapter():
    """Demo 1: Using a single framework adapter (LangChain)."""
    print("\n" + "=" * 80)
    print("DEMO 1: Single Framework Adapter (LangChain)")
    print("=" * 80)

    # Create mock LangChain agent
    mock_langchain_agent = MockLangChainRunnable()

    # Wrap in OpenBench workflow using layers
    data_layer = DataLayer(sources=DemoDataSource())
    intelligence_layer = IntelligenceLayer(agents=DemoLangChainAdapter(mock_langchain_agent))
    output_layer = OutputLayer(generators=DemoOutputGenerator())

    workflow = Workflow(name="langchain-demo", chain=data_layer | intelligence_layer | output_layer)

    print("\nWorkflow: Data → LangChain Agent → Output")
    result = workflow.run({})
    print(f"✓ Result: {result}")


def demo_2_mixed_frameworks():
    """Demo 2: Mixing multiple frameworks in one workflow."""
    print("\n" + "=" * 80)
    print("DEMO 2: Mixed Framework Workflow")
    print("=" * 80)

    # Create mock agents from different frameworks
    langchain_agent = MockLangChainRunnable()
    ag2_agent = MockAG2Agent("Analyst")
    crewai_crew = MockCrewAICrew()

    # Mix them in one workflow using sequential agent composition
    from openbench.core import Chain

    # Chain multiple framework adapters together
    multi_agent = Chain(
        [
            DemoLangChainAdapter(langchain_agent),
            DemoAG2Adapter(ag2_agent),
            DemoCrewAIAdapter(crewai_crew),
        ]
    )

    data_layer = DataLayer(sources=DemoDataSource())
    intelligence_layer = IntelligenceLayer(agents=multi_agent)
    output_layer = OutputLayer(generators=DemoOutputGenerator())

    workflow = Workflow(
        name="mixed-framework-demo",
        chain=data_layer | intelligence_layer | output_layer,
    )

    print("\nWorkflow: Data → LangChain → AG2 → CrewAI → Output")
    print("✓ Three different frameworks in one workflow!")
    result = workflow.run({})
    print(f"✓ Result: {result}")


def demo_3_custom_code_sandbox():
    """Demo 3: Running custom code in E2B sandbox."""
    print("\n" + "=" * 80)
    print("DEMO 3: Custom Code Execution (E2B Sandbox)")
    print("=" * 80)

    # Custom transformation code
    custom_code = """
import pandas as pd
# User's custom analysis
df = pd.DataFrame(input_data)
result = df.describe().to_dict()
"""

    data_layer = DataLayer(sources=DemoDataSource())
    intelligence_layer = IntelligenceLayer(agents=DemoE2BAdapter(custom_code))
    output_layer = OutputLayer(generators=DemoOutputGenerator())

    workflow = Workflow(
        name="custom-code-demo", chain=data_layer | intelligence_layer | output_layer
    )

    print("\nWorkflow: Data → E2B Sandbox (custom code) → Output")
    print("✓ Run untrusted user code safely in isolated environment")
    result = workflow.run({})
    print(f"✓ Result: {result}")


def demo_4_adapter_interface():
    """Demo 4: Show the minimal adapter interface."""
    print("\n" + "=" * 80)
    print("DEMO 4: Creating Your Own Adapter")
    print("=" * 80)

    print("\nThe FrameworkAdapter interface is minimal:")
    print("""
class FrameworkAdapter(ABC):
    @property
    @abstractmethod
    def framework_name(self) -> str:
        \"\"\"Name of the framework.\"\"\"
        pass

    @abstractmethod
    def invoke(self, input, config=None):
        \"\"\"Execute the wrapped agent.\"\"\"
        pass
    """)

    print("That's it! Just 2 methods and your framework works with OpenBench.")

    # Create a simple custom adapter
    class MyCustomAdapter(FrameworkAdapter):
        framework_name = "my-custom-framework"

        def __init__(self, agent):
            self.agent = agent

        def invoke(self, input, config=None):
            return f"[{self.framework_name}] {self.agent}: {input}"

    adapter = MyCustomAdapter("CustomAgent")
    result = adapter.invoke("test data")
    print(f"\n✓ Custom adapter result: {result}")


# ============================================================================
# Main Execution
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print(" " * 20 + "OpenBench Framework Adapters Demo")
    print("=" * 80)
    print("\nOpenBench: The Universal Control Plane for Agentic AI")
    print("\nBring your own agents from ANY framework:")
    print("  • LangChain  • AG2 (AutoGen)  • CrewAI  • Google ADK  • E2B  • Mastra")
    print("\nNo rewrites. No lock-in. Pure interoperability.")

    # Run all demos
    demo_1_single_framework_adapter()
    demo_2_mixed_frameworks()
    demo_3_custom_code_sandbox()
    demo_4_adapter_interface()

    print("\n" + "=" * 80)
    print("KEY TAKEAWAYS")
    print("=" * 80)
    print("""
1. FrameworkAdapter is a minimal interface (just invoke() method)
2. Wrap any framework's agent in 5 lines of code
3. Mix frameworks freely in workflows (LangChain → AG2 → CrewAI)
4. OpenBench provides data, orchestration, state, and outputs
5. Zero migration cost - use existing agents as-is

OpenBench is not another framework.
It's the control plane and plumbing that connects them all.
""")
    print("=" * 80)
