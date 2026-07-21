---
id: sizing-y-liquidez
title: Tamaño de posición, liquidez y cantidades exactas
status: approved
topic: risk
---

# Sizing y liquidez

## Cantidades
Las cantidades a vender **no pueden superar** la tenencia del snapshot. El validator (F5) lo verifica de forma determinista.

## Liquidez
Instrumentos con poco volumen o spreads amplios (ciertos bonos o CEDEARs chicos) no admiten rebalanceos agresivos en un solo día. El plan debe señalar fraccionamiento o condicionamiento.

## Modo degradado
Sin `.xlsx` fresco, las cantidades finas quedan **condicionadas/bloqueadas** (staleness). Mercado puede refrescar precios vía market-data, pero las cantidades vienen del snapshot previo.
