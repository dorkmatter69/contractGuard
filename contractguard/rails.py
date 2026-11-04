"""Extension boundaries: identity discovery never grants spend authority."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AgentRegistryReference:
    chain_id: int
    registry: str
    agent_id: int


class AgentIdentityResolver(Protocol):
    """Future ERC-8004 registry lookup; ownership is not task authorization."""
    def owner(self, reference: AgentRegistryReference) -> str: ...


class PayPerUseRail(Protocol):
    """Future x402 buyer gateway: reserve first, verify exact quote and supplier.

    Implementations must bind chain/token/amount/payee/expiry/resource to the
    authorized commitment and reconcile ambiguous outcomes, never auto-sign a 402.
    """
    def purchase(self, commitment_id: str, signed_quote: bytes) -> str: ...


class UnavailableRail:
    def purchase(self, commitment_id: str, signed_quote: bytes) -> str:
        raise NotImplementedError('x402 supplier/facilitator integration is not configured')
