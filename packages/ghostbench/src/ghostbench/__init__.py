"""GhostBench: proof harness for GhostSlice.

Zero-dependency (Python stdlib only), local-first, no network,
no telemetry. Token counts are ESTIMATES from the GhostSlice
estimator method (or a formula-compatible fallback when GhostSlice
is not installed), never exact tokenizer counts and never billed
amounts.

Tier A is static, free, and deterministic. Tier B is live and
opt-in: it runs only an agent command the user configures in
GHOSTBENCH_AGENT_CMD, inside a contained copy, and labels its
reports with verification_level "live-agent" (see ghostbench.tierb).
"""
__version__ = "0.1.0"
TOOL = "ghostbench"
__all__ = ["__version__", "TOOL"]
