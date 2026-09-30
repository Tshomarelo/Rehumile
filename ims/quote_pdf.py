"""
Printable PDF for a Quotation.

Client-facing only: it shows quantities, prices, VAT and totals, but never the
internal cost / margin figures that live on the quotation.
"""
import io
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

BRAND = colors.HexColor('#50181E')
TINT = colors.HexColor('#FDF5F5')
GREY = colors.HexColor('#666666')
LIGHT = colors.HexColor('#DDDDDD')
LOGO = Path(settings.BASE_DIR) / 'staticfiles' / 'img' / 'rehumile-logo.jpeg'

STAMPS = {'draft': 'DRAFT', 'expired': 'EXPIRED', 'declined': 'DECLINED'}


def _t(value):
    """Escape user text for reportlab Paragraphs and keep newlines."""
    return escape(str(value or '')).replace('\n', '<br/>')


def money(value):
    return 'R ' + f"{float(value or 0):,.2f}".replace(',', ' ')


def _styles():
    base = getSampleStyleSheet()['Normal']
    def s(name, **kw):
        return ParagraphStyle(name, parent=base, fontName=kw.pop('fontName', 'Helvetica'), **kw)
    return {
        'body': s('body', fontSize=9, leading=12),
        'small': s('small', fontSize=8, leading=10.5, textColor=GREY),
        'label': s('label', fontSize=7.5, leading=9, textColor=GREY),
        'h': s('h', fontSize=9, leading=11, textColor=BRAND, fontName='Helvetica-Bold'),
        'name': s('name', fontSize=12, leading=14, textColor=BRAND, fontName='Helvetica-Bold'),
        'title': s('title', fontSize=24, leading=26, textColor=BRAND, fontName='Helvetica-Bold', alignment=TA_RIGHT),
        'right': s('right', fontSize=9, leading=12, alignment=TA_RIGHT),
        'rsmall': s('rsmall', fontSize=8, leading=10.5, textColor=GREY, alignment=TA_RIGHT),
        'th': s('th', fontSize=8, leading=10, textColor=colors.white, fontName='Helvetica-Bold'),
        'thr': s('thr', fontSize=8, leading=10, textColor=colors.white, fontName='Helvetica-Bold', alignment=TA_RIGHT),
        'cell': s('cell', fontSize=9, leading=11.5),
        'cellr': s('cellr', fontSize=9, leading=11.5, alignment=TA_RIGHT),
        'tot': s('tot', fontSize=9, leading=12, alignment=TA_RIGHT),
        'grand': s('grand', fontSize=11, leading=13, alignment=TA_RIGHT, textColor=colors.white, fontName='Helvetica-Bold'),
    }


