# 32 — Node Registration Fails When Cumulative Tag String Exceeds 128 Characters

Production configuration is documented in [`notes/deploy/02-render-nodes.md` Section 6](../deploy/02-render-nodes.md#6-dispatch-tags-rqd_tags); this document records the investigation and database fix.

Environment: Clean sandbox deployment from empty database, 2026-09-25.

---

## 1. Symptoms

Following [`deploy/02`](../deploy/02-render-nodes.md) to configure a workstation from scratch and starting RQD, `cueadmin -lh` remained empty indefinitely. RQD logs stalled at `RQD Started` with zero error messages. Cuebot logs showed:

```
HostReportHandler   : Unable to find host LAPTOP-ULJICLO8 ...
HostManagerService  : set LAPTOP-ULJICLO8 to the given allocation local.desktop
CueExceptionUtil    : ... PL/pgSQL function recalculate_tags(character varying) line 15 at EXECUTE;
                      ERROR: value too long for type character varying(128)
```

Node registration aborted mid-transaction, preventing the host record from being committed.

---

## 2. Root Cause

The PostgreSQL stored procedure `recalculate_tags()` concatenates all tags in `host_tag` separated by spaces and writes the result into `host.str_tags` (`V1__Initial_schema.sql`):

| Variable / Column | Character Limit |
|---|---|
| Function local variable `full_str_tag` | 256 |
| **`host.str_tags` table column** | **128** |

Workstation configuration tag string generated upon registration (actual string written post-fix):

```
desktop desktop desktop general houdini22 houdini_22_0_429 maya_2027 maya2027 nuke17 nuke_17_0v1 rqdv-dev windows LAPTOP-ULJICLO8
```

**Total length: 129 characters.** `desktop` appeared three times: prefix in `RQD_TAGS` (to target allocation `local.desktop`), `OVERRIDE_IS_DESKTOP = True`, and the allocation name itself.

The legacy sandbox did not encounter this because `RQD_TAGS` originally began with `general`, generating two `desktop` tokens and totaling 121 characters. In production, supporting multiple concurrent DCC versions adds 10–16 characters per version, inevitably exceeding the 128-character limit.

---

## 3. Resolution: Widening Database Columns

Added a studio repeatable Flyway migration [`R__Studio_widen_host_tags.sql`](../deploy/server/migrations/R__Studio_widen_host_tags.sql) to the custom Flyway image:

- Altered `host.str_tags` to `VARCHAR(4000)` (matching `layer.str_tags`).
- Widened the local variable in `recalculate_tags()` to 4000; preserved remaining function logic verbatim.

Implementation design choices:

- **Repeatable Migration (`R__`)**: Flyway executes repeatable migrations after all versioned migrations have completed, running again only if file contents change. Future upstream migrations (`V50`, `V51`) will not conflict.
- **Upstream files preserved unmodified**: Created [`deploy/server/flyway.Dockerfile`](../deploy/server/flyway.Dockerfile), identical to `sandbox/flyway.Dockerfile` but copying `notes/deploy/server/migrations/`; updated `build.yml` to target this Dockerfile.
- No database views depend on `host.str_tags` (verified via `pg_depend`), allowing non-blocking `ALTER TABLE` execution.
- Cuebot Java codebase enforces no character limit validations on this column.

---

## 4. Empirical Verification

| Test Scenario | Result |
|---|---|
| Dry run within transaction on active database followed by rollback | Column temporarily widened to 4000; restored to 128 upon rollback |
| Applied locally built image to database with **pre-existing data and failed registrations** | `Migrating schema "public" with repeatable migration "Studio widen host tags"`; node registered automatically on next report cycle into `local.desktop` with 129-char tag string |
| Deployed **clean database** from scratch using same image (ephemeral postgres container) | 43 migrations executed (42 versioned + 1 repeatable); column created at 4000; show `testing` and 5 allocations seeded successfully |
| Executing **legacy** upstream Flyway image against database with `R__` applied | **Exit code 1**: `Validate failed ... Detected applied migration not resolved locally: Studio widen host tags` |

The final result establishes that once a database applies this migration, **it cannot be managed by upstream images lacking the repeatable migration**. The stack environment variable `OPENCUE_FLYWAY_IMAGE` must point to the studio build before redeployment.

---

## 5. Pending Verification Items

- Official images published via GitHub Actions (tests utilized locally built images).
- Clean database stack deployment orchestrated end-to-end via Portainer.
- Auditing whether future upstream updates to `recalculate_tags()` reset the local variable back to 256.
