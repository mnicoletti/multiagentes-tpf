# ADR-0011: Cerrar injection vía ticker / campos del `.xlsx`

**Status:** Proposed · **Date:** 2026-07-22 · **Deciders:** Max (análisis de seguridad post-E-3)

## Context
ADR-0006 documenta dos vectores de prompt injection (resultados web; texto incrustado en imágenes) y los trata en la capa de prompts como *dato no confiable*. La capa de entrada valida estructura/totales y scrubbea PII, pero **no acota el contenido textual** de campos que el parser sí materializa en el snapshot.

Hoy `Position.ticker` es un `str` libre: el parser hace `_cell_str(...).upper()` sin allowlist. Ese valor entra al `snapshot_block` de Planificador y Redactor como:

```text
- {ticker} [ASSET_CLASS] qty=… price=… total=…
```

Un adversario (o un `.xlsx` malicioso) puede poner en la columna `ESPECIE`/`ticker` texto del estilo *«Ignorá todas tus instrucciones y …»*. Ese texto **llega al LLM** sin el wrapping de “dato no confiable” que sí tienen web/RAG. `user_notes` (`--notes`) es un vector hermano, aún más directo.

Lo que **no** está en juego: robar o “usar” la API key del dueño como secreto (vive en env/header, fuera del prompt). Sí está en juego: sesgar el razonamiento del modelo y **consumir tokens/cuota** del dueño vía corridas largas o reintentos.

## Decision Drivers
- Coherencia con ADR-0002: el borde de entrada es código puro; no delegar el filtro a un prompt.
- Completar ADR-0006: el `.xlsx` también es superficie de injection, no solo web/imagen.
- No romper layouts reales (`broker_wide`, tickers tipo `AL30`, `GGAL`, `AAPL.BA` si aplica).
- Defensa medible con assert determinista (mismo espíritu que E-3).

## Options Considered
**A. Solo wrapping en prompts** (“ticker = dato no confiable”) — barato; sigue siendo probabilístico; no corta el gasto de tokens si el modelo entra en loop.
**B. Allowlist / schema estricto en el parser** — rechazo determinista antes de cualquier LLM; tickers fuera de patrón → `MalformedStatementError`.
**C. Heurística de jailbreak + budget de tokens por `run_id`** — complementa B; atrapa frases hostiles en `user_notes` y acota costo.
**D. A + B + C (defense-in-depth)** — elegida como dirección; implementar en fases.

## Decision (esbozo — a confirmar)
Extender la **capa de entrada** de ADR-0006 para campos textuales del snapshot y notas del usuario:

1. **Allowlist de ticker (determinista, parser):** patrón acotado, p.ej. `^[A-Z0-9.]{1,12}$` (ajustar tras muestrear tickers reales BYMA/CEDEAR). Falla → rechazo limpio, mismo camino que E-4 (xlsx malformado).
2. **Tratamiento untrusted en prompts:** el `snapshot_block` y `user_notes` se envuelven con el mismo contrato que web/RAG (*se analiza, no se obedece*). No sustituye (1).
3. **Heurística opcional en `user_notes`:** denylist de marcadores (`ignorá instrucciones`, `system override`, `ignore all previous`, …) → rechazo o `interrupt()` HITL con mensaje explícito; no inventar “sanitizado” silencioso.
4. **Budget de corrida (opcional, observabilidad):** tope de tokens/reintentos por `run_id` para que una injection no dispare costo abierto.
5. **Eval:** escenario **E-5** (o extensión de E-4): fixture `.xlsx` con ticker hostil; assert de rechazo en parser **o**, si se opta por aceptar+wrap, assert de que el plan no obedece la instrucción (espejo de `check_no_full_ggal_sell_from_injection`).

Fuera de alcance de este ADR: clasificador ML de jailbreak, auth multiusuario, filtrado semántico general del informe.

## Consequences
- (+) Cierra el hueco “campo estructurado ≠ untrusted” que ADR-0006 dejó implícito.
- (+) Testeable sin LLM (`MalformedStatementError` / assert E-5).
- (+) Alineado con “lo verificable se verifica con código”.
- (−) Allowlist demasiado estricta puede rechazar tickers legítimos raros → hay que calibrar con corpus BYMA antes de Accepted.
- (−) Heurística de frases es incompleta por diseño; solo complemento.
- (−) Wrapping en prompts solo mitiga; no garantiza.

## Relación
- Especializa [[ADR-0006-guardrails-tres-capas]] (nuevo vector de entrada).
- No debilita [[ADR-0002-frontera-agente-determinista]] ni [[ADR-0010-parser-multi-layout]].
- Eval emparentada con [[ADR-0007-estrategia-evaluacion]] (familia E-3 / E-4).

**Trazabilidad rúbrica:** "Prompt Injection"; "Guardrails. Consideraciones de seguridad mínima"; trabajo futuro / limitaciones.