def build_quote_pdf(quote, settings_obj, compress=True):
    """Return the quotation as PDF bytes. `settings_obj` is the CompanySettings singleton."""
    st = _styles()
    buf = io.BytesIO()
    cs = settings_obj
    company = cs.company_name or 'Rehumile TMW'
    items = list(quote.items.all())
    stamp = STAMPS.get(quote.status)

    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=20 * mm,
        title=f"Quotation {quote.quote_number}", author=company, subject=quote.title or 'Quotation',
        pageCompression=1 if compress else 0,
    )
    width = A4[0] - 36 * mm
    story = []

    # ── header: logo + company on the left, QUOTATION + number on the right ──
    left = []
    if LOGO.exists():
        left.append(Image(str(LOGO), width=42 * mm, height=15 * mm, kind='proportional', hAlign='LEFT'))
    left.append(Paragraph(f"<b>{_t(company)}</b>", st['body']))
    contact = [x for x in (
        _t(cs.address), f"Phone: {_t(cs.phone)}" if cs.phone else '', f"Email: {_t(cs.email)}" if cs.email else '',
        _t(cs.website), f"VAT Reg: {_t(cs.vat_number)}" if cs.vat_number else '') if x]
    if contact:
        left.append(Paragraph('<br/>'.join(contact), st['small']))
    right = [Paragraph('QUOTATION', st['title']), Spacer(1, 2),
             Paragraph(f"<b>{_t(quote.quote_number)}</b>", st['right'])]
    header = Table([[left, right]], colWidths=[width * 0.58, width * 0.42])
    header.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    story += [header, Spacer(1, 4), HRFlowable(width='100%', thickness=2.5, color=BRAND, spaceAfter=10)]

    # ── prepared for / document details ──
    to = [Paragraph('PREPARED FOR', st['label']), Paragraph(_t(quote.client_name), st['name'])]
    sub = [x for x in (_t(quote.client_email), _t(quote.client_phone)) if x]
    if sub:
        to.append(Paragraph('<br/>'.join(sub), st['small']))
    rows = [['Quote date', quote.issue_date.strftime('%d %B %Y')]]
    if quote.valid_until:
        rows.append(['Valid until', quote.valid_until.strftime('%d %B %Y')])
    if quote.company_id and quote.company:
        pass
    details = Table([[Paragraph(a, st['small']), Paragraph(f"<b>{_t(b)}</b>", st['right'])] for a, b in rows],
                    colWidths=[26 * mm, 40 * mm])
    details.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1)]))
    meta = Table([[to, details]], colWidths=[width - 70 * mm, 70 * mm])
    meta.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    story += [meta, Spacer(1, 8)]
    if quote.title:
        story += [Paragraph(f"<b>Re:</b> {_t(quote.title)}", st['body']), Spacer(1, 8)]

    # ── items ──
    data = [[Paragraph('#', st['th']), Paragraph('DESCRIPTION', st['th']), Paragraph('QTY', st['thr']),
             Paragraph('UNIT PRICE', st['thr']), Paragraph('AMOUNT', st['thr'])]]
    for n, it in enumerate(items, 1):
        qty = f"{float(it.quantity):g}"
        data.append([Paragraph(str(n), st['cell']), Paragraph(_t(it.description), st['cell']), Paragraph(qty, st['cellr']),
                     Paragraph(money(it.unit_price), st['cellr']), Paragraph(money(it.line_total), st['cellr'])])
    tbl = Table(data, colWidths=[9 * mm, width - 9 * mm - 18 * mm - 30 * mm - 32 * mm, 18 * mm, 30 * mm, 32 * mm], repeatRows=1)
    style = [('BACKGROUND', (0, 0), (-1, 0), BRAND), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
             ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
             ('LINEBELOW', (0, 1), (-1, -1), 0.4, LIGHT)]
    for r in range(2, len(data), 2):
        style.append(('BACKGROUND', (0, r), (-1, r), TINT))
    tbl.setStyle(TableStyle(style))
    story += [tbl, Spacer(1, 8)]

    # ── totals ──
    vat_label = f"VAT ({float(quote.vat_rate):g}%)"
    trows = [[Paragraph('Subtotal', st['tot']), Paragraph(money(quote.subtotal), st['tot'])],
             [Paragraph(vat_label, st['tot']), Paragraph(money(quote.tax_amount), st['tot'])],
             [Paragraph('TOTAL', st['grand']), Paragraph(money(quote.total_amount), st['grand'])]]
    totals = Table(trows, colWidths=[38 * mm, 38 * mm], hAlign='RIGHT')
    totals.setStyle(TableStyle([('BACKGROUND', (0, 2), (-1, 2), BRAND), ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                                ('LINEABOVE', (0, 2), (-1, 2), 1, BRAND)]))
    story += [totals, Spacer(1, 12)]

    # ── notes / terms / banking / acceptance ──
    blocks = []
    if quote.notes:
        blocks.append(KeepTogether([Paragraph('NOTES', st['h']), Spacer(1, 2), Paragraph(_t(quote.notes), st['body']), Spacer(1, 8)]))
    terms = quote.terms or cs.payment_terms
    if terms:
        blocks.append(KeepTogether([Paragraph('TERMS &amp; CONDITIONS', st['h']), Spacer(1, 2), Paragraph(_t(terms), st['small']), Spacer(1, 8)]))
    bank = [(k, v) for k, v in (('Account name', cs.account_name), ('Bank', cs.bank_name), ('Account number', cs.account_number),
                                 ('Branch code', cs.branch_code), ('SWIFT', cs.swift_code)) if v]
    if bank:
        bt = Table([[Paragraph(k, st['small']), Paragraph(f"<b>{_t(v)}</b>", st['body'])] for k, v in bank], colWidths=[32 * mm, 70 * mm])
        bt.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1)]))
        box = Table([[[Paragraph('BANKING DETAILS', st['h']), Spacer(1, 3), bt,
                       Paragraph(f"Use <b>{_t(quote.quote_number)}</b> as your payment reference.", st['small'])]]], colWidths=[width])
        box.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), TINT), ('LINEBEFORE', (0, 0), (0, -1), 3, BRAND),
                                 ('LEFTPADDING', (0, 0), (-1, -1), 10), ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
        blocks += [box, Spacer(1, 10)]
    sig = Table([[Paragraph('To accept this quotation, sign below and return it to us, or reply to confirm by email.', st['small']), ''],
                 ['', ''],
                 [Paragraph('Name &amp; signature', st['label']), Paragraph('Date', st['label'])]],
                colWidths=[width * 0.65, width * 0.35], rowHeights=[None, 14 * mm, None])
    sig.setStyle(TableStyle([('SPAN', (0, 0), (1, 0)), ('LINEBELOW', (0, 1), (0, 1), 0.6, GREY), ('LINEBELOW', (1, 1), (1, 1), 0.6, GREY),
                             ('RIGHTPADDING', (0, 1), (0, 1), 14), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    blocks.append(KeepTogether([Paragraph('ACCEPTANCE', st['h']), Spacer(1, 3), sig]))
    story += blocks

    def on_page(canvas, doc_):
        canvas.saveState()
        if stamp:
            canvas.setFont('Helvetica-Bold', 80)
            canvas.setFillColor(colors.Color(0.5, 0.5, 0.5, alpha=0.10))
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, stamp)
            canvas.rotate(-35)
            canvas.translate(-A4[0] / 2, -A4[1] / 2)
        canvas.setStrokeColor(LIGHT)
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(GREY)
        foot = f"{company}" + (f"  |  VAT Reg: {cs.vat_number}" if cs.vat_number else '') + f"  |  Quotation {quote.quote_number}"
        canvas.drawString(18 * mm, 10.5 * mm, foot)
        canvas.drawRightString(A4[0] - 18 * mm, 10.5 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
