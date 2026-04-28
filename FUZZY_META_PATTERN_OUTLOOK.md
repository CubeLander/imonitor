# Fuzzy Meta Pattern Discovery Outlook

This note records a follow-up research direction for `hprofile`: discovering
approximate runtime patterns from machine-level profiling traces without
hard-coding workload-specific rules such as "this is vLLM attention" or "this
must be an all-reduce".

## Motivation

Full machine-level traces show a useful phenomenon:

- Cross-process / cross-device synchronization events can form stable temporal
  structures.
- The compute regions around those synchronization structures are often not
  strictly identical.
- In LLM serving, this can happen because of continuous batching, prefill/decode
  differences, dynamic shape, KV-cache state, runtime branches, and framework
  scheduling decisions.

Therefore, exact sequence matching is too strict. We need an approximate pattern
discovery layer that can find stable macro-structure while allowing local
variation.

## Design Principle

The profiler should remain workload-agnostic.

It should not assume vLLM, attention, matmul, all-reduce, or any particular
framework path as prior knowledge. Instead, it should operate on generic runtime
signals:

- event category: `wait`, `comm`, `exec`, `runtime`, `memory`, `other`
- event label / normalized operator family
- process key
- device id
- stream id
- timestamp and duration
- temporal adjacency
- cross-stream / cross-process timing relation

Workload-specific interpretation can be added later as a source annotation or
manual explanation layer, not as the core discovery rule.

## Core Method Hypothesis

The central method hypothesis is:

> Distributed accelerator traces should first be viewed as a global
> machine-level event sequence, and then lifted into a temporal graph of
> cross-stream/process/device synchronization relations.

The two levels are:

```text
Layer 1: global event sequence
  all process/device/stream events sorted by timestamp

Layer 2: temporal graph
  nodes = (process_key, device_id, stream_id)
  edges = inferred synchronization / communication relations at time t
```

This lets us search for recurring global synchronization topology rather than
only exact per-stream kernel sequences.

This is especially important for LLM serving traces:

- Compute regions can vary because of continuous batching, shape changes,
  KV-cache state, prefill/decode differences, and runtime branches.
- Synchronization relations are often more stable because they are determined by
  the parallel strategy and collective communication structure.

Therefore, temporal graph motifs should be used to discover stable hard-anchor
skeletons, while soft compute regions are summarized as approximate features
around those anchors.

## Research Position After Reading

The related work now suggests a coherent position:

```text
ScalaTrace-like idea:
  distributed traces can be compressed structurally rather than reduced to
  aggregate counters.

Matrix Profile-like idea:
  repeated windows can be compared by extracted features, and useful patterns do
  not need every feature dimension to match.

hprofile contribution:
  apply these ideas to heterogeneous accelerator profiling traces, where the
  important structure spans process, device, stream, runtime API, wait,
  communication, and kernel events.
```

The key difference from ScalaTrace is that accelerator traces cannot rely only on
exact MPI-call sequence equality. They require:

- machine-level profile integration from per-process profiler artifacts;
- resource keys for `(process_key, device_id, stream_id)`;
- inferred temporal/synchronization edges;
- partial-order or DAG pattern representation;
- approximate matching between stable hard anchors and variable soft regions;
- ranking by reliability and optimization actionability.

Therefore, the method should be framed as:

> structure-preserving fuzzy compression and meta-pattern discovery for
> distributed accelerator runtime profiles.

This is both a profiling-analysis method and a trace-reduction method. Its output
is not just a smaller trace. Its output is an optimization-oriented pattern
report.

## Problem Model

### Input

The input is a set of per-process profiling artifacts:

```text
RawProfileSet = {profile_1, profile_2, ..., profile_n}
```

Each raw profile contains runtime events, device events, communication events,
wait events, stream identifiers, timestamps, durations, and optional source or
operator hints.

The first modeling step converts them into a machine-level profile:

```text
MachineProfile = (E, R, T)

E = normalized events
R = resources, such as process/device/stream
T = global timestamp domain
```

Recommended global resource keys:

```text
process_key       = source_db_id
process_device    = (process_key, device_id)
global_stream_key = (process_key, device_id, stream_id)
```

Each event can be represented as:

```text
event = {
  event_id,
  process_key,
  device_id,
  stream_id,
  category,
  label_family,
  start_ns,
  end_ns,
  duration_ns,
  args
}
```

### Structure Layer

The raw event set is lifted into a temporal graph:

```text
TemporalRuntimeGraph = (V, A)

V = resource nodes, usually global_stream_key or process_device
A = timestamped relation edges
```

Typical edge candidates:

```text
same_stream_order(e_i, e_j)
notify_wait_end_to_event_wait_start(e_i, e_j)
event_record_to_event_wait(e_i, e_j)
comm_end_to_wait_start(e_i, e_j)
runtime_api_to_device_activity(e_i, e_j)
```

This graph should remain workload-agnostic. An edge may later be interpreted as
collective communication or framework synchronization, but the discovery rule
should only rely on generic event categories, timestamps, resources, and labels.

### Pattern Object

A discovered runtime pattern should be represented as:

```text
RuntimeMetaPattern = {
  hard_anchor_graph,
  soft_region_summary,
  occurrence_set,
  participant_set,
  reliability_metrics,
  actionability_metrics,
  representative_examples,
  outliers
}
```

Hard anchors are stable temporal graph relations:

```text
hard_anchor_graph = {
  nodes: process/device/stream resources,
  edges: synchronization or temporal relations,
  edge_features: delta_t, relation_type, direction
}
```

Soft regions summarize variable nearby execution:

```text
soft_region_summary = {
  event_family_counts,
  duration_by_category,
  wait_comm_exec_ratio,
  active_stream_count,
  duration_histograms,
  optional_source_hints
}
```

