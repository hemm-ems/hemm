# HEMM A/B Solver Comparison Report

**Generated:** 2026-06-04T00:48:00.119372+00:00
**Total runtime:** 0.5s

## Summary

- **Scenarios tested:** 6
- **Avg cost gap (B vs A):** -1.20%
- **Avg speed ratio (B/A):** 0.54x
- **Backend A violations:** 0
- **Backend B violations:** 0
- **Backend B convergence:** 6/6

## Per-Scenario Results

| Scenario | Cost A (€) | Cost B (€) | Gap % | Time A | Time B | B Converged |
|----------|-----------|-----------|-------|--------|--------|-------------|
| onboarding | -3.45 | -3.55 | -2.8% | 0.153s | 0.047s | Yes |
| battery_arbitrage | -4.56 | -4.67 | -2.4% | 0.019s | 0.045s | Yes |
| heat_pump_shift | 0.00 | 0.00 | +0.0% | 0.010s | 0.000s | Yes |
| ev_departure | 0.00 | 0.00 | +0.0% | 0.017s | 0.000s | Yes |
| water_heater_legionella | 0.24 | 0.24 | +0.8% | 0.023s | 0.000s | Yes |
| full_house | -3.90 | -4.01 | -2.9% | 0.100s | 0.048s | Yes |

## Decision Metrics (Phase 6 Gate)

| Metric | Threshold | Result | Pass |
|--------|-----------|--------|------|
| Cost gap (avg) | < 3% | 1.20% | PASS |
| Comfort violations | B ≤ A | 0 scenarios worse | PASS |
| Plan stability | <= 1.5x A | 1.00x | PASS |
