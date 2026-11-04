"""Explicit bridges, not automatic harness interception or identity verification."""
from dataclasses import dataclass
from .core import Guard, Mandate


@dataclass(frozen=True)
class DeepAgentsAdapter:
    guard: Guard
    mandate: str
    agent: str  # Bound by the trusted host; never accepted from an LLM argument.

    def call(self, tool: str, arguments: dict, invocation_id: str):
        """Host routes a framework tool call here with its stable invocation ID."""
        return self.guard.execute(self.mandate, self.agent, tool, arguments, invocation_id)


@dataclass(frozen=True)
class DeepSeekHarnessAdapter:
    guard: Guard

    def admit(self, mandate: Mandate, ticket: str, assignment: str, validator: str):
        """Map normalized native records; operator authenticates admission upstream.

        Each step is durable but the bridge is not one atomic transaction. Duplicate
        admission raises a uniqueness error; inspect persisted records on recovery.
        No parsing of untrusted issue text into authority happens here.
        """
        self.guard.issue(mandate)
        self.guard.create_ticket(ticket, mandate.id, validator)
        self.guard.assign(assignment, ticket, mandate.agent, mandate.expires)
