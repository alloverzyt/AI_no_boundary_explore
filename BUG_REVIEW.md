# Bug review and validation

## Scope

This review cross-checked the root README, technical status, technical route, report material, archived Track-B statement/scoring rules, and every Python module under `agent/`. The official documents are treated as the source of truth for the legal observation/action contract; historical experiment notes are not treated as reproducible evidence unless their artifacts are in this checkout.

## Fixed in this branch

1. **Progression was unreachable.** `Agent.act()` returned the navigation arbiter before checking goals, inventory, crafting, placement, equipment, or mining stages. With no visual cooldown, `nav_step()` always returned an action, so the agent could walk forever without crafting. Progression now runs first; exploration/mining remains the fallback path.
2. **Navigation phase timers were bypassed.** Jump, dig, and detour handling was nested under the moving-state stuck threshold. After entering a recovery phase, subsequent frames fell through to ordinary walking. Each active phase now owns its timer and runs for the documented bounded interval.
3. **Scan failure immediately retriggered.** A failed 360-degree scan left `no_sight >= 10`, so the next frame started another scan. The navigator now resets sight state and gives itself a bounded travel window after a scan.
4. **Two navigation controllers advanced the same state.** The legacy `walk()` watchdog could call `nav_step()` from inside `walk_policy()`. The duplicate watchdog is removed; `walk_policy()` is the single safety entry point and retains water avoidance.
5. **Episode state leaked across resets.** Reset now clears navigation, lock, placement, portable-table, visual-arbiter, and movement state, and rebuilds the planner fallback for a fresh episode.
6. **Portable workbench could never be placed after the first table.** Stone-stage placement now checks whether the agent is near the known table, rather than treating any table ever placed as globally available.
7. **Planner fallback did not match its documentation.** Planner selection now recognizes evaluation-environment credentials and correctly validates the model name/key. After three model failures, it permanently uses the local heuristic planner.
8. **Uniform water was reported as far-left.** Water offset now uses the occupancy centroid, so a broad centered water surface is detected as centered instead of selecting the first tied column.
9. **Iron progression could request smelting after only one ore.** The iron phase now tracks raw ore plus ingots, only requests legal smelting actions, and avoids repeatedly issuing an invalid iron-pickaxe craft request when the recipe is unavailable.
10. **Wood search dug ground during the tutorial phase.** The exploratory obstacle fallback was guarded only by `STABLE`, not by its `explore` argument. The real Docker run showed 277 attacks against grass/dirt and no collected wood; the fallback is now restricted to the mining/exploration phase, with a regression test.

## Validation

The new tests use only the public observation/action contract and do not access MineDojo internals:

```text
python -m unittest discover -s tests -v
python -m py_compile agent/agent.py agent/planner.py agent/model_api.py agent/vision.py agent/minecraft_actions.py
```

Both commands pass locally. The Windows host still has no Docker Desktop or WSL2, so the real-world smoke run was executed on a GitHub-hosted Linux runner with the official Docker image. The first run completed 1,500 steps with zero invalid actions but failed to complete woodcraft; after item 10 was fixed, the second run completed all five woodcraft objectives in 1,170 steps, with zero invalid actions and zero deaths. A stone-tools run is now included in the workflow for the next verification pass.

## Documentation findings

- The root README still describes code as a future/reserved directory, while the current implementation lives under `agent/`.
- The technical-status run instructions refer to `pack_agent.py`, `practice.py`, and `practice-scenes.json`, none of which exist in this checkout. The official starter documentation says packaging is a manual ZIP workflow, so repository-specific commands need to be checked in or removed.
- The status report's latest-run table lists 127 `stuck -> jumping` transitions and 124 jump failures in one run, but its concluding text says 127 jumps led to only one dig; the conclusion mixes data or is stale.
- The report template and experiment log lack reproducible artifacts for the historical success figures and cite machine-local external paths. The technical route file remains a blank template.
- The official scoring rules define one evolving world per episode and constrain access to public observations. The implementation audit relied only on the documented public observation/action contract.
- The public repository contains identifiable group-chat records and third-party materials while labeling them team-only; licensing/privacy review is still needed before redistribution.

## Remaining review items

- The iron phase is still not a complete furnace/fuel acquisition workflow. It now avoids invalid repeated craft requests, but can wait if the episode never exposes a legal `iron_ingot` or `iron_pickaxe` recipe; the complete chain and state-machine tuning need a full run in the official Linux/Docker environment.
