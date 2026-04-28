# Fuzzy Meta Pattern Reading Notes

## Mannila et al. 1997: Discovery of Frequent Episodes in Event Sequences

- PDF: `01_mannila_frequent_episodes_1997.pdf`
- Text: `01_mannila_frequent_episodes_1997.txt`
- Status: keep. This paper is useful for `hprofile`.
- Thesis citation: yes.
- Future paper citation: yes.

### Problem

The paper studies how to discover frequent episodes from a timestamped event
sequence. An episode is a partially ordered collection of event types that occur
close to each other in time.

This is directly relevant to `hprofile` because our machine-level runtime trace
is also a timestamped event sequence, except that our event type can include
process, device, stream, category, and normalized label.

### Core Representation

The paper models an event as:

```text
(event_type, timestamp)
```

An episode is:

```text
episode = (V, partial_order, label_mapping)
```

Important episode classes:

- serial episode: ordered events, such as `A -> B`;
- parallel episode: events co-occur in a window, order not constrained;
- partially ordered episode: some events are ordered, others can vary.

The partial-order idea is the main takeaway for us. Our distributed runtime
patterns should not require strict equality of full event sequences. A collective
meta pattern can be represented as a partially ordered or graph-like structure:

```text
NotifyWait_end -> EventWait_start
```

with optional compute events around it.

### Frequency, Support, and Confidence

The WINEPI method counts in how many fixed-width windows an episode occurs.

Useful concepts:

- `window_width`: maximum time span in which events must appear;
- `frequency`: fraction of windows containing the episode;
- `episode rule`: `beta -> alpha`;
- `confidence`: occurrence ratio of a superepisode given a subepisode.

Mapping to `hprofile`:

```text
beta  = source-side synchronization event
alpha = source-side synchronization event + target-side wait event
confidence = how often the source event predicts the target event within delta
```

This can be used to rank candidate cross-rank synchronization edges.

### Minimal Occurrences

The MINEPI method uses minimal occurrences instead of fixed windows. A minimal
occurrence is the shortest interval in which an episode occurs.

This is highly relevant because runtime traces have dense events and overlapping
windows. Fixed-window counting can over-count repeated micro-events. Minimal
occurrence support is closer to what we need for repeated synchronization steps:

```text
minimal occurrence = shortest interval containing one candidate synchronization motif
```

For `hprofile`, minimal occurrences can become step boundaries:

```text
[step_start, step_end) = minimal interval covering a collective anchor pattern
```

### Why It Helps hprofile

This paper gives us a principled non-vLLM-specific basis for fuzzy pattern
discovery:

1. Workload-agnostic event types.
2. Time-window based co-occurrence.
3. Partial order rather than strict sequence equality.
4. Support/confidence for ranking discovered rules.
5. Minimal occurrence intervals for avoiding excessive over-counting.

### Limitations for Our Case

The paper is useful but not sufficient by itself.

Main gaps:

- It assumes one event sequence, while we have process-device-stream topology.
- It does not model temporal graphs directly.
- It does not handle duration-rich events as a first-class concern.
- It mostly works with symbolic event types, while we also need numeric features:
  duration, skew, wait/comm/exec ratio, event density.
- It discovers episodes, but does not directly cluster approximate variants with
  soft compute regions.

Therefore, Mannila et al. is best used as the episode-mining foundation, not the
complete algorithm.

### Proposed hprofile Experiment

Use `analyzer/out/20260422_163744` as the first test case.

1. Build an event stream from integrated profile:

```text
event_type = (
  process_key,
  device_id,
  stream_id,
  semantic_category,
  normalized_label_family
)
```

2. Start with anchor-only episodes:

```text
A = Notify Wait end on node_i
B = EVENT_WAIT start on node_j
episode = A -> B within delta
```

3. Count support and confidence:

```text
support(A -> B) = number of minimal intervals containing A then B
confidence(A -> B) = support(A -> B) / support(A)
```

4. Keep high-support, high-confidence edges as candidate synchronization edges.

5. Group edges by repeated time windows to form collective meta pattern
   candidates.

### Keep / Drop Decision

Keep.

