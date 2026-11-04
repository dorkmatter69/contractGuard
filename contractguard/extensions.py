"""Future integration contracts. No cryptographic proof or payment implementation."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProofStatement:
    contract_hash: str
    artifact_hash: str
    validator_version: str
    circuit_id: str
    public_inputs_hash: str


class ProofVerifier(Protocol):
    def verify(self, statement: ProofStatement, proof: bytes) -> bool: ...


class UnavailableZKP:
    def verify(self, statement: ProofStatement, proof: bytes) -> bool:
        raise NotImplementedError('No ZKP backend configured; acceptance must fail closed')


class Payments(Protocol):
    """Provider must implement durable idempotency and ambiguous-outcome recovery."""
    def settle(self, receipt_hash: str, amount_minor: int, currency: str, key: str) -> str: ...


class DisabledPayments:
    def settle(self, receipt_hash: str, amount_minor: int, currency: str, key: str) -> str:
        raise NotImplementedError('Payments disabled; credits are not money')
