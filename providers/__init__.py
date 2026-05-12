"""
Metis provider adapters.

Each file exposes at least:
    chat(messages, model=None, stream=False, temperature=0.7) -> str | Generator[dict]

Providers here translate Metis's internal message format to vendor APIs so
`brain_engine.py` can stay vendor-agnostic.
"""
