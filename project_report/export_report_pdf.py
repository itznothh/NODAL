"""Export the editable NODAL report to a matching paginated PDF.

Run with the Codex bundled Python runtime. This fallback preserves the DOCX
content and embedded figures when LibreOffice/Word automation is unavailable.
"""
from io import BytesIO
from pathlib import Path
import html

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph as DocxParagraph
from docx.table import Table as DocxTable
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "NODAL_Project_Report_Editable.docx"
DEST = ROOT / "NODAL_Project_Report.pdf"

font_dir = Path("C:/Windows/Fonts")
for name, filename in (("TNR", "times.ttf"), ("TNRB", "timesbd.ttf"), ("TNRI", "timesi.ttf")):
    try:
        pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    except Exception:
        pass
body_font = "TNR" if "TNR" in pdfmetrics.getRegisteredFontNames() else "Times-Roman"
bold_font = "TNRB" if "TNRB" in pdfmetrics.getRegisteredFontNames() else "Times-Bold"

styles = {
    "Normal": ParagraphStyle("body", fontName=body_font, fontSize=10.3, leading=13.3,
                              alignment=TA_JUSTIFY, spaceAfter=5),
    "Title": ParagraphStyle("title", fontName=bold_font, fontSize=22, leading=27,
                             textColor=colors.HexColor("#263F35"), alignment=TA_CENTER, spaceAfter=10),
    "Heading 1": ParagraphStyle("h1", fontName=bold_font, fontSize=15, leading=19,
                                 textColor=colors.HexColor("#263F35"), spaceBefore=11, spaceAfter=6, keepWithNext=True),
    "Heading 2": ParagraphStyle("h2", fontName=bold_font, fontSize=12.2, leading=15,
                                 textColor=colors.HexColor("#263F35"), spaceBefore=8, spaceAfter=4, keepWithNext=True),
    "Heading 3": ParagraphStyle("h3", fontName=bold_font, fontSize=10.8, leading=13.5,
                                 textColor=colors.HexColor("#343A40"), spaceBefore=6, spaceAfter=3, keepWithNext=True),
}

def escaped(value):
    return html.escape(value, quote=False).replace("\n", "<br/>")

def paragraph_markup(paragraph):
    pieces = []
    for run in paragraph.runs:
        value = escaped(run.text)
        if not value:
            continue
        if run.bold:
            value = f"<b>{value}</b>"
        if run.italic:
            value = f"<i>{value}</i>"
        pieces.append(value)
    return "".join(pieces) or escaped(paragraph.text)

def page_footer(canvas, document):
    canvas.saveState()
    canvas.setFont(body_font, 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawCentredString(letter[0] / 2, .42 * inch,
                             f"NODAL  |  ACADEMIC PROJECT REPORT  •  {document.page}")
    canvas.restoreState()

document = Document(SOURCE)
related = document.part.related_parts
story = []
for element in document.element.body.iterchildren():
    kind = element.tag.rsplit("}", 1)[-1]
    if kind == "p":
        paragraph = DocxParagraph(element, document)
        if element.xpath('.//w:br[@w:type="page"]'):
            story.append(PageBreak())
            continue
        image_refs = element.xpath(".//a:blip")
        if image_refs:
            for image_ref in image_refs:
                part = related[image_ref.get(qn("r:embed"))]
                image = Image(BytesIO(part.blob))
                scale = min((6.3 * inch) / image.imageWidth, (7 * inch) / image.imageHeight)
                image.drawWidth *= scale
                image.drawHeight *= scale
                image.hAlign = "CENTER"
                story.append(image)
            continue
        content = paragraph_markup(paragraph)
        if not content.strip():
            story.append(Spacer(1, 5))
            continue
        style = styles.get(paragraph.style.name, styles["Normal"])
        if paragraph.style.name.startswith("List Bullet"):
            content = "•  " + content
        elif paragraph.style.name.startswith("List Number"):
            content = "–  " + content
        story.append(Paragraph(content, style))
    elif kind == "tbl":
        source_table = DocxTable(element, document)
        rows = []
        for row_index, row in enumerate(source_table.rows):
            output_row = []
            for cell in row.cells:
                content = "<br/>".join(escaped(item.text) for item in cell.paragraphs)
                if row_index == 0:
                    content = f"<b>{content}</b>"
                cell_style = ParagraphStyle(
                    f"cell-{row_index}", fontName=bold_font if row_index == 0 else body_font,
                    fontSize=7.6, leading=9.4,
                    textColor=colors.white if row_index == 0 else colors.black,
                )
                output_row.append(Paragraph(content, cell_style))
            rows.append(output_row)
        if rows:
            widths = [6.55 * inch / len(rows[0])] * len(rows[0])
            output_table = Table(rows, colWidths=widths, repeatRows=1, hAlign="CENTER")
            output_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263F35")),
                ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#AAA99F")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F5EF")]),
            ]))
            story.extend((Spacer(1, 4), output_table, Spacer(1, 7)))

pdf = SimpleDocTemplate(str(DEST), pagesize=letter, rightMargin=inch, leftMargin=inch,
                        topMargin=.72 * inch, bottomMargin=.68 * inch,
                        title="NODAL Academic Project Report", author="[TEAM MEMBERS — EDITABLE PLACEHOLDERS]")
pdf.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
print(f"Created {DEST}")
