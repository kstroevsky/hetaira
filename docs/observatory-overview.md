# Observatory Overview v1

The Overview is the primary analytical surface. It is a content-hashed projection of one immutable corpus snapshot; the message timeline remains an evidence debugger.

Every Overview build creates:

- one `AnalysisRun` and idempotent task fingerprinted by snapshot manifest and analysis version;
- nine independent `MeasurementResult` records;
- descriptive `Finding` records linked to their source measurements;
- one `AnalyticalArtifact` containing the compact dashboard model;
- derivation edges from measurements to findings and the artifact.

## Current dimensions

### Source and temporal structure

Monthly message counts use resolved source timestamps. Change points are large month-to-month log-count movements measured against the median absolute deviation of all movements. They are anomaly markers, not causal events. Edge months may be incomplete.

Telegram HTML exports lack timezone offsets. Hetaira preserves the original local timestamp and records UTC only as a reversible placeholder with reduced resolution confidence.

### Participation

The Overview exposes message shares, Shannon entropy, normalized entropy, and the Gini coefficient. These describe contribution volume and balance only. They are not measures of influence, expertise, power, or conversation quality.

### Reply structure

Only `explicit=true`, `relation_type=REPLIES_TO` relations with both endpoints in the snapshot enter reciprocity and latency calculations. Reply markers whose targets are absent from the export remain visible as missing data. Response latency excludes negative values and values over 30 days from the displayed latency sample.

### Interaction network

The directed participant graph is weighted by explicit reply counts. The Overview reports PageRank, directed betweenness, degree, and weighted undirected multilevel communities. These are interaction-centrality and interaction-community measurements—not intellectual influence, persuasion, power, or position coalitions.

### Functional profiles

Provisional profiles combine message volume, question rate, reply rate, attention received, and interaction betweenness. Labels such as `broker-like`, `response-oriented`, and `attention hub` describe behavior in this snapshot. They are not permanent roles or personality labels.

### Lexical evolution

Russian tokens are counted by message-level document frequency. Frequent terms are connected by within-message co-occurrence and grouped into navigation clusters. These are lexical navigation aids, not validated semantic topics, beliefs, or topic prevalence estimates. Arbitrary first/second-half comparisons are deliberately excluded.

### Conversation-health primitives

The current vector contains participation balance, resolved reply targets, dyadic reciprocity, response latency, and session count. It deliberately has no aggregate score. Semantic responsivity, grounding, repair, constructiveness, and goal progress remain missing until their Russian validation gates pass.

## Epistemic boundary

Overview findings are `L2_MEASUREMENT` with `descriptive` causal status. Each finding shows at least one alternative explanation and links to exact source evidence when available. No current Overview output supports causal, clinical, personality, influence, persuasion, or power claims.
