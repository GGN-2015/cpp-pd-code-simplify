# Algorithm and Correctness

This document describes the core ideas used by `cpp-pd-code-simplify`.
The implementation is a standalone C++ translation of the mathematical
algorithmic structure, not a wrapper around a Python or graph library.

## Scope And Guarantees

The default reducer is a certified local-move reducer in the following
implementation sense: every accepted simplification is either a directly
recognized local Reidemeister/nugatory deletion, a validated red-green disk
witness, or a deterministic sequence of RIII moves followed by those same
local deletions. The program does not claim that the returned diagram has the
minimum possible crossing number. It only claims that the moves it actually
applies are valid under the checks described here.

`--reapr` is different. It enables an experimental deterministic projection
oracle with an invariant guard. That guard is useful for hard examples, but it
is not an equivalence proof. The option is disabled by default, and accepted
results carry an explicit warning in JSON output.

All command-line and Python entry points use the same high-level algorithm.
The Python C++ interface calls the C++ backend. The pure Python prototype
implements the same move ordering, guards, and deterministic retry sequences so
that differential tests can compare output exactly.

## Terminology

This manual uses the following terms. Standard knot-theory terms are listed in
[References](#references); engineering terms are defined here because they are
project-specific.

- **PD code**: a planar diagram code written as a list of crossing quadruples
  such as `PD[X[1,5,2,4],X[3,1,4,6],X[5,3,6,2]]`. Each integer label names one
  diagram edge and must occur exactly twice. The empty PD code `PD[]`
  represents a diagram with no crossing-bearing components; crossingless
  components are tracked separately.
- **Endpoint**: an internal half-edge address `(crossing_index, strand_index)`.
  The strand index is in `{0,1,2,3}` around one crossing.
- **Component**: a link component recovered by walking through crossings with
  the oriented successor operation `next`. A component can have crossings or be
  crossingless.
- **Crossingless component count**: an explicit integer carried next to the PD
  code because a plain PD string cannot store a component that has no crossings.
- **Face**: a connected complementary region of the planar diagram. The
  unbounded exterior region is one of these faces.
- **Dual graph**: the graph with one vertex per face and one edge for each
  diagram edge separating two faces.
- **Red path**: the diagram arc that the mid-simplification algorithm proposes
  to delete. It is a sequence of endpoints along an oriented component.
- **Green path**: the replacement arc searched in the dual graph. It runs
  through faces and crosses diagram edges.
- **Witness**: a red path, a green path, a side choice, and over/under data
  that together pass the disk-consistency validator and can be applied to make
  a new PD code.
- **Preprocessing**: the repeated local deletion pass that removes R1 moves,
  true R2 bigons, and nugatory crossings before and after larger moves.
- **Canonical output**: the display-only PD form where labels start at `1`,
  components are walked deterministically, crossing rows are sorted, and each
  row starts at the under-incoming strand.
- **Efficient phase**: the first 180 seconds of default heuristic mode. It uses
  the fast adaptive route whose initial stage order is RIII prepass, legacy
  first-hit red-green search, then non-monotone failover.
- **Big heuristic route**: the hard-case route entered only after the efficient
  phase expires. It uses deterministic multi-worker red-path batches and
  chooses the validated witness with the best measured crossing reduction
  inside a fixed lookahead window.
- **Failover**: a deterministic helper stage that is tried when the direct
  current route cannot reduce the diagram. Failovers are not random restarts.
- **Resource-limited result**: a result returned because a configured search
  budget was exhausted. It is a safe partial result, not a proof that no move
  exists.

## Full Reduction Pipeline

For one input PD code, the high-level reducer runs the following pipeline.

1. Parse and validate the PD labels. Each label must appear exactly twice.
   Face and component structure are reconstructed on demand by the stages that
   need them. Internally rebuilt PD codes produced by witness application are
   additionally checked by the planar Euler guard described below.
2. Run preprocessing to a fixed point: R1 deletion, true R2-bigon deletion, and
   nugatory crossing deletion. Update crossingless-component accounting after
   every deletion that removes a component's last crossing.
3. If `--reapr` is enabled, try the experimental projection oracle. A candidate
   is accepted only if the invariant profile matches. Accepted candidates are
   cleaned by the same preprocessing pass and then re-enter the normal loop.
4. Enter the iterative reduction loop. With `--reduction-round -1`, the loop
   continues until every enabled stage fails, times out, or hits a resource
   guard. With `--reduction-round K`, at most `K` mid-simplification witnesses
   or replayed non-monotone steps are applied.
5. In default heuristic mode, use the efficient adaptive route for 180 seconds.
   The initial order is RIII prepass, legacy first-hit red-green search, and
   non-monotone failover. Stage priorities adapt after successes, misses, and
   soft timeouts.
6. If the efficient phase expires, canonicalize the best PD code seen so far
   and continue with the big heuristic route. That route prefers witnesses that
   remove more crossings while keeping deterministic red-path order.
7. If adaptive stages fail to reduce the diagram, run streaming brute-force
   green-path enumeration from the canonical handoff state. If the brute-force
   budget is exhausted, return the best known PD code with `resource_limited`.
8. If brute force also fails, run the final deterministic RIII failover. If it
   exposes a local deletion, apply it and restart the loop. Otherwise the
   diagram is reported as stable for the configured search.
9. Before JSON/text output, canonicalize the displayed PD code. This final
   formatting is a relabeling, not a topological move.

## Diagram Model

A planar diagram code is represented as a list of crossings

```text
[(a0, a1, a2, a3), ...]
```

where every label occurs exactly twice. Equal labels identify the two ends
of the same diagram edge. Internally, an endpoint is stored as
`(crossing_index, strand_index)`.

The implementation works with the cyclic order of the four entries at each
crossing. After canonical formatting, entry `0` is the under-incoming edge,
entry `1` is an over edge, entry `2` is the under-outgoing edge, and entry `3`
is the other over edge. During the internal search the row order may be less
pretty, so the `Diagram` constructor computes rotations and crossing signs
before any traversal is used. This is why the final output can be made elegant
without changing the search state too early.

The implementation reconstructs the same local operations used by crossing
entry based link libraries:

- `opposite(e)` follows the diagram edge with the same PD label;
- `next(e)` moves through one crossing along the same link component;
- `next_corner(e)` moves along the boundary of a complementary face.

The code first orients all crossings consistently with the PD component
orientation convention. This gives each crossing a sign and determines the
two crossing entries used by component traversal and red path generation.
The same orientation data is reused by Alexander-root checks and by final
crossing rotation.

## Face Dual Graph

After the endpoint operations are available, the algorithm enumerates all
faces by repeatedly applying `next_corner`. Each face becomes a vertex in a
dual graph. Each diagram edge separates two faces, so it becomes an edge in
the dual graph.

The exterior unbounded region is not special-cased away. It is reached by the
same `next_corner` face traversal and therefore becomes a normal dual-graph
vertex. This matters for examples where the simplifying green arc runs through
the outside of the drawing.

For each dual edge, the implementation stores the two endpoint interfaces
that it crosses. This is important later: a candidate green path is a path
in the dual graph, but the over/under consistency test must know exactly
which diagram strand each dual edge crosses.

The planarity sanity check compares vertices, edges, faces, and crossing-graph
components through the Euler relation

```text
crossings - diagram_edges + faces = 2 * crossing_graph_components.
```

Here `diagram_edges = 2 * crossings` for a valid four-valent PD diagram. This
check is not a layout algorithm; when the guard is called, it catches malformed
PD structures and bad internal rewrites.

## PD Preprocessing

The command-line tools and high-level Python helpers first simplify the PD
code by repeatedly removing R1 moves, true Reidemeister-II bigons, and
nugatory crossings. A nugatory crossing is not treated as an R2 move: the R2
detector specifically looks for two adjacent crossings joined by the two sides
of a removable bigon, while the nugatory detector removes a single crossing
whose deletion disconnects the crossing graph in the required way. The C++
implementation does this in C++; the Python prototype implements the same
preprocessing in Python. Both versions update the explicit
crossingless-component count when deleted crossings were the last crossings of
a component.

The preprocessing loop is intentionally local and deterministic:

- an R1 move is a one-crossing loop where a PD edge returns to the same
  crossing in the local pattern recognized by the implementation;
- a true R2 bigon is a pair of crossings connected by the two opposite sides of
  a disk-shaped bigon, with compatible strand parity;
- a nugatory crossing is a crossing whose removal separates the crossing graph,
  so it is a one-crossing connected-sum artifact rather than a two-crossing
  bigon.

After each successful deletion, the PD labels are renumbered by the local
renumbering routine selected for that deletion. The loop then starts over so
newly exposed local moves are not missed. The final user-facing result is
canonicalized separately.

The lower-level `find_simplification` function still searches exactly the PD
code it receives. This keeps the mid-simplification search independently
testable while the user-facing tools run the faster default preprocessing
pipeline.

## Final PD Formatting

The simplification algorithms keep their internal crossing order and label
numbering unchanged while searching and applying moves. At the final output
boundary, `format_final_pd_code` converts the resulting diagram to a display
form:

- the existing component-orientation pass identifies the incoming endpoint of
  each under strand;
- each crossing tuple is rotated so entry `0` is that under-incoming endpoint
  and entries `1`, `2`, and `3` continue around the crossing in the same local
  order used by the rest of the library;
- labels are then renumbered by walking the directed components, processing
  components in increasing old-label order and assigning labels from `1`.
- crossing rows are sorted lexicographically after relabeling, matching the
  stable order used by diagram sanity round trips.

This is only a relabeling and local cyclic reindexing of crossing endpoints.
It does not change the pairing of PD labels, crossing signs, component count,
or the result of the simplification search.

## Red Path Enumeration

The simplification search starts from possible red boundary arcs. For each
crossing entry, the algorithm walks forward with `next` until it returns to
a crossing already seen. This gives a component arc with no repeated
crossing except the closing crossing.

Every prefix long enough to bound a nontrivial disk is considered a red
candidate. For a red path with `n` endpoints, the algorithm searches for a
shorter green path between the faces adjacent to the red path endpoints.
The intended crossing reduction is the difference between the number of
crossings removed from the red arc and the number of new crossings inserted
along the green arc. A candidate is useful only when the applied and cleaned PD
code has fewer crossings than the starting PD code.

Interior red edges are assigned a large dual-graph weight. This prevents a
green path from simply crossing the red boundary through its interior. The
remaining dual graph is searched for simple paths with total weight less
than the red path length.

If the source and target endpoint regions are the same face, the green path
is represented by the single-face path `[face]`. This is a valid zero-crossing
dual path: the green arc stays inside one complementary region, including the
unbounded exterior region when that is the shared face.

When `max_paths` is not `-1`, the implementation uses the bounded depth-first
ordering. When `max_paths` is `-1`, the default search is the shared
C++/Python deterministic heuristic described in
[Heuristic Path Sampling](heuristic-path-sampling.md). Passing
`--ban-heuristic` with `max_paths=-1` restores exhaustive simple-path
enumeration for the current red path. Exhaustive enumeration is streaming:
each green path is passed to the validator immediately instead of being stored
in one large path list. This is still exact when the brute-force budget is not
exhausted, and it prunes branches whose current weight plus the shortest
possible remaining dual-graph distance is already too large to beat the red
path.

The three path-search modes differ only in candidate ordering and candidate
coverage:

- **bounded** (`max_paths` finite): examine at most the configured number of
  simple green paths for each red path.
- **heuristic** (`max_paths=-1`, no `--ban-heuristic`): use deterministic
  beam/priority sampling to focus on shorter and more promising dual paths. In
  the big heuristic route, red paths are batched across workers and validated
  witnesses are ranked by actual crossing reduction.
- **bruteforce** (`max_paths=-1 --ban-heuristic`): stream all eligible simple
  green paths unless `bruteforce_budget` or a global timeout stops the job.

Only brute-force mode without resource exhaustion is complete for the current
red-green disk model. Bounded and heuristic modes are acceleration strategies:
they can miss a witness, but any witness they return still passes the same
validator and application checks.

## Green Path Validation

A short green path in the dual graph is only a topological candidate. It
still has to be compatible with the crossing information of the diagram.

For each candidate green path, the checker runs twice: once treating the red
path as a left boundary and once treating it as a right boundary.

The checker propagates required strand levels from the red boundary through
the disk:

- even strand indices are treated as under strands;
- odd strand indices are treated as over strands;
- opposite endpoints of the same diagram edge must have the same level;
- local crossing constraints forbid a strand from being forced both over
  and under;
- when the propagation reaches the green path, the green crossing receives
  the complementary level.

If propagation completes with no contradiction, the red and green paths
bound a valid simplifying disk. The result records the red path, the green
path, the side used, and the green crossing data.
If the same endpoint and level are reached twice during one propagation trace
before hitting the red boundary or green path, the candidate is rejected. Such
a repeated state is a closed propagation orbit, and rejecting it keeps the
validator finite without accepting an uncertified witness.

The validator deliberately tries both sides of the red arc. The same red path
can bound a disk on its left or on its right, and the valid side depends on the
current embedding. The returned witness records the successful side so the
application step can rebuild the PD code with the same over/under choices.

## Applying A Witness

The high-level simplifier does not stop at the witness. It applies the
witness to produce a new PD code:

- crossings on the deleted red arc are removed;
- the non-red strand through each removed crossing is smoothed;
- every edge crossed by the green path is split;
- new crossings are inserted along the green path with the over/under levels
  computed by the validator;
- the resulting half-edge pairing is checked so every active PD label has
  exactly two ends, then labels are renumbered deterministically.

The application code performs several rejection checks before accepting the new
PD code:

- the red path must not repeat a removed crossing;
- the green path must not cross a half-edge removed with the red arc;
- the green path must not split the same old PD label twice;
- every active half-edge equivalence class after rewiring must contain exactly
  two endpoints;
- the rebuilt PD code must pass the planarity sanity check.

These checks are the reason the implementation can apply a witness rather than
only reporting that one exists.

After applying one ordinary witness, the implementation immediately runs R1,
R2, and nugatory preprocessing again. This can expose additional local
simplifications before the next mid-simplification search round. In the
hard-case best-batch route described below, heuristic witnesses deliberately
keep the prototype-compatible internal order and use order-preserving cleanup
until the next non-heuristic handoff. In this context, order-preserving cleanup
means R1 and nugatory deletion without immediate R2 deletion or canonical row
reordering. That exception avoids hiding large delayed witnesses by premature
canonicalization or R2 cleanup.

`--reduction-round K` caps the number of applied mid-simplification rounds.
Final JSON/text output and `--show-step-pd` output are always canonicalized.
This canonicalization relabels each component from 1, sorts crossings, and
rotates each crossing so the displayed row starts at the under-incoming strand.
It is not a topological move.

The default `--reduction-round -1` repeats until no applicable witness remains.
In default heuristic mode, the reducer first gives the fast adaptive route an
efficient 180 second phase. That route uses the deterministic scheduler below;
its initial order is RIII prepass, then legacy first-hit heuristic search, then
non-monotone failover. This preserves the old timing profile for ordinary
zip-random inputs where local RIII/preprocessing cascades are enough. If the
efficient phase expires before the job finishes, the current best PD code is
canonicalized and the remaining reduction switches to a deterministic
multi-worker best-batch heuristic: red paths are searched in deterministic
batches and the best validated witness in the batch window is selected by
actual crossing reduction. If the active stage lowers the crossing count, the
next loop immediately returns to the active route.
When heuristic search misses, the implementation canonicalizes the current PD
code at the non-heuristic handoff boundary, then continues with the small RIII
prepass, deterministic non-monotone failover, brute force, and final RIII
failover described below.

Each helper strategy has fixed base priority, then gains priority after
successes and loses priority after misses or soft stage timeouts. This prevents
a helper strategy that keeps missing from permanently blocking later helpers,
while allowing a productive helper to run earlier after heuristic search has
missed. The RIII prepass has a 15 second soft slice, and non-monotone failover
has a 60 second soft slice. A soft slice only changes that stage's scheduler
score; the global `--timeout` remains the hard job timeout.

The adaptive scheduler is deterministic. The base priorities are:

```text
r3_prepass:       300
heuristic_search: 240
non_monotone:     120
```

For each stage, the runtime score is the base score plus rewards for successes
and consecutive successes, minus penalties for misses, consecutive misses,
timeouts, and consecutive timeouts. Ties are broken by the fixed base order.
The purpose is not to predict topology; it is to avoid repeatedly spending time
on a stage that has just failed while still letting a productive stage run
early. Verbose mode prints the current order, score, success count, miss count,
timeout count, and streak counters.

If a helper stage lowers the crossing count, its result is canonicalized and
the next round starts again in heuristic mode. If all helper stages miss, the
simplifier runs a brute-force pass from the canonical handoff diagram. If brute
force finds a witness, that witness is applied, canonicalized, and the loop
continues in heuristic mode. If brute force also fails, the larger deterministic
RIII failover described below is tried before the diagram is reported as final.

Brute-force search has a separate resource guard, `bruteforce_budget`, exposed
as `--bruteforce-budget` in the CLIs. The default budget is `200000`
green-path checks per PD-code job; `-1` disables the guard. If the budget is
exhausted, the simplifier stops the current job, returns the best PD code known
so far, and sets `resource_limited`. This is a safety result rather than a
stability proof: it means the implementation deliberately stopped before
finishing the brute-force proof attempt.

Timeouts and interrupts are handled at stage boundaries and inside expensive
loops. A positive `--timeout K` is a per-PD-code wall-clock limit. When it
fires, the job returns the best crossing count reached so far and sets
`timed_out`. `Ctrl+C` uses the same cancellation checks but exits the process
with the interrupt status instead of returning a successful JSON result. The
option `--quit-at-crossing N` is different from timeout: it is a requested early
success condition. As soon as the current PD code has at most `N` crossings,
the reducer returns immediately and sets `stopped_by_crossing_limit`.

## Deterministic Non-Monotone Failover

Some diagrams need a short detour before a crossing-decreasing move becomes
visible. The non-monotone failover is a deterministic beam search over
temporary diagrams whose crossing count is allowed to stay the same or rise by
a small fixed amount. In default heuristic mode it participates in the adaptive
stage scheduler with the RIII prepass and heuristic red-green search. It remains
before the terminal brute-force proof pass.

Each beam node stores a canonical PD code, the explicit crossingless-component
count, and the sequence of temporary steps that produced it. Candidate steps
are generated in two ways:

- apply a bounded number of deterministic RIII moves, then immediately run the
  normal R1, R2, and nugatory cleanup;
- sample short green paths with a fixed limited heuristic budget, apply only
  witnesses accepted by the same red-green validator, and immediately run the
  same cleanup.

The candidate queue is bounded by fixed constants shared by C++ and Python:
maximum red length `80`, maximum depth `72`, beam width `32`, at most `96`
candidates per state, at most `4` accepted surgery candidates per red length,
and at most `4,000,000` green-path tests for one non-monotone call. Candidate
red paths are grouped by length, and ties are rotated by a stable FNV-1a hash of
the canonical PD code. This makes the search deterministic while avoiding a
single incidental red-path ordering from dominating every state.

The failover accepts only a state whose cleaned crossing count is strictly
smaller than the starting crossing count. When that happens, every stored step
is replayed as a counted mid-simplification round and every intermediate PD
code is canonicalized. If no such state is found within the fixed budgets, the
algorithm continues to the brute-force proof pass.

The failover is not a completeness proof: bounded beam search can miss a
useful detour. It is sound because every accepted temporary surgery still comes
from the same validated red-green witness application, every RIII candidate is
a standard crossing-preserving local move, and every cleanup uses the ordinary
R1/R2/nugatory deletion checks.

## Deterministic RIII Failover

Some diagrams cannot be reduced by the current red-green witness search from
their present crossing order, even though crossing-preserving Reidemeister-III
moves can expose a later R2 bigon. The 16-crossing regression fixture

```text
PD[X[1,24,2,25],X[2,16,3,15],X[4,27,5,28],X[6,29,7,30],
X[8,18,9,17],X[11,21,12,20],X[13,23,14,22],X[16,8,17,7],
X[19,11,20,10],X[21,13,22,12],X[23,32,24,1],X[25,15,26,14],
X[26,3,27,4],X[28,5,29,6],X[30,9,31,10],X[31,18,32,19]]
```

has exactly this shape: the witness search and brute-force green-path search
find no immediate crossing-decreasing disk, but four RIII moves expose one R2
bigon and reduce it to 14 crossings.

The prepass and failover use the same deterministic RIII engine and are shared
by C++ and Python:

- enumerate triangular faces in the current face decomposition;
- keep only triangles incident to three distinct crossings and with the local
  strand parity pattern required for an RIII move;
- sort candidate RIII moves by crossing index and strand index;
- run a breadth-first search over canonicalized diagrams, bounded by a fixed
  depth and state limit;
- after every RIII move, run the same R1/R2/nugatory preprocessing;
- accept the first canonical state whose crossing count is lower than the
  starting state.

The prepass uses a smaller depth and state budget than the final failover. It
is intended to catch fast reductions such as the 16-to-14 crossing regression
without making every heuristic round pay for the full depth-8 search. The full
failover remains after the brute-force red-green search fails.

No random choice is made. The Python C++ interface calls the same native C++
backend, so it inherits the same move ordering and the same output. If the
failover lowers the crossing count, the main simplification loop starts over
from heuristic witness search on the new canonical PD code.

## Experimental REAPR Oracle

`--reapr` enables an experimental deterministic oracle that is intentionally
outside the strict correctness proof for the default simplifier. It is meant
for hard diagrams where the certified red-green witness search cannot make
progress, and it is disabled by default.

The internal implementation does not call REAPR, Knoodle, SnapPy, or
`pd-code-to-diagram`. It computes its guard invariants directly in C++ and in
the Python prototype. The determinant code is isolated in the C++ namespace
`alexander_determinant_guard`; the stricter REAPR acceptance profile is in
`reapr_invariant_guard`. The Python prototype uses the same matrix
construction, the same finite-field primes, and the same acceptance order.

The word "oracle" here means "an optional proposal generator whose candidate is
screened by invariants." It does not mean a mathematically complete decision
procedure. The proposal generator is deterministic:

- attempt `0` proposes a very small template when the determinant fingerprint
  admits one;
- later attempts derive a SplitMix64 seed from the attempt number, determinant
  value, and current crossing count;
- that seed generates a fixed closed-braid candidate pool;
- C++ and Python use the same seed formula and the same candidate ordering.

For a one-component input, the oracle tries a deterministic projection
candidate only when it can make the crossing count smaller. There is no
crossing-drop window: an extremely small projection can be accepted if it
passes the invariant profile below. This makes `--reapr` more useful on hard
diagrams, but also makes the oracle riskier than the default simplifier.

- determinant `1` proposes the empty unknot projection;
- an odd determinant `d > 1` proposes the canonical `(2,d)` torus-knot
  projection template, but only when `d` is below the current crossing count.

If the first template is rejected, the oracle may continue through a bounded
deterministic retry sequence. Each retry seed generates a closed-braid
candidate pool using the same pseudo-random integer stream in C++ and Python.
The default cap is three attempts; `--reapr-retry-max N` changes that cap, and
`0` disables REAPR candidate attempts. These retries are deterministic because
the seed for attempt `i` is derived only from `i`, the determinant, and the
current crossing count.

The candidate is canonicalized through the same final PD formatter used by the
rest of the project. It is accepted only if the following profile matches the
original diagram exactly:

- total component count, including crossingless components;
- Alexander determinant fingerprint over the primes `1000003`, `1000033`, and
  `1000037`;
- nonzero Alexander roots over `F_11`, `F_19`, and `F_31`.

For efficiency, the implementation first checks component count and the
determinant fingerprint. The three finite-field root sets are computed only
after those faster checks match. No Goeritz-signature guard is used. If more
than one candidate
matches, the oracle chooses the least aggressive successful candidate: the one
whose cleaned crossing count is largest while still below the current count.
Deterministic PD-code text is the tie-breaker. Accepted results then run
through the ordinary R1/R2/nugatory cleanup and continue into the normal
reduction loop.

The determinant fingerprint is computed from a Fox-coloring-style matrix at
`t=-1`: after canonicalizing the PD code, over-strand labels are identified,
each crossing contributes the row `2*over - under_in - under_out`, one minor is
deleted, and the determinant is computed modulo the three large primes. The
stored residue is normalized up to sign by taking `min(r, p-r)`.

The Alexander root profile uses the oriented crossing sign. For each
nonzero `t` in `F_p`, the implementation builds the Alexander matrix row

```text
positive crossing: (1-t)*over + t*under_in - under_out
negative crossing: (1-t)*over - under_in + t*under_out
```

then tests whether the same fixed minor has determinant zero modulo `p`. The
profile records the sorted list of nonzero roots for `p = 11, 19, 31`.
This is intentionally cheaper than computing a full symbolic Alexander
polynomial, but it is also weaker.

This guard is stronger than the original determinant-only screen, but it is
still not a proof that two knots or links are equivalent. The output therefore
carries `reapr_warning`, `reapr_status`, `alexander_determinant_before`,
`alexander_determinant_after`, `reapr_invariants_before`, and
`reapr_invariants_after`. Users who enable `--reapr` should still verify
independent invariants. The project tests compare the same invariant-profile
guard used by the REAPR acceptance check: component count, Alexander
determinant fingerprint, and Alexander root sets modulo 11, 19, and 31. The
tests also include a `pd_k0.txt` regression fixture
where `--reapr` is expected to accept a determinant-profile-compatible
projection template and collapse the 481-crossing diagram to a much smaller
PD code. This regression intentionally exercises the experimental, non-proof
part of the project.

## Component Accounting

Plain PD codes cannot represent components with no crossings. This matters
when a move removes the last crossing from a connected component: if the
component is simply dropped from the PD code, the link information is lost.

The library therefore tracks component metadata separately:

- `analyze_components` reports components represented by crossings plus an
  explicit count of already crossingless components;
- `analyze_components_after_removing_crossings` simulates crossing deletion
  and increments `crossingless_components` for each component that loses all
  crossing indices;
- `simplify_pd_code` preserves this count while removing R1 moves, true R2
  bigons, and nugatory crossings before the mid-simplification search.

This makes deletion-safe simplification possible even when the resulting PD
code is empty.

## Correctness Argument

The implementation preserves the combinatorial diagram because every
endpoint operation is derived from PD label pairing and crossing-local
indices. The face enumeration is correct because `next_corner` follows the
boundary of one complementary region, and every endpoint belongs to exactly
one such region. Therefore the dual graph has exactly one vertex per face
and one edge per diagram edge separating two faces.

The red path enumeration is complete for the class of simplifications
targeted by the algorithm: every candidate disk boundary contains a red arc
following the diagram from one crossing entry to another without repeating
an interior crossing. Walking forward from every crossing entry and taking
all long enough prefixes includes each such red arc.

For a fixed red path, any valid simplifying disk must have its other
boundary arc in the complement of the red interior. Assigning large weights
to interior red dual edges excludes paths that cross through that boundary.
In brute-force mode, the simple-path search over the dual graph therefore
enumerates exactly the eligible green arcs when the resource budget is not
exhausted; shortest-distance pruning only removes branches that cannot possibly
satisfy the strict weight cutoff. In bounded and heuristic modes, and in a
resource-limited brute-force run, the search is intentionally incomplete, but
every candidate that reaches the validator is checked by the same
crossing-consistency rules.

The validation step is sound because it checks the local crossing
constraints induced by the disk. A contradiction means some strand would be
forced to be both over and under, or two ends of the same diagram edge would
receive inconsistent levels. If no contradiction is found, all strands met
by the disk boundary admit a consistent over/under assignment, so the
reported red and green paths describe a valid simplifying witness.

The application step is sound at the PD-code level because it rewires the
diagram only along the certified disk boundary. The implementation rejects a
witness if the green path would cross a deleted red-strand half-edge, if a
crossed PD label would be split twice, or if the reconstructed active
half-edge graph cannot be paired into valid PD labels. The final renumbering
changes only labels, not the underlying diagram.

Heuristic and non-monotone modes do not change this soundness argument because
they only change candidate ordering, sampling, witness selection, and whether a
bounded detour is searched before the terminal proof pass. Heuristic selection,
whether single-worker first-hit or multi-worker best-batch, returns only
witnesses that have already passed validation and have been applied to a
temporary PD code. These modes can miss a useful route; they cannot make an
unvalidated witness valid. Use
`--ban-heuristic --max-paths -1` for complete direct green-path enumeration on
inputs where that cost is acceptable.

The RIII failover is sound because each RIII step rewires only the six boundary
arcs of a triangular face according to the standard Reidemeister-III local
move. It preserves the crossing count and link type. The subsequent R1, R2,
and nugatory deletions are local Reidemeister or nugatory simplifications, and
the same half-edge pairing checks used elsewhere reject invalid rewrites.

The experimental `--reapr` oracle is not covered by this soundness argument.
Its invariant guard is a screening check, not an equivalence proof. This is
why the option is opt-in and why accepted output carries an explicit warning.

The component accounting is correct because a component is represented by
the set of crossings visited while walking `next` along that component.
After deleting a crossing set, a component has no crossing-bearing
representative exactly when all of its crossing indices were removed. The
analysis increments the explicit crossingless count in precisely that case,
so the total number of link components is not lost.

## Randomized Stress Tests

The test suite includes deterministic randomized tests for trefoil,
figure-eight, and cinquefoil fixtures. For each fixture, the test generator
applies inverse Reidemeister I moves to increase the crossing count without
changing the link type. The default preprocessing stage must then reduce the
diagram back to the original crossing count by removing R1 moves, R2 bigons,
and any nugatory crossings it exposes.

These tests do not prove minimality for arbitrary input. They do verify that
the implementation can survive nontrivial random diagram growth while
preserving component counts and removing the artificial crossings it created.

## References

The implementation is not a new mathematical algorithm; it is an engineering
port and extension around the prototype credited in the README. The following
references are useful background for terminology used in this manual:

- K. Reidemeister, "Elementare Begruendung der Knotentheorie", *Abhandlungen aus
  dem Mathematischen Seminar der Universitaet Hamburg* 5, 24-32, 1927. This is
  the classical source for the local diagram moves now called Reidemeister
  moves.
- J. W. Alexander, "Topological invariants of knots and links", *Transactions
  of the American Mathematical Society* 30(2), 275-306, 1928. This is the
  original source of the Alexander polynomial used by the optional invariant
  guard.
- L. H. Kauffman, *Knots and Physics*, World Scientific, 1991. A standard
  reference for diagrammatic knot manipulations and polynomial invariants.
- P. R. Cromwell, *Knots and Links*, Cambridge University Press, 2004. A
  standard text for knot diagrams, Reidemeister moves, and link invariants.
- D. Bar-Natan and S. Morrison, The Knot Atlas,
  [Planar Diagrams](https://katlas.org/wiki/Planar_Diagrams). This documents
  the `PD[X[...], ...]` style notation commonly used by software around knot
  tables.
