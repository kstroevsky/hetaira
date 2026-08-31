# Observatory Overview v1

The Overview is the primary analytical surface. It is a content-hashed projection of one immutable corpus snapshot; the message timeline remains an evidence debugger.

Every Overview build creates:

- one `AnalysisRun` and idempotent task fingerprinted by snapshot manifest and analysis version;
- ten independent `MeasurementResult` records;
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

### Provisional semantic themes

The semantic explorer preserves the versioned eight-hour structural episodes, then splits long episodes into deterministic windows of at most 40 consecutive messages. This prevents one long, multi-topic session from becoming a single semantic unit. Russian text is lemmatized with `pymorphy3`, represented by TF-IDF unigrams and bigrams, compressed with truncated SVD, and normalized before K-means clustering. The cluster count is selected from bounded candidates using cosine silhouette; candidates that create clusters smaller than 1% of windows (minimum two) are rejected. Silhouette evaluation is deterministically sampled at 2,000 windows to keep large local corpora tractable. Theme labels rank terms by their TF-IDF distinctiveness from the corpus-wide centroid rather than raw frequency.

For each theme the artifact preserves:

- characteristic terms and the automatically generated navigation label;
- episode and message counts;
- monthly message share rather than an arbitrary corpus midpoint;
- robust month-to-month change candidates and the number of subsequent months for which the direction persists;
- participant composition using source display names;
- three typical episodes and a message selected by TF-IDF proximity to the theme centroid as inspectable evidence.

The theme layer is `provisional_semantic_navigation`. Its labels are not human-validated topics, its monthly shifts do not establish causes, and participation inside thematic episodes is not authorship, expertise, or influence. A later embedding challenger and adjudicated Russian evaluation set can replace or complement this baseline without changing the public artifact contract.

The UI exposes cosine silhouette as an internal separation diagnostic and labels values below `0.10` as low separation, `0.10–0.20` as moderate, and `≥0.20` as high. These are conservative navigation heuristics, not universal scientific thresholds. Low-separation themes remain explorable but cannot automatically create a top-level `Finding`; their change candidates must be checked from representative source messages.

### Conversation-health primitives

The current vector contains participation balance, resolved reply targets, dyadic reciprocity, response latency, and session count. It deliberately has no aggregate score. Semantic responsivity, grounding, repair, constructiveness, and goal progress remain missing until their Russian validation gates pass.

## Epistemic boundary

Overview findings are `L2_MEASUREMENT` with `descriptive` causal status. Each finding shows at least one alternative explanation and links to exact source evidence when available. No current Overview output supports causal, clinical, personality, influence, persuasion, or power claims.
