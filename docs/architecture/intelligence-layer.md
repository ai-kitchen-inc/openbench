# Intelligence Layer Architecture

## Overview

The Intelligence Layer is where OpenBench orchestrates AI agents to perform complex, multi-step workflows. It transforms data into insights through autonomous and semi-autonomous agent execution.

## Core Concepts

### Agents

An **agent** is an autonomous unit that:
- Has a specific goal or task
- Can use tools to accomplish its goal
- Makes decisions based on context
- Produces structured outputs

### Workflows

A **workflow** is a directed acyclic graph (DAG) of agents that:
- Coordinate to achieve complex objectives
- Share context and data
- Execute in parallel where possible
- Include human-in-the-loop checkpoints

## Agent Types

### 1. Research Agents

**Purpose:** Gather information from multiple sources

**Capabilities:**
- Multi-source search (documents, web, databases)
- Source verification and credibility assessment
- Information synthesis
- Citation tracking

**Example:**
```python
from openbench.agents import ResearchAgent

agent = ResearchAgent(
    goal="Gather competitive intelligence on top 5 competitors",
    sources=[
        "vector_db",
        "web_search",
        "crunchbase_api",
        "news_feeds"
    ],
    depth="comprehensive",  # or "quick", "deep"
    citation_required=True
)

result = agent.execute()
```

**Output Structure:**
```python
{
    "findings": [
        {
            "topic": "Competitor A - Product Strategy",
            "summary": "...",
            "sources": ["url1", "doc2"],
            "confidence": 0.89
        }
    ],
    "sources_consulted": 47,
    "execution_time": 12.3
}
```

### 2. Analysis Agents

**Purpose:** Perform quantitative and qualitative analysis

**Capabilities:**
- Statistical analysis
- Trend detection
- Forecasting
- Classification
- Anomaly detection

**Example:**
```python
from openbench.agents import AnalysisAgent

agent = AnalysisAgent(
    goal="Identify sales trends and forecast Q1 2025",
    data_source="postgresql://sales_db",
    methods=["time_series", "regression", "clustering"],
    visualize=True
)

result = agent.execute()
```

**Output Structure:**
```python
{
    "analysis": {
        "trends": [...],
        "forecast": {...},
        "anomalies": [...],
        "confidence_intervals": {...}
    },
    "visualizations": ["chart1.png", "chart2.png"],
    "methodology": "...",
    "statistical_significance": 0.95
}
```

### 3. Content Agents

**Purpose:** Generate written content

**Capabilities:**
- Long-form writing
- Summarization
- Translation
- Tone adaptation
- Style matching

**Example:**
```python
from openbench.agents import ContentAgent

agent = ContentAgent(
    goal="Draft executive summary of Q4 performance",
    input_data=analysis_results,
    style="executive",
    length=500,  # words
    tone="professional",
    include_sections=["highlights", "challenges", "outlook"]
)

result = agent.execute()
```

### 4. Action Agents

**Purpose:** Execute actions and integrations

**Capabilities:**
- API calls
- Database updates
- File operations
- Email/notifications
- System integrations

**Example:**
```python
from openbench.agents import ActionAgent

agent = ActionAgent(
    goal="Update CRM with enriched customer data",
    actions=[
        {
            "type": "api_call",
            "endpoint": "https://crm.example.com/api/customers",
            "method": "PATCH",
            "auth": "bearer_token"
        },
        {
            "type": "notify",
            "channel": "slack",
            "webhook": "..."
        }
    ]
)

result = agent.execute()
```

### 5. Meta Agents

**Purpose:** Coordinate other agents

**Capabilities:**
- Task decomposition
- Agent selection and orchestration
- Dynamic workflow creation
- Conflict resolution

**Example:**
```python
from openbench.agents import MetaAgent

agent = MetaAgent(
    goal="Create comprehensive market analysis report",
    available_agents=[
        "research", "analysis", "content", "action"
    ],
    constraints={
        "max_cost": 10.0,  # dollars
        "max_time": 600,   # seconds
        "quality_threshold": 0.85
    }
)

# Meta agent automatically creates and executes workflow
result = agent.execute()
```

## Agent Architecture

### Agent Lifecycle

```
┌─────────────────────────────────────────────────────┐
│                 Agent Lifecycle                      │
└─────────────────────────────────────────────────────┘

1. Initialize
   │
   ├─► Load configuration
   ├─► Validate inputs
   └─► Setup tools and memory

2. Plan
   │
   ├─► Decompose goal into sub-tasks
   ├─► Select tools and strategies
   └─► Estimate resources needed

3. Execute
   │
   ├─► For each sub-task:
   │   ├─► Invoke tools
   │   ├─► Process results
   │   ├─► Update context
   │   └─► Check stopping conditions
   │
   └─► Handle errors and retries

4. Validate
   │
   ├─► Check output quality
   ├─► Verify goal achievement
   └─► Request human feedback (if needed)

5. Finalize
   │
   ├─► Format output
   ├─► Log metrics
   └─► Return result
```

