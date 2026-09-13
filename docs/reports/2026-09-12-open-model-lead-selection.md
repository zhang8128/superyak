# Open-Weight Model Selection for the Research Community

**Superseded selection, later September 12:** Kairos now requires
[American models only](../model-policy.md), with Gemma 4 preferred. The selections
below are preserved as a dated comparison; they no longer authorize Qwen, Kimi,
GLM, or DeepSeek use. Gemma role assignments and project performance remain to
be measured.

## Historical recommendation

**Kimi K3 and GLM-5.3 are the preferred lead families**, following Kairos's suggestion to use both for several leaders. Kairos accepted the starting arrangement of four persistent K3 leaders and four GLM-5.3 leaders on 12 September 2026. Retain Qwen3.8-27B as the preferred worker baseline, DeepSeek V4.1 Flash as an alternative to evaluate, and Nemotron 3 Ultra as a deployment and performance comparison. See the [whole-cluster plan](2026-09-12-stampede3-whole-cluster-plan.md) for proposed responsibilities and memory separation.

This is a revised recommendation based on public evidence checked on 12 September 2026. None of these larger models has been evaluated on this project's research tasks or on Stampede3 by this session. A generic benchmark lead supports prioritizing a candidate; it does not establish biomedical research quality.

## Current comparable evidence

Artificial Analysis's current Intelligence Index is version 4.3. The following are the rounded values displayed in the current model pages or leaderboard for the specified reasoning settings. This is a composite index, not a percentage of correct clinical decisions, and its differences should not be interpreted as ratios of intelligence.

| Model and setting | Current index | Role in the comparison |
| --- | ---: | --- |
| [GLM-5.3, max](https://artificialanalysis.ai/models/glm-5-3) | 45 | Preferred lead family, paired with K3 for comparison across research responsibilities. |
| [Kimi K3, max](https://artificialanalysis.ai/models/kimi-k3) | 44 | Preferred lead family, paired with GLM-5.3 for comparison across research responsibilities. |
| [DeepSeek V4.1 Flash, max](https://artificialanalysis.ai/models/deepseek-v4-1-flash) | 40 | New September candidate for multimodal research and long-input workloads. |
| [DeepSeek V4 Pro 0813, max](https://artificialanalysis.ai/models/deepseek-v4-pro) | 36 | August flagship update; useful comparison, without assuming the Pro label establishes superiority. |
| [Qwen3.8-27B, xhigh](https://artificialanalysis.ai/models/qwen3-8-27b) | 34 | Preferred worker baseline and a necessary control for whether a much larger model helps. |
| [Nemotron 3 Ultra, reasoning](https://artificialanalysis.ai/models/nvidia-nemotron-3-ultra-550b-a55b) | 23 | Known hardware-fit candidate; current composite evidence does not support making it the default stronger researcher. |

The [current leaderboard](https://artificialanalysis.ai/leaderboards/models) supplies the comparison context. These evaluations use particular served models, reasoning settings, and test procedures. Their measured API speeds are not Stampede3 benchmarks. The current GLM and Kimi pages rank them first and second within the evaluator's large open-weight comparison class; that is narrower than claiming first and second across all models or all tasks.

Date and benchmark version matter. Artificial Analysis's [June launch evaluation of Nemotron](https://artificialanalysis.ai/articles/nvidia-nemotron-3-ultra-released) reported 47.7 on the index then in use and described a speed–quality tradeoff. Comparing that historical 47.7 directly with today's 45 for GLM would be invalid. The evaluator also disclosed working with NVIDIA before release. The current comparison above uses the updated index instead.

## New releases and model identity

DeepSeek V4.1 Flash is a particularly relevant addition: its official repository was created on 10 September 2026, and its card describes native text/image input, a million-token context, a 552B backbone, and an additional conditional-memory component. It activates different amounts of computation during input processing and generation. These distinctions are reasons to examine its actual research behavior and deployment requirements, not treat the word Flash as a model-size specification. [Official card](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash), [repository metadata](https://huggingface.co/api/models/deepseek-ai/DeepSeek-V4.1-Flash)

DeepSeek's internal component named Engram is separate from Superyak's Engram memory system. Its presence in a model does not supply this project's participant-owned histories or explicit sharing protocol.

Qwen3.8-2.4T-A95B also belongs on the broader shortlist. However, its card's headline evaluation table is labeled **Qwen3.8-Max**, the hosted product. The card explicitly distinguishes hosted features such as vision and non-thinking support from the downloadable checkpoint. Hosted results should not silently become scores for our local weights and harness. [Official Qwen card](https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B)

License terms must likewise follow the exact release. DeepSeek V4.1 Flash identifies its license as MIT. GLM-5.3, Kimi K3, and Qwen3.8's large model carry named custom licenses; calling all of them unrestricted open source would be inaccurate. [GLM license](https://huggingface.co/zai-org/GLM-5.3/blob/main/LICENSE), [Kimi license](https://huggingface.co/moonshotai/Kimi-K3/blob/main/LICENSE), [Qwen license](https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B/blob/main/LICENSE)

## Stampede3 implications

The whole-machine reservation remains the planning premise. Model selection changes how its H100 pool should be divided. The previous twelve-replica calculation applied specifically to eight-H100 Nemotron NVFP4 placements; it is not a model-independent count of lead services.

GLM-5.3's official card points to maintained serving implementations, and its native checkpoint uses FP8. The vLLM recipe's standard deployment uses eight H200s. Adapting that to Stampede3's four-H100 nodes requires an explicit multi-node placement and runtime check; a supported-Hardware selector does not demonstrate this exact cluster configuration. [GLM card](https://huggingface.co/zai-org/GLM-5.3), [vLLM recipe](https://recipes.vllm.ai/zai-org/GLM-5.3)

Kimi K3's recipe emphasizes GB300 hardware, while Qwen's large-model recipe includes large Blackwell/H200 placements and specific quantization backends. Sufficient aggregate RAM does not establish that their optimized kernels work on H100. Treat Hopper compatibility, checkpoint precision, communication, and practical context lengths as explicit measurements before committing replicas. [Kimi recipe](https://recipes.vllm.ai/moonshotai/Kimi-K3), [Qwen recipe](https://recipes.vllm.ai/Qwen/Qwen3.8-2.4T-A95B)

A community can support the agreed eight lead identities with a separately measured number of model-serving replicas. Each identity retains its own memory and request state. Distinct families may provide useful disagreements, but shared training data and evaluation methods mean their agreement is not automatically independent corroboration. Neither the eight identities nor the available 96 H100s establishes that both selected checkpoints can be served together at useful latency.

## Selection experiment

Compare the candidates in parallel on the same public-source research questions, including study reconstruction, conflicts between papers, dataset overlap, biological-model assumptions, and revision after a source correction. Include document and figure interpretation when that is part of the intended role. Keep question and evidence versions fixed; record each model's native reasoning and tool protocol instead of silently flattening them into one chat template.

Assess source fidelity, unsupported inferences, useful counterarguments, correction behavior, and participant-facing clarity. Report time and resource use separately. Preserve a held-out set of questions to avoid selecting a model solely on the tasks used to tune its prompts. Include evaluation independent of the generating model, using objective checks where possible and domain review where interpretation is necessary.

The preferred pairing is Kimi K3 and GLM-5.3, with the number of serving replicas pending hardware tests. DeepSeek V4.1 Flash remains a substantive alternative if deployment or research results warrant a change. Refresh release and backend information before the allocation starts, then pin exact checkpoints for each comparison. No model was downloaded or launched, and no deployment configuration was changed by this review.