This paper should be cited in the thesis as the theoretical basis for temporal
episode mining and non-strict pattern discovery in event sequences. It should not
be presented as a complete solution for machine-level accelerator traces; our
extension is to combine episode mining with process-device-stream keys, temporal
graph motifs, and soft-region features.

## Paranjape et al. 2017: Motifs in Temporal Networks

- PDF: `02_paranjape_temporal_motifs_2017.pdf`
- Text: `02_paranjape_temporal_motifs_2017.txt`
- Status: keep. This paper is highly relevant for cross-process / cross-device
  synchronization motifs.
- Thesis citation: yes, if we include collective meta pattern in the thesis.
- Future paper citation: yes.

### Problem

The paper defines and counts motifs in temporal networks. A temporal network is
a set of timestamped directed edges:

```text
(u, v, t)
```

A delta-temporal motif is a time-ordered sequence of edges that occurs within a
bounded duration:

```text
t1 < t2 < ... < tl
tl - t1 <= delta
```

This maps naturally to our cross process/device/stream synchronization analysis.

### Core Representation

The paper's temporal graph:

```text
T = {(u_i, v_i, t_i)}
```

Our mapping:

```text
node = (process_key, device_id, stream_id)
edge = inferred temporal relation between runtime events
     = (source_node, target_node, timestamp, relation_type)
```

Examples of edge types in `hprofile`:

- `notify_end_to_event_wait_start`
- `event_record_to_event_wait`
- `comm_end_to_wait_start`
- future: `runtime_api_to_device_event`

### Why It Helps hprofile

This paper gives a formal foundation for the graph side of fuzzy meta pattern
discovery:

1. It treats patterns as small temporal subgraphs, not flat sequences.
2. It requires edge order and a bounded time window.
3. It supports repeated edges between the same node pair.
4. It gives a natural way to model cross-stream and cross-process relations.
5. It is workload-agnostic.

For our collective pattern:

```text
rank/process/device/stream = node
NotifyWait/EventWait time-pair = temporal edge
one all-reduce micro-step = small temporal motif
```

### Difference from Mannila et al.

Mannila et al. is better for event episodes in one sequence:

```text
A then B within window
```

Paranjape et al. is better for temporal relations between entities:

```text
u -> v at t1, v -> w at t2, ... within delta
```

For `hprofile`, the two should be combined:

- use episode mining to discover candidate event relations;
- convert repeated relations into temporal graph edges;
- count/cluster temporal graph motifs on process-device-stream nodes.

### Limitations for Our Case

The paper is useful but still not the complete solution.

Main gaps:

- It focuses on counting exact temporal motifs, not clustering approximate
  variants.
- It treats edges as timestamped instantaneous links; our raw runtime events have
  durations.
- It counts motifs but does not necessarily enumerate every occurrence in the
  form needed for source attribution.
- It does not model soft compute regions around hard synchronization anchors.

Therefore, it should be used as the foundation for cross-node temporal motif
representation and counting, while our extension handles approximate matching,
duration-rich events, and soft-region features.

### Proposed hprofile Experiment

Use `analyzer/out/20260422_163744`.

1. Build candidate temporal edges:

```text
node = (process_key, device_id, stream_id)
edge = (node_i, node_j, t, relation_type, delta_t)
```

2. Start with one relation type:

```text
notify_wait_end -> event_wait_start
```

3. Group temporal edges by a delta window, such as 5us, 20us, 100us, or a
data-driven percentile threshold.

4. Count simple motifs:

```text
2-node repeated edge motif
3-node star motif
4-node collective synchronization motif
```

5. For each motif occurrence, attach soft-region features from nearby compute
events.

6. Compare motif counts with manual Perfetto observations.

### Keep / Drop Decision

Keep.

This paper should be cited for temporal graph motif modeling. It gives a strong
formal basis for treating collective synchronization as a repeated temporal
subgraph in a machine-level runtime profile.

### Core hprofile Method Hypothesis

The useful abstraction is two-layered:

```text
Layer 1: global event sequence
  Merge all process/device/stream events into one machine-level timeline.

Layer 2: temporal graph
  Extract cross-stream/process/device synchronization relations from the global
  event sequence.
```

In this graph:

