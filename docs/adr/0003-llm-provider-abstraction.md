# ADR-0003 — LLM provider abstraction; Ollama over stdlib HTTP; no vendor SDK in the engine

- Status: Accepted
- Date: 2026-07-09
- Phase: 0

## Context

Legacy `core/llm.py` was hardwired to Ollama through `langchain-ollama` /
`langchain-community`. That couples the domain core to both a specific vendor and
a large, fast-moving framework — violating "LLM vendors belong behind
interfaces/adapters" and "minimal vendor lock-in", and adding heavy dependencies.

## Decision

Define `ats_engine.providers.LLMProvider`, a `Protocol` with `identity` (a stable
string used as a cache key) and `complete(prompt) -> str`. Domain code depends
only on this interface plus two helpers (`generate_text`, `generate_json`) that
add content-hash caching and JSON self-repair. The bundled `OllamaProvider`
implements the Protocol by calling Ollama's `/api/chat` endpoint **directly over
the Python standard library** (`urllib`) — no LangChain, no SDK.

Provider output is always treated as untrusted and re-validated by the
deterministic gates. Every step works with `provider=None` (deterministic
fallback), so a missing model is a normal state.

## Consequences

- The engine has **zero** LLM-vendor SDK dependencies; adding OpenAI/Anthropic/
  Azure later means adding a sibling adapter, with no change to domain code.
- Dropping LangChain removes a large, frequently-breaking dependency and its
  transitive weight.
- Decoupling providers from the cache key (`identity`) keeps caching correct
  across models and decoding parameters.
- We own the small amount of HTTP/JSON plumbing that the SDK previously provided;
  this is a deliberate, low-risk trade for portability and independence.
