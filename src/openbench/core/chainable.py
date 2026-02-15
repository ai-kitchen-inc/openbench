"""
Chainable workflow system compatible with LangChain's Runnable interface.

Enables DAG-based workflows with pipe operator composition.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Type variables for input/output
Input = TypeVar("Input")
Output = TypeVar("Output")
OtherOutput = TypeVar("OtherOutput")


@dataclass
class RunnableConfig:
    """
    Configuration for Chainable execution.

    Compatible with LangChain's RunnableConfig.
    """

    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    callbacks: list[Any] = field(default_factory=list)
    run_name: str | None = None
    max_concurrency: int | None = None
    recursion_limit: int = 25
    configurable: dict[str, Any] = field(default_factory=dict)


class Chainable(ABC, Generic[Input, Output]):
    """
    Abstract base for chainable workflow components.

    Compatible with LangChain's Runnable interface.

    All workflow components (agents, transformers, etc.) should inherit from this.
    """

    @abstractmethod
    def invoke(self, input: Input, config: RunnableConfig | None = None) -> Output:
        """
        Execute this chainable synchronously.

        Args:
            input: Input data
            config: Execution configuration

        Returns:
            Output data
        """

    async def ainvoke(self, input: Input, config: RunnableConfig | None = None) -> Output:
        """
        Execute this chainable asynchronously.

        Default implementation wraps invoke(). Override for true async.

        Args:
            input: Input data
            config: Execution configuration

        Returns:
            Output data
        """
        return self.invoke(input, config)

    def batch(self, inputs: list[Input], config: RunnableConfig | None = None) -> list[Output]:
        """
        Execute this chainable on multiple inputs.

        Args:
            inputs: List of inputs
            config: Execution configuration

        Returns:
            List of outputs
        """
        return [self.invoke(input, config) for input in inputs]

    async def abatch(
        self, inputs: list[Input], config: RunnableConfig | None = None
    ) -> list[Output]:
        """
        Execute this chainable on multiple inputs asynchronously.

        Args:
            inputs: List of inputs
            config: Execution configuration

        Returns:
            List of outputs
        """
        tasks = [self.ainvoke(input, config) for input in inputs]
        return await asyncio.gather(*tasks)

    def stream(self, input: Input, config: RunnableConfig | None = None):
        """
        Stream output from this chainable.

        Default implementation yields final output. Override for true streaming.

        Args:
            input: Input data
            config: Execution configuration

        Yields:
            Output chunks
        """
        yield self.invoke(input, config)

    # Composition operators (pipe and parallel)

    def __or__(self, other: Chainable[Output, OtherOutput]) -> Chain[Input, OtherOutput]:
        """
        Pipe operator: self | other

        Chains this chainable with another sequentially.

        Example:
            >>> workflow = data_loader | analyzer | reporter
            >>> result = workflow.invoke(input_data)

        Args:
            other: Next chainable in the chain

        Returns:
            Chain combining self and other
        """
        return Chain(steps=[self, other])

    def __and__(self, other: Chainable) -> Parallel:
        """
        Parallel operator: self & other

        Runs this chainable and another in parallel.

        Example:
            >>> parallel_analysis = trend_analyzer & competitor_analyzer
            >>> results = parallel_analysis.invoke(data)

        Args:
            other: Chainable to run in parallel

        Returns:
            Parallel combining self and other
        """
        return Parallel(branches=[self, other])


class ChainExecutionError(Exception):
    """Error raised when a Chain step fails, with step context."""

    def __init__(self, message: str, step_index: int, step_name: str, partial_result: Any = None):
        super().__init__(message)
        self.step_index = step_index
        self.step_name = step_name
        self.partial_result = partial_result


class Chain(Chainable[Input, Output]):
    """
    Sequential chain of chainables: A → B → C

    Example:
        >>> # Using pipe operator
        >>> workflow = loader | processor | analyzer | reporter
        >>>
        >>> # Direct creation
        >>> workflow = Chain(steps=[loader, processor, analyzer, reporter])
        >>>
        >>> # With error handler
        >>> workflow = Chain(
        ...     steps=[loader, processor, analyzer],
        ...     on_error=lambda e, i, r: r  # Return partial result on error
        ... )
        >>>
        >>> # Execute
        >>> result = workflow.invoke(initial_data)
    """

    def __init__(self, steps: list[Chainable], on_error: Callable | None = None):
        """
        Initialize chain.

        Args:
            steps: List of chainables to execute sequentially
            on_error: Optional error handler callable(exception, step_index, partial_result) -> Any.
                      If provided, its return value becomes the chain result on error.
                      If not provided, a ChainExecutionError is raised.
        """
        if not steps:
            raise ValueError("Chain must have at least one step")
        self.steps = steps
        self.on_error = on_error

    def invoke(self, input: Input, config: RunnableConfig | None = None) -> Output:
        """
        Execute all steps sequentially.

        Output of each step becomes input to the next.

        Args:
            input: Initial input
            config: Execution configuration

        Returns:
            Final output

        Raises:
            ChainExecutionError: If a step fails and no on_error handler is set
        """
        result = input
        for i, step in enumerate(self.steps):
            try:
                result = step.invoke(result, config)
            except Exception as e:
                step_name = getattr(step, "name", step.__class__.__name__)
                if self.on_error:
                    return self.on_error(e, i, result)
                raise ChainExecutionError(
                    f"Step {i} ({step_name}) failed: {e}",
                    step_index=i,
                    step_name=step_name,
                    partial_result=result,
                ) from e
        return result

    async def ainvoke(self, input: Input, config: RunnableConfig | None = None) -> Output:
        """
        Execute all steps sequentially (async).

        Args:
            input: Initial input
            config: Execution configuration

        Returns:
            Final output

        Raises:
            ChainExecutionError: If a step fails and no on_error handler is set
        """
        result = input
        for i, step in enumerate(self.steps):
            try:
                result = await step.ainvoke(result, config)
            except Exception as e:
                step_name = getattr(step, "name", step.__class__.__name__)
                if self.on_error:
                    return self.on_error(e, i, result)
                raise ChainExecutionError(
                    f"Step {i} ({step_name}) failed: {e}",
                    step_index=i,
                    step_name=step_name,
                    partial_result=result,
                ) from e
        return result

    def __or__(self, other: Chainable) -> Chain:
        """
        Extend this chain with another step.

        Args:
            other: Next step to add

        Returns:
            Extended chain (preserves on_error handler)
        """
        return Chain(steps=[*self.steps, other], on_error=self.on_error)


class Parallel(Chainable[Input, list[Any]]):
    """
    Parallel execution of multiple chainables: [A, B, C]

    All branches receive the same input and execute concurrently.

    Example:
        >>> # Using & operator
        >>> parallel = analyzer_a & analyzer_b & analyzer_c
        >>>
        >>> # Direct creation
        >>> parallel = Parallel(branches=[analyzer_a, analyzer_b, analyzer_c])
        >>>
        >>> # Execute
        >>> results = parallel.invoke(data)  # Returns [result_a, result_b, result_c]
    """

    def __init__(self, branches: list[Chainable]):
        """
        Initialize parallel execution.

        Args:
            branches: List of chainables to execute in parallel
        """
        if not branches:
            raise ValueError("Parallel must have at least one branch")
        self.branches = branches

    def invoke(self, input: Input, config: RunnableConfig | None = None) -> list[Any]:
        """
        Execute all branches sequentially and collect results.

        Note: Use ainvoke() for true concurrent execution.

        Args:
            input: Input data (sent to all branches)
            config: Execution configuration

        Returns:
            List of outputs from all branches
        """
        return [branch.invoke(input, config) for branch in self.branches]

    async def ainvoke(self, input: Input, config: RunnableConfig | None = None) -> list[Any]:
        """
        Execute all branches in parallel (asynchronously).

        Args:
            input: Input data (sent to all branches)
            config: Execution configuration

        Returns:
            List of outputs from all branches (exceptions included as-is)
        """
        tasks = [branch.ainvoke(input, config) for branch in self.branches]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        errors = [(i, r) for i, r in enumerate(results) if isinstance(r, Exception)]
        if errors:
            logger.warning(
                f"Parallel execution had {len(errors)} failure(s): "
                + ", ".join(f"branch {i}: {type(e).__name__}: {e}" for i, e in errors)
            )

        return list(results)

    def __and__(self, other: Chainable) -> Parallel:
        """
        Add another branch to this parallel execution.

        Args:
            other: Another branch to add

        Returns:
            Extended parallel execution
        """
        return Parallel(branches=[*self.branches, other])


class Conditional(Chainable[Input, Output]):
    """
    Conditional routing: if condition(input) then true_branch else false_branch

    Example:
        >>> # Create conditional
        >>> workflow = Conditional(
        ...     condition=lambda x: x['type'] == 'research',
        ...     true_branch=research_agent,
        ...     false_branch=analysis_agent
        ... )
        >>>
        >>> # Execute - routes based on input
        >>> result = workflow.invoke({'type': 'research', 'query': '...'})
    """

    def __init__(
        self,
        condition: Callable[[Input], bool],
        true_branch: Chainable,
        false_branch: Chainable | None = None,
    ):
        """
        Initialize conditional.

        Args:
            condition: Function that takes input and returns bool
            true_branch: Chainable to execute if condition is True
            false_branch: Chainable to execute if condition is False (optional)
        """
        self.condition = condition
        self.true_branch = true_branch
        self.false_branch = false_branch

    def invoke(self, input: Input, config: RunnableConfig | None = None) -> Output:
        """
        Execute conditional logic.

        Args:
            input: Input data
            config: Execution configuration

        Returns:
            Output from selected branch
        """
        if self.condition(input):
            return self.true_branch.invoke(input, config)
        elif self.false_branch:
            return self.false_branch.invoke(input, config)
        else:
            return input  # Passthrough if no false branch

    async def ainvoke(self, input: Input, config: RunnableConfig | None = None) -> Output:
        """
        Execute conditional logic (async).

        Args:
            input: Input data
            config: Execution configuration

        Returns:
            Output from selected branch
        """
        if self.condition(input):
            return await self.true_branch.ainvoke(input, config)
        elif self.false_branch:
            return await self.false_branch.ainvoke(input, config)
        else:
            return input


class Router(Chainable[Input, Output]):
    """
    Multi-way routing based on key function.

    Routes input to different branches based on a routing key.

    Example:
        >>> # Create router
        >>> workflow = Router(
        ...     routes={
        ...         'research': research_agent,
        ...         'analysis': analysis_agent,
        ...         'content': content_agent
        ...     },
        ...     router=lambda x: x['task_type'],
        ...     default=fallback_agent
        ... )
        >>>
        >>> # Execute - routes to 'research' branch
        >>> result = workflow.invoke({'task_type': 'research', 'query': '...'})
    """

    def __init__(
        self,
        routes: dict[str, Chainable],
        router: Callable[[Input], str],
        default: Chainable | None = None,
    ):
        """
        Initialize router.

        Args:
            routes: Dict mapping route keys to chainables
            router: Function that takes input and returns route key
            default: Default chainable if route key not found (optional)
        """
        self.routes = routes
        self.router = router
        self.default = default

    def invoke(self, input: Input, config: RunnableConfig | None = None) -> Output:
        """
        Route input to appropriate branch.

        Args:
            input: Input data
            config: Execution configuration

        Returns:
            Output from selected branch

        Raises:
            ValueError: If route key not found and no default
        """
        key = self.router(input)
        if key in self.routes:
            return self.routes[key].invoke(input, config)
        elif self.default:
            return self.default.invoke(input, config)
        else:
            raise ValueError(
                f"Route key '{key}' not found and no default route specified. "
                f"Available routes: {list(self.routes.keys())}"
            )

    async def ainvoke(self, input: Input, config: RunnableConfig | None = None) -> Output:
        """
        Route input to appropriate branch (async).

        Args:
            input: Input data
            config: Execution configuration

        Returns:
            Output from selected branch
        """
        key = self.router(input)
        if key in self.routes:
            return await self.routes[key].ainvoke(input, config)
        elif self.default:
            return await self.default.ainvoke(input, config)
        else:
            raise ValueError(f"Route key '{key}' not found and no default route specified")


class Lambda(Chainable[Input, Output]):
    """
    Wrapper for simple functions as Chainables.

    Example:
        >>> # Wrap a function
        >>> uppercase = Lambda(lambda x: x.upper())
        >>>
        >>> # Use in chain
        >>> workflow = loader | uppercase | processor
        >>>
        >>> # Execute
        >>> result = workflow.invoke("hello")  # "HELLO"
    """

    def __init__(self, func: Callable[[Input], Output], name: str | None = None):
        """
        Initialize lambda chainable.

        Args:
            func: Function to wrap
            name: Optional name for this lambda
        """
        self.func = func
        self.name = name or func.__name__

    def invoke(self, input: Input, config: RunnableConfig | None = None) -> Output:
        """
        Execute wrapped function.

        Args:
            input: Input data
            config: Execution configuration (ignored)

        Returns:
            Function output
        """
        return self.func(input)


class Passthrough(Chainable[Input, Input]):
    """
    Identity chainable that passes input through unchanged.

    Useful as placeholder or in conditional branches.

    Example:
        >>> workflow = Conditional(
        ...     condition=lambda x: x['process'],
        ...     true_branch=processor,
        ...     false_branch=Passthrough()  # Do nothing
        ... )
    """

    def invoke(self, input: Input, config: RunnableConfig | None = None) -> Input:
        """
        Return input unchanged.

        Args:
            input: Input data
            config: Execution configuration (ignored)

        Returns:
            Input data unchanged
        """
        return input
