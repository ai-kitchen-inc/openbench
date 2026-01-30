#!/usr/bin/env python3
"""
Agent Registry Demo - Dynamic Agent Registration and Creation.

Demonstrates the new AgentFactory with AgentRegistry:
1. List built-in agent types
2. Create agents using factory
3. Register custom agents
4. Use custom agents in workflows
"""

from openbench.intelligence import AgentFactory, BaseAgent
from openbench.core import AgentRegistry, ExecutionContext


def demo_list_agents():
    """Demo 1: List all registered agent types."""
    print("=" * 60)
    print("DEMO 1: List Registered Agent Types")
    print("=" * 60)

    # List all agent types
    agent_types = AgentFactory.list_types()
    print(f"\nRegistered agent types: {agent_types}")

    # List providers for each type
    for agent_type in agent_types:
        providers = AgentFactory.list_providers(agent_type)
        print(f"  - {agent_type}: providers = {providers}")

    print()


def demo_create_builtin_agents():
    """Demo 2: Create built-in agents using factory."""
    print("=" * 60)
    print("DEMO 2: Create Built-in Agents")
    print("=" * 60)

    # Create different agent types
    research_agent = AgentFactory.create(
        goal="Research AI trends",
        agent_type="research",
        model="gpt-4o"
    )
    print(f"\nResearch Agent: {research_agent}")
    print(f"  - Type: {research_agent.agent_type}")
    print(f"  - Model: {research_agent.model}")
    print(f"  - Goal: {research_agent.goal}")

    # Using shortcut methods
    analysis_agent = AgentFactory.analysis(goal="Analyze sales data")
    print(f"\nAnalysis Agent: {analysis_agent}")
    print(f"  - Type: {analysis_agent.agent_type}")

    content_agent = AgentFactory.content(goal="Write blog post", style="casual")
    print(f"\nContent Agent: {content_agent}")
    print(f"  - Type: {content_agent.agent_type}")
    print(f"  - Style: {content_agent.style}")

    print()


def demo_register_custom_agent():
    """Demo 3: Register and use custom agents."""
    print("=" * 60)
    print("DEMO 3: Register Custom Agent")
    print("=" * 60)

    # Define custom agent
    class SummarizerAgent(BaseAgent):
        """Agent specialized in summarizing content."""

        def __init__(
            self,
            goal: str,
            max_words: int = 100,
            style: str = "concise",
            **kwargs
        ):
            system_prompt = f"""You are a summarization agent with the goal: {goal}

Your task is to create {style} summaries.
Maximum words: {max_words}

Guidelines:
1. Extract key points
2. Maintain accuracy
3. Be {style}
4. Stay within word limit"""

            super().__init__(goal=goal, system_prompt=system_prompt, **kwargs)
            self.max_words = max_words
            self.style = style

        @property
        def agent_type(self) -> str:
            return "summarizer"

    # Register the custom agent
    AgentFactory.register(
        agent_type="summarizer",
        provider="custom",
        agent_class=SummarizerAgent,
        description="Agent specialized in summarizing content"
    )

    print("\nRegistered 'summarizer' agent type")
    print(f"Available types now: {AgentFactory.list_types()}")
    print(f"Providers for 'summarizer': {AgentFactory.list_providers('summarizer')}")

    # Create instance of custom agent
    summarizer = AgentFactory.create(
        goal="Summarize quarterly reports",
        agent_type="summarizer",
        provider="custom",
        max_words=50,
        style="executive"
    )

    print(f"\nCreated Summarizer Agent:")
    print(f"  - Type: {summarizer.agent_type}")
    print(f"  - Goal: {summarizer.goal}")
    print(f"  - Max Words: {summarizer.max_words}")
    print(f"  - Style: {summarizer.style}")

    print()


