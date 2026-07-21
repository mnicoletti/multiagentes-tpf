---
id: cedears-argentina
title: CEDEARs — representación de activos extranjeros en el panel local
status: approved
topic: instruments
---

# CEDEARs (Certificados de Depósito Argentinos)

## Qué son
Un CEDEAR representa un activo extranjero (acción, ETF) negociable en pesos o dólares en el mercado local. El **ratio de conversión** vincula cantidad de CEDEARs con la acción subyacente.

## Drivers de riesgo (no exhaustivo)
1. Precio del subyacente en su mercado de origen.
2. Tipo de cambio (MEP/CCL) cuando la valuación se piensa en USD.
3. Liquidez y spread del CEDEAR vs el subyacente.
4. Riesgo regulatorio / custodia local.

## Implicancia para clustering

El extracto agrupa por **sección contable** (ACCIONES, BONOS, CEDEARS).
Eso **no** es un criterio de riesgo.

- Incorrecto: cluster “CEDEARS” = {VIST, AAPL, MELI, SPY}
  (comparten hoja del Excel, no el mismo shock).
- Correcto: cluster “energía argentina” = {YPFD, VIST}
  aunque YPFD esté en ACCIONES y VIST en CEDEARS.

Regla: agrupar por **driver de riesgo** (qué las mueve juntas),
nunca por la etiqueta de sección del estado de cuenta.