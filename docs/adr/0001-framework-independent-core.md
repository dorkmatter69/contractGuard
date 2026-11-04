# ADR 0001: Framework-independent authority

Status: accepted.

Context: Deep Agents and DeepSeek Harness have different orchestration and lifecycle models. Prompt instructions cannot enforce permissions.

Decision: Keep mandate authority, ledger, evidence and acceptance in a standard-library core. Expose explicit identity-bound bridges; preserve Mandate/Ticket/Assignment concepts rather than treating DSH as LangChain middleware.

Consequences: Core runs offline and can be tested without LLMs. Native schema transport and complete SDK interception remain integration work. An in-process bridge is not a credential or process security boundary.
