import os
from PIL import Image, ImageDraw, ImageFont
out = "/tmp/km_selftest"; os.makedirs(out, exist_ok=True)
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
f = ImageFont.truetype(FONT, 34, index=2)   # index 2 ~ TC variant in the Noto CJK collection; any CJK glyphs work for traditional text
# 1) Traditional Chinese + English text image (OCR case)
im = Image.new("RGB", (1500, 760), "white"); d = ImageDraw.Draw(im)
lines = ["KM 圖片分析測試報告", "設備型號:RTF8246VW 無線路由器", "傳輸速率:最高 1200 Mbps,支援 Wi-Fi 6 與 WPA3", "測試日期:2026 年 11 月 20 日  測試人員:陳小明", "結果:下載吞吐量 934 Mbps,延遲 12 ms,封包遺失率 0.1%", "備註:本圖片僅供 KM 開發環境自動化驗證使用"]
for i, t in enumerate(lines): d.text((60, 60 + i * 105), t, fill="black", font=f)
im.save(f"{out}/selftest_zh.png")
# 2) diagram with almost no text (vision case)
im = Image.new("RGB", (900, 600), "white"); d = ImageDraw.Draw(im)
d.rectangle((80, 200, 300, 380), outline="black", width=6, fill="#cfe3ff")
d.rectangle((600, 200, 820, 380), outline="black", width=6, fill="#ffd9a8")
d.line((300, 290, 600, 290), fill="red", width=8); d.polygon([(600, 290), (560, 265), (560, 315)], fill="red")
d.ellipse((400, 80, 500, 180), outline="green", width=6)
d.text((150, 270), "A", fill="black", font=ImageFont.truetype(FONT, 60)); d.text((690, 270), "B", fill="black", font=ImageFont.truetype(FONT, 60))
im.save(f"{out}/selftest_diagram.png")
# 3) equipment spec workbook (Excel case)
from openpyxl import Workbook
wb = Workbook(); ws = wb.active; ws.title = "規格"
rows = [["型號", "RTF8246VW", ""], ["廠商", "Askey", ""], ["無線標準", "Wi-Fi 6 (IEEE 802.11ax)", ""], ["最高速率", "1200 Mbps", "5 GHz"], ["連接埠", "4 x 1GbE LAN, 1 x WAN", ""], ["安全", "WPA3, WPA2", ""], ["已知限制", "DFS 通道切換時會短暫中斷約 60 秒", ""]]
for r in rows: ws.append(r)
ws2 = wb.create_sheet("測試結果"); ws2.append(["項目", "結果", "單位"]); ws2.append(["下載吞吐量", 934, "Mbps"]); ws2.append(["上傳吞吐量", 871, "Mbps"]); ws2.append(["延遲", 12, "ms"])
wb.save(f"{out}/selftest_equipment.xlsx")
print(sorted(os.listdir(out)))
