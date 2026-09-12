# Whole-Cluster Stampede3 Research Capacity

The planning scope is the entire Stampede3 reservation for the anticipated allocation week, as explicitly confirmed by Kairos on 12 September 2026. The earlier four-PVC-node example is superseded as a capacity plan. Ordinary shared-queue limits describe the old pilot's environment; they do not establish the size of this reservation. Its actual submission mechanism remains an execution detail to obtain when access arrives.

## Proposed population and placement

The working proposal is **10,000 persistent Qwen3.8-27B researchers and eight larger-model lead identities: four Kimi K3 and four GLM-5.3**, served by approximately **1,800 Qwen replicas and a model-dependent lead pool on the 96 H100s**. Kairos accepted four K3 and four GLM-5.3 leaders as the starting group on 12 September 2026. This is an agreed agent count, not measured serving capacity. The Qwen population and placements also remain proposals. Agent identities retain separate histories while sharing inference services. The [current model review](2026-09-12-open-model-lead-selection.md) records the preferred pairing and remaining comparisons; the earlier 24-leader and uniform Nemotron allocation proposals are superseded.

The inventory basis is TACC's current operational guide: 560 SPR, 1,060 SKX, 224 ICX, three large-memory nodes, 20 four-GPU PVC nodes, and 24 four-GPU H100 nodes. Its per-node memory figures make one 27B replica per main CPU node a reasonable memory-fit candidate. Actual model loading and useful request rates remain unmeasured. [TACC architecture](https://docs.tacc.utexas.edu/hpc/stampede3/#system-architecture)

| Proposed placement | Research service | Replicas |
| --- | --- | ---: |
| 560 SPR nodes | One Qwen service per node | 560 |
| 960 SKX nodes | One Qwen service per node | 960 |
| 192 ICX nodes | One Qwen service per node | 192 |
| 20 PVC nodes, four physical GPUs each | One Qwen service per physical GPU | 80 |
| 24 H100 nodes | Preferred Kimi K3 / GLM-5.3 lead pool, pending backend and placement tests | To be measured |
| Remaining 100 SKX, 32 ICX, and three large-memory nodes | Retrieval, source processing, analysis tools, coordination, memory indexes, and recovery | Assigned by workload |

This accounts for all node classes in the published inventory without consuming every CPU node for language inference. The Qwen total is **1,792 replicas**; the population proposal averages about 5.6 persistent researchers per replica. Their actual assignment should reflect measured differences in hardware performance. GPU-node host CPUs also remain available for colocated supporting services where appropriate.

## Larger models

**Kimi K3 and GLM-5.3 are the preferred lead families**, following Kairos's latest suggestion. Their successful deployment on Stampede3 remains unverified; in particular, K3's published serving recipe emphasizes GB300 hardware. The [model-selection review](2026-09-12-open-model-lead-selection.md) retains DeepSeek V4.1 Flash as an alternative and Nemotron as a comparison. Serving replicas and GPU placement must follow backend tests and measured research workloads.

The agreed eight leaders begin with four pairs, each containing one K3 and one GLM-5.3 agent:

| Initial responsibility | Lead identities |
| --- | --- |
| Research direction and question formation | One K3, one GLM-5.3 |
| Evidence synthesis and unresolved disagreements | One K3, one GLM-5.3 |
| Methods, causal assumptions, and statistical scrutiny | One K3, one GLM-5.3 |
| Case applicability and participant priorities | One K3, one GLM-5.3 |

These are starting responsibilities, with room to rotate and follow new questions. They do not establish model-specific medical expertise. Each leader retains a private history, forms an initial assessment before seeing its counterpart's conclusions, and explicitly shares findings with their sources. Preserve dissent and changed judgments. Separate histories and different model families may diversify perspectives, but do not make errors statistically independent. Agents attending to participant priorities use priorities expressed by those participants; they cannot supply consent or decide what someone wants.

Eight lead identities need not mean eight loaded model replicas. Several identities can share a model service while retaining separate memory and request state. Leads help with difficult questions and cross-specialty synthesis; routine findings should not require approval from every leader.

For the retained **Nemotron 3 Ultra 550B-A55B comparison scenario**, NVIDIA's NVFP4 model card lists an eight-H100 minimum. The 96-H100 pool therefore provides twelve eight-GPU placements, each spanning two of Stampede3's four-GPU nodes. This is hardware-count arithmetic; successful inter-node serving, usable context, and end-to-end performance still need verification. [NVIDIA NVFP4 model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4)

The BF16 card lists sixteen H100s, giving six placements across the same pool if that precision is selected. Both counts describe the retained Nemotron comparison scenario; neither establishes a replica count for K3 or GLM-5.3. [NVIDIA BF16 model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16)

This candidate has not demonstrated better biomedical research performance in this project. Compare its source fidelity, reasoning, and ability to resolve specific research problems against the 27B baseline before assigning authority to its outputs. The lead pool can host competing model choices as evidence warrants. Leads should coordinate difficult questions and cross-specialty synthesis; routine findings should not all wait for approval from one central model pool.

## Memory and cadence

A nominal 27-billion-parameter model needs approximately 54 GB for BF16 weights, or 13.5 GB for four-bit weights before quantization metadata. Both estimates exclude sequence state, workspace, runtime overhead, and other processes. Memory capacity establishes candidate placements; it does not establish generation speed or the number of concurrent long-context requests.

For a population `N`, `C` model calls per research turn, and an average interval `W` minutes between turns, the required aggregate service rate is:

`R_required = N × C / W` requests per minute.

For 10,000 researchers, two calls per turn, and one turn per hour, the target is approximately **333 completed requests per minute across the Qwen pool**. This is a workload requirement, not a forecast. Retrieval, reasoning, review, retries, and memory formation must be included in the measured call count. Token lengths and completion latency must accompany request-rate measurements.

Cadence can differ across the community. Some agents may interact frequently; others may revisit a question over hours. A slower researcher can still contribute useful independent work. There is no requirement that all 10,000 maintain live inference state simultaneously, nor that they all communicate with one another directly.

## Preparation and measurement

The [two-turn model probe](../lead-model-probes.md) now provides a bounded text
protocol check for an existing endpoint, including preserved assistant state
and response to a fictional source correction. It does not load models or
establish hardware compatibility.

Run CPU and GPU compatibility probes and representative research tasks in parallel across hardware classes. Compare supported precision choices using identical evidence and questions within each experimental comparison. Record model revisions, backend support, input/output lengths, memory use, failures, and latency; preserve hardware and precision as explicit factors in research comparisons.

Separate the continuing community from experimental copies. Route evidence through topic-based discovery and explicit sharing, while preserving each participant's private history and source dependencies. Reserve the supporting nodes for actual research computations as well as the infrastructure required to sustain the community.

The existing launcher remains a four-node synthetic pilot. It needs CPU serving profiles, use of all assigned GPUs, reservation-aware scheduling, larger population support, and live cross-node research exchange before it can execute this proposal. No cluster job, model download, or application-code change was performed for this capacity revision. Whole-cluster availability is accepted as the planning premise; successful deployment and inference capacity remain to be demonstrated.