This directly models the observed phenomenon:

```text
stable part:
  cross-rank synchronization skeleton

variable part:
  local compute, matmul presence, kernel duration, host runtime behavior
```

## Method Pipeline

The concrete method can be organized as six stages:

```text
1. Integrate
   per-process raw profiler artifacts -> machine-level runtime profile

2. Normalize
   raw event names/resources -> categories, label families, global resource keys

3. Anchor
   mine frequent temporal relations and synchronization edges

4. Segment
   use repeated anchor groups to cut candidate local windows or steps

5. Match
   compare local DAGs and soft feature subspaces to cluster approximate repeats

6. Explain
   rank patterns by reliability/actionability and emit optimization hypotheses
```

The most important design choice is to avoid one flat equality rule. Matching
should use a layered criterion:

```text
match(pattern_i, pattern_j) =
  hard_anchor_match
  AND approximate_timing_match
  AND sufficient_soft_feature_fit
```

where:

```text
hard_anchor_match:
  stable temporal topology is the same or highly similar

approximate_timing_match:
  edge deltas, skew, and span are within robust statistical bounds

soft_feature_fit:
  a useful subset of feature dimensions matches, while irrelevant or unstable
  dimensions are allowed to differ
```

The Matrix Profile VI-inspired part is the last line: the analyzer should be able
to report which dimensions are stable and which dimensions are variable.

## Relation-First Modeling

An important correction to the simple window-based view is that the profiler is
not only a collection of timestamped events. It also contains repeated runtime
relations. For example:

```text
CPU runtime event:
  Runtime@EventRecord

GPU/accelerator stream event:
  event record on a device stream
```

These two events may describe the same logical synchronization action from two
different layers. Similarly, CPU runtime calls and GPU stream activities can both
record parts of one all-reduce or synchronization phase.

Therefore, the core modeling target should be:

```text
events + relations between events
```

not only:

```text
events inside the same time window
```

### Why Window-Only Matching Is Unsafe

CPU-to-GPU execution is asynchronous. A CPU runtime call may enqueue work into a
device stream, while the device stream executes it later after earlier queued work
finishes. If the device queue becomes longer, the CPU event and its corresponding
GPU event can drift farther apart:

```text
CPU loop k      -> enqueues GPU work k
CPU loop k + 1  -> enqueues GPU work k + 1

GPU stream may still be executing work k - 1 or k
```

This creates a growing queueing time gap. A fixed time window can then mix
different logical iterations:

```text
window around CPU loop k + 1
  may contain GPU events from loop k
```

If the analyzer uses only timestamp proximity, it can incorrectly match a later
CPU loop to earlier GPU stream events. This would corrupt both motif discovery
and bottleneck attribution.

### Queue-Aware Relation Types

The machine-level profile should explicitly model several relation families:

```text
enqueue_edge:
  CPU runtime call -> device stream event that was enqueued by the call

stream_order_edge:
  event_i -> event_j on the same stream by execution order

sync_edge:
  notify/event/record/wait relations across streams or process-device pairs

host_wait_edge:
  CPU thread wait/block event -> device or runtime event that releases it

collective_relation_edge:
  semantically similar runtime/device communication events across ranks
```

The relation graph then becomes:

```text
RuntimeRelationGraph = (events, relation_edges)
```

where edges are typed and can carry evidence:

```text
relation_edge = {
  source_event_id,
  target_event_id,
  relation_type,
  confidence,
  evidence: {
    same_stream,
    same_thread,
    same_label_family,
    same_correlation_id,
    monotonic_order,
    bounded_rank_distance,
    timestamp_delta
  }
}
```

### Matching Policy

Relation matching should prefer strong evidence over time proximity:

```text
1. explicit ids / flow ids / correlation ids if available
2. exact resource match: process, device, stream, thread
3. event semantic match: Runtime@EventRecord -> stream event record
4. monotonic order matching within the same resource queue
5. timestamp consistency as a weak check, not the primary key
```

For CPU-to-GPU queue matching, a useful first heuristic is monotonic bipartite
matching:

```text
given:
  CPU enqueue-like events C = c1, c2, ..., cn
  GPU stream events     G = g1, g2, ..., gm

find:
  c_i -> g_j

subject to:
  event families are compatible
  resource keys are compatible
  if c_i -> g_j and c_k -> g_l and i < k, then j <= l
  g_j starts after or near c_i under a broad tolerance
```

This treats the device stream as a queue rather than a synchronous execution
lane. The output can expose queueing delay:

```text
queue_delay = gpu_event_start_ns - cpu_enqueue_end_ns
```

Queueing delay should be a first-class feature because it explains why CPU and
GPU views drift apart.

### Implication for Meta-Pattern Discovery

The local pattern should be extracted around relation-connected neighborhoods,
not only around time windows:

```text
anchor event
-> follow relation edges
-> include ordered stream neighbors
-> include nearby events only as secondary context
```

This changes local DAG extraction:

```text
LocalDAG(anchor) = relation-neighborhood(anchor, depth, time_guard)
```

instead of:

```text
LocalDAG(anchor) = all events in [anchor_ts - w, anchor_ts + w]
```

A time guard is still useful to avoid unbounded expansion, but it should not be
the definition of "same logical step".

### New Failure Modes to Track

The analyzer should explicitly report uncertain relations:

```text
ambiguous_match:
  multiple GPU events are plausible targets for one CPU runtime event

missing_match:
  CPU runtime event has no visible device counterpart, or vice versa

queue_drift:
  enqueue-to-execution gap grows across iterations

cross_iteration_mix:
  time-window extraction would include relation targets from another iteration
```

These are not just implementation details. They are performance signals:

