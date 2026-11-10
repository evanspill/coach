"""Deterministic fallbacks for each coaching skill.

In live runs Claude makes these decisions (following .claude/skills/*/SKILL.md) and writes JSON that the
validator checks. These functions are used (a) when Claude's plan fails validation 3 times and (b) by
`coach simulate`, where no Claude is available. Everything they produce is marked generated_by="fallback".
"""
