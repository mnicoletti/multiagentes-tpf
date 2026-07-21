---
id: panel-local-vs-subyacente
title: Panel local versus subyacente — gaps de precio y arbitraje imperfecto
status: approved
topic: instruments
---

# Panel local vs subyacente

## Por qué divergen
CEDEARs y ADRs/acciones originales pueden cotizar con prima/descuento por:
- FX (MEP/CCL)
- Horarios de mercado distintos
- Liquidez local
- Impuestos y fricciones operativas

## Lectura para el Analista de Mercado
Al citar un precio de panel local, aclarar la **fuente** (fixture o API). No mezclar un last en ARS con un target en USD sin pasar por el FX explícito del market-data.

## Relación con MEP implícito
Si el extracto valúa en ARS y USD de forma inconsistente con el MEP de mercado, priorizar el **warning de divergencia** antes de proponer rotaciones grandes.