- increasing queue drift may indicate host/device pacing imbalance;
- missing or ambiguous matches may indicate insufficient trace correlation data;
- cross-iteration mixing warns that window-based analysis is unreliable for that
  region.

## Ascend Deterministic Relation Registry

The ideal analyzer should exploit deterministic or near-deterministic relations
already present in Ascend profiling artifacts before falling back to heuristic
matching. The current `20260422_163744` trace shows several strong relation
sources.

### Connection ID as a Strong Edge Key

The following tables expose connection identifiers:

```text
msprof_*.db:
  CANN_API.connectionId
  TASK.connectionId
  COMMUNICATION_OP.connectionId

host/sqlite:
  api_event.ApiData.connection_id
  runtime.HostTask.connection_id
  hccl.HCCLOP.connection_id / kfc_connection_id

device_n/sqlite:
  ascend_task.AscendTask.connection_id
  hccl_single_device.HCCLOpSingleDevice.connection_id
  hccl_single_device.HCCLTaskSingleDevice.connection_id

mindstudio_profiler_output/msprof_*.json:
  args.connection_id
```

This means many CPU/runtime/device edges are not guesses. They should be created
by exact key joins.

Example relationship:

```text
CANN_API: aclrtRecordEvent / EventRecord / aclrtStreamWaitEvent
  connectionId = X

TASK:
  connectionId = X
  taskType = EVENT_RECORD or EVENT_WAIT
  deviceId, streamId, taskId, globalTaskId, startNs, endNs
```

The outer `AscendCL@aclrt...` API event often carries the connection id that
joins to the device-side task. The inner `Runtime@...` event may have its own
connection id and is still useful as a host-side runtime event, but the API-level
connection id is the stronger enqueue-to-device edge in the sampled trace.

### Communication Operation Expansion

HCCL communication exposes another strong relation:

```text
COMMUNICATION_OP.connectionId
  -> TASK rows with same connectionId
  -> COMMUNICATION_TASK_INFO rows by globalTaskId
```

This expands one communication operation into its device tasks:

```text
hcom_allReduce_ / hcom_allGather_
  -> SDMA / AI_CORE / Write Value / Notify Wait / Notify Record tasks
  -> srcRank, dstRank, notifyId, transportType, linkType, size, bandwidth
```

This is extremely valuable for cross-rank meta-pattern discovery. Instead of
inferring all-reduce structure from timestamps alone, the analyzer can first group
device tasks by `connectionId` and `opId`, then use `srcRank`, `dstRank`, and
`notifyId` as internal structure.

### Notify ID as a Synchronization Edge Hint

Communication task rows include:

```text
notifyId
srcRank
dstRank
transportType
linkType
opId
```

These fields can define stronger synchronization edges than generic
`EVENT_WAIT -> EVENT_RECORD` time pairing. Candidate rules:

```text
same connectionId + same opId + compatible notifyId
  -> internal communication-step edge

Notify_Record / Write Value with notifyId A
  -> Notify_Wait with corresponding notifyId B
     when relation is encoded by HCCL task metadata

same groupName + same opId + rank pair
  -> cross-rank communication relation
```

The exact notify matching rule still needs to be documented from Ascend/HCCL
semantics and verified empirically, but `notifyId` should be treated as strong
evidence, not as an ordinary label.

### Relation Evidence Priority

The analyzer should rank relation evidence by strength:

```text
Level 0: exact profiler edge
  explicit flow / connection / correlation id directly links two events

Level 1: exact connection-id join
  CANN_API.connectionId -> TASK.connectionId
  COMMUNICATION_OP.connectionId -> TASK.connectionId

Level 2: structured communication metadata
  connectionId + opId + groupName + src/dst rank + notifyId

Level 3: queue-aware monotonic matching
  compatible CPU enqueue sequence -> compatible device stream sequence

Level 4: time-window proximity
  used only as a weak fallback or sanity check
```

The main rule is:

> time proximity should validate a relation, not create it when stronger
> profiler-provided keys are available.

### Data Model Addition

The intermediate representation should include an explicit relation table:

```text
runtime_relations(
  relation_id,
  source_event_id,
  target_event_id,
  relation_type,
  evidence_level,
  confidence,
  connection_id,
  op_id,
  group_name,
  notify_id,
  src_rank,
  dst_rank,
  queue_delay_ns,
  notes
)
```

Suggested relation types:

```text
api_to_task
runtime_to_api
communication_op_to_task
communication_task_internal
notify_record_to_wait
same_stream_order
queue_enqueue_to_execute
```

This table should become the primary input for local DAG and meta-pattern
discovery. Raw time windows should be secondary context.

### Immediate Engineering Task

Before implementing fuzzy matching, add a small relation extraction pass:

```text
1. Load CANN_API, TASK, COMMUNICATION_OP, COMMUNICATION_TASK_INFO, STRING_IDS.
2. Join CANN_API.connectionId -> TASK.connectionId for API-to-device edges.
3. Join COMMUNICATION_OP.connectionId -> TASK.connectionId for communication
   operation expansion.
4. Join TASK.globalTaskId -> COMMUNICATION_TASK_INFO.globalTaskId for HCCL
   task semantics.
5. Export runtime_relations.csv and relation_summary.md.
6. In the machine-level Perfetto output, optionally emit flow events for these
   relations so humans can inspect the CPU/GPU linkage visually.
```

Validation checks:

```text
api_to_task_join_rate
communication_op_to_task_join_rate
unmatched_connection_ids
ambiguous_connection_ids
queue_delay_distribution
top relation types by covered duration
```

This step is a prerequisite for reliable cross-stream and CPU/GPU pattern
matching.

### Observed Pitfall: Host Thread Is Not Device Stream

