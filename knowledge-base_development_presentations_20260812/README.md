# Knowledge Base 開發簡報彙整

產生日期：2026-08-12（Asia/Taipei）

此目錄由 Knowledge Base Git 全部分支與歷史提交還原。正式簡報依「首次提交時間」排序，檔案內容取該路徑最後一次提交版本；來源檔案未被移動或修改。

## 正式簡報

| 順序 | 首次提交日期 | 投影片數 | 分享檔名 | 原始路徑 | 最新來源 commit |
|---:|---|---:|---|---|---|
| 1 | 2026-06-09 | 1 | `20260609_01_chat_stability_question_types.pptx` | `chat_stability_question_types.pptx` | `8a84603b44bc` |
| 2 | 2026-06-09 | 3 | `20260609_02_kb_architecture_slide.pptx` | `kb_architecture_slide.pptx` | `8a84603b44bc` |
| 3 | 2026-06-09 | 3 | `20260609_03_manual_ingest_customer_intro.pptx` | `manual_ingest_customer_intro.pptx` | `8a84603b44bc` |
| 4 | 2026-06-09 | 1 | `20260609_04_neo4j_customer_intro.pptx` | `neo4j_customer_intro.pptx` | `8a84603b44bc` |
| 5 | 2026-06-09 | 1 | `20260609_05_qdrant_customer_intro.pptx` | `qdrant_customer_intro.pptx` | `8a84603b44bc` |
| 6 | 2026-06-09 | 3 | `20260609_06_query_examples_slide.pptx` | `query_examples_slide.pptx` | `8a84603b44bc` |
| 7 | 2026-08-06 | 22 | `20260806_07_ANRITSU_AGENT_A2A_IMPLEMENTATION_GUIDE.pptx` | `ANRITSU_AGENT_A2A_IMPLEMENTATION_GUIDE.pptx` | `35d8d56a713d` |
| 8 | 2026-08-06 | 1 | `20260806_08_SUB2API_LLM_Architecture_Diagram.pptx` | `SUB2API_LLM_Architecture_Diagram.pptx` | `e3d7d29e2103` |
| 9 | 2026-08-06 | 4 | `20260806_09_anritsu_amarisoft_kb_architecture.pptx` | `anritsu_amarisoft_kb_architecture.pptx` | `e3d7d29e2103` |
| 10 | 2026-08-06 | 5 | `20260806_10_dual_test_env_ollama_architecture.pptx` | `dual_test_env_ollama_architecture.pptx` | `e3d7d29e2103` |
| 11 | 2026-08-06 | 5 | `20260806_11_knowledge_base_architecture_all_dig_style.pptx` | `knowledge_base_architecture_all_dig_style.pptx` | `e3d7d29e2103` |
| 12 | 2026-08-06 | 5 | `20260806_12_knowledge_base_architecture_diagrams.pptx` | `knowledge_base_architecture_diagrams.pptx` | `e3d7d29e2103` |
| 13 | 2026-08-06 | 10 | `20260806_13_knowledge_base_enterprise_architecture.pptx` | `knowledge_base_enterprise_architecture.pptx` | `e3d7d29e2103` |
| 14 | 2026-08-06 | 3 | `20260806_14_knowledge_base_topology_gap_comparison.pptx` | `knowledge_base_topology_gap_comparison.pptx` | `e3d7d29e2103` |
| 15 | 2026-08-06 | 9 | `20260806_15_new_machine_rebuild_guide.pptx` | `new_machine_rebuild_guide.pptx` | `e3d7d29e2103` |
| 16 | 2026-08-06 | 7 | `20260806_16_onprem_post_install_connection_guide.pptx` | `onprem_post_install_connection_guide.pptx` | `e3d7d29e2103` |
| 17 | 2026-08-06 | 8 | `20260806_17_sub2api_development_progress.pptx` | `sub2api_development_progress.pptx` | `e3d7d29e2103` |
| 18 | 2026-08-06 | 1 | `20260806_18_sub2api_simple_architecture.pptx` | `sub2api_simple_architecture.pptx` | `e3d7d29e2103` |
| 19 | 2026-08-10 | 15 | `20260810_19_KM_MODERNIZATION_WP0-WP13_ROADMAP.pptx` | `docs/km-modernization/KM_MODERNIZATION_WP0-WP13_ROADMAP.pptx` | `519486759166` |
| 20 | 2026-08-11 | 7 | `20260811_20_AI-KM-Weekly-2026-W33.pptx` | `docs/km-modernization/progress/presentations/AI-KM-Weekly-2026-W33.pptx` | `47cb977e3191` |
| 21 | 2026-08-11 | 17 | `20260811_21_AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx` | `AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx`（由 `dce63ae653d5` 版本擴充 80 條 WP0/WP1 台帳） | `LOCAL 2026-08-12` |

## 範本

- `templates/TEMPLATE_weekly-report-template.pptx`：7 頁，來源 `docs/km-modernization/progress/templates/weekly-report-template.pptx`，commit `1beee3d8e644`。

## 完整性

- `presentation_manifest.csv` 包含首次／最新 commit、原始路徑、檔案大小、投影片數及 SHA-256。
- 所有 PPTX 都已執行 ZIP 結構驗證；實際 LibreOffice 渲染驗證結果另記錄於 `RENDER_VALIDATION.md`。
- 檔名前綴只供時間排序，不代表原始檔名被改寫。
- 第 21 份簡報於 2026-08-12 依實際 WP0/WP1 commit、測試及部署證據由 7 頁擴充為 17 頁；WP0 32 條、WP1 48 條，每條獨立列出動作、功能、改動及檔案／證據。原 Git 基準為 `dce63ae653d5`，新版尚未提交 Git，因此 Manifest 明確標記為 `LOCAL-ITEMIZED-20260812`。