```text
node = (process_key, device_id, stream_id)
edge = inferred synchronization or communication relation at time t
```

Example edges:

```text
NotifyWait end  -> EVENT_WAIT start
EVENT_RECORD    -> EVENT_WAIT
comm end        -> wait start
```

This changes the core question from:

```text
Does one stream repeat the same kernel sequence?
```

to:

```text
Does the whole machine repeatedly form a similar synchronization topology?
```

This is important because in distributed LLM inference the compute region can be
unstable due to batching, shape, KV-cache state, and runtime branches. In
contrast, the communication/synchronization skeleton is often determined by the
parallel strategy and collective communication pattern, and is therefore more
stable. Temporal graph motifs are a good foundation for finding these stable
synchronization skeletons.

## Tax et al. 2016/2017: Mining Local Process Models

- PDF: `03_tax_local_process_models_2016.pdf`
- Text: `03_tax_local_process_models_2016.txt`
- Status: keep as a quality/ranking reference. Do not directly implement the
  full process tree / Petri net algorithm for `hprofile` at this stage.
- Thesis citation: optional but useful if we discuss local pattern quality.
- Future paper citation: yes.

### Problem

The paper studies how to discover frequent local behavioral patterns in event
logs. A Local Process Model (LPM) is smaller than a full start-to-end process
model, but richer than a simple sequential pattern. It can express:

- sequence;
- concurrency;
- exclusive choice;
- loops.

This is conceptually relevant because `hprofile` also wants local runtime
patterns, not a full model of the entire machine execution.

### Core Representation

The paper represents local patterns as process trees / Petri nets. This is more
formal and heavier than what we likely need for accelerator traces.

For `hprofile`, the analogous object is not necessarily a Petri net. It is more
likely:

```text
LocalRuntimePattern = hard-anchor temporal graph + soft-region feature summary
```

However, LPMs help justify why local pattern mining is preferable to global
process discovery when traces are noisy and unstructured.

### Most Useful Takeaway: Quality Dimensions

The paper defines five quality dimensions:

1. support;
2. confidence;
3. language fit;
4. coverage;
5. determinism.

These map well to our fuzzy meta patterns:

```text
support      -> how many times the motif occurs
confidence   -> how reliably an anchor predicts the full motif
coverage     -> how much event time or event count the motif explains
determinism  -> how predictable the continuation is after seeing a prefix/anchor
language fit -> whether the pattern overgeneralizes too much
```

For `hprofile`, possible metrics:

```text
support(pattern) =
  number of motif occurrences

coverage(pattern) =
  total duration or event count covered by occurrences / run total

confidence(anchor -> pattern) =
  matched occurrences of full motif / occurrences of anchor

determinism(pattern) =
  1 / average number of plausible next edges or next event families

soft_fit(pattern) =
  similarity of soft-region features across occurrences
```

This is likely more useful than the paper's full process-tree search.

### Why It Helps hprofile

This paper gives language for a key argument:

> A full distributed runtime trace may be too unstructured to model from start
> to end, but frequent local patterns can still be meaningful and actionable.

This fits our situation exactly. We do not need to discover a full process model
for all vLLM/NPU runtime activity. We need to find local repeated
synchronization and execution structures that explain important wait/comm time.

### Limitations for Our Case

- Business-process event logs are case-based; profiling traces are continuous
  machine timelines.
- LPM discovery assumes activity sequences; we need process-device-stream
  topology and temporal edges.
- Petri nets and process trees are expressive but likely too heavy for the first
  `hprofile` implementation.
- The paper focuses on mining process models, not source-level performance
  diagnosis.

### Proposed hprofile Use

Do not implement full Local Process Model discovery first.

Instead:

1. Use episode mining and temporal graph motifs to generate candidate patterns.
2. Rank candidate patterns using LPM-inspired quality dimensions:
   support, confidence, coverage, determinism, soft fit.
3. Report top patterns with representative occurrences and outliers.

### Keep / Drop Decision

Keep, but as an evaluation/ranking reference rather than a direct algorithmic
implementation.

## Pattern Reliability and Actionability Criteria

This section records the quality criteria we should use when turning discovered
runtime patterns into optimization evidence. The goal is to avoid treating every
repeated visual shape as a meaningful bottleneck.