While inspecting `20260422_163744`, `proc04/tid=671147` appears to contain a
dense sequence of AscendCL/CANN API calls. It is tempting to look for a
corresponding device stream named `671147`, but this is a category error:

```text
671147 = host thread id
device stream ids in proc04 = e.g. 1160, 1162, 1165, 1166, 1168, ...
```

In the sampled proc04 database:

```text
TASK rows:
  deviceId = 5
  count    = 875837

HostTask rows for thread_id = 671147:
  stream 1165: FFTS_PLUS, EVENT_RECORD, EVENT_WAIT, ...
  stream 1162: KERNEL_AIVEC, KERNEL_MIX_AIC, MEMCPY_ASYNC, ...
  stream 1166: KERNEL_AIVEC, EVENT_WAIT, EVENT_RECORD, ...
  stream 1168: KERNEL_AIVEC, ...
```

Therefore, host API lanes should not be interpreted as device stream lanes. A CPU
thread can enqueue work to many device streams, and a device stream can receive
work from runtime activity that is not visually adjacent in the same Perfetto
lane.

Another observed issue is join sparsity by API name:

```text
aclrtStreamGetId / aclrtGetStreamAttribute / CacheLastTaskOpInfo
  often have no TASK counterpart because they are query/cache/metadata calls.

inner Runtime@EventRecord / Runtime@StreamWaitEvent
  may not directly join to TASK by the same connection id.

outer AscendCL@aclrtRecordEvent / AscendCL@aclrtStreamWaitEvent
  more often join to EVENT_RECORD / EVENT_WAIT TASK rows.

Node@launch / launch
  can join to actual kernel tasks with queue delay.
```

In a 200 ms host-heavy window around proc04, many CANN API calls appear, but only
a smaller number of device tasks start in the same absolute window. This is
expected under asynchronous queueing:

```text
API call time != device execution time
```

The relation extractor should report:

```text
host_thread_id
target_device_stream_ids
api_name
connection_id
joined_task_count
unmatched_reason_guess
queue_delay_ns
```

This prevents a false conclusion that "device task records are missing" when the
actual issue is that host activity is being compared against the wrong device
stream or the wrong time window.

### Observed Pitfall: HCCL Host API Is Not the Communication Task Key

In `proc04` around relative time `61.4s-61.6s`, the host thread contains many
`hcom_allReduce_` API calls interleaved with local compute API calls such as
`aclnnInplaceFillScalar`. The local compute tasks can be seen nearby on device
streams, but all-reduce communication tasks do not appear under the same
`CANN_API.connectionId` and may not appear inside the exact same time window.

Empirical observation:

```text
CANN_API hcom_allReduce_:
  connectionId = 296436, 296587, ...
  direct TASK join count = 0
  direct COMMUNICATION_OP join count = 0

COMMUNICATION_OP hcom_allReduce__...:
  connectionId = 308906, 309051, ...
  starts later
  expands to ~35 TASK rows per op through TASK.connectionId
```

In the sampled window, the first visible `COMMUNICATION_OP` all-reduce starts
around relative time `61.571s`, while earlier `hcom_allReduce_` host API calls
started around `61.402s`. The gap is on the order of hundreds of milliseconds
for some calls. In contrast, nearby local compute tasks can appear with much
shorter enqueue-to-execution delay.

This suggests that HCCL should be modeled as a layered relation:

```text
host CANN/HCCL API call
  -> HCCL op construction / scheduling layer
  -> COMMUNICATION_OP
  -> HCCL TASK group
  -> Notify/Write/SDMA/AI_CORE/EVENT tasks
```

The `CANN_API.connectionId` for `hcom_allReduce_` should not be assumed to equal
`COMMUNICATION_OP.connectionId`. For HCCL, better primary keys are likely:

```text
COMMUNICATION_OP.connectionId
COMMUNICATION_OP.opId
COMMUNICATION_OP.groupName
COMMUNICATION_TASK_INFO.globalTaskId
COMMUNICATION_TASK_INFO.notifyId
srcRank / dstRank
```

The relation extractor should therefore treat high-level HCCL host APIs as
semantic host-side markers, not direct device-task keys, unless an explicit flow
or correlation field proves otherwise.

## First Implementable Algorithm

The first implementation should be deliberately simple and testable.

### Step 1: Build Event Table

Create a structured event table from the integrated profile:

```text
events(
  event_id,
  process_key,
  device_id,
  stream_id,
  category,
  label_family,
  start_ns,
  end_ns,
  duration_ns
)
```

### Step 2: Mine Anchor Edges

Start with candidate relations between wait/notify/event families:

```text
anchor_edge = (
  source_event_id,
  target_event_id,
  source_node,
  target_node,
  relation_type,
  delta_ns
)
```

Keep high-support and high-confidence relation families:

```text
support(edge_family) >= threshold
confidence(source_family -> target_family) >= threshold
```

Before relying on temporal windows, build relation edges where possible:

```text
Runtime@EventRecord -> stream event record
Runtime enqueue/call -> device stream activity
notify/event/record  -> wait counterpart
```

Use monotonic matching within compatible resource queues so that CPU events are
not accidentally matched to GPU events from the wrong logical iteration.

### Step 3: Group Edges into Local Motifs

Within a bounded window, group anchor edges into a local temporal graph:

```text
candidate_motif_occurrence = {
  time_window,
  participant_nodes,
  anchor_edges
}
```

Use canonicalized topology signatures:

```text
topology_signature =
  hash(sorted(normalized_node_roles, normalized_edge_roles, edge_order))
```

### Step 4: Extract Soft Features

For each occurrence, compute features around the window:

