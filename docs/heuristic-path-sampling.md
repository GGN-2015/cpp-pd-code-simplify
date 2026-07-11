# Heuristic Path Sampling

This document describes the deterministic green-path heuristic used when
`max_paths` is `-1`.

## Search Modes

The simplifier has three green-path search modes:

| Setting | Mode | Meaning |
| --- | --- | --- |
| `max_paths != -1` | `bounded` | Use depth-first green-path ordering and stop after the configured cap. |
| `max_paths == -1` | `heuristic` | Use deterministic priority sampling with fixed budgets. This is the default. |
| `max_paths == -1` plus `--ban-heuristic` | `bruteforce` | Stream all eligible simple green paths for each red path, unless the brute-force budget is exhausted. |

The command-line JSON field `last_path_search_mode` records the last search
mode used by the reduction loop. The Python prototype and the C++
implementation use the same mode names, constants, ordering rules, and
tie-breaking rules. The Python C++ interface calls the C++ backend directly.

## Motivation

For a fixed red path, the green search is a simple-path search in the face
dual graph. Brute-force enumeration is complete, but the number of simple
paths can grow quickly on large diagrams. A small fixed cap such as
`max_paths=100` is fast but brittle because it depends on incidental DFS
ordering.

The default `max_paths=-1` mode therefore does not mean "pick a hidden cap".
It switches to a separate deterministic sampling strategy that tries to spend
work on paths that are more likely to pass the disk-consistency validator.

Brute-force mode is complete only when it is allowed to finish. The
implementation uses streaming DFS and does not cache the full path set, but it
also has a separate safety budget: `--bruteforce-budget 200000` by default,
or `--bruteforce-budget -1` for no budget. Budget exhaustion returns the
current best PD code with `resource_limited=true`.

In the full high-level reduction loop, the first 180 seconds use the efficient
adaptive route. Its initial order is the small RIII prepass, then legacy
first-hit heuristic search, then deterministic non-monotone failover. This is
important for ordinary zip-random inputs, where RIII/preprocessing cascades are
often much faster than trying a large red-green path search first. If the
efficient phase expires before the job finishes, the reducer switches from the
current best PD code to the multi-worker best-batch heuristic route.

## Scoring

Before green paths are sampled, heuristic mode keeps red paths in the original
prototype generation order. The simplifier also keeps the internal PD row and
label order in a prototype-compatible form while heuristic witnesses keep
succeeding. This looks less greedy than sorting by apparent red-path length, but
it is deliberate: on some hard diagrams, the useful large witness is only
exposed after many earlier legacy first-hit steps.

For each source-target face pair, the heuristic first computes a reverse
breadth-first distance from every face to the target. This distance ignores
high-weight red-interior barriers, so it is only a reachability and length
estimate, not a proof that a final path is valid.

The sampler then expands partial paths through a priority queue. Each state
stores:

- the current face;
- the path from the source;
- the visited-face set;
- the accumulated dual-graph weight;
- a branch penalty, increased when a step has many low-priority alternatives;
- a deterministic serial number used only for stable tie-breaking.

Candidate next steps are sorted by:

1. edge weight;
2. estimated remaining distance to the target;
3. degree penalty of the next face;
4. next face id;
5. dual-edge index.

The priority queue orders states by:

1. accumulated weight plus estimated remaining distance;
2. current path length plus estimated remaining distance;
3. branch penalty;
4. accumulated weight;
5. current path length;
6. insertion serial number.

The first two keys prefer short and low-weight paths. The branch penalty keeps
the search from spending all budget inside a single locally dense area. The
serial number makes the result reproducible across platforms.

For a red path in default heuristic mode, sampled green paths are streamed
through the usual witness validator and temporary PD application. With one
worker, the first validated witness is returned immediately. This is the
legacy first-hit rule shared by the C++ implementation, the Python prototype,
and the Python C++ interface.

When `max_paths=-1`, the efficient phase expires, and more than one worker is
selected by `--max-thread`, the same red-path order is split into deterministic
batches. Each worker still uses the same per-red-path green sampler and
validator. At the end of a batch, validated witnesses are ranked by actual
crossing reduction, then final crossing count, red-path length, and green-path
length. The search stops after the best witness has survived a fixed lookahead
window of additional batches. This preserves reproducibility while letting hard
diagrams use multiple CPU cores and while preferring a witness that removes more
crossings when several early red paths succeed at the same time.

When `max_paths` is set to a finite positive value, the bounded non-default
search still scores validated candidates inside one red path by actual crossing
reduction before selecting a witness. Exhaustive brute-force mode
(`--max-paths -1 --ban-heuristic`) streams red paths in parallel when multiple
threads are available.

## Fixed Budgets

The heuristic uses fixed constants shared by C++ and Python:

```text
beam width per (depth, face): 8
state budget: min 128, max 4096
path budget: min 24, max 384
best-witness lookahead after a hit: 8 batches
efficient legacy phase: 180 seconds
```

For each red path, the concrete state budget is derived from the face count and
the red-path cutoff:

```text
state_budget = clamp(face_count * cutoff * 8, 128, 4096)
path_budget  = clamp(face_count * 2 + cutoff * 8, 24, 384)
```

These budgets are not inferred from `max_paths`. They are part of the heuristic
search mode itself. The best-witness lookahead is used only by multi-worker
heuristic batches. Single-worker heuristic mode follows the original prototype
first-hit rule.

## Validation And Correctness

The heuristic only changes which green candidates are proposed to the existing
validator. It does not accept a path by score alone. Every returned witness
still passes the same over/under propagation and disk-consistency checks used
by brute-force mode.

Therefore a witness reported by heuristic mode is sound. The heuristic is not
complete: it can miss a witness or a useful detour that later failover stages
may find if it falls outside the sampled frontier. Use
`--ban-heuristic --max-paths -1 --bruteforce-budget -1` when complete
enumeration is required for a manageable input.
