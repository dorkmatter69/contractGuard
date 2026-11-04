# ADR 0003: Layered evidence, no simulated cryptographic success

Status: accepted.

Context: Hashes, validator results, signatures and ZK proofs establish different claims.

Decision: Ship local hash-linked receipts and deterministic artifact validation. Define a ZKP statement interface binding contract/artifact/validator/circuit/public inputs; unavailable backend raises. Payments are optional and disabled. Blockchain is deferred.

Consequences: The demo is honest about what it proves. Local receipts are neither signed nor externally anchored. Future proof verification must additionally authenticate circuit/version and statement binding and integrate with acceptance before any proof-required task can be supported. Do not mark tasks as ZKP-required today: no such acceptance mode exists.