```text
soft_features = [
  wait_us_by_node,
  comm_us_by_node,
  exec_us_by_node,
  runtime_us_by_node,
  event_count_by_family,
  active_stream_count,
  skew_us,
  span_us
]
```

### Step 5: Cluster Approximate Occurrences

Cluster occurrences with:

```text
same_or_similar_topology_signature
low timing distance
subspace soft-feature similarity
```

The output should explicitly say:

```text
stable dimensions:
  sync edges, participant topology, wait/comm timing

variable dimensions:
  compute family counts, kernel duration, optional runtime calls
```

### Step 6: Rank and Explain

For each cluster:

```text
reliability = support + confidence + topology stability + timing tightness
actionability = coverage + bottleneck direction + source locality + verification path
```

Emit a report:

```text
motif_report.md
anchor_edges.csv
motif_occurrences.csv
motif_soft_features.csv
motif_outliers.csv
```

## Thesis-Level Claims

A conservative thesis claim can be:

> This work constructs a machine-level profiling representation from raw NPU
> profiler artifacts and proposes a structure-preserving analysis method that
> compresses repeated runtime behavior into loop and meta-pattern summaries.
> Compared with raw timelines and aggregate counters, the method better preserves
> the synchronization and execution structure needed for performance diagnosis.

A stronger future-paper claim can be:

> This work introduces a workload-agnostic fuzzy meta-pattern discovery method
> for distributed accelerator traces. It combines hard-anchor temporal graph
> motifs with soft-region subspace matching, enabling repeated synchronization
> structures to be identified even when surrounding compute regions are
> non-identical.

## Candidate Representation

A candidate fuzzy pattern can be represented as:

```text
FuzzyMetaPattern = {
  hard_anchors: stable temporal edges or synchronization events,
  soft_regions: variable event windows around anchors,
  support: number of occurrences,
  confidence: matching quality,
  anomaly_edges: unstable or outlier relations,
  source_hints: optional source/operator-family hints
}
```

For collective-like behavior:

```text
ApproxCollectiveStep = {
  anchors: E_notify_to_event,
  soft_features_by_process_device: {
    node_i: {
      event_family_counts,
      event_family_durations,
      wait_comm_exec_ratio,
      duration_histogram,
      source_hints
    }
  }
}
```

Pattern similarity can combine:

```text
similarity =
  alpha * topology_similarity(hard_anchors)
  + beta * timing_similarity(delta_t, skew, span)
  + gamma * soft_feature_similarity(event families, ratios, source hints)
```

## Anchor-Centered Local DAG Matching Idea

An important extension is to treat a runtime pattern as a partial order / DAG
rather than a strict sequence. A partial order and a DAG are nearly equivalent
for our purpose: nodes are events or event groups, and directed edges encode
temporal precedence, synchronization, or inferred dependency.

The key idea:

1. Pick anchor occurrences from generic runtime facts.
   - Example anchor: same normalized event family on the same
     `(process_key, device_id, stream_id)`.
   - This does not require knowing vLLM, attention, or all-reduce semantics.

2. Around each anchor occurrence, extract a local machine-level timeline
   neighborhood.
   - Include nearby events on the same stream.
   - Include cross-stream or cross-process wait/notify/event edges.
   - Include events in a bounded time window before and after the anchor.

3. Convert the neighborhood into a local DAG:

```text
LocalDAG(anchor_i) = {
  nodes: runtime events or compressed event families,
  edges: temporal order + inferred synchronization edges,
  node_features: category, label family, duration, process/device/stream,
  edge_features: delta_t, relation type
}
```

4. Compare local DAGs from different anchor occurrences.
   - If the anchor is the same event family on the same stream, but its local
     DAG neighborhoods are similar, these occurrences likely belong to the same
     loop/meta-pattern position.
   - If the local DAG differs significantly, the same event may appear in a
     different phase or under a different runtime branch.

Possible similarity components:

```text
dag_similarity =
  a * node_label_similarity
  + b * edge_topology_similarity
  + c * timing_similarity
  + d * stream/process placement_similarity
  + e * soft_feature_similarity
```

This can be implemented approximately first:

- canonicalize node labels into event families;
- keep only top-k nearest events or events within a time window;
- compare DAGs using Weisfeiler-Lehman graph hashing, graph edit distance
  approximation, or vectorized graph features;
- cluster similar local DAGs.

Potential output:

```text
anchor_occurrences.csv
local_dag_features.csv
local_dag_clusters.csv
local_dag_cluster_report.md
```

This idea may help answer:

- Does the same event family on a stream repeatedly appear in the same global
  runtime context?
- Which anchor occurrences belong to the same loop position?
- Which occurrences are structurally similar but have different compute load?
- Which local DAG clusters map to repeated source-level code regions?

## Algorithm Sketch

1. Build a machine-level runtime profile.
   - Merge all process-level `msprof` artifacts.
   - Preserve `(process_key, device_id, stream_id)` as the global stream key.
   - Produce a machine-level Perfetto timeline and structured event table.

2. Abstract raw events.
   - Normalize event names.
   - Classify events into coarse categories.
   - Optionally map labels into operator families by generic string features,
     not framework-specific rules.

3. Discover hard anchors.
   - Mine frequent temporal adjacency relations.
   - Example: event family A ends near event family B starts within a time
     window.
   - Candidate relation:

```text
edge = (source_node, source_event_family, target_node, target_event_family, delta_t)
```

4. Segment steps.
   - Use repeated anchor groups to split the timeline into candidate steps.
   - Each step is a small temporal graph rather than a flat sequence.

5. Extract soft-region features.
   - For each node/rank/process-device in a step, summarize the nearby compute
     and runtime region.
   - Use counts, total duration, p95, category ratios, and event-family
     histograms.

