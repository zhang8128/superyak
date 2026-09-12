"""Rebuild the planning workbook: python3 this_file.py (requires xlsxwriter).

This is an artifact generator, not a deployment or benchmark script.
No measurements are supplied. Formula caches reproduce the stated assumptions.
"""

from pathlib import Path
import math
import itertools
import random

import xlsxwriter


OUTPUT = Path(__file__).with_suffix(".xlsx")
TACC = "https://docs.tacc.utexas.edu/hpc/stampede3/"
wb = xlsxwriter.Workbook(OUTPUT)
wb.set_properties({"title": "Stampede3 community capacity", "comments": "Planning assumptions; no measured throughput."})
title = wb.add_format({"bold": True, "font_size": 17, "font_color": "#222222"})
head = wb.add_format({"bold": True, "bg_color": "#E6E6E6", "text_wrap": True, "valign": "top", "bottom": 1})
body = wb.add_format({"text_wrap": True, "valign": "top"})
num = wb.add_format({"num_format": "0.00", "valign": "top"})
integer = wb.add_format({"num_format": "0", "valign": "top"})
entry = wb.add_format({"font_color": "#165B8C", "bg_color": "#F2F6F8", "num_format": "0.00", "valign": "top"})
pct = wb.add_format({"font_color": "#165B8C", "bg_color": "#F2F6F8", "num_format": "0%", "valign": "top"})
link = wb.add_format({"font_color": "#165B8C", "underline": 1, "text_wrap": True, "valign": "top"})


def sheet(name, label, widths):
    ws = wb.add_worksheet(name)
    ws.hide_gridlines(2)
    ws.set_default_row(28)
    for col, width in enumerate(widths):
        ws.set_column(col, col, width, body)
    ws.merge_range(0, 0, 0, len(widths) - 1, label, title)
    ws.set_row(0, 34)
    ws.freeze_panes(3, 1)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)
    ws.set_paper(9)
    return ws


def positive(ws, cells, whole=False, maximum=1e9):
    ws.data_validation(cells, {"validate": "integer" if whole else "decimal", "criteria": "between", "minimum": 0.000001 if not whole else 1, "maximum": maximum, "error_type": "stop", "error_message": "Enter a positive value within the stated bounds."})


read = sheet("Read me", "Stampede3 community capacity", [31, 94])
read.write_row(2, 0, ["Item", "Meaning"], head)
notes = [
    ("Status", "Research planning artifact, September 12, 2026. No Stampede3 benchmark, allocation entitlement, or deployment is represented."),
    ("Editable inputs", "Blue cells are editable. Throughput and available device-memory inputs are intentionally blank. Their dependent capacity estimates remain pending."),
    ("Run budget", "Parallel campaign budget: 110 allocated node-hours, including continuing-community nodes and idle wave capacity. Reserve is 20% of the total budget. Queue waits are separate."),
    ("Parallel screen", "16 factorial cells plus four serial references. Editable node/slot assumptions show elapsed compute time and billed node-hours; this is a draft schedule, not a Slurm submission."),
    ("Agent cadence", "Population means persistent agents receiving turns at a target interval. It is not a count of simultaneous GPU requests or model replicas."),
    ("Measured rate", "Measure the whole serving pool at the target prompt/output mix and acceptable latency. Include real memory/review traffic in calls per turn. Do not extrapolate linearly across nodes."),
    ("Memory fit", "A hypothetical conventional dense-transformer calculation. Parameter count and KV layout are examples, not a selected model. A memory bound is not measured serving concurrency."),
    ("Separate budgets", "The report also proposes 20% of research turns for discretionary exploration. That is independent of the SU reserve and the serving-capacity factor."),
    ("Formula caches", "Initial cached values are included for viewers. Excel/LibreOffice recalculate on edit. The generator makes no network calls and changes only its sibling XLSX file."),
    ("Companion report", "2026-09-12-stampede3-research-community.md contains the evidence, architecture, experimental design, source versions, and unresolved decisions."),
    ("Reproduce", "Run python3 2026-09-12-stampede3-capacity.py with xlsxwriter available. This is not a cluster launch script."),
]
for row, values in enumerate(notes, 3):
    read.write_row(row, 0, values, body)
    read.set_row(row, 57)

