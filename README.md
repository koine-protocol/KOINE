# KOINE

**The semantic payload layer for AI agents — the HTTP of agent-to-agent meaning.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-green.svg)](spec/KOINE.md)
[![Spec](https://img.shields.io/badge/spec-KOINE%2F1.0-purple.svg)](spec/KOINE.md)

Dense, evolvable, transformer-native messages that ride on top of MCP/A2A.
40%+ smaller payloads, built-in identity, and a self-extending grammar.

[Spec](/spec/KOINE.md) | [Live Demo](/demo) | [Benchmark](/benchmarks/results/koine_v1_benchmark.md)

https://github.com/koine-protocol/KOINE/raw/main/demo/koine_demo.mp4

<!-- STAR-HISTORY-CHART: insert SVG after launch -->

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/koine-protocol/KOINE.git && cd KOINE

# 2. Install the reference implementation
pip install -e .

# 3. Parse a message
python - <<'EOF'
from koine import parse_message, render

msg = parse_message("""
KOINE/1.0 TASK_REQUEST
@id: tr-9f2a1c
@from: orchestrator
@to: summarizer
@ts: 1712534400
---
intent: summarize
input: Q1 revenue rose 12% YoY. Churn fell to 2.1%.
output_format: plain
constraints: max_tokens=80,style=executive
priority: normal
""".strip())

print(render(msg))
EOF

# 4. Run the benchmark (requires ANTHROPIC_API_KEY)
cd benchmarks && python run_benchmark.py --anthropic-model claude-sonnet-4-6 --runs 3

# 5. Run the live demo
cd demo && python server.py   # open http://localhost:8787
```

---

## Why KOINE

| Problem | KOINE answer |
|---|---|
| JSON agent messages are verbose | 40% smaller payloads per message, measured across providers |
| Natural language is non-deterministic | Tagged fields, strict types, deterministic English rendering |
| No standard identity layer | Built-in `@did` (W3C DID) + Ed25519 signature field |
| Proprietary formats lock you in | Rides on any transport: MCP, A2A, HTTP, WebSocket |
| Format changes require rewrites | Unknown fields preserved, not rejected. Extend in-band. |

---

## Benchmark

Two-step summarize-then-rewrite pipeline, 3 runs per provider.
Payload bytes = UTF-8 length of the user message only (system prompt excluded).

| Provider | Format | Model | Runs | Success | Avg Input Tok | Avg Output Tok | Avg Total Tok | Avg Payload (B) |
|---|---|---|---|---|---|---|---|---|
| Anthropic | JSON  | `claude-sonnet-4-6`   | 3 | 100%   | 1011 | 217 | 1228 | 949 |
| Anthropic | KOINE | `claude-sonnet-4-6`   | 3 | 100%   | 2582 | 312 | 2894 | 568 |
| OpenAI    | JSON  | `gpt-5.4`             | 3 | 100%   |  877 | 251 | 1128 | 998 |
| OpenAI    | KOINE | `gpt-5.4`             | 3 | 100%   | 2317 | 311 | 2628 | 610 |
| Google    | JSON  | `gemini-2.5-flash`    | 3 |  33%\* |  659 | 137 |  796 | 952 |
| Google    | KOINE | `gemini-2.5-flash`    | 3 |  66%\* | 1677 | 186 | 1863 | 602 |

**Payload savings: 40.1% (Anthropic), 38.9% (OpenAI), 36.8% (Google).**

\* Google failures caused by free-tier quota limits (429 RESOURCE\_EXHAUSTED, 503 UNAVAILABLE), not format errors. The runs that completed validated correctly in both formats.

KOINE's system prompt is a one-time overhead of ~678 tokens per session.
Break-even: 8 messages. Every message after that saves ~91 input tokens.

Full methodology and raw run log: [benchmarks/results/koine_v1_benchmark.md](/benchmarks/results/koine_v1_benchmark.md)

---

## Economics

At $3/M input tokens (claude-sonnet-4-6 pricing), 91 tokens saved per message:

| Scale | Monthly messages | Annual savings |
|---|---|---|
| Small team | 500K | ~$1,638 |
| Mid-size deployment | 5M | **~$13,500** |
| Large pipeline | 50M | ~$135,000 |

Savings compound with session length. An agent loop exchanging 20 messages saves 5x more than one exchanging 4.

---

## How It Works

KOINE is a message format, not a framework. Every message has a one-line header (`KOINE/1.0 TASK_REQUEST`), a block of `@meta` fields for routing and identity, a `---` separator, and typed semantic fields below it. The grammar is strict enough to parse deterministically and loose enough that unknown fields pass through unchanged, making it safe to extend without breaking existing agents. See the full grammar, type system, and worked examples in [spec/KOINE.md](/spec/KOINE.md).

---

## Roadmap

| Version | Name | What changes |
|---|---|---|
| v1.0 | Human-legible universal | Current. UTF-8 text, human-readable, works with any frontier model out of the box. |
| v2.0 | High-efficiency mode | Optional abbreviated field names and binary encoding for agent pairs with established context. Opt-in per session. |
| v3.0 | Emergent compression | Pair-specific learned compression. Agent pairs that have exchanged enough messages develop a shared shorthand, converging toward minimum-token communication for their domain. |

---

## Contributing

1. Open an issue to discuss before submitting a PR.
2. All changes to the spec require a corresponding test in `tests/`.
3. Benchmark results must be reproducible with the scripts in `benchmarks/`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

---

## License and Community

Licensed under [Apache 2.0](LICENSE). Build on it, fork it, ship products with it.

- Spec issues and proposals: [GitHub Issues](https://github.com/koine-protocol/KOINE/issues)
- Discussions: [GitHub Discussions](https://github.com/koine-protocol/KOINE/discussions)