def demo_multiple_providers():
    """Demo 4: Register multiple providers for same agent type."""
    print("=" * 60)
    print("DEMO 4: Multiple Providers for Same Type")
    print("=" * 60)

    # Define two different translation agents
    class BasicTranslator(BaseAgent):
        """Basic translation agent."""

        def __init__(self, goal: str, target_lang: str = "en", **kwargs):
            super().__init__(
                goal=goal,
                system_prompt=f"Translate to {target_lang}. Goal: {goal}",
                **kwargs
            )
            self.target_lang = target_lang

        @property
        def agent_type(self) -> str:
            return "translator"

    class PremiumTranslator(BaseAgent):
        """Premium translation with context awareness."""

        def __init__(self, goal: str, target_lang: str = "en", context: str = "", **kwargs):
            super().__init__(
                goal=goal,
                system_prompt=f"Premium translation to {target_lang}. Context: {context}. Goal: {goal}",
                **kwargs
            )
            self.target_lang = target_lang
            self.context = context

        @property
        def agent_type(self) -> str:
            return "translator"

    # Register both with different providers
    AgentFactory.register("translator", "basic", BasicTranslator, "Basic translation")
    AgentFactory.register("translator", "premium", PremiumTranslator, "Premium translation with context")

    print(f"\nProviders for 'translator': {AgentFactory.list_providers('translator')}")

    # Create different implementations
    basic = AgentFactory.create(
        goal="Translate document",
        agent_type="translator",
        provider="basic",
        target_lang="id"
    )

    premium = AgentFactory.create(
        goal="Translate legal document",
        agent_type="translator",
        provider="premium",
        target_lang="id",
        context="legal terminology"
    )

    print(f"\nBasic Translator: target_lang={basic.target_lang}")
    print(f"Premium Translator: target_lang={premium.target_lang}, context={premium.context}")

    print()


def demo_registry_direct_access():
    """Demo 5: Direct AgentRegistry access."""
    print("=" * 60)
    print("DEMO 5: Direct AgentRegistry Access")
    print("=" * 60)

    # Use AgentRegistry directly
    print(f"\nAll registered plugins: {AgentRegistry.list_plugins()}")

    # Get metadata
    metadata = AgentRegistry.get_metadata("research", "default")
    if metadata:
        print(f"\nResearch agent metadata:")
        print(f"  - Name: {metadata.name}")
        print(f"  - Description: {metadata.description}")
        print(f"  - Plugin Type: {metadata.plugin_type}")
        print(f"  - Provider: {metadata.provider}")

    # Check if registered
    print(f"\nIs 'research:default' registered? {AgentRegistry.is_registered('research', 'default')}")
    print(f"Is 'unknown:provider' registered? {AgentRegistry.is_registered('unknown', 'provider')}")

    print()


def demo_workflow_with_custom_agent():
    """Demo 6: Using custom agent in workflow composition."""
    print("=" * 60)
    print("DEMO 6: Custom Agent in Workflow")
    print("=" * 60)

    from openbench.core import Chain, Lambda

    # Define workflow steps
    extract_data = Lambda(lambda x: {
        **x,
        "extracted": f"Data extracted for: {x.get('topic', 'unknown')}"
    })

    # Create agent step (wrapping agent execution)
    def agent_step(data):
        agent = AgentFactory.create(
            goal=f"Analyze: {data.get('topic', 'data')}",
            agent_type="analysis"
        )
        # In real usage, you'd call agent.execute(context)
        return {
            **data,
            "agent_type": agent.agent_type,
            "agent_goal": agent.goal,
            "analysis": f"Analysis complete for: {data.get('topic')}"
        }

    format_output = Lambda(lambda x: {
        "result": f"Processed: {x.get('topic')} -> {x.get('analysis')}",
        "agent_used": x.get('agent_type')
    })

    # Compose workflow
    workflow = extract_data | Lambda(agent_step) | format_output

    # Execute
    input_data = {"topic": "Q4 Sales Performance"}
    result = workflow.invoke(input_data)

    print(f"\nInput: {input_data}")
    print(f"Output: {result}")

    print()


def main():
    """Run all demos."""
    print("\n" + "=" * 60)
    print("AGENT REGISTRY DEMO")
    print("Demonstrating Dynamic Agent Registration")
    print("=" * 60 + "\n")

    demo_list_agents()
    demo_create_builtin_agents()
    demo_register_custom_agent()
    demo_multiple_providers()
    demo_registry_direct_access()
    demo_workflow_with_custom_agent()

    print("=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