budget = sheet("Run budget", "Allocation budget — proposed use", [35, 17, 21, 23, 18, 53])
budget.write_row(2, 0, ["Input", "Value", "Unit", "Status", "", "Basis"], head)
for row, label, value, unit, status, basis in [
    (3, "PVC charge rate", 3, "SU / node-hour", "Documented", "Source S1; verify current allocation accounting."),
    (4, "Minimum billed job duration", .25, "hours", "Documented", "Applies to each started job."),
    (5, "Reserve / total requested budget", .20, "fraction", "Assumption", "Reserve covers retries and additional checks; not a guarantee."),
    (6, "Available SU", None, "SU", "Unknown", "Enter confirmed allocation balance; do not infer from machine size."),
]:
    budget.write(row, 0, label)
    budget.write_blank(row, 1, None, entry) if value is None else budget.write_number(row, 1, value, pct if row == 5 else entry)
    budget.write(row, 2, unit)
    budget.write(row, 3, status)
    budget.write(row, 5, basis)
budget.write_comment("B4", "S1: TACC Stampede3 guide, accessed 2026-09-12. " + TACC)
budget.write_comment("B5", "S1: charging equation includes a 0.25-hour minimum per job. " + TACC)
positive(budget, "B4:B5")
positive(budget, "B7")
budget.data_validation("B6", {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": .95})
budget.write_row(8, 0, ["Stage", "Nodes", "Hours per job", "Node-hours", "SU", "Proposed purpose"], head)
stages = [
    ("Parallel readiness", 4, 1, "Independent inference and memory/recovery probes"),
    ("Opening comparisons", 4, 10.5, "Three comparison nodes plus one continuing community; includes final idle slot"),
    ("Targeted diagnostics", 4, 3, "Up to six comparison slots plus continuing community"),
    ("Replication", 4, 6, "Up to twelve comparison slots plus continuing community"),
    ("Community extension", 1, 12, "Longer research and observation"),
    ("Synthesis and replay", 1, 8, "Source review and selected interventions"),
    ("Export and restore", 1, 8, "Durable state and restore"),
]
for row, (name, nodes, hours, purpose) in enumerate(stages, 9):
    budget.write(row, 0, name)
    budget.write_number(row, 1, nodes, entry)
    budget.write_number(row, 2, hours, entry)
    excel = row + 1
    budget.write_formula(row, 3, f"=B{excel}*C{excel}", num, nodes * hours)
    budget.write_formula(row, 4, f"=B{excel}*MAX(C{excel},$B$5)*$B$4", num, nodes * max(hours, .25) * 3)
    budget.write(row, 5, purpose)
positive(budget, "B10:B16", whole=True, maximum=4)
positive(budget, "C10:C16", maximum=48)
budget.write("A18", "Planned total", head)
budget.write_formula("D18", "=SUM(D10:D16)", num, 110)
budget.write_formula("E18", "=SUM(E10:E16)", num, 330)
budget.write("A19", "Requested total including reserve")
budget.write_formula("E19", "=E18/(1-B6)", num, 412.5)
budget.write("A20", "Reserve in SU")
budget.write_formula("E20", "=E19-E18", num, 82.5)
budget.write("A21", "Balance after requested total")
budget.write_formula("E21", '=IF(B7="","Unknown",B7-E19)', num, "Unknown")
budget.merge_range("A23:F24", "Stages are editable allocation envelopes and may exchange slots. Every started job has its own minimum charge. The opening row follows Parallel screen inputs; other stages are independent budget assumptions. This does not guarantee a full sample or reservation.", body)
budget.write_row(26, 0, ["Arithmetic envelope", "Nodes", "Total hours", "Node-hours", "SU", "Meaning"], head)
for row, nodes in enumerate([1, 2, 4], 27):
    excel = row + 1
    budget.write(row, 0, "Continuous week, multiple jobs")
    budget.write_number(row, 1, nodes, integer)
    budget.write_number(row, 2, 168, integer)
    budget.write_formula(row, 3, f"=B{excel}*C{excel}", num, nodes * 168)
    budget.write_formula(row, 4, f"=D{excel}*$B$4", num, nodes * 168 * 3)
    budget.write(row, 5, "Arithmetic only; not one valid job or a reservation.")

screen = sheet("Parallel screen", "Parallel comparison schedule", [23, 23, 19, 18, 20, 19, 48])
screen.write_row(2, 0, ["Input / result", "Value", "Unit", "", "", "", "Meaning"], head)
for row, label, value, unit, note in [
    (3, "Comparison nodes", 3, "nodes", "Independent node-local cells; lower when allocation is smaller."),
    (4, "Community nodes", 1, "nodes", "Separate continuing community; can be zero in a reduced schedule."),
    (5, "Slot duration", 1.5, "hours", "Hypothetical time box including initialization and snapshot."),
    (6, "Factorial cells", 16, "cells", "Individual/shared booleans × populations 32/128 × request caps 4/16."),
    (7, "Serial references", 4, "cells", "One agent and one in-flight request for each individual/shared memory condition."),
]:
    screen.write(row, 0, label)
    screen.write_number(row, 1, value, entry if row < 6 else integer)
    screen.write(row, 2, unit)
    screen.write(row, 6, note)
    screen.set_row(row, 46)
positive(screen, "B4", whole=True, maximum=4)
screen.data_validation("B5", {"validate": "integer", "criteria": "between", "minimum": 0, "maximum": 3})
positive(screen, "B6", maximum=48)
screen.write("A10", "Number of waves")
screen.write_formula("B10", "=ROUNDUP((B7+B8)/B4,0)", integer, 7)
screen.write("A11", "Compute window")
screen.write_formula("B11", "=B10*B6", num, 10.5)
screen.write("C11", "hours; excludes queue waits")
screen.write("A12", "Allocated node-hours")
screen.write_formula("B12", "=(B4+B5)*B11", num, 42)
screen.write("A13", "Opening SU")
screen.write_formula("B13", "=(B4+B5)*MAX(B11,'Run budget'!B5)*'Run budget'!B4", num, 126)
screen.write("A14", "Node-limit check")
screen.write_formula("B14", '=IF(B4+B5>4,"Exceeds published limit","Within published limit")', body, "Within published limit")
screen.merge_range("A16:G17", "Draft interleaving; rotate nodes/order for follow-up seeds. Same model, precision, context limits, and placement across the screen. Do not infer statistical significance from one seed per cell. Request caps are not GPU counts. No measurements are represented.", body)
screen.write_row(19, 0, ["Cell", "Individual", "Shared", "Population", "Request cap", "Wave", "Logical comparison node / role"], head)
cells = [(i, s, p, c, "factorial") for i, s, p, c in itertools.product([False, True], [False, True], [32, 128], [4, 16])]
cells += [(i, s, 1, 1, "serial reference") for i, s in itertools.product([False, True], repeat=2)]
random.Random(1729).shuffle(cells)
for index, (ind, shared, population, cap, kind) in enumerate(cells):
    row = index + 20
    screen.write_row(row, 0, [f"screen-{index+1:02d}", "on" if ind else "off", "on" if shared else "off", population, cap])
    screen.write_formula(row, 5, f"=ROUNDDOWN({index}/$B$4,0)+1", integer, index // 3 + 1)
    screen.write_formula(row, 6, f'=MOD({index},$B$4)+1&" / {kind}"', body, f"{index % 3 + 1} / {kind}")
screen.autofilter(19, 0, 39, 6)
budget.write_formula("B11", "='Parallel screen'!B4+'Parallel screen'!B5", num, 4)
budget.write_formula("C11", "='Parallel screen'!B11", num, 10.5)

cad = sheet("Agent cadence", "Agent population — measurement first", [47, 25, 25, 70])
cad.write_row(2, 0, ["Input / result", "Value", "Unit / status", "Interpretation"], head)
inputs = [
    (3, "Measured whole-pool completed request rate (R)", None, "requests / minute", "Enter a sustained rate at the actual context/output mix and acceptable latency."),
    (4, "Target interval between agent turns (W)", 10, "minutes / turn", "Proposed cadence; agent identity persists while waiting."),
    (5, "Usable fraction of measured capacity (U)", .8, "fraction", "Assumption: headroom and competing workloads use the remainder."),
    (6, "Mean model requests per research turn (C)", 2, "requests / turn", "Assumption; include memory formation, review, retries, and synthesis. Replace with measurement."),
]
for row, label, value, unit, note in inputs:
    cad.write(row, 0, label)
    cad.write_blank(row, 1, None, entry) if value is None else cad.write_number(row, 1, value, pct if row == 5 else entry)
    cad.write(row, 2, unit)
    cad.write(row, 3, note)
    cad.set_row(row, 48)
positive(cad, "B4:B5")
positive(cad, "B7")
cad.data_validation("B6", {"validate": "decimal", "criteria": "between", "minimum": .000001, "maximum": 1})
cad.write("A9", "Cadence population estimate", head)
cad.write_formula("B9", '=IF(B4="","Await measurement",ROUNDDOWN(B4*B5*B6/B7,0))', integer, "Await measurement")
cad.write("D9", "A scheduling estimate. Tool latency, serialization, and review may lower it.")
cad.write("A11", "Target population", head)
cad.write_number("B11", 64, entry)
positive(cad, "B11", whole=True)
cad.write("A12", "Required whole-pool request rate")
cad.write_formula("B12", "=B11*B7/(B5*B6)", num, 16)
cad.write("C12", "requests / minute")
cad.write("A13", "Target interval at measured rate")
cad.write_formula("B13", '=IF(B4="","Await measurement",B11*B7/(B4*B6))', num, "Await measurement")
cad.write("C13", "minutes / agent turn")
cad.merge_range("A15:D16", "Illustrations below are hypothetical rates, not predictions or measurements. They use the editable cadence/calls/headroom inputs above. Do not interpret them as a hardware limit.", body)
cad.write_row(18, 0, ["Hypothetical requests / minute", "Cadence population", "Status", "Basis"], head)
for row, rate in enumerate([2, 8, 32], 19):
    excel = row + 1
    cad.write_number(row, 0, rate, entry)
    cad.write_formula(row, 1, f"=ROUNDDOWN(A{excel}*$B$5*$B$6/$B$7,0)", integer, math.floor(rate * 10 * .8 / 2))
    cad.write(row, 2, "Hypothetical")
    cad.write(row, 3, "S2: analyst-selected sensitivity input, not an observed benchmark.")
positive(cad, "A20:A22")
cad.write_comment("B4", "A benchmark record must state model/tokenizer revisions, backend/driver, replica configuration, input/output lengths, latency distribution, failures, and total wall time.")

mem = sheet("Memory fit", "Device memory — illustrative accounting", [47, 25, 26, 68])
mem.write_row(2, 0, ["Input", "Value", "Unit", "Status / meaning"], head)
memory_inputs = [
    (3, "Parameters", 8, "billion", "Hypothetical dense model; no particular model selected."),
    (4, "Weight precision", 16, "bits / parameter", "Approximation excludes quantization metadata."),
    (5, "Transformer layers", 32, "layers", "Hypothetical conventional KV-cache layout."),
    (6, "KV heads", 8, "heads", "Use KV heads, which may differ from query heads."),
    (7, "Head dimension", 128, "elements", "Replace with actual model configuration."),
    (8, "KV precision", 2, "bytes / element", "Assumption; may differ from weight precision."),
    (9, "Cached tokens per sequence", 8192, "tokens", "Includes prompt and generated tokens retained in cache."),
    (10, "Other runtime allocation", 4, "GiB", "Illustrative placeholder; measure buffers and allocator overhead."),
    (11, "Available memory for this replica", None, "GiB", "Enter a verified allocatable limit for the actual placement; do not sum unpooled GPUs."),
    (12, "Device memory reserve fraction", .20, "fraction", "Assumption; independent of SU reserve."),
]
for row, label, value, unit, note in memory_inputs:
    mem.write(row, 0, label)
    mem.write_blank(row, 1, None, entry) if value is None else mem.write_number(row, 1, value, pct if row == 12 else entry)
    mem.write(row, 2, unit)
    mem.write(row, 3, note)
    mem.set_row(row, 42)
positive(mem, "B4:B12")
mem.data_validation("B13", {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": .95})
weights = 8e9 * 16 / 8 / 2**30
mem.write("A15", "Approximate weights")
mem.write_formula("B15", "=B4*1000000000*B5/8/POWER(2,30)", num, weights)
mem.write("C15", "GiB")
mem.write("A16", "Approximate KV / sequence")
mem.write_formula("B16", "=2*B6*B7*B8*B9*B10/POWER(2,30)", num, 1)
mem.write("C16", "GiB / sequence")
mem.write("A17", "Memory-only sequence upper bound", head)
mem.write_formula("B17", '=IF(B12="","Await measurement",MAX(0,ROUNDDOWN((B12*(1-B13)-B15-B11)/B16,0)))', integer, "Await measurement")
mem.write("D17", "Not a supported concurrency or throughput claim. Model/backend behavior can impose tighter bounds.")
mem.merge_range("A20:D22", "This approximation is unsuitable without adjustment for architectures with nonstandard caches, sliding-window attention, shared prefixes, offloading, or different tensor placement. Measure actual allocation and valid request performance. GB and GiB differ; these formulas report GiB.", body)
mem.write_comment("B4", "S2: hypothetical accounting inputs, selected to make the formula inspectable. Not model specifications.")
mem.write_comment("B12", "S1 documents physical GPU/tile memory, which is not substituted for an actual framework-visible allocatable limit. " + TACC)

src = sheet("Sources", "Sources and assumptions", [12, 30, 53, 28, 76, 49])
src.write_row(2, 0, ["ID", "Publisher", "Title", "Date / version", "URL or access note", "Use"], head)
sources = [
    ("S1", "TACC", "Stampede3 User Guide", "Accessed 2026-09-12", TACC, "Charge rate, per-job minimum, queue limits. Live settings may change."),
    ("S2", "Planning analysis", "Superyak research-community proposal", "2026-09-12", "Sibling 2026-09-12-stampede3-research-community.md", "Proposed durations, reserves, cadence assumptions, and hypothetical transformer layout. No measured performance."),
    ("S3", "PyTorch contributors", "Getting Started on Intel GPU", "PyTorch 2.14; updated 2026-08-21", "https://docs.pytorch.org/docs/2.14/notes/get_start_xpu.html", "Device and software preflight; not a throughput source."),
    ("S4", "vLLM contributors", "GPU installation: Intel XPU", "Latest docs, accessed 2026-09-12", "https://docs.vllm.ai/en/latest/getting_started/installation/gpu/", "Serving-stack compatibility; not a capacity benchmark."),
    ("S5", "ggml-org contributors", "llama.cpp SYCL backend", "Master docs, accessed 2026-09-12", "https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md", "Fallback backend support; no benchmark rates transferred."),
    ("S6", "NIST/SEMATECH", "Selecting an experimental design", "Accessed 2026-09-12", "https://www.itl.nist.gov/div898/handbook/pri/section3/pri33.htm", "Structured cross-comparisons; exact matrix and schedule are planning choices."),
]
for row, values in enumerate(sources, 3):
    src.write_row(row, 0, values, body)
    if values[4].startswith("https:"):
        src.write_url(row, 4, values[4], link, string=values[4])
    src.set_row(row, 78)
src.autofilter(2, 0, 2 + len(sources), 5)
for ws in wb.worksheets():
    ws.set_print_scale(80)
wb.close()
print(OUTPUT)
