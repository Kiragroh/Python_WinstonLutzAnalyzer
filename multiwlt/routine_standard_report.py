"""Compact MultiWLT measurement report: overview, numbers, four acquired views."""
from pathlib import Path
import html


def write_report(result,output):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import landscape,A4
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import Paragraph,Table,TableStyle
    from reportlab.lib.styles import ParagraphStyle
    output=Path(output);pdf=output/'MultiWLT_Report.pdf'
    width,height=landscape(A4);c=canvas.Canvas(str(pdf),pagesize=(width,height))
    c.setTitle('MultiWLT – Measurement report')
    style=ParagraphStyle('body',fontName='Helvetica',fontSize=9,leading=12,textColor=HexColor('#243357'))
    fmt=lambda value:'not available' if value is None else f'{value:.3f}'
    def paragraph(text,x,y,w):
        p=Paragraph(text,style);_,h=p.wrap(w,1000);p.drawOn(c,x,y-h);return y-h-8
    def header(title,page):
        c.setFillColor(HexColor('#243357'));c.rect(0,height-51,width,51,fill=1,stroke=0)
        c.setFillColorRGB(1,1,1);c.setFont('Helvetica-Bold',18);c.drawString(30,height-33,title)
        c.setFillColor(HexColor('#59667c'));c.setFont('Helvetica',8)
        c.drawString(30,17,('SYNTHETIC DEMO' if result.get('synthetic') else 'MultiWLT · Measurement report')+' · no automatic clinical acceptance decision')
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
    header('MultiWLT | Results after expected-offset correction',1)
    s=result.get('spheres',{});pooled=s.get('pooled_all_rays',{})
    sphere=output/'Ray_Envelopes.png'
    if sphere.exists():c.drawImage(str(sphere),18,203,width=548,height=328,preserveAspectRatio=True,anchor='c')
    else:paragraph('No 3D result available.',35,470,490)
    card(575,437,235,'Overall: maximum extra 2D displacement',fmt(result['max_extra_mm'])+' mm','Maximum across all balls and images')
    diameter_label='Pooled envelope diameter' if pooled.get('status')=='sphere_3d' else 'Pooled envelope: 3D unavailable'
    card(575,343,235,diameter_label,fmt(pooled.get('diameter_mm'))+' mm','All corrected rays')
    y=paragraph(f'<b>{result["valid_count"]} / {result["expected_count"]} ball–field pairs</b><br/>'+html.escape(result.get('acquisition_mode','Acquisition mode: see image export')),581,328,223)
    paragraph('<b>Analysis status:</b> '+('Review field-centre method' if result.get('field_method_review') else 'complete' if result['valid_count']==result['expected_count'] else 'incomplete'),581,y,223)
    data=[['Ball / rays','Envelope diameter / mm','Remaining 3D offset* / mm','Max. extra 2D / mm']]
    for b in s.get('per_ball',[]):data.append([b['id'],fmt(b.get('diameter_mm')),fmt(b.get('center_distance_mm')),fmt(b.get('max_2d_extra_mm'))])
    data.append(['All rays pooled',fmt(pooled.get('diameter_mm')),fmt(pooled.get('center_distance_mm')),fmt(result['max_extra_mm'])])
    y=table(data,30,203,[150,200,230,200],19)
    y=paragraph('<b>Expected offsets already removed:</b> The planned aperture offset was subtracted as a vector in each image. <b>*Remaining 3D offset:</b> Distance from the fitted envelope centre to the red cross (= the corresponding CT ball centre). Arrows show this residual distance. For the pooled fit, each CT ball centre is translated to (0, 0, 0).',30,y,780)
    if result.get('field_method_review'):
        hint=result['field_method_review'][0]
        im=next(im for im in result['images'] if im['beam_number']==hint['beam'])
        t=next(t for t in im['targets'] if t['id']==hint['ball'])
        paragraph(f'<b>Review note:</b> {t["id"]} / G{im["gantry_deg"]:.0f}: Extra displacement {t["distance_mm"]:.3f} mm; field-centre method difference {hint["difference_mm"]:.3f} mm. Two different quantities; explained on page 2.',30,y,780)
    c.showPage();header('MultiWLT | Measurements and analysis status',2)
    y=height-69
    y=paragraph('<b>Extra vector = (ball − field)<sub>MV</sub> − (CT ball projection − planned aperture centre).</b> Subtract X and Y components before calculating the magnitude. 2D values are at the isocentre plane; the 3D envelope uses the local CT ball position.',30,y,780)
    rows=[['Gantry','Ball','Expected X / Y (mm)','Observed X / Y (mm)','Extra X / Y (mm)','Extra / mm']]
    pair=lambda v:' / '.join(f'{x:+.3f}' for x in v)
    for im in result['images']:
        for t in im['targets']:
            valid=t['status']=='measured'
            rows.append([f'{im["gantry_deg"]:.0f}°',t['id'],pair(t['expected_mm']) if valid else '–',pair(t['measured_mm']) if valid else '–',pair(t['residual_mm']) if valid else '–',fmt(t.get('distance_mm'))])
    y=table(rows,30,y,[55,55,170,170,170,160],17)
    for hint in result.get('field_method_review',[]):
        im=next(im for im in result['images'] if im['beam_number']==hint['beam']);t=next(t for t in im['targets'] if t['id']==hint['ball'])
        y=paragraph(f'<b>{t["id"]} / Gantry {im["gantry_deg"]:.0f}°:</b> measured extra displacement <b>{t["distance_mm"]:.3f} mm</b>. Separately: <b>{hint["difference_mm"]:.3f} mm</b> between the area centroid (search aid only) and opposing 50% edges (field centre used). This flags a method comparison; it is not another ball displacement or an uncertainty estimate.',30,y,780)
    y=paragraph('<b>Supplementary: remaining 3D offset after expected-offset correction.</b> Distance from the fitted local isocentre sphere centre to the CT ball centre of the same target. The expected aperture offset has already been removed; do not subtract it again. This describes the displacement of the envelope, whereas its diameter describes the spread of rays around that centre. Both use the same measured directions; residual positioning errors remain included.',30,y,780)
    y=paragraph('<b>Reference:</b> '+html.escape(result['reference_note'])+'<br/><b>Positioning:</b> confirmed CT reference pose; do not apply setup corrections to the CT ball positions again. No pose fit to the MV images.',30,y,780)
    paragraph('<b>Method:</b> pylinac ball detection, field centre from 50% edges; CT ball centres from image data. Results apply to the acquired angles. Review / sign-off: ____________________',30,y,780)
    for page,im in enumerate(result['images'],3):
        c.showPage();header(f'MultiWLT | Gantry {im["gantry_deg"]:.0f}° · Collimator {im["collimator_deg"]:.0f}°',page)
        c.drawImage(str(output/im['figure']),18,42,width=width-36,height=height-104,preserveAspectRatio=True,anchor='c')
    c.save();result['pdf_file']=str(pdf)
    body=f'<h2>Results overview</h2><p><b>Maximum extra 2D displacement: {fmt(result["max_extra_mm"])} mm</b> · Pooled envelope diameter: {fmt(pooled.get("diameter_mm"))} mm</p>'
    if sphere.exists():body+='<img src="Ray_Envelopes.png" alt="Local isocentre spheres referenced to CT ball centres">'
    body+='<p>Remaining 3D offset = fitted envelope centre relative to the corresponding CT ball centre. The expected aperture offset was subtracted before the 3D calculation.</p>'
    for im in result['images']:body+=f'<h2>Gantry {im["gantry_deg"]:.0f}°</h2><img src="{im["figure"]}" alt="Expected and observed ball centres">'
    (output/'report.html').write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><title>MultiWLT measurement report</title><style>body{{font:17px Arial;color:#243357;margin:32px;max-width:1300px}}img{{width:100%;max-width:1100px}}</style><h1>MultiWLT · Measurement report</h1><p><a href="MultiWLT_Report.pdf">PDF</a> · <a href="results.csv">Measurements</a></p>{body}</html>',encoding='utf-8')
    result['report_file']=str(output/'report.html')
