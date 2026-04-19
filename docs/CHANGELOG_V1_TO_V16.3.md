# Metis — Version History V1 → V16.3 Apex

A compressed engineering log of how the product evolved from a one-file
chatbot prototype into the Apex local-first autonomous AI operating system.

| Version | Theme                              | Key additions |
|--------:|------------------------------------|---------------|
| V1      | Chat-only prototype                 | Single Streamlit page, Ollama wrapper, mistral model. |
| V2      | Persistent memory                   | `memory.py` + Supabase `memory` table with RLS. |
| V3      | Cognitive loop v0                   | `memory_vault.py` (ChromaDB) + pre-prompt semantic recall. |
| V4      | Hardware awareness                  | `hardware_scanner.py` + auto tier (Lite / Pro / Sovereign). |
| V5      | Identity                            | `identity_matrix.py` personas + `build_system_prompt()`. |
| V6      | Skill registry                      | `skill_forge.py` + in-process `@register` decorator + Supabase `skills`. |
| V7      | Outreach comms                      | `comms_link.py` SMTP + Twilio SMS; lead-gen `web_researcher` + `communicator`. |
| V8      | Supabase auth + cloud sync          | `auth_engine.py`, `cloud_sync.py`, `sync_log` table. |
| V9      | Custom tools + DuckDuckGo           | `custom_tools.py` `internet_search`. |
| V10     | Hybrid fallback                     | CrewAI uses OpenAI if `OPENAI_API_KEY` present, else Ollama. |
| V11     | Glassmorphism UI stub               | Dark mode + electric cyan + Inter / Fira Code. |
| V12     | Modular strategy                    | Budget / Standard / Sovereign tier plan; `module_manager.py`. |
| V13     | Mass-market playbook                | Apple-style tier naming; never show GB on download. |
| V14     | Cognitive playbook                  | 4 Pillars loop doctrine. |
| V15     | Hybrid ecosystem                    | Supabase App Store + GitHub CI concept. |
| V16     | Apex stack                          | CrewAI swarm + Docker sandbox + Stripe marketplace. |
| V16.1   | Coder engine swap                   | Qwen 3.6 replaces DeepSeek as primary Coder. |
| V16.2   | Tri-core                            | Qwen (Coder) + GLM (Scholar) + DeepSeek (Thinker). |
| V16.3   | **Apex Golden Master** (this build) | 5-agent hierarchical swarm, Computer Use, Voice I/O, FastAPI bridge, Claude/Codex UI, `.mts` file format, Creative Studio stub, seeded marketplace. |
