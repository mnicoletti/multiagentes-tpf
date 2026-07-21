---
id: clustering-drivers-riesgo
title: Marco de clustering por drivers de riesgo
status: approved
topic: clustering
---

# Clustering semántico por driver de riesgo

## Principio
Una radiografía útil agrupa posiciones que **se mueven juntas** ante el mismo shock, no las que comparten hoja del Excel (ACCIONES / BONOS / CEDEARS).

## Ejemplos de drivers
- Energía argentina (upstream/downstream, regulación local, crudo)
- Banca / ciclo doméstico
- Tecnología global vía CEDEAR
- Crédito soberano
- Liquidez / cash en ARS o USD

## Reglas de cobertura
1. Cada ticker del snapshot en **exactamente un** cluster.
2. Ningún cluster vacío.
3. El peso del cluster se calcula **afuera del LLM** (suma de totales / total_ars).

## Anti-patrón
“Cluster CEDEARS” o “Cluster acciones” = falla de diseño. Preferir nombres como “energía argentina” aunque mezcle YPFD (acción) y VIST (CEDEAR).
