# Validation gates

- `gold-ru-v1`: 1,200 stratified utterance/exchange units; 30% double-annotated; complete-episode 60/20/20 split.
- Span extraction: exact and overlap F1.
- Labels: macro/micro F1; relations: endpoint-aware F1.
- Calibration: ECE and Brier score.
- Promotion: five-point macro-F1 non-inferiority margin against a trained annotator, plus task floor (0.80 simple classification, 0.70 difficult span/relation tasks).
- Retrieval: at least 300 Russian queries and recall@20 ≥ 0.90 before evidence-backed synthesis promotion.
- Any failed task remains `provisional` and cannot feed an unqualified composite finding.
- Forecasting uses forward-time validation only.
- Pivotalness cannot ship before the associated forecaster is calibrated and prospectively validated.
