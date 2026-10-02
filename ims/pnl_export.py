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


# ── Profit by invoice ─────────────────────────────────────────────────────────

def build_invoice_pdf(rep, company_name='Rehumile TMW', compress=True):
    st = _styles()
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=18 * mm,
                            title='Profit by invoice', author=company_name, pageCompression=1 if compress else 0)
    W = page[0] - 28 * mm
    P = lambda t, s='cell': Paragraph(_t(t), st[s])
    TH = lambda t, r=False: Paragraph(_t(t), st['thr' if r else 'th'])
    red = lambda v: Paragraph(f"<font color='#B00020'>{_t(money(v))}</font>" if v < 0 else _t(money(v)), st['cellr'])
    story = []
    head = []
    if LOGO.exists():
        head.append(Image(str(LOGO), width=38 * mm, height=13 * mm, kind='proportional', hAlign='LEFT'))
    head.append(Paragraph(f"<b>{_t(company_name)}</b>", st['body']))
    ht = Table([[head, [Paragraph('PROFIT BY INVOICE', st['title']), Paragraph(_t(rep['label']) + ' — amounts exclude VAT', st['rsmall'])]]], colWidths=[W * 0.4, W * 0.6])
    ht.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    story += [ht, HRFlowable(width='100%', thickness=2.5, color=BRAND, spaceAfter=6), P(rep['note'], 'small'), Spacer(1, 6)]
    widths = [30 * mm, 48 * mm, 52 * mm, 25 * mm, 25 * mm, 25 * mm, W - 205 * mm]

    def inv_table(title, sec, total_label):
        data = [[TH('INVOICE'), TH('CLIENT'), TH('JOB'), TH('AMOUNT', True), TH('COSTS', True), TH('PROFIT', True), TH('NOTE')]]
        for r in sec['rows']:
            data.append([P(r['invoice']), P(r['client']), P(r['job']), P(money(r['amount']), 'cellr'), P(money(r['cost']), 'cellr'), red(r['profit']), P(r['note'])])
        t = sec['totals']
        data.append([P(total_label, 'h'), P(''), P(''), P(money(t['amount']), 'cellr'), P(money(t['cost']), 'cellr'), red(t['profit']), P('')])
        tb = Table(data, colWidths=widths, repeatRows=1)
        tb.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), BRAND), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
                                ('LINEBELOW', (0, 1), (-1, -1), 0.3, LIGHT), ('BACKGROUND', (0, -1), (-1, -1), TINT), ('LINEABOVE', (0, -1), (-1, -1), 1, BRAND),
                                ('SPAN', (0, -1), (2, -1))]))
        return [Paragraph(title, st['h']), Spacer(1, 3), tb, Spacer(1, 10)]

    story += inv_table('A. STILL UNPAID', rep['unpaid'], 'Total still unpaid')
    story += inv_table('B. ALREADY PAID', rep['paid'], 'Total already paid')
    story.append(Paragraph(f"C. RUNNING COSTS — {money(rep['running']['amount'])}", st['h']))
    rows = [[P(g['item']), P(', '.join(sorted({r['label'] for r in g['rows']}))), P(money(g['amount']), 'cellr')] for g in rep['running']['items']]
    rows.append([P('Total running costs', 'h'), P(''), P(money(rep['running']['amount']), 'cellr')])
    story += [Spacer(1, 3), Table(rows, colWidths=[90 * mm, W - 90 * mm - 35 * mm, 35 * mm], style=[('LINEBELOW', (0, 0), (-1, -1), 0.3, LIGHT), ('VALIGN', (0, 0), (-1, -1), 'TOP')]), Spacer(1, 10)]
    story.append(Paragraph('D. PROFIT IF EVERYONE PAYS', st['h']))
    d = [[P(f"{l['sign']} {l['label']}", 'h' if l.get('total') else 'body'), red(l['amount']) if l['key'] == 'net' else P(money(l['amount']), 'cellr')] for l in rep['summary']]
    c = rep['check']
    d.append([P('Check: dashboard and Profit & Loss net profit ' + ('agree' if c['ok'] else f"DIFFER ({money(c['dashboard'])} / {money(c['pnl'])})"), 'small'), P('')])
    story += [Spacer(1, 3), Table(d, colWidths=[W * 0.6, 40 * mm], style=[('LINEBELOW', (0, 0), (-1, -1), 0.3, LIGHT)]), Spacer(1, 10)]
    story.append(Paragraph('E. WHAT WE OWE SUPPLIERS', st['h']))
    story.append(P(rep['suppliers']['note'], 'small'))
    sd = [[P(b['account']), P(b['covers']), P(b['status']), P(money(b['amount']), 'cellr')] for b in rep['suppliers']['rows']]
    sd.append([P('Total / still to pay', 'h'), P(''), P(''), P(f"{money(rep['suppliers']['total'])} / {money(rep['suppliers']['still_to_pay'])}", 'cellr')])
    story.append(Table(sd, colWidths=[35 * mm, W - 35 * mm - 25 * mm - 55 * mm, 25 * mm, 55 * mm], style=[('LINEBELOW', (0, 0), (-1, -1), 0.3, LIGHT), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))

    def on_page(canvas, d_):
        canvas.saveState()
        canvas.setStrokeColor(LIGHT)
        canvas.line(14 * mm, 13 * mm, page[0] - 14 * mm, 13 * mm)
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(14 * mm, 8.5 * mm, f"Profit by invoice  |  {rep['label']}  |  Generated {rep['generated_at']}  |  amounts exclude VAT")
        canvas.drawRightString(page[0] - 14 * mm, 8.5 * mm, f"Page {d_.page}  |  Internal — contains costs")
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def build_invoice_csv(rep):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Profit by invoice', rep['label'], 'Amounts exclude VAT'])
    w.writerow(['Generated', rep['generated_at']])
    for title, sec in (('A. Still unpaid', rep['unpaid']), ('B. Already paid', rep['paid'])):
        w.writerow([])
        w.writerow([title])
        w.writerow(['Invoice', 'Client', 'Job', 'Amount', 'Costs', 'Profit', 'Note'])
        for r in sec['rows']:
            w.writerow([r['invoice'], r['client'], r['job'], f"{r['amount']:.2f}", f"{r['cost']:.2f}", f"{r['profit']:.2f}", r['note']])
        t = sec['totals']
        w.writerow(['Total', '', '', f"{t['amount']:.2f}", f"{t['cost']:.2f}", f"{t['profit']:.2f}"])
    w.writerow([])
    w.writerow(['C. Running costs'])
    for g in rep['running']['items']:
        w.writerow([g['item'], '', '', f"{g['amount']:.2f}"])
        for r in g['rows']:
            w.writerow(['', r['label'], r['line'], f"{r['amount']:.2f}", r['date']])
    w.writerow(['Total running costs', '', '', f"{rep['running']['amount']:.2f}"])
    w.writerow([])
    w.writerow(['D. Profit if everyone pays'])
    for l in rep['summary']:
        w.writerow([l['label'], '', '', f"{l['amount']:.2f}"])
    w.writerow(['Check (dashboard / Profit & Loss agree)', 'yes' if rep['check']['ok'] else 'NO'])
    w.writerow([])
    w.writerow(['E. What we owe suppliers', rep['suppliers']['note']])
    w.writerow(['Account', 'Covers', 'Status', 'Amount'])
    for b in rep['suppliers']['rows']:
        w.writerow([b['account'], b['covers'], b['status'], f"{b['amount']:.2f}"])
    w.writerow(['Total', '', '', f"{rep['suppliers']['total']:.2f}"])
    w.writerow(['Still to pay', '', '', f"{rep['suppliers']['still_to_pay']:.2f}"])
    return out.getvalue()
