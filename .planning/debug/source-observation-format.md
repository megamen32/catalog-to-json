---
status: verified
trigger: strict review rejects source-equivalent numeric and header representations
---

# OPN27 source-observation format

Confirmed original142 findings contained139 representational differences,1 real energy-unit error,2 flags for an unsupported added time unit. Independent visual review checked168 parameter cells and merge scope. Numeric types/decimal separators, source-only verified unit/qualifier relocation, and complete diameter tokens must compare correctly. Wrong explicit units, prefix/operator changes, conditional current units promoted to voltage, unknown parent headers and unsupported added time units still block. New observer instructions require complete parent headers without ellipsis.

RED:6 equivalent cases falsely refused; decimal drawing47.6 falsely passed476. GREEN:17 source-equivalence scenarios and19 existing tool tests. Retained actualcandidate1 no longer has95 numeric/12 diagram false findings;9 remaining include7 incomplete source-header observations and2 unsupported8/20 timeunit findings. Do not dismiss them or infer units from candidate. Next: independent adversarial review and native source-bound review gate/canary with released1.4.5.

Independent adversarial review PASS;90 core checks11.54s and package build PASS. Native source33 MCP2/SDK transport exactSHA,3chunks/no truncation and repeated-image notice verified without provider calls. Model accuracy remains unproven for1.4.5; old complete cohorts must stay unchanged.