6. Cluster approximate steps.
   - Cluster by anchor topology, timing distribution, and soft feature vectors.
   - Allow missing or extra compute events as long as the anchor skeleton and
     aggregate features are similar.

7. Emit meta patterns.
   - Output support, confidence, representative occurrences, outliers, and
     possible source hints.

## Pattern Quality and Optimization Actionability

The analyzer should separate two questions:

```text
Is this pattern reliable?
Is this pattern useful for optimization?
```

Reliability should be judged by generic pattern-mining evidence:

- support: how many times the pattern appears;
- confidence: how reliably an anchor expands into the whole pattern;
- coverage: how much event count, wait time, communication time, or wall-clock
  span the pattern explains;
- topology stability: whether the hard-anchor graph is stable;
- temporal tightness: whether edge deltas, step spans, and skew have low
  variance;
- soft fit: whether nearby compute/runtime feature vectors are similar enough;
- cross-run reproducibility: whether the same structure appears in another
  comparable trace.

Actionability should be judged by performance-engineering evidence:

- resource dominance: the pattern matters on important process/device/stream
  resources;
- bottleneck direction: the pattern suggests who waits for whom or which stream
  gates progress;
- source locality: the pattern can be mapped to a small source region, operator
  family, runtime call family, or repeated execution phase;
- intervention path: there is a plausible code or scheduling change;
- verification path: a before/after trace can measure the expected improvement;
- implementation risk: the optimization cost and correctness risk are
  reasonable.

This gives the thesis and future paper a defensible evidence chain:

```text
raw profiling trace
-> reliable repeated runtime pattern
-> dominant wait/comm/exec contribution
-> source/runtime localization
-> optimization hypothesis
-> before/after verification
```

## Related Work Directions

These are not one-to-one solutions, but they provide useful algorithmic ideas.

### Frequent Episode Mining

Discovers temporal rules such as "A is frequently followed by B within a time
window". This is close to discovering synchronization edges like
`Notify Wait end -> EVENT_WAIT start`.

Potential keywords:

- frequent episode mining
- temporal event sequence mining
- MINEPI / EMMA
- Mannila episode mining

### Process Mining and Local Process Models

Process mining discovers behavior models from event logs. Local Process Models
are especially relevant because they focus on frequent local structures instead
of forcing the whole trace into one global process model.

Useful for:

- noisy event logs
- local repeated behavior
- loops, choices, and concurrency
- partial process discovery

### Temporal Graph Motifs

Temporal graph motifs model timestamped edges and discover repeated small graph
structures within a time window. This is a strong fit for cross-process and
cross-device synchronization patterns.

Useful for:

- process-device-stream nodes
- temporal edges from wait/notify/event matching
- repeated synchronization graphlets
- approximate motif counting

### Time Series Motifs and Matrix Profile

Matrix Profile methods discover similar subsequences by distance rather than
exact equality. This may be useful after converting trace windows into numeric
feature vectors.

Possible feature sequence:

```text
[wait_ratio, comm_ratio, exec_ratio, event_density, rank_skew, active_stream_count]
```

This direction is useful for approximate window matching and anomaly detection,
but it may lose structural information unless combined with event/graph
features.

### HPC Trace Compression

MPI/HPC trace compression methods such as ScalaTrace show how communication
structure can be compressed while preserving important behavior. They are useful
references for scalability and structural summarization, although they usually
assume more regular MPI-style traces than LLM serving traces.

## Paper Reading and Reproduction Plan

The goal is not only to cite these papers, but to try their core ideas on our
machine-level timeline and decide which ones are actually useful for `hprofile`.

### P0: Must Read and Try

| Direction | Paper | Why it matters | hprofile reproduction idea | Thesis use |
| --- | --- | --- | --- | --- |
| Frequent episode mining | Mannila H, Toivonen H, Verkamo A I. Discovery of Frequent Episodes in Event Sequences. Data Mining and Knowledge Discovery, 1997, 1(3):259-289. https://www.cs.helsinki.fi/u/htoivone/pubs/dmkd97episodes.pdf | Defines frequent episodes in temporal event sequences. This is the closest classic formulation for discovering repeated event relations without workload-specific rules. | Treat normalized runtime events as an event sequence; mine serial/parallel episodes such as `Notify Wait end -> EVENT_WAIT start` within a time window. Measure support, confidence, and occurrence windows. | Cite for temporal event sequence pattern discovery and episode support/confidence. |
| Temporal graph motifs | Paranjape A, Benson A R, Leskovec J. Motifs in Temporal Networks. WSDM 2017:601-610. DOI:10.1145/3018661.3018731. https://arxiv.org/abs/1612.09259 | Models repeated timestamped edge patterns in temporal graphs. This maps naturally to process-device-stream nodes and wait/notify temporal edges. | Build a temporal graph where nodes are `(process_key, device_id, stream_id)` and edges are mined temporal relations. Count repeated 3-edge/4-edge motifs within delta windows. | Cite for cross-process synchronization motif modeling. |
| Local process models | Tax N, Sidorova N, Haakma R, van der Aalst W M P. Mining Local Process Models. Journal of Innovation in Digital Ecosystems, 2016, 3(2):183-196. DOI:10.1016/j.jides.2016.11.001. https://arxiv.org/abs/1606.06066 | Discovers local behavior fragments instead of one global process model. This fits noisy runtime traces with loops, choices, concurrency, and partial behavior. | Convert each step/window into an event log case. Try to discover local process fragments around repeated synchronization anchors, allowing branches and optional compute events. | Cite for "local, partial, non-strict behavior model" framing. |
| Execution trace loop discovery | Xu Q, Subhlok J, Hammen N. Efficient Discovery of Loop Nests in Execution Traces. MASCOTS 2010. https://www2.cs.uh.edu/~jaspal/papers/10mascots.pdf | Already related to our Loop Analyzer. It is stricter and sequence-oriented, so it provides a baseline we extend beyond. | Compare exact loop/macro discovery on single stream with fuzzy cross-stream meta patterns. Use as "exact sequence compression baseline". | Already suitable for thesis related work and Loop Analyzer chapter. |
| HPC communication trace compression | Noeth M, Ratn P, Mueller F, Schulz M, de Supinski B. ScalaTrace: Scalable Compression and Replay of Communication Traces for High-Performance Computing. JPDC, 2009, 69(8):696-710. DOI:10.1016/j.jpdc.2008.09.001. https://arcb.csc.ncsu.edu/~mueller/ftp/pub/mueller/papers/jpdc08.pdf | Shows how distributed communication traces can be compressed while preserving communication structure. It is MPI-oriented but useful for scalable structural summarization. | Compare our collective meta pattern with MPI-style cross-node communication compression. Check whether two-level local/global summarization inspires process-local plus machine-level compression. | Cite for scalable communication trace structure preservation. |