### Reliability Criteria

A fuzzy meta pattern should be considered reliable only if several independent
signals agree.

```text
support(pattern)
  = number of non-overlapping or minimally-overlapping occurrences

confidence(anchor -> pattern)
  = occurrences where the anchor expands into the full pattern
    / all occurrences of the anchor

coverage(pattern)
  = event count, wait/comm/exec time, or wall-clock span explained by the pattern
    / corresponding total in the analyzed run

temporal_tightness(pattern)
  = low variance of edge deltas, step spans, and synchronization skew

topology_stability(pattern)
  = stable hard-anchor graph across occurrences

soft_fit(pattern)
  = similarity of nearby compute/runtime feature vectors across occurrences

cross_run_reproducibility(pattern)
  = whether the same pattern appears in another profile of a similar workload
```

Recommended ranking principle:

```text
reliability =
  w1 * support_score
  + w2 * confidence_score
  + w3 * topology_stability
  + w4 * temporal_tightness
  + w5 * soft_fit
  + w6 * cross_run_reproducibility
```

The weights do not need to be fixed initially. For the first implementation,
report the components separately and use a conservative heuristic sort:

```text
high confidence
then high coverage
then high support
then low timing variance
```

### Actionability Criteria

A reliable pattern is not automatically useful for performance tuning. A pattern
is actionable when it gives a concrete optimization entry point.

```text
resource_dominance
  = pattern explains a large fraction of wait/comm/exec time on important
    process-device-stream resources

bottleneck_direction
  = pattern suggests which side is likely causing delay, e.g. one rank finishes
    compute later and other ranks wait, or one stream repeatedly gates others

source_locality
  = pattern can be mapped to a small source-code region, operator family,
    runtime call family, or repeated framework phase

intervention_path
  = there is a plausible modification: overlap communication, rebalance compute,
    move synchronization point, fuse/split kernels, change batching policy,
    reduce host-side blocking, or adjust stream scheduling

verification_path
  = expected improvement can be checked by a before/after profile using the same
    metrics and the same discovered pattern

implementation_risk
  = estimated engineering effort and correctness risk of the optimization
```

For thesis writing, this gives a clean chain of evidence:

```text
raw trace
-> reliable repeated pattern
-> dominant wait/comm/exec contribution
-> likely source/runtime region
-> optimization hypothesis
-> before/after profiling verification
```

### hprofile Report Fields

Future reports should expose both reliability and actionability instead of only
showing a compressed sequence.

```text
pattern_id
support
confidence
coverage_event_count
coverage_duration_us
coverage_wait_us
coverage_comm_us
temporal_delta_mean_us
temporal_delta_std_us
topology_signature
soft_fit_score
representative_occurrence
outlier_occurrences
dominant_process_device_stream
source_or_operator_hints
optimization_hypothesis
verification_metric
```

This is also useful for a future paper: it connects pattern mining with
performance engineering, instead of stopping at trace compression.

## Yeh et al. 2016: Matrix Profile I

- PDF: `04_yeh_matrix_profile_i_2016.pdf`
- Text: `04_yeh_matrix_profile_i_2016.txt`
- Status: keep as background for numeric feature motif discovery.
- Thesis citation: optional. Cite only if we implement or describe numeric
  feature-window motif discovery.
- Future paper citation: yes, if fuzzy meta-pattern matching uses numeric
  feature time series.

### Problem

The paper introduces the Matrix Profile as a general primitive for time-series
subsequence similarity joins. Given a time series and a subsequence length, the
Matrix Profile records, for every subsequence, the distance to its nearest
neighbor subsequence.

Key concepts:

```text
time series T
subsequence T[i : i + m)
distance profile = distances from one query subsequence to all subsequences
matrix profile P[i] = distance from subsequence i to its nearest neighbor
matrix profile index I[i] = location of that nearest neighbor
```

The lowest values in the matrix profile indicate repeated motifs. The highest
values indicate discords or anomalies.

### Why It Matters

Matrix Profile gives a clean way to find approximate repeated shapes without
asking the user to define a similarity threshold. This is relevant to our fuzzy
matching problem because trace windows can be converted into numeric feature
vectors:

