"""
L2 System-Level Layer Orchestrators.

DataLayer, IntelligenceLayer, and OutputLayer are Chainable,
enabling E2E system composition: DataLayer | IntelligenceLayer | OutputLayer
"""

from typing import Any, Dict, List, Optional, Union
from openbench.core.chainable import Chainable, RunnableConfig
from openbench.core.abstractions import DataSource, DataStore, Agent, OutputGenerator, RawData

# Keys to preserve across layer boundaries
PRESERVED_KEYS = ("goal", "output_path", "title", "author", "template")


def _preserve_input_params(output: Dict[str, Any], input: Any) -> None:
    """Copy workflow-level parameters from input to output."""
    if isinstance(input, dict):
        for key in PRESERVED_KEYS:
            if key in input:
                output[key] = input[key]


class DataLayer(Chainable[Any, Dict[str, Any]]):
    """
    L2: Data Layer Orchestrator.

    Manages data sources and stores. Sources can be:
    - Single DataSource
    - Chainable workflow of DataSources (L1 composition)

    Example:
        >>> # Single source
        >>> layer = DataLayer(sources=pdf_source, stores=[vector_store])
        >>>
        >>> # Multiple sources (L1 workflow)
        >>> sources_workflow = video1 | video2 | video3
        >>> layer = DataLayer(sources=sources_workflow, stores=[vector_store])
        >>>
        >>> # Use in L2 workflow
        >>> workflow = layer | intelligence_layer | output_layer
        >>> result = workflow.invoke({})
    """

    def __init__(
        self,
        sources: Optional[Union[DataSource, Chainable]] = None,
        stores: Optional[List[DataStore]] = None
    ):
        """
        Initialize Data Layer.

        Args:
            sources: Single DataSource or Chainable workflow of sources
            stores: List of DataStores for indexing
        """
        self.sources = sources
        self.stores = stores or []

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        """
        Execute data layer.

        Steps:
        1. Execute source(s) - either single source or L1 workflow
        2. Index results in all configured stores
        3. Return aggregated data

        Args:
            input: Input data (passed to sources)
            config: Execution configuration

        Returns:
            Dict containing:
                - raw_data: List of RawData from sources
                - indexed_ids: IDs from indexing
                - metadata: Layer execution metadata
                - (preserved) goal, output_path, title, etc. from input
        """
        results = []

        if self.sources:
            # Execute source(s) - could be single source or workflow
            source_output = self.sources.invoke(input, config)

            # Normalize output to list
            if isinstance(source_output, list):
                results.extend(source_output)
            else:
                results.append(source_output)

        # Index in all stores
        indexed_ids = []
        for store in self.stores:
            for result in results:
                # Only index if result is RawData
                if isinstance(result, RawData):
                    item_id = store.index(result)
                    indexed_ids.append(item_id)

        output = {
            "raw_data": results,
            "indexed_ids": indexed_ids,
            "metadata": {
                "layer": "data",
                "num_sources": len(results),
                "num_stores": len(self.stores),
                "num_indexed": len(indexed_ids)
            }
        }

        _preserve_input_params(output, input)
        return output


class IntelligenceLayer(Chainable[Any, Dict[str, Any]]):
    """
    L2: Intelligence Layer Orchestrator.

    Manages AI agents. Agents can be:
    - Single Agent
    - Chainable workflow of Agents (L1 composition)

    Example:
        >>> # Single agent
        >>> layer = IntelligenceLayer(agents=research_agent)
        >>>
        >>> # Multiple agents (L1 workflow)
        >>> agent_workflow = research | analysis | synthesis
        >>> layer = IntelligenceLayer(agents=agent_workflow)
        >>>
        >>> # Use in L2 workflow
        >>> workflow = data_layer | layer | output_layer
        >>> result = workflow.invoke({})
    """

    def __init__(self, agents: Union[Agent, Chainable]):
        """
        Initialize Intelligence Layer.

        Args:
            agents: Single Agent or Chainable workflow of agents
        """
        self.agents = agents

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        """
        Execute intelligence layer.

        Runs agent(s) - either single agent or L1 workflow.

        Args:
            input: Input data (from DataLayer or previous layer)
            config: Execution configuration

        Returns:
            Dict containing:
                - intelligence_output: Output from agents
                - metadata: Layer execution metadata
                - (preserved) goal, output_path, title, etc. from input
        """
        # Execute agent(s)
        result = self.agents.invoke(input, config)

        output = {
            "intelligence_output": result,
            "metadata": {
                "layer": "intelligence"
            }
        }

        _preserve_input_params(output, input)
        return output


class OutputLayer(Chainable[Any, Dict[str, Any]]):
    """
    L2: Output Layer Orchestrator.

    Manages output generators. Generators can be:
    - Single OutputGenerator
    - Chainable workflow of OutputGenerators (L1 composition)

    Example:
        >>> # Single generator
        >>> layer = OutputLayer(generators=pdf_gen)
        >>>
        >>> # Multiple generators (L1 workflow)
        >>> output_workflow = pdf_gen & pptx_gen  # Parallel
        >>> layer = OutputLayer(generators=output_workflow)
        >>>
        >>> # Use in L2 workflow
        >>> workflow = data_layer | intelligence_layer | layer
        >>> result = workflow.invoke({})
    """

    def __init__(self, generators: Union[OutputGenerator, Chainable]):
        """
        Initialize Output Layer.

        Args:
            generators: Single OutputGenerator or Chainable workflow of generators
        """
        self.generators = generators

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        """
        Execute output layer.

        Runs generator(s) - either single generator or L1 workflow.

        Args:
            input: Input data (from IntelligenceLayer or previous layer)
            config: Execution configuration

        Returns:
            Dict containing:
                - generated_outputs: List of GeneratedOutput objects
                - metadata: Layer execution metadata
        """
        # Execute generator(s)
        outputs = self.generators.invoke(input, config)

        # Normalize to list
        if not isinstance(outputs, list):
            outputs = [outputs]

        return {
            "generated_outputs": outputs,
            "metadata": {
                "layer": "output",
                "num_outputs": len(outputs)
            }
        }


# Convenience function for creating complete workflows
def create_workflow(
    data_sources: Optional[Union[DataSource, Chainable]] = None,
    data_stores: Optional[List[DataStore]] = None,
    agents: Optional[Union[Agent, Chainable]] = None,
    generators: Optional[Union[OutputGenerator, Chainable]] = None
) -> Chainable:
    """
    Create complete L2 workflow from components.

    Args:
        data_sources: DataSource(s) - single or L1 workflow
        data_stores: List of DataStores for indexing
        agents: Agent(s) - single or L1 workflow
        generators: OutputGenerator(s) - single or L1 workflow

    Returns:
        Complete Chainable workflow: DataLayer | IntelligenceLayer | OutputLayer

    Example:
        >>> # Create workflow from components
        >>> workflow = create_workflow(
        ...     data_sources=video1 | video2 | pdf,
        ...     data_stores=[vector_store],
        ...     agents=research | analysis,
        ...     generators=pdf_gen & pptx_gen
        ... )
        >>>
        >>> # Execute E2E
        >>> result = workflow.invoke({"project": "Market Analysis"})
    """
    layers = []

    if data_sources or data_stores:
        layers.append(DataLayer(sources=data_sources, stores=data_stores))

    if agents:
        layers.append(IntelligenceLayer(agents=agents))

    if generators:
        layers.append(OutputLayer(generators=generators))

    if not layers:
        raise ValueError("Must provide at least one layer component")

    # Chain layers together
    workflow = layers[0]
    for layer in layers[1:]:
        workflow = workflow | layer

    return workflow