### Agent Components

```
┌────────────────────────────────────────────────┐
│               Agent Components                  │
├────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────────────────────────────────┐ │
│  │            LLM Backbone                   │ │
│  │  (GPT-4, Claude, Llama, etc.)            │ │
│  └──────────────────────────────────────────┘ │
│                     ▲  │                       │
│                     │  │                       │
│          ┌──────────┘  └──────────┐           │
│          │                        │           │
│  ┌───────▼─────┐         ┌───────▼─────┐    │
│  │   Memory    │         │    Tools    │    │
│  │             │         │             │    │
│  │ • Short-term│         │ • Search    │    │
│  │ • Long-term │         │ • Code Exec │    │
│  │ • Episodic  │         │ • API Calls │    │
│  └─────────────┘         └─────────────┘    │
│          │                        │           │
│          └──────────┬──────────────┘          │
│                     │                         │
│              ┌──────▼──────┐                  │
│              │  Controller │                  │
│              │             │                  │
│              │ • Planning  │                  │
│              │ • Execution │                  │
│              │ • Reflection│                  │
│              └─────────────┘                  │
└────────────────────────────────────────────────┘
```

## Workflow Orchestration

### Workflow Definition

```python
from openbench.workflows import Workflow, Task

workflow = Workflow(name="market_analysis")

# Define tasks
research = Task(
    agent=ResearchAgent(...),
    id="research",
    timeout=300
)

analyze = Task(
    agent=AnalysisAgent(...),
    id="analyze",
    depends_on=["research"]  # Wait for research to complete
)

write = Task(
    agent=ContentAgent(...),
    id="write",
    depends_on=["analyze"]
)

review = Task(
    agent="human",  # Human-in-the-loop
    id="review",
    depends_on=["write"],
    prompt="Please review and approve the draft"
)

finalize = Task(
    agent=ActionAgent(...),
    id="finalize",
    depends_on=["review"]
)

# Add tasks to workflow
workflow.add_tasks([research, analyze, write, review, finalize])

# Execute workflow
result = workflow.execute()
```

### Workflow Visualization

```
research
   │
   ▼
analyze
   │
   ├──────────┐
   ▼          ▼
 write     charts
   │          │
   └────┬─────┘
        ▼
     review (human)
        │
        ▼
    finalize
```

### Parallel Execution

```python
# Tasks can run in parallel when no dependencies

workflow = Workflow(name="competitor_analysis")

# These run in parallel
competitor_1 = Task(agent=ResearchAgent(target="Competitor A"))
competitor_2 = Task(agent=ResearchAgent(target="Competitor B"))
competitor_3 = Task(agent=ResearchAgent(target="Competitor C"))

# This waits for all three to complete
synthesis = Task(
    agent=ContentAgent(...),
    depends_on=[competitor_1, competitor_2, competitor_3]
)

workflow.add_tasks([competitor_1, competitor_2, competitor_3, synthesis])
```

### Conditional Workflows

```python
from openbench.workflows import ConditionalTask

# Conditional branching
analysis = Task(agent=AnalysisAgent(...))

# Branch based on result
followup = ConditionalTask(
    condition=lambda result: result["confidence"] < 0.8,
    if_true=Task(agent=ResearchAgent(goal="Deep dive research")),
    if_false=Task(agent=ContentAgent(goal="Write report"))
)

workflow = Workflow()
workflow.add_task(analysis)
workflow.add_task(followup, depends_on=[analysis])
```

## Tool System

Agents use tools to interact with the world.

### Built-in Tools

```python
from openbench.tools import (
    SearchTool,
    SQLTool,
    PythonREPL,
    APICallTool,
    FileSystemTool
)

# Search tool
search = SearchTool(
    providers=["vector_db", "web", "elasticsearch"]
)

# SQL tool
sql = SQLTool(
    connection="postgresql://...",
    read_only=True  # Safety measure
)

# Python execution
python = PythonREPL(
    allowed_imports=["pandas", "numpy", "matplotlib"],
    timeout=30
)

# API calls
api = APICallTool(
    base_url="https://api.example.com",
    auth={"type": "bearer", "token": "..."}
)
```

### Custom Tools

```python
from openbench.tools import BaseTool

class CustomTool(BaseTool):
    """Custom tool for specific business logic."""

    name = "custom_calculator"
    description = "Calculates custom business metrics"

    def __init__(self, config: dict):
        self.config = config

    def run(self, inputs: dict) -> dict:
        """Execute the tool."""
        # Your custom logic here
        result = self.calculate(inputs)
        return result

    def calculate(self, inputs: dict) -> dict:
        # Implementation
        pass

# Register tool
from openbench.tools import register_tool
register_tool(CustomTool)
```

## Memory Systems

### Short-term Memory (Context)

Stores the immediate conversation/task context.

