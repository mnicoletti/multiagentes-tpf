---
id: mep-ccl-fx
title: Dólar MEP y CCL — contado con liquidación y MEP bursátil
status: approved
topic: instruments
---

# MEP y CCL

## Definiciones operativas
- **MEP (dólar bolsa)**: se obtiene operando activos que permiten pasar de ARS a USD en cuenta local.
- **CCL (contado con liquidación)**: similar pero con liquidación en el exterior / otra forma de acceso a USD.

## Por qué importa al sistema
El extracto deriva un **MEP implícito** = total_ARS / total_USD. Ese valor se **contrasta** con el MEP de mercado (vía market-data-mcp). Una divergencia por encima del umbral configurable genera **warning** en el estado/informe.

## Criterio
El sistema **no redondea** ni deja que un LLM “corrija” el MEP. Los números salen del parser y de la API/fixture.
