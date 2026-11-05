# Neraium-Poly engineering rules

Use installed Neraium Citadel v1.3.5, scoped to the active checkout. Orient with citadel-state.citadel_status and codebase-memory.get_architecture. Preserve existing uncommitted integration state and unrelated evidence. Runtime scripts resolve under /home/ubuntu/.local/share/neraium-citadel/runtime-v1.3.5/scripts/.

Paper execution only. PAPER_TRADING=true; LIVE_TRADING_ENABLED=false. Never add wallet credentials or submit live transactions. Risk and data validation fail closed. Record UTC event and availability time. No proprietary Neraium-2.0 code.

Shared contracts live in backend/neraium_poly/contracts.py; changes require integration review. Quantities are outcome shares, prices USD/share, notional USD. Floating arithmetic must use explicit tolerances; audit records preserve inputs. Statistical findings never independently prove mispricing. BUY-only research is acceptable; unsupported operations must reject explicitly.

Writing agents must use separate worktrees created by citadel-neraium worktree UNIQUE_NAME. Write only your assigned directories and test file. Commit logical milestones; report commit IDs. Integration coordinator reviews and cherry-picks after tests. No deployment. User explicitly authorized feature branches, commits, push and PR creation for this build.

Run uv run --extra dev pytest, uv run --extra dev ruff check backend tests, and dashboard npm checks before integration. Keep test evidence and resumable campaign state under .planning/. Do not commit .env, databases, local Citadel config, or unrelated archived evidence.