```python
from openbench.memory import ShortTermMemory

memory = ShortTermMemory(
    max_tokens=8000,
    truncation_strategy="fifo"  # or "importance"
)

# Automatically managed during agent execution
agent = ResearchAgent(
    goal="...",
    memory=memory
)
```

### Long-term Memory (Vector Store)

Persistent storage of information across sessions.

```python
from openbench.memory import LongTermMemory

memory = LongTermMemory(
    vector_store="pinecone",
    index_name="agent_memory"
)

# Store important findings
memory.store(
    content="Market size for Product X is $2.5B",
    metadata={"source": "research_task_123", "date": "2024-01-15"}
)

# Retrieve relevant memories
memories = memory.retrieve(
    query="What do we know about Product X market size?",
    top_k=5
)
```

### Episodic Memory (Workflow History)

Records of past workflow executions for learning.

```python
from openbench.memory import EpisodicMemory

memory = EpisodicMemory()

# Automatically logged after workflow completion
# Can be queried to improve future executions

similar_workflows = memory.find_similar(
    goal="Competitive analysis",
    limit=10
)

# Learn from past successes
best_practices = memory.extract_patterns(
    filter={"success": True, "rating": "> 4.0"}
)
```

## LLM Integration

### Multi-Model Support

```python
from openbench.llm import LLMConfig

# Use different models for different tasks
research_agent = ResearchAgent(
    llm=LLMConfig(
        provider="anthropic",
        model="claude-opus-4",
        temperature=0.7
    )
)

analysis_agent = AnalysisAgent(
    llm=LLMConfig(
        provider="openai",
        model="gpt-4",
        temperature=0.2  # More deterministic
    )
)

# Cost-optimized for simple tasks
simple_agent = ContentAgent(
    llm=LLMConfig(
        provider="openai",
        model="gpt-3.5-turbo",
        temperature=0.5
    )
)
```

### Model Fallback

```python
from openbench.llm import LLMConfig

config = LLMConfig(
    primary_model="gpt-4",
    fallback_models=["claude-opus", "gpt-3.5-turbo"],
    retry_on_error=True,
    max_retries=3
)
```

## Human-in-the-Loop

### Approval Gates

```python
from openbench.workflows import ApprovalGate

workflow = Workflow()

# ... agent tasks ...

approval = ApprovalGate(
    prompt="Please review the generated content before publishing",
    timeout=3600,  # 1 hour
    approvers=["manager@example.com"],
    require_all=False  # Any one approver
)

workflow.add_task(approval, depends_on=["content_generation"])
```

### Interactive Refinement

```python
from openbench.agents import InteractiveAgent

agent = InteractiveAgent(
    goal="Draft marketing copy",
    max_iterations=5,
    feedback_prompt="How would you like me to refine this?"
)

# Agent will iterate based on user feedback
result = agent.execute(interactive=True)
```

## Monitoring & Debugging

### Execution Tracing

```python
from openbench.workflows import Workflow

workflow = Workflow(
    name="analysis",
    enable_tracing=True,
    trace_level="detailed"  # or "basic", "verbose"
)

result = workflow.execute()

# View execution trace
print(result.trace)
```

**Trace Output:**
```
[2024-01-15 10:00:00] Workflow started: analysis
[2024-01-15 10:00:01] Task started: research
[2024-01-15 10:00:05]   Tool called: vector_search(query="...")
[2024-01-15 10:00:06]   Tool result: 47 documents found
[2024-01-15 10:00:10] Task completed: research (9.2s)
[2024-01-15 10:00:11] Task started: analyze
...
```

### Performance Metrics

```python
# Available metrics
- agent.execution.duration
- agent.llm.tokens.input
- agent.llm.tokens.output
- agent.llm.cost
- agent.tool.calls.count
- workflow.tasks.completed
- workflow.tasks.failed
```

## Best Practices

1. **Start Simple**: Begin with single-agent workflows, add complexity as needed
2. **Parallel Execution**: Identify independent tasks for parallel execution
3. **Error Handling**: Always include error handling and fallback strategies
4. **Cost Management**: Monitor token usage, use cheaper models for simple tasks
5. **Human Oversight**: Include approval gates for high-stakes decisions
6. **Memory Management**: Use appropriate memory types for different use cases
7. **Tool Safety**: Restrict tool capabilities (e.g., read-only database access)
8. **Logging**: Enable detailed logging for debugging and improvement

## Troubleshooting

### Agent Not Completing

- Check timeout settings
- Review tool availability
- Verify LLM API keys and quotas
- Check memory limits

### Poor Quality Outputs

- Adjust temperature settings
- Improve prompt engineering
- Use more capable model
- Add validation steps
- Include human review

### High Costs

- Use model fallback chain (expensive → cheap)
- Cache intermediate results
- Reduce token usage with summarization
- Use local models where possible

---

**Next:** [Output Layer](./output-layer.md)
