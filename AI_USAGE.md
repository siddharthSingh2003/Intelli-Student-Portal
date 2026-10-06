# AI-usage disclosure

| Part | AI assistant used | How it was verified |
|---|---|---|
| Initial scaffold of all modules | Claude | Each owner read, ran and modified their module; unit tests per layer; every member can explain their code |
| Synthetic student data | qwen2.5:7b-instruct (local) | Pydantic schema, validation script, correction log, hand-checked edge cases |
| Evaluation questions | Written by the team | Expected answers hand-verified against the source documents |

Fill in the details honestly for anything else (Copilot completions, prompt drafting, debugging help).
