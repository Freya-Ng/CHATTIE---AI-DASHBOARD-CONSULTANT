---
name: Use Gemini 2.5 models
description: User explicitly wants gemini-2.5-flash (not 2.0-flash) for this project
type: feedback
---

Always use `gemini-2.5-flash` as primary and `gemini-2.5-flash-lite` as fallback in settings.py.

**Why:** User explicitly instructed "FROM NOW, USE GEMINI 2.5 MODEL" and rejected a change to gemini-2.0-flash.

**How to apply:** Never downgrade the model to gemini-2.0-flash. Keep gemini-2.5-flash in SUPPORTED_PROVIDERS["gemini"]["model"].
