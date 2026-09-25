"""Compact MultiWLT measurement report: overview, numbers, four acquired views."""
from pathlib import Path
import html


def write_report(result,output):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import landscape,A4
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import Paragraph,Table,TableStyle
    from reportlab.lib.styles import ParagraphStyle
    output=Path(output);pdf=output/'MultiWLT_Auswertung.pdf'
    width,height=landscape(A4);c=canvas.Canvas(str(pdf),pagesize=(width,height))
    c.setTitle('MultiWLT – Messbericht')
    style=ParagraphStyle('body',fontName='Helvetica',fontSize=9,leading=12,textColor=HexColor('#243357'))
    fmt=lambda value:'offen' if value is None else f'{value:.3f}'
    def paragraph(text,x,y,w):
        p=Paragraph(text,style);_,h=p.wrap(w,1000);p.drawOn(c,x,y-h);return y-h-8
    def header(title,page):
        c.setFillColor(HexColor('#243357'));c.rect(0,height-51,width,51,fill=1,stroke=0)
        c.setFillColorRGB(1,1,1);c.setFont('Helvetica-Bold',18);c.drawString(30,height-33,title)
        c.setFillColor(HexColor('#59667c'));c.setFont('Helvetica',8)
        c.drawString(30,17,('SYNTHETISCHE DEMO' if result.get('synthetic') else 'MultiWLT · Messbericht')+' · keine automatische Grenzwertfreigabe')
        c.drawRightString(width-30,17,str(page))
    def table(data,x,y,widths,rowheight=20):
        t=Table(data,colWidths=widths,rowHeights=rowheight)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),HexColor('#243357')),('TEXTCOLOR',(0,0),(-1,0),HexColor('#ffffff')),('FONTSIZE',(0,0),(-1,-1),9),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('ROWBACKGROUNDS',(0,1),(-1,-1),[HexColor('#f0f4f8'),HexColor('#ffffff')]),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
        _,h=t.wrap(sum(widths),y);t.drawOn(c,x,y-h);return y-h-8
    def card(x,y,w,label,value,detail):
        c.setFillColor(HexColor('#f0f4f8'));c.roundRect(x,y,w,83,6,fill=1,stroke=0)
        paragraph('<b>'+label+'</b>',x+12,y+72,w-24)
        c.setFillColor(HexColor('#243357'));c.setFont('Helvetica-Bold',25);c.drawString(x+12,y+29,value)
        paragraph(detail,x+12,y+19,w-24)
    header('MultiWLT | Ergebnisübersicht · sollkorrigiert',1)
    s=result.get('spheres',{});pooled=s.get('pooled_all_rays',{})
    sphere=output/'Strahlungs_Huellkugeln.png'
    if sphere.exists():c.drawImage(str(sphere),18,203,width=548,height=328,preserveAspectRatio=True,anchor='c')
    else:paragraph('Keine 3D-Auswertung verfügbar.',35,470,490)
    card(575,437,235,'Gesamtwert: zusätzlicher 2D-Versatz',fmt(result['max_extra_mm'])+' mm','Maximum über alle Kugeln und Bilder')
    diameter_label='Gemeinsamer Hüll-Durchmesser' if pooled.get('status')=='sphere_3d' else 'Gemeinsame Hülle: 3D nicht bestimmt'
    card(575,343,235,diameter_label,fmt(pooled.get('diameter_mm'))+' mm','Alle korrigierten Strahlgeraden')
    y=paragraph(f'<b>{result["valid_count"]} / {result["expected_count"]} Kugel–Feld-Paare</b><br/>'+html.escape(result.get('acquisition_mode','Aufnahmemodus: siehe Bildexport')),581,328,223)
    paragraph('<b>Auswertestatus:</b> '+('Feldmitten-Methode prüfen' if result.get('field_method_review') else 'vollständig' if result['valid_count']==result['expected_count'] else 'unvollständig'),581,y,223)
    data=[['Kugel / Strahlen','Hüll-Durchmesser / mm','3D-Restversatz* / mm','Max. Zusatz 2D / mm']]
    for b in s.get('per_ball',[]):data.append([b['id'],fmt(b.get('diameter_mm')),fmt(b.get('center_distance_mm')),fmt(b.get('max_2d_extra_mm'))])
    data.append(['Alle zusammen',fmt(pooled.get('diameter_mm')),fmt(pooled.get('center_distance_mm')),fmt(result['max_extra_mm'])])
    y=table(data,30,203,[150,200,230,200],19)
    y=paragraph('<b>Sollkorrektur bereits enthalten:</b> Der geplante Öffnungsversatz wurde je Bild vektoriell abgezogen. <b>*3D-Restversatz:</b> Abstand der berechneten Hüllmitte zum roten Kreuz (= jeweilige CT-Kugelmitte). Die Pfeile zeigen diesen verbleibenden Abstand. Für den gemeinsamen Fit sind alle CT-Kugelorte auf (0, 0, 0) gelegt.',30,y,780)
    if result.get('field_method_review'):
        hint=result['field_method_review'][0]
        im=next(im for im in result['images'] if im['beam_number']==hint['beam'])
        t=next(t for t in im['targets'] if t['id']==hint['ball'])
        paragraph(f'<b>Prüfhinweis:</b> {t["id"]} / G{im["gantry_deg"]:.0f}: Zusatzversatz {t["distance_mm"]:.3f} mm; Methodenunterschied der Feldmitte {hint["difference_mm"]:.3f} mm. Zwei verschiedene Größen; Erläuterung auf Seite 2.',30,y,780)
    c.showPage();header('MultiWLT | Messwerte und Auswertestatus',2)
    y=height-69
    y=paragraph('<b>Zusatzvektor = (Kugel − Feld)<sub>MV</sub> − (CT-Kugelprojektion − geplante Öffnungsmitte).</b> Erst nach der Subtraktion von X und Y wird der Abstand gebildet. 2D-Werte beziehen sich auf die Isozentrumsebene; die 3D-Hülle auf den lokalen CT-Kugelort.',30,y,780)
    rows=[['Gantry','Kugel','Soll X / Y (mm)','Ist X / Y (mm)','Zusatz X / Y (mm)','Zusatz / mm']]
    pair=lambda v:' / '.join(f'{x:+.3f}' for x in v)
    for im in result['images']:
        for t in im['targets']:
            valid=t['status']=='measured'
            rows.append([f'{im["gantry_deg"]:.0f}°',t['id'],pair(t['expected_mm']) if valid else '–',pair(t['measured_mm']) if valid else '–',pair(t['residual_mm']) if valid else '–',fmt(t.get('distance_mm'))])
    y=table(rows,30,y,[55,55,170,170,170,160],17)
    for hint in result.get('field_method_review',[]):
        im=next(im for im in result['images'] if im['beam_number']==hint['beam']);t=next(t for t in im['targets'] if t['id']==hint['ball'])
        y=paragraph(f'<b>{t["id"]} / Gantry {im["gantry_deg"]:.0f}°:</b> gemessener Zusatzversatz <b>{t["distance_mm"]:.3f} mm</b>. Davon getrennt: <b>{hint["difference_mm"]:.3f} mm</b> zwischen Flächenschwerpunkt (nur Suchhilfe) und gegenüberliegenden 50%-Kanten (verwendete Feldmitte). Das ist ein Methoden-Prüfhinweis, kein weiterer Kugelversatz und keine Unsicherheitsangabe.',30,y,780)
    y=paragraph('<b>Ergänzend: 3D-Restversatz nach Sollkorrektur.</b> Abstand der berechneten lokalen Isozentrumskugel-Mitte zum CT-Kugelort derselben Met. Der geometrisch erwartete Öffnungsversatz ist bereits abgezogen und wird nicht erneut korrigiert. Er misst eine Verschiebung der Hülle. Ihr Durchmesser beschreibt dagegen die Bündelung der Strahlgeraden um diese Mitte. Beides wird aus denselben gemessenen Richtungen bestimmt; verbleibende Lagerungsfehler bleiben enthalten.',30,y,780)
    y=paragraph('<b>Referenz:</b> '+html.escape(result['reference_note'])+'<br/><b>Positionierung:</b> bestätigte CT-Sollposition; Setup-Korrekturen nicht erneut auf die CT-Kugelorte anwenden. Kein Lagefit an die MV-Bilder.',30,y,780)
    paragraph('<b>Methode:</b> Kugeldetektion mit pylinac, Feldmitte aus 50%-Kanten; CT-Kugelorte aus Bilddaten. Ergebnisse gelten für die aufgenommenen Winkel. Bewertung / Freigabe: ____________________',30,y,780)
    for page,im in enumerate(result['images'],3):
        c.showPage();header(f'MultiWLT | Gantry {im["gantry_deg"]:.0f}° · Kollimator {im["collimator_deg"]:.0f}°',page)
        c.drawImage(str(output/im['figure']),18,42,width=width-36,height=height-104,preserveAspectRatio=True,anchor='c')
    c.save();result['pdf_file']=str(pdf)
    body=f'<h2>Ergebnisübersicht</h2><p><b>Maximaler zusätzlicher 2D-Versatz: {fmt(result["max_extra_mm"])} mm</b> · Gemeinsamer Hüll-Durchmesser: {fmt(pooled.get("diameter_mm"))} mm</p>'
    if sphere.exists():body+='<img src="Strahlungs_Huellkugeln.png" alt="Lokale Isozentrumskugeln und CT-Kugelmitten als Bezug">'
    body+='<p>3D-Restversatz nach Sollkorrektur = berechnete Hüllmitte zum jeweiligen CT-Kugelort. Der geplante Öffnungsversatz wurde schon vor der 3D-Berechnung abgezogen.</p>'
    for im in result['images']:body+=f'<h2>Gantry {im["gantry_deg"]:.0f}°</h2><img src="{im["figure"]}" alt="Soll- und Ist-Kugelmitten">'
    (output/'report.html').write_text(f'<!doctype html><html lang="de"><meta charset="utf-8"><title>MultiWLT Messbericht</title><style>body{{font:17px Arial;color:#243357;margin:32px;max-width:1300px}}img{{width:100%;max-width:1100px}}</style><h1>MultiWLT · Messbericht</h1><p><a href="MultiWLT_Auswertung.pdf">PDF</a> · <a href="results.csv">Messwerte</a></p>{body}</html>',encoding='utf-8')
    result['report_file']=str(output/'report.html')
