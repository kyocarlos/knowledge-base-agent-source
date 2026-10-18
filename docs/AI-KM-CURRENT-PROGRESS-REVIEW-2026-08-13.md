# AI KM 目前進度 Review Index

日期：2026-08-13  
用途：提供主管與 review agent 以 GitHub 分支為基準進行程式、測試、文件與安全 Gate 審查。

## 總結

目前已保留 WP0/WP1 既有成果，並完成 KM OpenClaw → Anritsu OpenClaw 的受控 dry-run 通訊驗證。真實儀器測試尚未放行。

```text
WP0/WP1：既有成果保留，依實際 branch/commit/PR/CI 證據判定
A2A dry-run：PASS
R0 real-run contract/Gate：規格完成，放行 NO-GO
R1 mock contract/runtime/registry/safety：PASS
R2 KM-local shadow adapter：PASS
R2 跨機 Anritsu shadow：NO-GO
R3 真實儀器：NO-GO
```

## 主要文件

- [`docs/km-modernization/`](km-modernization/)：KM modernization 規劃與 WP 追溯。
- [`docs/pre-real-test-review-2026-08-13.md`](pre-real-test-review-2026-08-13.md)：真實測試前 Gate 審查。
- [`docs/r0-real-run-contract-and-gate-2026-08-13.md`](r0-real-run-contract-and-gate-2026-08-13.md)：R0 real-run contract、威脅模型、批准與放行條件。
- [`docs/r1-mock-real-transport-2026-08-13.md`](r1-mock-real-transport-2026-08-13.md)：R1 mock lifecycle、registry、safety evidence。
- [`docs/r2-shadow-adapter-integration-2026-08-13.md`](r2-shadow-adapter-integration-2026-08-13.md)：KM-local Anritsu shadow adapter evidence。
- [`docs/KM_OPENCLAW_ANRITSU_OPENCLAW_A2A_CONTRACT.md`](KM_OPENCLAW_ANRITSU_OPENCLAW_A2A_CONTRACT.md)：KM 與 Anritsu A2A 邊界。
- [`ANRITSU_AGENT_A2A_REQUIREMENTS.md`](../ANRITSU_AGENT_A2A_REQUIREMENTS.md)：Anritsu 端配合清單。
- [`PROJECT_MEMORY.md`](../PROJECT_MEMORY.md)：完整歷史決策與實測紀錄。

## 程式與測試

- `km_a2a_bridge/real_contracts.py`：獨立 real-run schema，未接入現有 dry-run runtime。
- `km_a2a_bridge/mock_real_runtime.py`：mock-only lifecycle。
- `km_a2a_bridge/real_registry.py`：SQLite approval/lock registry，未接入 production service。
- `km_a2a_bridge/safety_lifecycle.py`：cancel → safe-state → cleanup contract。
- `km_a2a_bridge/anritsu_shadow_adapter.py`：KM-local shadow adapter contract。
- `tests/test_km_a2a_real_contracts.py`、`test_km_a2a_mock_real_runtime.py`、`test_km_a2a_real_registry.py`、`test_km_a2a_safety_lifecycle.py`、`test_km_a2a_anritsu_shadow_adapter.py`：R0/R1/R2 測試。
- `scripts/km_anritsu_command.py`：現有受控 KM 命令入口，固定 dry-run。

## 驗證證據

最新 R0/R1/R2 focused tests：

```bash
PYTHONPATH=. uv run --with a2a-sdk==1.1.2 --with pytest \
  pytest -q tests/test_km_a2a_real_contracts.py \
  tests/test_km_a2a_mock_real_runtime.py \
  tests/test_km_a2a_real_registry.py \
  tests/test_km_a2a_safety_lifecycle.py \
  tests/test_km_a2a_anritsu_shadow_adapter.py
```

結果：`30 passed`。

既有跨機 dry-run 最新證據：

- `run_id=pre-real-gate-20260813T040736Z`
- `state=completed`
- `openclaw_forward_status=accepted`
- `openclaw_receiver=anritsu-openclaw`
- 七項 dry-run side-effect counters 全部為 `0`

## Review 注意事項

1. 本分支包含工作區目前可追溯的進度；Python `__pycache__`、`.env`、token、`.age` 等本機或秘密資料不應納入 Git。
2. 不得因 R1/R2 mock 或 dry-run PASS 就宣稱真實儀器測試完成。
3. 目前仍保持 `KM_A2A_TRANSPORT=sdk-dry-run` 與 `real_instrument_access=false`。
4. 真實測試前仍需 Anritsu 端跨機 shadow adapter 證據、正式安全傳輸、real service integration、approval/lock persistence integration、artifact/ingest、crash recovery 與回滾驗收。
5. Review agent 應優先檢查：現有 runtime 是否仍與 R1/R2 模組隔離、dry-run contract 是否仍固定、秘密是否進入 Git、測試是否能重現 Gate 結論。

## 回滾

本分支未修改主 KM chat、search、report upload、ingest 或資料庫。若 review 後不採用，保留目前 `dev-work` 與既有 commit，或只刪除/停用尚未接入的 R1/R2 模組；不得 force push 或 reset 使用中的工作區。
