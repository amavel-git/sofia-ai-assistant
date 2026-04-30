# SOFIA WORKFLOW ENGINE — PHASE 1

## Overview

Sofia Phase 1 implements a **basic content workflow engine** that manages:

- Content idea intake
- Workspace resolution
- Cannibalization checks
- Draft creation
- Review queue routing
- Workspace memory updates

This phase is intentionally simple and deterministic, with minimal logic and no external integrations.

---

## Core Workflow

The workflow follows this sequence:

1. Content idea is added manually to `content_intake.json`
2. Sofia processes the next item with status `"new"`
3. Workspace is resolved via `workspaces.json`
4. Cannibalization is checked:
   - Workspace memory (`site_content_memory.json`)
   - Existing drafts (`draft_registry.json`)
5. If valid:
   - Draft is created
   - Draft is routed to review queue
   - Workspace memory is updated
6. Intake item is updated accordingly

---

## File Structure (Relevant to Workflow)
