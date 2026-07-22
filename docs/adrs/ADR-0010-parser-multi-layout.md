# ADR-0010: Parser multi-layout y totales declarados del bróker

**Status:** Proposed · **Date:** 2026-07-21 · **Deciders:** Max (sesión E2E real)

## Context
La fixture sintética usa un layout compacto (`Ticker|Cantidad|Precio|Total` + sección `TOTALES`) con exactitud al centavo y `cantidad × precio == total`. Los exports reales de bróker argentino traen columnas anchas (`ESPECIE`, `CANT. DISPONIBLE`, `VALOR CORRIENTE`, …), cash multi-línea (`$` + varias líneas USD), totales en cabecera (`TOTAL CARTERA…` / `TOTAL USD…`) y montos con más de 2 decimales por ruido de Excel / valuación FX.

ADR-0002 exige que el parser sea determinista y que ningún LLM toque números; no exige un único layout de archivo.

## Decision Drivers
- Poder correr el sistema contra un `.xlsx` propio sin conversión manual.
- No romper golden cases / fixture sintética (reglas estrictas intactas).
- No redondear en el sentido de “inventar” un total distinto al del bróker.

## Options Considered
**A. Script one-shot que reescribe el xlsx al layout sintético** — UX pobre; el README no puede decir “pasá tu estado”.
**B. Un solo parser estricto; exigir al usuario el formato fixture** — contradice el objetivo original del proyecto.
**C. Detección de layout + normalización a `AccountSnapshot`** — elegida.

## Decision
El parser detecta `compact` vs `broker_wide` y normaliza ambos a `AccountSnapshot` (scrub PII → `INV-001`).

| Layout | Fuente de verdad de fila | Totales | Decimales |
|---|---|---|---|
| `compact` | `cantidad × precio == total` (exacto) | Sección `TOTALES`; `Total ARS = cash_ARS + Σ posiciones` | `_quantize_cent` estricto |
| `broker_wide` | `VALOR CORRIENTE` declarado | Cabecera `TOTAL CARTERA` / `TOTAL USD`; validación `Σ valor_corriente(cash+pos) ≈ total` con tolerancia menor por float de Excel | Se aceptan los Decimal del bróker sin forzar qty×precio ni centavos |

Cash broker: `$`→ARS; líneas USD se **agregan** por `CANT. DISPONIBLE`. Filas `SUBTOTAL` se ignoran.

## Consequences
- (+) `.xlsx` propio usable; tickers nuevos entran solos al snapshot.
- (+) Fixture y tests F1 siguen verdes.
- (−) En `broker_wide` ya no hay invariante qty×precio (el bróker puede haber redondeado); la auditoría es contra el valor declarado.
- (−) Tolerancia pequeña en totales broker por float de openpyxl — documentada; no es redondeo LLM.

**Relación:** especializa ADR-0002 (parser determinista) sin debilitar la frontera agente/determinista.
