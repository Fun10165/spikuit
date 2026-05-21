---
name: spkt-curator
description: Maintain and improve your Spikuit brain through conversation. Diagnose domain misalignment, clean up labels, merge or split domains, prune stale content, and run consolidation. Use when you want to review and tidy your knowledge graph.
allowed-tools: Bash(spkt *)
---

# Brain Curator Session

Help the user maintain and improve their Spikuit knowledge graph through conversation.

## Mandatory: cut a branch before any structural change

Curation is destructive — domain merges, neuron merges, consolidation runs,
weak-synapse pruning all touch many neurons at once. These MUST run on a
`consolidate/<date>` branch so the user can reject the result without
losing main.

```bash
spkt branch start consolidate-$(date +%Y-%m-%d)
# ... run the curation actions ...
# show the user a summary
spkt branch finish      # confirmed → ff-merge
spkt branch abandon     # rejected → throw the branch away
```

Read-only diagnostics (`spkt domain audit`, `diagnose`, `progress`,
`consolidate` dry-run) do not need a branch — they don't write.
Single targeted fixes (one `synapse remove`, one `synapse weight`) can
go to main directly; batch them onto a branch only when you're applying
several at once.

## Brain State

Stats: !`spkt stats --json 2>/dev/null || echo '{}'`
Domains: !`spkt domain list --json 2>/dev/null || echo '[]'`

## Session Flow

1. Run diagnostics to understand the current state
2. Present findings conversationally — prioritize actionable items
3. Walk through each suggestion with the user
4. Execute approved changes
5. Summarize what was done

## Diagnostic Commands

```bash
# Domain ↔ community alignment (splits, merges, keyword hints)
spkt domain audit --json

# Brain health (orphans, weak synapses, stale neurons, dangling prereqs)
spkt diagnose --json

# Learning progress (retention, weak spots, mastery)
spkt tutor progress --json

# Sleep-inspired consolidation plan (synapse weight decay/pruning)
spkt consolidate --json
```

## Common Curation Actions

### Domain cleanup

When `domain audit` suggests a split (domain spans multiple communities):
```bash
# Show what's in each cluster
spkt neuron list -d <domain> --json
spkt community list --json

# Rename a subset of neurons to a new sub-domain
# (manual: inspect, then update each neuron's domain)
spkt domain rename <old> <new>
```

When `domain audit` suggests a merge (multiple domains in one community):
```bash
spkt domain merge <domain1> <domain2> --into <target>
```

### Label fixes

```bash
# Rename domain
spkt domain rename old-name new-name

# Inspect a specific neuron for context
spkt neuron inspect <id> --json
```

### Orphan resolution

When `diagnose` finds orphans (neurons with no synapses):
```bash
# Find related neurons
spkt retrieve "<orphan content snippet>" --json

# Connect to discovered neighbors
spkt synapse add <orphan-id> <related-id> -t relates_to

# Or remove if the neuron has no value
spkt neuron remove <orphan-id>
```

### Weak synapse review

When `diagnose` finds weak synapses (weight < 0.3):
```bash
# Inspect the connection
spkt neuron inspect <pre-id> --json
spkt neuron inspect <post-id> --json

# Strengthen if the connection makes sense
spkt synapse weight <pre-id> <post-id> 0.6

# Remove if spurious
spkt synapse remove <pre-id> <post-id>
```

### Duplicate merging

```bash
# Search for similar content
spkt retrieve "<term>" --json

# Merge duplicates into the strongest one
spkt neuron merge <dup1> <dup2> --into <keeper>
```

### Consolidation

```bash
# Preview the plan (dry run — no branch needed, read-only)
spkt consolidate --json

# Cut a branch BEFORE applying
spkt branch start consolidate-$(date +%Y-%m-%d)
spkt consolidate apply --json

# Show the diff to the user, then either:
spkt branch finish      # approved
spkt branch abandon     # rejected
```

## Conversation Style

- Start with the highest-impact finding, not a wall of diagnostics
- Present one category at a time (domains → orphans → weak synapses → consolidation)
- For each suggestion: explain what and why, then ask for approval
- After each action, confirm success briefly
- Let the user steer — they may want to focus on one area

## Decision Framework

| Situation | Suggestion |
|-----------|-----------|
| Domain spans 2+ communities | Split into sub-domains using keyword hints |
| Multiple domains in 1 community | Merge into one, use most common or most descriptive name |
| Orphan neuron with related content nearby | Connect with appropriate synapse type |
| Orphan neuron with no related content | Ask user: keep isolated or remove? |
| Weak synapse between related concepts | Strengthen to 0.5-0.7 |
| Weak synapse between unrelated concepts | Remove |
| Stale neuron (never reviewed, old) | Ask user: still relevant? |
| Dangling prerequisite (requires → missing) | Find or create the missing concept |

## Output Format

Keep summaries concise. After a batch of changes:

```
Curated: 2 domains merged, 3 orphans connected, 1 weak synapse removed.
```

Do not dump raw JSON unless the user asks. Present findings in natural language.
When asking for approval, be specific:

```
Domain "ml" spans 2 communities:
  c0: supervised learning, regression, classification (12 neurons)
  c3: reinforcement learning, Q-learning, policy gradient (8 neurons)

Split into "ml-supervised" and "ml-reinforcement"? [Y/n]
```

## Commands Reference

```bash
spkt domain audit --json          # Domain ↔ community alignment
spkt diagnose --json              # Brain health diagnostics
spkt tutor progress --json        # Learning progress
spkt consolidate --json           # Consolidation dry-run
spkt consolidate apply --json     # Apply consolidation

spkt domain list --json
spkt domain rename <old> <new>
spkt domain merge <d1> <d2> --into <target>

spkt neuron list -d <domain> --json
spkt neuron inspect <id> --json
spkt neuron remove <id> --json
spkt neuron merge <id1> <id2> --into <target> --json

spkt synapse add <a> <b> -t <type>
spkt synapse weight <a> <b> <weight>
spkt synapse remove <a> <b>
spkt synapse list --neuron <id> --json

spkt retrieve "<query>" --json
spkt community detect --json
spkt community list --json
```
