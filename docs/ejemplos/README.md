# Carteras comitentes de ejemplo

Estados de cuenta **sintéticos y anonimizados** para probar PortfolioSentinel de punta a punta sin usar datos personales. Replican el layout `broker_wide` de un export real de bróker argentino (columnas `ESPECIE`, `CANT. DISPONIBLE`, `VALOR CORRIENTE`, totales de cabecera `TOTAL CARTERA` / `TOTAL USD`, cash multi-línea ARS+USD), por lo que los consume el parser multi-layout (ADR-0010) igual que un archivo real.

Titulares y comitentes son ficticios; el parser scrubbea la PII a `INV-001` de todos modos. MEP usado para valuar el cash USD: `≈ 1509.85`. Fecha de corte: `2026-07-21`. Los cuatro fueron validados con `parse_account_statement` (layout `broker_wide`, totales dentro de tolerancia, sin errores).

## Perfiles incluidos

| Archivo | Perfil | Posiciones | Total ARS | Concentración top | Para qué sirve |
|---|---|---|---|---|---|
| `comitente-01-conservador-hard-dollar.xlsx` | Conservador, dolarizado | 7 | ~41.15 M | AL30 20.5% · GD35 15.9% | Cartera diversificada y hard-dollar; baja concentración en equity AR. Diagnóstico esperado: perfil defensivo, sin alertas fuertes. |
| `comitente-02-agresivo-energia.xlsx` | Agresivo, concentrado en energía AR | 8 | ~27.56 M | **YPFD 61.4%** · PAMP 7.5% | Riesgo single-name extremo (energía). Ejercita el diagnóstico de hiperconcentración y la acción de desconcentrar. Buen caso "tentación" para el loop Planificador↔Validator. |
| `comitente-03-diversificado-cedears.xlsx` | Diversificado, US tech vía CEDEARs | 12 | ~26.68 M | NVDA 9.1% · GD35 7.5% | Cartera balanceada (acciones AR + bonos + CEDEARs tech). Screening y clustering por driver sobre una cartera amplia. |
| `comitente-04-cartera-inicial.xlsx` | Cartera chica / inicial | 5 | ~2.13 M | AL30 24.2% · SPY 11.1% | Cartera mínima. Verifica el parser y el flujo con pocas posiciones y montos bajos. |

## Cómo usarlos

```bash
# Corrida directa contra un ejemplo (market fixture, sin APIs vivas)
python -m portfoliosentinel.cli run \
  --xlsx docs/ejemplos/comitente-02-agresivo-energia.xlsx \
  --market-fixture --confirm-constraints

# O vía Makefile
make run XLSX=docs/ejemplos/comitente-03-diversificado-cedears.xlsx
```

## Composición por instrumento

**01 — Conservador hard-dollar:** cash ARS 1.85 M + USD (8 200 divisa, 3 100 renta); ACCIONES GGAL, PAMP; BONOS AL30 (grande), GD35, GD38; CEDEARS SPY, GLD (defensivos).

**02 — Agresivo energía:** cash bajo (ARS 420 k, USD 900); ACCIONES YPFD (dominante), PAMP, CEPU, TGNO4, METR; BONOS GD35 (chico); CEDEARS VIST (energía), XLU (utilities).

**03 — Diversificado CEDEARs:** cash ARS 1.2 M + USD (4 500 + 1 800); ACCIONES BMA, GGAL, PAMP; BONOS GD35, AL30; CEDEARS AAPL, NVDA, GOOGL, AMZN, QQQ, SPY, GLD.

**04 — Cartera inicial:** cash ARS 280 k + USD 350; ACCIONES GGAL, PAMP; BONOS AL30; CEDEARS SPY, AAPL.

## Regeneración

Estos archivos se generan con un script determinista (`scripts/gen_ejemplos.py` si se versiona) que computa `VALOR CORRIENTE = cantidad × precio`, arma los subtotales y el `TOTAL CARTERA` como suma exacta (cash valuado + posiciones), de modo que la validación de totales del parser pasa dentro de la tolerancia. Los precios son plausibles al 2026-07-21 pero no representan cotizaciones reales.

> Nota de privacidad: ninguno de estos archivos contiene datos personales reales. Son carteras inventadas con fines de demostración y evaluación.
