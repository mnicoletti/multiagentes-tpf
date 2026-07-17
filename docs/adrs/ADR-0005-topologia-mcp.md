# ADR-0005: Topología MCP — dos servers custom FastMCP, web search fuera de MCP, modo fixture

**Status:** Accepted · **Date:** 2026-07-15 · **Deciders:** Max (confirmado en grill)

## Context
La rúbrica pide consulta a servicio externo vía MCP (mínimos) y escritura en BD vía MCP (medios). Las APIs públicas argentinas (dolarapi, paneles) son inestables y la demo es el 22/7. El autor ya construyó servers FastMCP (`libs-mcp`), lo que baja costo y riesgo de defensa.

## Decision Drivers
- Criterio de selección explicable: **MCP donde aporta contrato tipado y reuso entre agentes; tool nativa donde el proveedor ya lo resuelve mejor**.
- Demostrar construcción de MCP, no solo consumo.
- Demo y evals reproducibles sin depender de APIs vivas.

## Options Considered
**A. Consumir un MCP de terceros** — cumple el mínimo pero demuestra menos; acopla la demo a un servicio ajeno.
**B. Todo detrás de MCP (incluida web search)** — ceremonia sin beneficio; la tool nativa del proveedor es superior para búsqueda.
**C. Dos servers custom + web search nativa** — elegida.

## Decision
1. **`portfolio-store-mcp`** (FastMCP): `read_active_constraints`, `read_last_snapshot`, `write_snapshot`, `write_report`, `list_reports` — cubre escritura ([[ADR-0003-doble-persistencia]]).
2. **`market-data-mcp`** (FastMCP): `get_fx_rates` (dolarapi MEP/CCL/oficial), `get_quotes` (panel local) — cubre consulta externa; habilita verificación cruzada del MEP implícito.
3. **Web search: tool nativa del modelo, NO MCP.**
4. **Modo fixture obligatorio en `market-data-mcp`**: flag que sirve respuestas grabadas desde disco — mismo binario, misma interfaz, fuente intercambiable. Base de los evals reproducibles y seguro anti-caída para la demo.

## Consequences
- (+) Ambos ítems MCP cubiertos con propósito de dominio real; preguntas del final sobre MCP se responden con kilometraje propio.
- (+) Demo inmune a la disponibilidad de APIs públicas.
- (−) Dos servers a mantener — mitigado: FastMCP + tools chicas y tipadas.

**Trazabilidad rúbrica:** "consulta a servicio externo mediante MCP"; "escribir en BD vía MCP"; §5 del enunciado (justificar mecanismo y trade-off por fuente).
