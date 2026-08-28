"""Layer 3 of the pyramid: output evals, graded with DeepEval.

Deliberately offline. The cases are pre-recorded into `evals/output/golden.json` by
`seed_golden.py`, so `pytest evals/output/` needs no harness, no MCP server and
no UI - only a judge key. Re-runs cost nothing until the set is re-seeded.
"""