```text
window_feature(t) = [
  wait_ratio,
  comm_ratio,
  exec_ratio,
  event_density,
  active_stream_count,
  synchronization_edge_count,
  step_span_us,
  skew_us
]
```

Then motif discovery becomes:

```text
Find windows whose feature trajectories have nearest neighbors.
```

This is useful for soft-region matching around hard anchors. It is less suitable
as the only representation of cross-process synchronization structure.

### Useful Properties

- It searches local subsequences rather than global time-series properties.
- It is nearest-neighbor based, so it avoids a manually chosen similarity
  threshold.
- It supports exact, approximate/anytime, and incremental variants in the
  Matrix Profile family.
- It provides both motifs and discords from the same representation.
- It can be accelerated and parallelized.

### Limitations for hprofile

Matrix Profile assumes a regularly sampled numeric time series and a fixed
subsequence length. Raw profiler traces are event-based, sparse, duration-rich,
and structured by process/device/stream topology.

Therefore, direct application would lose important structure:

- partial order between events;
- cross-stream and cross-process synchronization edges;
- categorical event names and operator families;
- variable-length execution phases;
- missing or optional compute regions.

For `hprofile`, Matrix Profile is best treated as an auxiliary method for
soft-feature similarity, not as the primary temporal-graph representation.

### Proposed hprofile Experiment

Use the machine-level event table from `analyzer/out/20260422_163744`.

1. Build fixed-width or anchor-centered windows.
2. Convert each window into numeric features:

```text
wait_us
comm_us
exec_us
runtime_us
event_count
active_process_device_count
active_stream_count
sync_edge_count
duration_p95
```

3. Run a Matrix-Profile-like nearest-neighbor search on the feature sequence.
4. Compare discovered numeric motifs with temporal graph motifs.
5. Use numeric motifs as soft-fit evidence:

```text
soft_fit(anchor_occurrence_i, anchor_occurrence_j)
  = distance(feature_window_i, feature_window_j)
```

### Keep / Drop Decision

Keep as background and future implementation option.

Do not make Matrix Profile the first core algorithm. The first core algorithm
should remain episode mining + temporal graph motifs + local DAG matching,
because those preserve process/device/stream structure.

## Yeh et al. 2017: Matrix Profile VI, Meaningful Multidimensional Motif Discovery

- PDF: `05_yeh_matrix_profile_vi_multidimensional_2017.pdf`
- Text: `05_yeh_matrix_profile_vi_multidimensional_2017.txt`
- Status: keep as a strong reference for subspace motif discovery.
- Thesis citation: optional unless we add numeric soft-region matching.
- Future paper citation: yes.

### Problem

The paper argues that multidimensional motif discovery often fails when all
dimensions are forced into the distance calculation. A repeated behavior may
exist only in a small subset of dimensions, while irrelevant dimensions swamp
the signal.

This maps strongly to `hprofile`:

```text
some dimensions = useful synchronization / wait / comm signals
other dimensions = variable compute regions, unrelated streams, noise
```

If we blindly compare every feature and every stream, true runtime motifs can be
hidden by irrelevant or unstable dimensions.

### Core Representation

The paper introduces subdimensional motifs:

```text
MTS = d-dimensional time series
k-dimensional motif = most similar subsequence pair using the best k dimensions
k-dimensional matrix profile = nearest-neighbor distance using best k dimensions
matrix profile subspace = the selected dimensions for each motif
```

The key idea is not merely "multidimensional distance", but "discover the
natural subset of dimensions where the motif is meaningful".

### Algorithmic Ideas Useful for hprofile

1. Compute distance profiles per dimension.
2. Sort dimension-wise distances for each candidate match.
3. For each k, combine the best k dimensions.
4. Use an elbow or MDL-style criterion to choose a natural dimensionality.
5. Support constrained search:

```text
include dimensions = must participate
exclude dimensions = must not participate
```

For `hprofile`, dimensions could be:

```text
per process-device wait ratio
per process-device comm ratio
per stream event density
sync edge count by relation type
step skew
kernel/operator family duration buckets
host runtime call duration buckets
```

### Why It Helps hprofile

