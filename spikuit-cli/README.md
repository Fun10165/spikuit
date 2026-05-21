# spikuit-cli

[![PyPI](https://img.shields.io/pypi/v/spikuit-cli.svg)](https://pypi.org/project/spikuit-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/spikuit-cli.svg)](https://pypi.org/project/spikuit-cli/)
[![License](https://img.shields.io/github/license/takyone/spikuit.svg)](https://github.com/takyone/spikuit/blob/main/LICENSE)

**The `spkt` command — CLI for [Spikuit](https://github.com/takyone/spikuit), a knowledge base that gets smarter the more you use it.**

> ⚠️ Pre-1.0 / under active development. Expect frequent breaking changes until v1.0.0.

`spikuit-cli` installs the `spkt` command and pulls in
[`spikuit-core[engine]`](https://pypi.org/project/spikuit-core/) so you get
the full Brain engine (FSRS + knowledge graph + spreading activation) out of
the box.

```bash
pip install spikuit-cli
spkt --help
```

If you want the CLI plus everything else under one install target, use the
[`spikuit`](https://pypi.org/project/spikuit/) metapackage instead.

## Quick start

```bash
# Create a brain in the current directory
spkt init -p openai-compat \
  --base-url http://localhost:1234/v1 \
  --model text-embedding-nomic-embed-text-v1.5

# Ingest a source
spkt source ingest https://en.wikipedia.org/wiki/Monad_(category_theory) -d math

# Search the graph
spkt retrieve "What is a monad?"

# Review what's due (FSRS)
spkt tutor due
spkt neuron fire <id> -g fire

# Export a read-only bundle for a server
spkt export qabot --output ./brain.db
```

## Resource-oriented commands

| Resource | Subcommands |
|---|---|
| `spkt neuron`    | `add`, `list`, `inspect`, `remove`, `merge`, `fire` |
| `spkt synapse`   | `add`, `remove`, `weight`, `list` |
| `spkt source`    | `learn`, `list`, `inspect`, `update`, `refresh` |
| `spkt domain`    | `list`, `rename`, `merge`, `audit` |
| `spkt community` | `detect`, `list` |
| `spkt tutor`     | `due`, `quiz`, `progress` |
| `spkt brain`     | `set-default`, `current` |
| `spkt skills`    | `install`, `list` |

Plus root commands: `init`, `config`, `stats`, `retrieve`,
`visualize`, `embed-all`, `export`, `import`, `diagnose`.

All commands support `--json` for machine-readable output and `--brain
<path>` to target a specific Brain.

## Links

- **Documentation**: <https://takyone.github.io/spikuit/>
- **CLI reference**: <https://takyone.github.io/spikuit/cli/>
- **Source**: <https://github.com/takyone/spikuit>
- **Issues**: <https://github.com/takyone/spikuit/issues>

## License

Apache-2.0
