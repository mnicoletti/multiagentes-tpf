---
id: gestion-riesgo-stops
title: Criterios de gestión de riesgo y stops
status: approved
topic: risk
---

# Gestión de riesgo y stops

## Principio HITL (ADR-0001 / SPEC)
Si falta un gráfico o un nivel para definir un **stop**, el sistema debe **pedir** el input (`interrupt()` / `info_gaps`). **Prohibido inventar niveles** de stop, take-profit o invalidación.

## Tipos de stop (vocabulario)
- **Stop porcentual**: distancia fija al precio de entrada/referencia.
- **Stop técnico**: bajo un mínimo / media / zona visible en el gráfico.
- **Trailing stop**: sigue al precio a favor; requiere reglas explícitas.

## Qué debe quedar en el informe
1. Si el stop está **confirmado** (usuario aportó gráfico/nivel) vs **propuesto** (analista sugiere pedir dato).
2. Ticker afectado y razón (protección de ganancia, corte de pérdida, etc.).
3. Nunca lenguaje de ejecución (“ya puse el stop en el broker”).