This paper gives us a formal argument for not over-constraining fuzzy pattern
matching. In distributed accelerator traces, not every stream or feature should
match for two occurrences to represent the same meta pattern.

This supports our design:

```text
hard anchors = stable dimensions
soft regions = optional or variable dimensions
```

A discovered pattern should be allowed to say:

```text
The synchronization skeleton matches strongly on dimensions A, B, C.
The compute region differs on dimensions D, E, F.
```

That is exactly the situation the user observed: cross-rank synchronization is
stable, but matmul/compute activity can vary or disappear.

### Relation to Local DAG Matching

Matrix Profile VI works on numeric feature subspaces. Our local DAG idea works
on temporal graph structure.

They can be combined:

```text
1. Use temporal graph motifs / local DAG matching to identify hard-anchor
   candidate occurrences.
2. Convert each occurrence neighborhood into feature dimensions.
3. Use subspace similarity to decide which dimensions are stable and which are
   variable.
4. Rank the pattern by hard-anchor reliability plus soft-region subspace fit.
```

This gives a principled way to avoid strict matching while also avoiding
arbitrary manual rules.

### Limitations for Our Case

- It assumes numeric time series rather than event graphs.
- It assumes subsequences can be compared with z-normalized Euclidean distance.
- It does not preserve causality, synchronization edges, or partial orders.
- The window length still matters.
- The MDL/natural-dimensionality criterion may need adaptation for event-count
  and duration features.

### Proposed hprofile Experiment

After extracting candidate collective/meta-pattern occurrences:

1. Build an occurrence-feature matrix:

```text
rows = motif occurrences
columns = feature dimensions
values = normalized duration/count/ratio/skew features
```

2. For each pair of occurrences, compute per-dimension distances.
3. Sort dimensions by similarity and find the best-k subspace.
4. Report:

```text
stable_dimensions
variable_dimensions
subspace_similarity
natural_k
soft_fit_score
```

5. Use this to explain approximate matching:

```text
The meta pattern repeats because the synchronization dimensions are stable,
even though compute dimensions vary.
```

### Keep / Drop Decision

Keep.

This is one of the better references for our "non-strict matching" argument.
It should be cited in future work if we implement subspace soft-feature matching.
For the undergraduate thesis, cite only if the experiment section includes a
numeric feature motif or soft-fit analysis.

## Noeth et al. 2009: ScalaTrace

- PDF: `06_noeth_scalatrace_2009.pdf`
- Text: `06_noeth_scalatrace_2009.txt`
- Status: keep. This is highly relevant for communication trace structure
  compression and replay.
- Thesis citation: yes if we discuss distributed communication trace compression
  or source localization from repeated communication loops.
- Future paper citation: yes.

### Problem

The paper addresses a classic HPC tracing tension:

```text
profiling = scalable aggregate statistics, but loses temporal structure
tracing   = preserves event order and structure, but produces huge files
```

ScalaTrace tries to bridge this by producing compressed MPI communication traces
that preserve structural and temporal-order information.

This maps closely to `hprofile`:

```text
raw Perfetto/msprof timeline = complete but huge and difficult to inspect
simple summaries             = compact but lose runtime structure
hprofile meta patterns       = compact while preserving important structure
```

### Core Representation

ScalaTrace compresses MPI events using Regular Section Descriptors (RSDs) and
Power-RSDs (PRSDs):

```text
RSD  = <iteration_count; event1; event2; ...>
PRSD = recursive/nested RSD representation
```

This is similar in spirit to our loop analyzer:

```text
repeated event sequence -> compressed loop/tree representation
```

However, ScalaTrace is focused on MPI communication calls and their parameters,
while `hprofile` works on heterogeneous accelerator timelines with process,
device, stream, runtime API, wait, communication, and kernel events.

### Intra-Node Compression

ScalaTrace maintains a local queue of MPI events and greedily matches repeated
adjacent sequences. Once a repeated sequence is found, it is replaced by an RSD
or PRSD.

Important details:

- call sequence signatures distinguish the same MPI call from different source
  locations;
- recursion-folding signatures make recursive and iterative forms compress
  similarly;
- relative endpoint encodings allow ranks with the same communication structure
  but different absolute rank IDs to match;
