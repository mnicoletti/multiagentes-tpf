# RESULTS-run2 — evidencia GATE-F7 / TC-F7-03

Fecha: 2026-07-21  
Corrida de referencia: **GC-2** Anthropic híbrido (post `enrich_restricted_mitigations`).

```
pytest evals/golden/test_gc2.py -v --tb=short -s
→ 1 passed in 209.83s
```

- Deterministas: restricción YPFD + riesgo/mitigación + 7 secciones: PASS.
- Judge: faithfulness=5, relevancy=5, completitud=5, avg=5.00.
- Redactor LLM: informe ~23k chars, `used_fallback=false`, linter approved.

Ver cierre completo en `evals/RESULTS.md`.
