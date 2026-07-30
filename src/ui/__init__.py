"""
簡單的前端介面 - 使用 Gradio
提供基本/深層搜尋雙模式
"""

import logging
import gradio as gr
from typing import Optional

logger = logging.getLogger(__name__)


class KnowledgeBaseUI:
    """Gradio 前端介面"""

    def __init__(self, knowledge_base_system):
        """
        初始化 UI

        Args:
            knowledge_base_system: KnowledgeBaseSystem 實例
        """
        self.kb = knowledge_base_system

    def build_interface(self) -> gr.Blocks:
        """建置 Gradio 介面"""

        with gr.Blocks(title="知識庫搜尋系統") as app:
            gr.Markdown("# 🔍 知識庫搜尋系統")
            gr.Markdown("使用 GraphRAG + RAG 混合架構，選擇搜尋模式找到你要的答案")

            # 搜尋模式選擇
            with gr.Row():
                mode_selector = gr.Radio(
                    ["basic", "deep", "auto"],
                    value="auto",
                    label="搜尋模式",
                    info="Basic: 快速向量搜尋 | Deep: 知識圖譜推理 | Auto: 自動選擇"
                )

            # 搜尋輸入
            query_input = gr.Textbox(
                label="輸入你的問題",
                placeholder="例如：特休假可以請幾天？",
                lines=3
            )

            # 搜尋按鈕
            search_btn = gr.Button("🔍 搜尋", variant="primary")

            # 結果顯示
            answer_output = gr.Markdown(label="答案")
            sources_output = gr.JSON(label="來源文件")

            # 模式說明
            gr.Markdown("""
            ### 📖 搜尋模式說明

            | 模式 | 適用情境 | 說明 |
            |------|---------|------|
            | **Basic** | 簡單事實查詢 | 速度快，用向量相似度搜尋 |
            | **Deep** | 複雜多跳推理 | 使用知識圖譜，可跨文件關聯 |
            | **Auto** | 不確定時 | 系統自動判斷複雜度選擇合適模式 |

            ### 💡 使用建議

            - **FAQ、事實查詢** → Basic
            - **比較、推理、跨文件問題** → Deep
            - **不知道選哪個** → Auto
            """)

            # 綁定事件
            search_btn.click(
                fn=self._search_handler,
                inputs=[query_input, mode_selector],
                outputs=[answer_output, sources_output]
            )

        return app

    def _search_handler(self, query: str, mode: str) -> tuple:
        """處理搜尋請求"""
        if not query.strip():
            return "⚠️ 請輸入搜尋內容", {}

        try:
            result = self.kb.search(query, mode)

            if result["status"] == "success":
                answer = f"### ✅ 答案\n\n{result.get('answer', '（無答案）')}"

                # 顯示來源
                sources = result.get("sources", result.get("graph_results", []))
                sources_text = f"**模式：** {result.get('mode', 'unknown')}\n\n**來源：**\n"
                for i, src in enumerate(sources[:5], 1):
                    if isinstance(src, dict):
                        sources_text += f"{i}. {src.get('source', '未知來源')}\n"

                return answer, {"mode": result.get("mode"), "sources": sources}
            else:
                return f"❌ 搜尋失敗：{result.get('message', '未知錯誤')}", {}

        except Exception as e:
            logger.error(f"搜尋錯誤: {e}")
            return f"❌ 發生錯誤：{str(e)}", {}

    def launch(self, server_name: str = "0.0.0.0", server_port: int = 7860):
        """啟動 Gradio 服務"""
        app = self.build_interface()
        app.launch(server_name=server_name, server_port=server_port)


# ===== 啟動範例 =====

def main():
    """啟動 UI（需先完成系統設定）"""
    # from main import KnowledgeBaseSystem

    # kb = KnowledgeBaseSystem("config/config.yaml")
    # ui = KnowledgeBaseUI(kb)
    # ui.launch()

    print("請先完成 config/config.yaml 設定，然後取消這段註解")


if __name__ == "__main__":
    main()