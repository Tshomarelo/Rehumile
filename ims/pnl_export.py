"""PDF and CSV exports of the Profit & Loss (internal: shows costs and profit)."""
import csv
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .quote_pdf import BRAND, GREY, LIGHT, LOGO, TINT, _styles, _t, money


def _tbl(data, widths, header=False):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5), ('LINEBELOW', (0, 0), (-1, -1), 0.3, LIGHT)]
    if header:
        style.append(('BACKGROUND', (0, 0), (-1, 0), BRAND))
    for r in range(1 if header else 0, len(data), 2):
        if r % 2 == 0:
            style.append(('BACKGROUND', (0, r), (-1, r), TINT))
    t.setStyle(TableStyle(style))
    return t


def build_pdf(rep, company_name='Rehumile TMW', compress=True):
    st = _styles()
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=18 * mm,
                            title='Profit & Loss', author=company_name, pageCompression=1 if compress else 0)
    W = page[0] - 28 * mm
    P = lambda t, s='cell': Paragraph(_t(t), st[s])
    TH = lambda t, r=False: Paragraph(_t(t), st['thr' if r else 'th'])
    story = []
    head = []
    if LOGO.exists():
        head.append(Image(str(LOGO), width=38 * mm, height=13 * mm, kind='proportional', hAlign='LEFT'))
    head.append(Paragraph(f"<b>{_t(company_name)}</b>", st['body']))
    ht = Table([[head, [Paragraph('PROFIT &amp; LOSS', st['title']), Paragraph(_t(rep['period']['label']) + ' — ' + _t(rep['view_label']), st['rsmall'])]]], colWidths=[W * 0.4, W * 0.6])
    ht.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    story += [ht, HRFlowable(width='100%', thickness=2.5, color=BRAND, spaceAfter=6), P(rep['note'], 'small'), Spacer(1, 6)]
    lines = [[P(f"{l['sign']} {l['label']}", 'h' if l.get('total') else 'body'), P(money(l['amount']), 'right')] for l in rep['lines']]
    lines.append([P('Net margin', 'small'), P(f"{rep['margin_pct']}%", 'rsmall')])
    story += [_tbl(lines, [W * 0.5, 40 * mm]), Spacer(1, 10)]
    S = rep['sections']

    def rows_table(rows, with_cost=False):
        data = [[TH('REF'), TH('CLIENT / SUPPLIER'), TH('LINE'), TH('DATE'), TH('PAID'), TH('SOURCE'), TH('AMOUNT', True)]]
        for r in rows:
            data.append([P(r.get('ref', '')), P(r.get('label', '')), P(r.get('line', '')), P(r.get('date') or ''), P('yes' if r.get('paid') else 'no'), P(r.get('source', '')), P(money(r['amount']), 'cellr')])
        return _tbl(data, [28 * mm, 45 * mm, 52 * mm, 22 * mm, 12 * mm, W - 28 * mm - 45 * mm - 52 * mm - 22 * mm - 12 * mm - 28 * mm, 28 * mm], header=True)

    for key in ('revenue', 'cost_of_sales', 'operating'):
        sec = S[key]
        story += [Paragraph(f"{_t(sec['label']).upper()} — {money(sec['amount'])}", st['h']), P(sec['explain'], 'small')]
        for g in sec['groups']:
            story += [Spacer(1, 3), Paragraph(f"<b>{_t(g['label'])}</b> — {money(g['amount'])}", st['body']), rows_table(g['rows'])]
        story.append(Spacer(1, 10))
    story += [Paragraph(f"PAYROLL — {money(S['payroll']['amount'])}", st['h']), P(S['payroll']['explain'], 'small')]
    if S['payroll']['rows']:
        story.append(rows_table(S['payroll']['rows']))
    story.append(Spacer(1, 12))
    o = rep['owed_to_us']
    story += [Paragraph(f"MONEY OWED TO US — {money(o['amount'])} (overdue {money(o['overdue'])})", st['h']), P(o['explain'], 'small')]
    if o['rows']:
        data = [[TH('INVOICE'), TH('CLIENT'), TH('DUE'), TH('DAYS LATE', True), TH('TOTAL', True), TH('PAID', True), TH('BALANCE', True)]]
        for r in o['rows']:
            data.append([P(r['ref']), P(r['label']), P(r['due'] or ''), P(str(r['days_overdue']), 'cellr'), P(money(r['total']), 'cellr'), P(money(r['paid']), 'cellr'), P(money(r['amount']), 'cellr')])
        story.append(_tbl(data, [32 * mm, 80 * mm, 26 * mm, 22 * mm, 30 * mm, 30 * mm, W - 220 * mm], header=True))
    story.append(Spacer(1, 10))
    w = rep['we_owe']
    story += [Paragraph(f"MONEY WE OWE — {money(w['amount'])}", st['h']), P(w['explain'], 'small')]
    if w['rows']:
        data = [[TH('SUPPLIER'), TH('FOR'), TH('DATE'), TH('AMOUNT', True)]]
        for r in w['rows']:
            data.append([P(r['label']), P((r['ref'] + ' — ' if r['ref'] else '') + (r['line'] or '')), P(r['date']), P(money(r['amount']), 'cellr')])
        story.append(_tbl(data, [60 * mm, W - 60 * mm - 28 * mm - 30 * mm, 28 * mm, 30 * mm], header=True))

    def on_page(canvas, d):
        canvas.saveState()
        canvas.setStrokeColor(LIGHT)
        canvas.line(14 * mm, 13 * mm, page[0] - 14 * mm, 13 * mm)
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(14 * mm, 8.5 * mm, f"View: {rep['view_label']}  |  Period: {rep['period']['label']} ({rep['period']['start']} to {rep['period']['end']})  |  Generated {rep['generated_at']}  |  amounts exclude VAT")
        canvas.drawRightString(page[0] - 14 * mm, 8.5 * mm, f"Page {d.page}  |  Internal — contains costs")
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def build_csv(rep):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Profit & Loss', rep['view_label']])
    w.writerow(['Period', rep['period']['label'], rep['period']['start'], rep['period']['end']])
    w.writerow(['Generated', rep['generated_at'], 'Amounts exclude VAT'])
    w.writerow([rep['note']])
    w.writerow([])
    for l in rep['lines']:
        w.writerow([l['sign'], l['label'], f"{l['amount']:.2f}"])
    w.writerow(['', 'Net margin %', rep['margin_pct']])
    w.writerow([])
    w.writerow(['Section', 'Group', 'Ref', 'Client / supplier', 'Line', 'Branch', 'Date', 'Paid', 'Revenue / amount', 'Cost', 'Source'])
    S = rep['sections']
    for key in ('revenue', 'cost_of_sales', 'operating'):
        for g in S[key]['groups']:
            for r in g['rows']:
                w.writerow([S[key]['label'], g['label'], r.get('ref', ''), r.get('label', ''), r.get('line', ''), r.get('branch', ''), r.get('date') or '',
                            'yes' if r.get('paid') else 'no', f"{r['amount']:.2f}", f"{r.get('cost', 0):.2f}" if key == 'revenue' else '', r.get('source', '')])
    for r in S['payroll']['rows']:
        w.writerow(['Payroll', '', r['ref'], r['label'], r['line'], '', r['date'], 'yes', f"{r['amount']:.2f}", '', r['source']])
    w.writerow([])
    w.writerow(['Money owed to us', f"{rep['owed_to_us']['amount']:.2f}", f"overdue {rep['owed_to_us']['overdue']:.2f}"])
    for r in rep['owed_to_us']['rows']:
        w.writerow(['', '', r['ref'], r['label'], '', '', r['due'] or '', '', f"{r['amount']:.2f}", '', f"{r['days_overdue']} days overdue" if r['overdue'] else 'not yet due'])
    w.writerow([])
    w.writerow(['Money we owe', f"{rep['we_owe']['amount']:.2f}"])
    for r in rep['we_owe']['rows']:
        w.writerow(['', '', r['ref'], r['label'], r['line'], '', r['date'], 'no', f"{r['amount']:.2f}"])
    return out.getvalue()
