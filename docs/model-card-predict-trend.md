# Model card — predict_trend

**Status:** F5 · **Artifact:** `artifacts/ml/trend/logreg_trend.joblib`

## Qué predice
Clasificación de **tendencia de corto plazo** en tres labels: `up` | `down` | `sideways`, con probabilidad (`proba`).

API: `predict_trend(features) -> {label, proba}`.

## Con qué datos se entrenó
Dataset **sintético** (360 filas) generado en `scripts/train_trend_model.py` a partir de reglas sobre indicadores:

| Feature | Semántica |
|---|---|
| `rsi_14` | RSI 14 períodos |
| `macd_hist` | Histograma MACD |
| `sma_slope` | Pendiente de media móvil |
| `return_5d` | Retorno 5 sesiones |
| `volume_z` | Volumen estandarizado |

No usa cotizaciones reales, ni tenencias, ni PII.

## Algoritmo
`StandardScaler` + `LogisticRegression` multinomial (scikit-learn), versionado con joblib. Meta en `artifacts/ml/trend/meta.json`.

## Rol en el sistema (ADR-0002)
Es **un insumo más** del Planificador de Rebalanceo. **Nunca** es decisión autónoma: no fija stops, no viola restricciones, no sustituye al validator.

El plan debe **citar** la señal (`ml_inputs` / `ml_signal_cited`) en el razonamiento; si aparece como conclusión sin más, es un bug de diseño.
