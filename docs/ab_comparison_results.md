# HEMM A/B Solver Comparison Report

**Generated:** 2026-05-11T05:39:09.412446+00:00
**Total runtime:** 6.2s

## Summary

- **Scenarios tested:** 6
- **Avg cost gap (B vs A):** +96.20%
- **Avg speed ratio (B/A):** 0.10x
- **Backend A violations:** 0
- **Backend B violations:** 0
- **Backend B convergence:** 1/6

## Per-Scenario Results

| Scenario | Cost A (€) | Cost B (€) | Gap % | Time A | Time B | B Converged |
|----------|-----------|-----------|-------|--------|--------|-------------|
| onboarding | -3.45 | -4.65 | -34.8% | 3.578s | 0.078s | No |
| battery_arbitrage | -4.56 | -1.77 | +61.1% | 0.282s | 0.047s | Yes |
| heat_pump_shift | 0.00 | 13.38 | +100.0% | 0.906s | 0.062s | No |
| ev_departure | 0.00 | 3.42 | +100.0% | 0.250s | 0.016s | No |
| water_heater_legionella | 0.00 | 0.43 | +100.0% | 0.125s | 0.016s | No |
| full_house | -4.13 | 6.23 | +250.9% | 0.750s | 0.093s | No |

## Decision Metrics (Phase 6 Gate)

| Metric | Threshold | Result | Pass |
|--------|-----------|--------|------|
| Cost gap (avg) | < 3% | 96.20% | FAIL |
| Comfort violations | B ≤ A | 0 scenarios worse | PASS |
| Plan stability | <= 1.5x A | 1.00x | PASS |
