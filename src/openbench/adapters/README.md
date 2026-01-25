# OpenBench Framework Adapters

## Vision

**OpenBench is not another framework. It's the control plane and plumbing that connects them all.**

Users shouldn't have to rewrite their agents when they switch from LangChain to Mastra, or from AG2 to Google ADK. OpenBench provides:

1. **Universal Data Layer** - Connect any data source, use any vector store
2. **Framework Adapters** - Bring your own agents from any framework
3. **Unified Orchestration** - Same workflow syntax regardless of underlying framework
4. **Portable Outputs** - Generate outputs independent of how you processed data

## The Adapter Pattern

Every external framework integrates through a simple `FrameworkAdapter` interface:

```python
class FrameworkAdapter(ABC):
    @property
    @abstractmethod
    def framework_name(self) -> str:
        """Name of the framework (e.g., 'langchain', 'ag2')."""
        pass

    @abstractmethod
    def invoke(self, input: Any, config=None) -> Any:
        """Execute the wrapped agent/workflow."""
        pass
```

**That's it.** One method to implement, and your framework works with OpenBench.

## Available Adapters

### LangChainAdapter

Wrap any LangChain Runnable (agents, chains, LCEL):

```python
from openbench.adapters.langchain import LangChainAdapter
from langchain.agents import create_react_agent, AgentExecutor
from langchain_openai import ChatOpenAI

# Your existing LangChain agent
llm = ChatOpenAI(model="gpt-4")
agent = create_react_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools)

# Use in OpenBench
from openbench import Workflow
from openbench.data import WebSource
from openbench.output import PDFGenerator

workflow = Workflow(
    name="langchain-workflow",
    chain=(
        WebSource("https://example.com")
        | LangChainAdapter(agent_executor)
        | PDFGenerator()
    )
)
```

### AG2Adapter

Wrap AG2 (AutoGen) agents:

```python
from openbench.adapters.ag2 import AG2Adapter
from autogen import AssistantAgent

# Your existing AG2 agent
my_ag2_agent = AssistantAgent(
    name="analyst",
    llm_config={"model": "gpt-4"}
)

# Use in OpenBench
workflow = Workflow(
    name="ag2-analysis",
    chain=(
        PDFSource("report.pdf")
        | AG2Adapter(my_ag2_agent)
        | PDFGenerator()
    )
)
```

### CrewAIAdapter

Wrap CrewAI crews:

```python
from openbench.adapters.crewai import CrewAIAdapter
from crewai import Crew, Agent, Task

# Your existing CrewAI setup
researcher = Agent(role="Researcher", goal="Research topics", ...)
writer = Agent(role="Writer", goal="Write content", ...)
crew = Crew(agents=[researcher, writer], tasks=[...])

# Use in OpenBench
workflow = Workflow(
    name="crewai-workflow",
    chain=(
        PDFSource("doc.pdf")
        | CrewAIAdapter(crew)
        | PPTXGenerator()
    )
)
```

### E2BAdapter

Run custom code in sandboxed environments:

```python
from openbench.adapters.e2b import E2BAdapter

# Custom data transformation
custom_transform = E2BAdapter(
    code='''
import pandas as pd
df = pd.DataFrame(input_data)
result = df.describe().to_dict()
''',
    packages=["pandas"]
)

# Use in OpenBench
workflow = Workflow(
    name="custom-analysis",
    chain=(
        CSVSource("data.csv")
        | custom_transform  # Runs in isolated sandbox
        | PDFGenerator()
    )
)
```

### GoogleADKAdapter

Wrap Google ADK agents:

```python
from openbench.adapters.google_adk import GoogleADKAdapter

# Your existing Google ADK agent
# (API structure is hypothetical - adjust based on actual SDK)
my_google_agent = Agent(name="analyst", model="gemini-pro")

# Use in OpenBench
workflow = Workflow(
    name="google-workflow",
    chain=(
        YouTubeSource("video_id")
        | GoogleADKAdapter(my_google_agent)
        | PPTXGenerator()
    )
)
```

## Mixed-Framework Workflows

The real power: combine agents from different frameworks in a single workflow:

```python
from openbench import Workflow
from openbench.adapters.langchain import LangChainAdapter
from openbench.adapters.crewai import CrewAIAdapter
from openbench.core import Parallel

# Mix LangChain and CrewAI in one workflow!
workflow = Workflow(
    name="hybrid-workflow",
    chain=(
        WebSource("https://example.com")
        | LangChainAdapter(my_langchain_agent)  # LangChain processes
        | CrewAIAdapter(my_crew)  # CrewAI refines
        | (PDFGenerator() & PPTXGenerator())  # OpenBench outputs
    )
)
```

## What OpenBench Provides

When you use adapters, OpenBench gives you:

1. **Data Ingestion** - YouTube, PDF, URL, databases (you don't rebuild this)
2. **Workflow Orchestration** - DAG composition with `|` and `&`
3. **State Management** - Checkpointing, resume, observability
4. **Output Generation** - PDF, PPTX, HTML, audio, video
5. **Execution Backends** - Local, cloud, sandboxed (E2B)

## Creating Your Own Adapter

To integrate a new framework:

1. Inherit from `FrameworkAdapter`
2. Implement `framework_name` property
3. Implement `invoke()` method

Example:

```python
from openbench.core import FrameworkAdapter

class MyFrameworkAdapter(FrameworkAdapter):
    framework_name = "myframework"

    def __init__(self, agent):
        self.agent = agent

    def invoke(self, input, config=None):
        # Call your framework's execution method
        return self.agent.execute(input)
```

That's it! Your framework now works with OpenBench.

## Philosophy

OpenBench doesn't try to be the best agent framework. Instead, it:

- **Lets experts be experts** - Use LangChain for chains, CrewAI for role-based agents
- **Eliminates lock-in** - Switch frameworks without rewriting workflows
- **Focuses on infrastructure** - Data, orchestration, state, outputs
- **Enables interoperability** - Mix and match frameworks freely

**OpenBench is the universal control plane for agentic AI.**
