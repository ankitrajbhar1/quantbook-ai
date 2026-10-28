from pathlib import Path
import fitz

out = Path(__file__).resolve().parents[1] / "demo_trading_book.pdf"
pdf = fitz.open()
p = pdf.new_page()
p.insert_text((65, 70), "QuantBook AI - Sample Trading Research", fontsize=18)
p.insert_textbox(fitz.Rect(65, 115, 520, 230), "Example: A moving average is the arithmetic mean of the previous N observations.\n\nThis page is synthetic test content, not a trading recommendation.", fontsize=12)
p.draw_rect(fitz.Rect(75, 280, 500, 510), color=(0.2, 0.4, 0.7), width=1)
p.draw_line((100, 480), (475, 480), color=(0, 0, 0))
p.draw_line((100, 480), (100, 300), color=(0, 0, 0))
points = [(100, 460), (160, 440), (220, 450), (280, 390), (340, 365), (400, 350), (475, 320)]
for a,b in zip(points,points[1:]):p.draw_line(a,b,color=(0.1,0.55,0.25),width=2)
p.insert_text((125, 530), "Illustrative price chart (not actual market data)", fontsize=10)
pdf.save(str(out))
print(out)
