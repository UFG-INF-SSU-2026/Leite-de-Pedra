"""Gera artigo.pdf a partir de artigo.md. Requer reportlab e as fontes Times do Windows.

    python entregas/Marco4/gerar_pdf.py
"""

import re
from pathlib import Path

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib import colors

RAIZ = Path(__file__).resolve().parent
ORIGEM = RAIZ / "artigo.md"
DESTINO = RAIZ / "artigo.pdf"
FONTES = Path(r"C:\Windows\Fonts")

pdfmetrics.registerFont(TTFont("Times", str(FONTES / "times.ttf")))
pdfmetrics.registerFont(TTFont("Times-Bold", str(FONTES / "timesbd.ttf")))
pdfmetrics.registerFont(TTFont("Times-Italic", str(FONTES / "timesi.ttf")))
pdfmetrics.registerFont(TTFont("Times-BoldItalic", str(FONTES / "timesbi.ttf")))


def xml(texto):
    texto = (texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    texto = re.sub(r"`([^`]+)`", r'<font face="Courier" size="9">\1</font>', texto)
    texto = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", texto)
    return texto


def estilos():
    return {
        "titulo": ParagraphStyle(
            "titulo", fontName="Times-Bold", fontSize=14, leading=18,
            alignment=TA_CENTER, spaceAfter=12, textColor=colors.black,
        ),
        "autores": ParagraphStyle(
            "autores", fontName="Times", fontSize=12, leading=16,
            alignment=TA_CENTER, spaceAfter=4,
        ),
        "h1": ParagraphStyle(
            "h1", fontName="Times-Bold", fontSize=12, leading=16,
            spaceBefore=14, spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2", fontName="Times-Bold", fontSize=12, leading=16,
            spaceBefore=10, spaceAfter=6,
        ),
        "corpo": ParagraphStyle(
            "corpo", fontName="Times", fontSize=12, leading=18,
            alignment=TA_JUSTIFY, firstLineIndent=1.25 * cm, spaceAfter=8,
        ),
        "corpo_solto": ParagraphStyle(
            "corpo_solto", fontName="Times", fontSize=12, leading=18,
            alignment=TA_JUSTIFY, spaceAfter=8,
        ),
        "ref": ParagraphStyle(
            "ref", fontName="Times", fontSize=12, leading=16,
            alignment=TA_JUSTIFY, leftIndent=0.75 * cm, firstLineIndent=-0.75 * cm,
            spaceAfter=6,
        ),
        "item": ParagraphStyle(
            "item", fontName="Times", fontSize=12, leading=16, alignment=TA_JUSTIFY,
        ),
        "comando": ParagraphStyle(
            "comando", fontName="Courier", fontSize=9, leading=12, spaceBefore=4, spaceAfter=8,
        ),
        "celula": ParagraphStyle(
            "celula", fontName="Times", fontSize=8, leading=10,
        ),
        "celula_h": ParagraphStyle(
            "celula_h", fontName="Times-Bold", fontSize=8, leading=10,
        ),
    }


def tabela(linhas, estilo):
    cabecalho = True
    dados = []
    for linha in linhas:
        celulas = [c.strip() for c in linha.strip().strip("|").split("|")]
        if set(celulas) <= {"", "-", "---"} or all(re.fullmatch(r"-+", c.replace(" ", "")) or c == "" for c in celulas):
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in celulas):
            continue
        fonte = estilo["celula_h"] if cabecalho else estilo["celula"]
        dados.append([Paragraph(xml(c), fonte) for c in celulas])
        cabecalho = False
    if not dados:
        return Spacer(1, 1)
    largura = 16 * cm
    col = largura / len(dados[0])
    grade = Table(dados, colWidths=[col] * len(dados[0]), repeatRows=1)
    grade.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.93, 0.93, 0.93)),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return grade


def fluxo(texto, estilo):
    linhas = texto.splitlines()
    story = []
    i = 0
    nas_referencias = False
    antes_das_secoes = True
    while i < len(linhas):
        linha = linhas[i]
        if not linha.strip():
            i += 1
            continue
        if linha.startswith("# "):
            story.append(Paragraph(xml(linha[2:].strip()), estilo["titulo"]))
            i += 1
            continue
        if linha.startswith("## "):
            titulo = linha[3:].strip()
            nas_referencias = titulo.lower().startswith("refer")
            antes_das_secoes = False
            story.append(Paragraph(xml(titulo), estilo["h1"]))
            i += 1
            continue
        if linha.startswith("### "):
            story.append(Paragraph(xml(linha[4:].strip()), estilo["h2"]))
            i += 1
            continue
        if linha.startswith("|"):
            bloco = []
            while i < len(linhas) and linhas[i].startswith("|"):
                bloco.append(linhas[i])
                i += 1
            story.append(Spacer(1, 4))
            story.append(tabela(bloco, estilo))
            story.append(Spacer(1, 8))
            continue
        if linha.startswith("- "):
            itens = []
            while i < len(linhas) and linhas[i].startswith("- "):
                itens.append(ListItem(Paragraph(xml(linhas[i][2:].strip()), estilo["item"]), leftIndent=12))
                i += 1
            story.append(ListFlowable(itens, bulletType="bullet", start="•", leftIndent=18))
            story.append(Spacer(1, 6))
            continue
        if linha.startswith("`") and linha.endswith("`") and linha.count("`") == 2:
            story.append(Preformatted(linha.strip("`"), estilo["comando"]))
            i += 1
            continue
        paragrafo = [linha.strip()]
        i += 1
        while i < len(linhas) and linhas[i].strip() and not linhas[i].startswith(("#", "|", "- ", "`")):
            paragrafo.append(linhas[i].strip())
            i += 1
        texto_p = xml(" ".join(paragrafo))
        if nas_referencias:
            story.append(Paragraph(texto_p, estilo["ref"]))
        elif antes_das_secoes:
            story.append(Paragraph(texto_p, estilo["autores"]))
        else:
            story.append(Paragraph(texto_p, estilo["corpo"]))
    return story


def numero(canvas, doc):
    canvas.saveState()
    canvas.setFont("Times", 10)
    canvas.drawCentredString(A4[0] / 2, 1.2 * cm, str(doc.page))
    canvas.restoreState()


def main():
    documento = SimpleDocTemplate(
        str(DESTINO), pagesize=A4,
        leftMargin=3 * cm, rightMargin=2 * cm, topMargin=3 * cm, bottomMargin=2 * cm,
        title="Balanceamento de filas de entrada com decisão na catraca por reconhecimento facial",
        author="Caio Castro Miranda; João Pedro de Brito Tomé; João Victor Braga; Jaime da Cruz",
    )
    documento.build(fluxo(ORIGEM.read_text(encoding="utf-8"), estilos()), onFirstPage=numero, onLaterPages=numero)
    print(DESTINO)


if __name__ == "__main__":
    main()
