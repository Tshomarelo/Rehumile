"""PDF and CSV exports of the Profit & Money Owed report (internal: shows costs and profit)."""
import csv
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .quote_pdf import BRAND, GREY, LIGHT, LOGO, TINT, _styles, _t, money


def _stamp(report):
    return f"Basis: {report['basis_label']}  |  Period: {report['period']['label']} ({report['period']['start']} to {report['period']['end']})  |  Generated {report['generated_at']}"


def _tbl(data, widths, header=True, zebra=True, align_right=()):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
             ('LINEBELOW', (0, 1), (-1, -1), 0.3, LIGHT)]
    if header:
        style.append(('BACKGROUND', (0, 0), (-1, 0), BRAND))
    if zebra:
        for r in range(2, len(data), 2):
            style.append(('BACKGROUND', (0, r), (-1, r), TINT))
    t.setStyle(TableStyle(style))
    return t


def build_pdf(report, company_name='Rehumile TMW', compress=True):
    st = _styles()
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=18 * mm,
                            title='Profit & Money Owed', author=company_name, pageCompression=1 if compress else 0)
    width = page[0] - 28 * mm
    P = lambda text, s='cell': Paragraph(_t(text), st[s])
    TH = lambda text, right=False: Paragraph(_t(text), st['thr' if right else 'th'])
    story = []

    head = []
    if LOGO.exists():
        head.append(Image(str(LOGO), width=38 * mm, height=13 * mm, kind='proportional', hAlign='LEFT'))
    head.append(Paragraph(f"<b>{_t(company_name)}</b>", st['body']))
    title = [Paragraph('PROFIT &amp; MONEY OWED', st['title']), Paragraph(_t(report['period']['label']) + ' — ' + _t(report['basis_label']), st['rsmall'])]
    ht = Table([[head, title]], colWidths=[width * 0.4, width * 0.6])
    ht.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    story += [ht, HRFlowable(width='100%', thickness=2.5, color=BRAND, spaceAfter=8)]

    story.append(Paragraph(_t(report['equation']), ParagraphStyleBig(st)))
    hl = [[P(h['sign'] + ' ' + h['label'], 'body' if h['key'] != 'net' else 'h'), P(money(h['amount']), 'right')] for h in report['headline']]
    story += [Spacer(1, 4), _tbl(hl, [width * 0.5, 40 * mm], header=False, zebra=False), Spacer(1, 8)]

    if report['warnings']:
        story.append(Paragraph('WARNINGS', st['h']))
        for w in report['warnings']:
            rows = [[P(r['ref']), P(r['label']), P(r.get('note', '')), P(money(r['amount']), 'right')] for r in w['rows']]
            block = [Paragraph(f"<b>{_t(w['title'])}</b> — {_t(w['detail'])}", st['body'])]
            if rows:
                block.append(_tbl(rows, [35 * mm, 70 * mm, width - 35 * mm - 70 * mm - 30 * mm, 30 * mm], header=False))
            story += [KeepTogether(block[:2]), Spacer(1, 4)] if len(block) > 1 else [block[0], Spacer(1, 4)]
        story.append(Spacer(1, 6))

    S = report['sections']
    # revenue: every invoice with its lines
    story += [Paragraph(f"{_t(S['revenue']['label']).upper()} — {money(S['revenue']['amount'])}", st['h']), P(S['revenue']['explain'], 'small')]
    for inv in S['revenue']['invoices']:
        top = (f"<b>{_t(inv['number'])}</b> — {_t(inv['client'])} · period {inv['period_start']} to {inv['period_end']} · issued {inv['issued'] or '—'} · "
               f"due {inv['due'] or '—'}" + (f" · <font color='#B00020'>{inv['days_overdue']} days overdue</font>" if inv['days_overdue'] else '') +
               f" · total {money(inv['total'])} · paid {money(inv['paid'])} · balance {money(inv['balance'])} · "
               f"<b>counted {money(inv['counted'])}</b> (cost {money(inv['cost'])}, profit {money(inv['profit'])})")
        data = [[TH('LINE'), TH('BRANCH'), TH('QTY', True), TH('PRICE', True), TH('COST / UNIT', True), TH('PROFIT', True), TH('COUNTED', True)]]
        for ln in inv['lines']:
            data.append([P(ln['description']), P(ln['branch']), P(f"{ln['quantity']:g}", 'cellr'), P(money(ln['unit_price']), 'cellr'),
                         P(money(ln['cost_per_unit']), 'cellr'), P(money(ln['profit']), 'cellr'), P(money(ln['counted']), 'cellr')])
        story += [Spacer(1, 4), KeepTogether([Paragraph(top, st['body']), _tbl(data, [width - 135 * mm - 28 * mm, 30 * mm, 14 * mm, 25 * mm, 28 * mm, 26 * mm, 28 * mm])])]
    if S['revenue']['direct_sales']:
        story += [Spacer(1, 4), Paragraph('<b>Till sales</b>', st['body']),
                  _tbl([[P(r['date']), P(r['label']), P(money(r['amount']), 'cellr')] for r in S['revenue']['direct_sales']], [30 * mm, width - 60 * mm, 30 * mm], header=False)]
    story.append(Spacer(1, 10))

    for key in ('provider_costs', 'running_costs', 'payroll'):
        sec = S[key]
        story += [Paragraph(f"{_t(sec['label']).upper()} — {money(sec['amount'])}", st['h']), P(sec['explain'], 'small')]
        rows = [[P(r.get('ref', '')), P(r.get('source') or r.get('label', '')), P(money(r['amount']), 'cellr')] for r in sec['rows']]
        if rows:
            story.append(_tbl(rows, [45 * mm, width - 45 * mm - 30 * mm, 30 * mm], header=False))
        if key == 'running_costs' and sec.get('recurring'):
            story += [Spacer(1, 3), Paragraph('<b>Recurring costs and whether they are posted</b>', st['body']),
                      _tbl([[P(t['name']), P(t['supplier']), P(t['category']), P(t['frequency']), P(money(t['amount']), 'cellr'), P(t['status'])] for t in sec['recurring']],
                           [55 * mm, 50 * mm, 55 * mm, 30 * mm, 28 * mm, width - 218 * mm], header=False)]
        story.append(Spacer(1, 10))

    if report['clients']:
        data = [[TH('CLIENT'), TH('COUNTED', True), TH('STILL OWED', True), TH('COST', True), TH('PROFIT', True), TH('OVERDUE', True), TH('OLDEST DUE')]]
        for c in report['clients']:
            data.append([P(c['client']), P(money(c['amount']), 'cellr'), P(money(c['owed']), 'cellr'), P(money(c['cost']), 'cellr'),
                         P(money(c['profit']), 'cellr'), P(money(c['overdue']), 'cellr'), P(c['oldest_due'] or '—')])
            for b in c['branches']:
                data.append([P('   ↳ ' + b['branch']), P(money(b['amount']), 'cellr'), P(''), P(money(b['cost']), 'cellr'), P(money(b['profit']), 'cellr'), P(''), P('')])
        story += [Paragraph('PER CLIENT', st['h']), _tbl(data, [width - 6 * 28 * mm] + [28 * mm] * 5 + [28 * mm])]

    def on_page(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(LIGHT)
        canvas.line(14 * mm, 13 * mm, page[0] - 14 * mm, 13 * mm)
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(14 * mm, 8.5 * mm, _stamp(report))
        canvas.drawRightString(page[0] - 14 * mm, 8.5 * mm, f"Page {doc_.page}  |  Internal — contains costs")
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def ParagraphStyleBig(st):
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle('eq', parent=st['body'], fontSize=11, leading=14, textColor=BRAND, fontName='Helvetica-Bold')


def build_csv(report):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Profit & Money Owed'])
    w.writerow(['Basis', report['basis_label']])
    w.writerow(['Period', report['period']['label'], report['period']['start'], report['period']['end']])
    w.writerow(['Generated', report['generated_at']])
    w.writerow([])
    w.writerow(['Headline'])
    for h in report['headline']:
        w.writerow([h['sign'], h['label'], f"{h['amount']:.2f}"])
    w.writerow([])
    w.writerow(['Invoice', 'Client', 'Billing period start', 'Billing period end', 'Issued', 'Due', 'Days overdue', 'Total', 'Paid', 'Balance',
                'Counted (ex VAT)', 'Cost', 'Profit', 'Line', 'Branch', 'Qty', 'Price', 'Cost per unit', 'Line profit', 'Line counted', 'Line cost counted'])
    for inv in report['sections']['revenue']['invoices']:
        base = [inv['number'], inv['client'], inv['period_start'], inv['period_end'], inv['issued'], inv['due'], inv['days_overdue'],
                inv['total'], inv['paid'], inv['balance'], inv['counted'], inv['cost'], inv['profit']]
        for ln in inv['lines'] or [None]:
            w.writerow(base + ([ln['description'], ln['branch'], ln['quantity'], ln['unit_price'], ln['cost_per_unit'], ln['profit'], ln['counted'], ln['counted_cost']] if ln else []))
    for r in report['sections']['revenue']['direct_sales']:
        w.writerow(['Till sale', r['label'], '', '', r['date'], '', '', '', '', '', r['amount']])
    for key in ('provider_costs', 'running_costs', 'payroll'):
        sec = report['sections'][key]
        w.writerow([])
        w.writerow([sec['label'], f"{sec['amount']:.2f}", sec['explain']])
        for r in sec['rows']:
            w.writerow([r.get('ref', ''), r.get('source') or r.get('label', ''), f"{r['amount']:.2f}"])
    w.writerow([])
    w.writerow(['Warnings'])
    for wn in report['warnings']:
        w.writerow([wn['title'], wn['detail']])
        for r in wn['rows']:
            w.writerow(['', r['ref'], r['label'], r.get('note', ''), f"{r['amount']:.2f}"])
    w.writerow([])
    w.writerow(['Client', 'Counted', 'Still owed', 'Cost', 'Profit', 'Overdue', 'Oldest due', 'Branch', 'Branch counted', 'Branch cost', 'Branch profit'])
    for c in report['clients']:
        w.writerow([c['client'], c['amount'], c['owed'], c['cost'], c['profit'], c['overdue'], c['oldest_due'] or ''])
        for b in c['branches']:
            w.writerow(['', '', '', '', '', '', '', b['branch'], b['amount'], b['cost'], b['profit']])
    return out.getvalue()