- request handles are encoded as relative positions instead of raw pointers;
- some nondeterministic repeated calls, such as `MPI_Waitsome`, are aggregated
  using MPI-specific semantics.

### Inter-Node Compression

After local compression, ScalaTrace merges compressed traces across nodes using a
tree reduction. Events and structures are merged when their event type,
parameters, structure, and iteration counts match.

The most relevant idea for `hprofile` is that cross-node structure can be
represented compactly by grouping participants:

```text
same event pattern + different rank set
-> one structure with compressed participant list
```

For our case:

```text
same synchronization motif + different process/device/stream participants
-> one meta pattern with participant sets
```

### Causal Reordering

ScalaTrace also observes that disjoint events from different ranks may have no
causal order, so their order can be rearranged during compression as long as
causal dependencies are preserved.

This is very important for our partial-order/DAG framing. It supports the idea
that exact global sequence order is too strict:

```text
if two events are on disjoint participant sets and have no dependency,
their textual order in a merged trace is not the real structure.
```

For `hprofile`, this strengthens the argument that a pattern should be modeled as
a partial order or local DAG, not as one flat sequence.

### Source Localization

ScalaTrace uses stack/calling sequence information to identify where MPI calls
come from. It also shows that compressed repeated communication loops can reveal
timestep loops and help locate source-level loop structure.

This is directly useful for the thesis claim:

```text
repeated runtime pattern
-> compressed structural representation
-> likely source-code repeated region
-> optimization entry point
```

This supports the sentence we wanted to add earlier: once repeated execution
structures are discovered, they often correspond to key repeated source regions
such as attention, communication, or scheduling phases, giving source analysis a
concrete handle.

### Reliability and Verification

ScalaTrace verifies compression correctness by replaying compressed traces and
checking:

- MPI semantics are preserved;
- aggregate MPI event counts match the original run;
- temporal ordering within a node is observed.

This suggests a useful validation idea for `hprofile`:

```text
compressed pattern reconstruction should preserve:
  event counts by category/family,
  participant topology,
  anchor ordering,
  wait/comm/exec duration totals within tolerance,
  representative timing deltas.
```

We likely cannot replay NPU execution, but we can reconstruct a summarized
timeline and compare structural statistics against the raw machine timeline.

### Why It Helps hprofile

ScalaTrace gives strong related-work support for four claims:

1. Communication traces need a representation between aggregate profiles and raw
   event traces.
2. Repeated communication structure can be compressed while preserving useful
   temporal/structural information.
3. Cross-rank structure should be represented by participant sets and relative
   encodings rather than absolute rank-specific events.
4. Source-level optimization can be guided by repeated communication structures.

### Key Difference from hprofile

ScalaTrace is mostly exact and MPI-specific. `hprofile` must be more approximate
and heterogeneous:

- NPU traces include host runtime APIs, device kernels, wait events, and
  communication events.
- Cross-process/device synchronization edges are inferred from timestamps and
  event semantics, not intercepted MPI calls.
- Compute regions can vary, so exact sequence equality is too strict.
- The profiler should not require prior knowledge of vLLM or a specific
  collective implementation.

Therefore, ScalaTrace is a strong structural-compression baseline, but our
contribution should emphasize fuzzy machine-level meta-pattern discovery.

### Proposed hprofile Experiment

Use ScalaTrace-inspired validation for our future meta-pattern analyzer:

1. Compress local stream sequences using loop analyzer / symbol compression.
2. Merge across process-device-stream participants into machine-level motifs.
3. Store participant sets compactly:

```text
participant_set = {
  process_keys,
  device_ids,
  stream_ids
}
```

4. Compare raw timeline vs compressed motif report:

```text
event_count_error
duration_sum_error
wait_comm_exec_ratio_error
anchor_order_preserved
participant_topology_preserved
```

5. If possible, render the compressed motif back into a small Perfetto timeline
   snippet for human inspection.

### Keep / Drop Decision

Keep.

This should be cited when we frame hprofile as a structural summarization and
analysis tool for distributed accelerator traces. It is not enough for our fuzzy
matching problem, but it is excellent background for trace compression,
communication structure preservation, and source localization.
