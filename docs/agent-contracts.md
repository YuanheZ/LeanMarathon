# Agent Contracts

LeanMarathon exposes four agent roles.

## Blueprinter

Creates the initial Lean blueprint from the problem file and proof source.
Delivery endpoint: a CI-green PR merged into `main`.

## Target-Reviewer

Read-only target auditor. It compares canonical problem statements against
the blueprint theorem nodes. Delivery endpoint: clean exit or a grouped
GitHub issue titled `Blueprint target review`.

## Refiner

Repairs grouped blueprint issues or Worker blocker issues. Delivery endpoint:
a CI-green repair PR merged into `main`.

## Worker

Proves one dynamic-leaf proof node in Stage 2. Delivery endpoint: either a
CI-green PR merged into `main`, or a blocker issue.