### P1: Try if P0 Looks Promising

| Direction | Paper | Why it matters | hprofile reproduction idea | Thesis use |
| --- | --- | --- | --- | --- |
| Matrix Profile / time-series motifs | Yeh C-C M, Zhu Y, Ulanova L, Begum N, Ding Y, Dau H A, Silva D F, Mueen A, Keogh E. Matrix Profile I: All Pairs Similarity Joins for Time Series. ICDM 2016. https://www.cs.ucr.edu/~eamonn/MatrixProfile.html | Finds similar subsequences by distance rather than exact event equality. Good for fuzzy matching after converting windows into numeric features. | Convert sliding windows into vectors: `[wait_ratio, comm_ratio, exec_ratio, event_density, active_stream_count, skew]`; run matrix-profile-like motif search or simpler distance-based motif search. | Cite if we use numeric feature motif discovery. |
| Matrix Profile with large-scale/GPU motif search | Zhu Y, Zimmerman Z, Senobari N S, Yeh C-C M, Funning G, Mueen A, Brisk P, Keogh E. Matrix Profile II: Exploiting a Novel Algorithm and GPUs to Break the One Hundred Million Barrier for Time Series Motifs and Joins. ICDM 2016. https://www.cs.ucr.edu/~eamonn/MatrixProfile.html | Relevant if we want scalable motif discovery over long profiling traces. | Use only after building feature time series. It may be overkill for undergraduate thesis but useful for future publication. | Outlook citation, not core unless implemented. |
| Generalized/minimal-occurrence episodes | Mannila H, Toivonen H. Discovering Generalized Episodes Using Minimal Occurrences. KDD 1996. https://f.aaai.org/Library/KDD/1996/kdd96-024.php | Minimal occurrences help avoid over-counting overlapping temporal patterns. | Test whether minimal occurrence counting gives more stable support for repeated notify/event edges. | Optional citation if frequent episode support counting becomes central. |
| Efficient frequent episode mining | Ao X, Luo P, Li C, Wang F, He Q. Efficient Mining of Frequent Episodes from Complex Sequences. Information Sciences, 2008. DOI:10.1016/j.ins.2007.11.003. https://www.sciencedirect.com/science/article/abs/pii/S0306437907000506 | Improves episode mining for more complex sequences. | Useful if basic episode mining is too slow or support counting is unstable. | Future work citation if needed. |

### P2: Background / Optional

| Direction | Paper | Why it matters | hprofile reproduction idea | Thesis use |
| --- | --- | --- | --- | --- |
| Distributed trace anomaly graph | ServiceAnomaly: An anomaly detection approach in microservices using distributed traces and profiling metrics. Journal of Systems and Software, 2024. https://www.sciencedirect.com/science/article/pii/S0164121223003126 | Combines trace graph and profiling metrics for anomaly detection. It is microservice-oriented, not accelerator trace-oriented. | Borrow the idea of annotated graphs and metric features, not the full method. | Optional outlook citation. |
| Automated MPI performance abstraction | Sikora A, Margalef T, Jorba J. Automated and dynamic abstraction of MPI application performance. Cluster Computing, 2016. https://link.springer.com/article/10.1007/s10586-016-0615-4 | Further background on MPI performance abstraction. | Compare with our machine-level abstraction if we need more HPC context. | Optional related work. |

## Reading Workflow

1. Create a local paper cache:

```text
paper/readings/fuzzy_meta_patterns/
```

2. Download PDFs and keep filenames stable:

```text
01_mannila_frequent_episodes_1997.pdf
02_paranjape_temporal_motifs_2017.pdf
03_tax_local_process_models_2016.pdf
04_xu_loop_nests_mascots_2010.pdf
05_noeth_scalatrace_2009.pdf
06_yeh_matrix_profile_i_2016.pdf
07_zhu_matrix_profile_ii_2016.pdf
```

3. For each paper, write a short note:

```text
paper/readings/fuzzy_meta_patterns/notes.md
```

Suggested note template:

```text
## Paper

- Problem:
- Core representation:
- Matching / mining algorithm:
- Noise or approximate matching support:
- What maps to hprofile:
- What does not map:
- Minimal experiment on 20260422_163744:
- Should cite in undergraduate thesis: yes/no
- Should cite in future paper: yes/no
```

4. Run one reproduction experiment per algorithm family, not per paper:

```text
episode_mining_baseline.py
temporal_graph_motif_baseline.py
local_process_model_notes.md
matrix_profile_feature_motif_baseline.py
```

5. Only promote a method into the thesis if it helps explain our real timeline.
   Avoid citing methods we do not actually use unless they are necessary
   background.

## Mapping to Our Thesis References

Likely undergraduate thesis citations:

