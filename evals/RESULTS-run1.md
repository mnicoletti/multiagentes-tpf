# RESULTS-run1 — evidencia GATE-F7 / TC-F7-03

Fecha: 2026-07-21  
Corrida de referencia: **GC-1** Anthropic híbrido.

```
pytest evals/golden/test_gc1.py -v --tb=short -s
→ 1 passed in 213.81s
```

- Deterministas: PASS (informe + linter).
- Judge: corrida completó (umbral ≥ 4/5).
- Notas: `redactor_structure_fallback` en esa corrida; técnico/mercado stub.

Ver cierre completo en `evals/RESULTS.md`.