1. Xu et al. 2010: exact loop discovery baseline for Loop Analyzer.
2. Mannila et al. 1997: temporal event episode mining.
3. Paranjape et al. 2017: temporal graph motif modeling.
4. Tax et al. 2016: local process model / partial behavior mining.
5. Noeth et al. 2009: scalable communication trace compression.

Likely future-paper citations:

1. Matrix Profile I/II if we implement numeric feature motif discovery.
2. ServiceAnomaly if we frame anomaly detection over annotated trace graphs.
3. Later LPM grouping/interest-driven LPM papers if local process model
   discovery becomes important.

## Reading Status

| Paper | Local files | Decision | Takeaway |
| --- | --- | --- | --- |
| Mannila et al. 1997, frequent episodes | `paper/readings/fuzzy_meta_patterns/01_mannila_frequent_episodes_1997.pdf`; `paper/readings/fuzzy_meta_patterns/01_mannila_frequent_episodes_1997.txt`; `paper/readings/fuzzy_meta_patterns/notes.md` | Keep | Use as the theoretical basis for time-window episodes, partial-order event patterns, support/confidence, and minimal occurrences. Good for anchor mining, but insufficient alone for process-device-stream temporal graphs and soft compute regions. |
| Paranjape et al. 2017, temporal network motifs | `paper/readings/fuzzy_meta_patterns/02_paranjape_temporal_motifs_2017.pdf`; `paper/readings/fuzzy_meta_patterns/02_paranjape_temporal_motifs_2017.txt`; `paper/readings/fuzzy_meta_patterns/notes.md` | Keep | Use as the theoretical basis for modeling cross-process/device/stream synchronization as repeated temporal graph motifs. Good for hard-anchor topology; needs extension for approximate variants, duration-rich events, and soft compute regions. |
| Tax et al. 2016/2017, local process models | `paper/readings/fuzzy_meta_patterns/03_tax_local_process_models_2016.pdf`; `paper/readings/fuzzy_meta_patterns/03_tax_local_process_models_2016.txt`; `paper/readings/fuzzy_meta_patterns/notes.md` | Keep as quality/ranking reference | Use its local-pattern framing and quality dimensions: support, confidence, coverage, determinism, language fit. Do not implement full process-tree/Petri-net LPM discovery first. |
| Yeh et al. 2016, Matrix Profile I | `paper/readings/fuzzy_meta_patterns/04_yeh_matrix_profile_i_2016.pdf`; `paper/readings/fuzzy_meta_patterns/04_yeh_matrix_profile_i_2016.txt`; `paper/readings/fuzzy_meta_patterns/notes.md` | Keep as numeric feature motif background | Use as an auxiliary method for approximate repeated feature-window discovery. It is useful for soft-region similarity, but it does not preserve process/device/stream topology or synchronization edges. |
| Yeh et al. 2017, Matrix Profile VI | `paper/readings/fuzzy_meta_patterns/05_yeh_matrix_profile_vi_multidimensional_2017.pdf`; `paper/readings/fuzzy_meta_patterns/05_yeh_matrix_profile_vi_multidimensional_2017.txt`; `paper/readings/fuzzy_meta_patterns/notes.md` | Keep as subspace motif reference | Strong support for the argument that motifs may exist only on a stable subset of dimensions. Maps well to stable synchronization skeletons plus variable compute regions. |
| Noeth et al. 2009, ScalaTrace | `paper/readings/fuzzy_meta_patterns/06_noeth_scalatrace_2009.pdf`; `paper/readings/fuzzy_meta_patterns/06_noeth_scalatrace_2009.txt`; `paper/readings/fuzzy_meta_patterns/notes.md` | Keep | Use as distributed communication trace compression and replay background. It supports the need for structure-preserving summaries between aggregate profiling and raw tracing, and motivates participant-set compression plus source localization. |

## Why This Matters

For distributed LLM inference, high wait/comm ratios are not just raw overhead
numbers. They often reflect repeated synchronization patterns between devices,
processes, and streams.

An approximate meta-pattern analyzer could help answer:

- Which synchronization skeletons dominate the workload?
- Which process-device pairs repeatedly form wait/notify relations?
- Which rank or process-device is often the slow side of a pattern?
- Are compute regions around the same synchronization skeleton stable or
  divergent?
- Which patterns are good candidates for source-level optimization?

## Near-Term Experiment Plan

1. Use `analyzer/out/20260422_163744` as the first full-trace test case.
2. Build `integrated_profile/events.csv` or SQLite event table from all raw dbs.
3. Implement anchor mining for generic event-family pairs within a time window.
4. Generate `collective_edges.csv` with process-device-stream keys and deltas.
5. Group repeated edge sets into candidate temporal graph motifs.
6. Extract soft-region feature vectors around each motif occurrence.
7. Cluster approximate occurrences and report support/confidence/outliers.
8. Compare the discovered motifs with manual Perfetto observations.
9. Add only optional source annotations after the generic pattern is discovered.

## Expected Output Artifacts

```text
derived/integrated_profile/
  machine_timeline.perfetto.json
  events.sqlite
  events.csv
  process_summary.csv
  device_summary.csv
  stream_summary.csv

derived/fuzzy_meta_patterns/
  anchor_edges.csv
  temporal_motifs.csv
  motif_occurrences.csv
  motif_soft_features.csv
  motif_outliers.csv
  motif_report.md
```

## Thesis / Paper Framing

This can be framed as:

> Approximate runtime meta-pattern discovery for distributed accelerator traces.

The key claim should remain conservative:

- We do not claim to automatically understand vLLM semantics.
- We discover recurring runtime structures from generic profiling events.
- Workload-specific interpretation is layered on top of discovered patterns.
