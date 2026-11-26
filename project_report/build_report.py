from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PIL import Image, ImageDraw, ImageFont
import textwrap

ROOT = Path(__file__).resolve().parent
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)
OUT = ROOT / "NODAL_Project_Report_Editable.docx"

def font(size=22, bold=False):
    candidates = ["C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf"]
    try: return ImageFont.truetype(candidates[1 if bold else 0], size)
    except OSError: return ImageFont.load_default()

def diagram(name, title, nodes, arrows, width=1500, height=760):
    im = Image.new("RGB", (width, height), "white"); d = ImageDraw.Draw(im)
    d.text((width//2, 28), title, fill="#263F35", font=font(34, True), anchor="ma")
    boxes={}
    for key,label,x,y,w,h in nodes:
        boxes[key]=(x,y,w,h)
        d.rounded_rectangle((x,y,x+w,y+h), radius=18, fill="#F4F0E7", outline="#263F35", width=3)
        lines=textwrap.wrap(label, width=max(12,int(w/17)))
        yy=y+h//2-(len(lines)*31)//2
        for line in lines:
            d.text((x+w//2,yy),line,fill="#343A40",font=font(22),anchor="mm"); yy+=31
    for a,b,label in arrows:
        ax,ay,aw,ah=boxes[a]; bx,by,bw,bh=boxes[b]
        p1=(ax+aw,ay+ah//2) if bx>ax else (ax+aw//2,ay+ah)
        p2=(bx,by+bh//2) if bx>ax else (bx+bw//2,by)
        d.line((p1,p2),fill="#D97757",width=5)
        import math
        angle=math.atan2(p2[1]-p1[1],p2[0]-p1[0]); L=18
        q1=(p2[0]-L*math.cos(angle-.45),p2[1]-L*math.sin(angle-.45)); q2=(p2[0]-L*math.cos(angle+.45),p2[1]-L*math.sin(angle+.45))
        d.polygon([p2,q1,q2],fill="#D97757")
        if label: d.text(((p1[0]+p2[0])//2,(p1[1]+p2[1])//2-18),label,fill="#343A40",font=font(17),anchor="mm")
    path=FIG/f"{name}.png"; im.save(path); return path

diagrams={}
diagrams['arch']=diagram('system_architecture','NODAL System Architecture',[
('cit','Citizen / Official / Administrator',40,260,250,110),('web','React 19 + Vite\nLeaflet UI',365,260,250,110),('api','Flask application\nAPI + authorization',700,260,260,110),('db','MongoDB\nusers, complaints, departments',1080,100,340,110),('ev','Evidence store\nfilesystem outside MongoDB',1080,400,340,110),('ml','Vision service\nImageNet demo / optional civic artifacts',700,520,300,110)],
[('cit','web','HTTPS/JSON'),('web','api','session + CSRF'),('api','db','PyMongo'),('api','ev','protected file I/O'),('web','ml','multipart prediction')])
diagrams['flow']=diagram('complaint_lifecycle','Complaint Lifecycle and Review',[
('submit','Citizen submits\ncategory, description, location',40,300,270,120),('suggest','System suggests department\n(status remains submitted)',390,300,290,120),('assign','Admin assigns department\nand optional verified official',760,300,310,120),('work','Official updates\nin progress + notes',1150,300,280,120),('review','Resolution submitted\nnotes + evidence references',1150,540,280,110),('decision','Admin reviews\napprove or return for work',760,540,310,110),('done','Resolved or returned\nCitizen may dispute',390,540,290,110)],
[('submit','suggest',''),('suggest','assign',''),('assign','work',''),('work','review',''),('review','decision',''),('decision','done','')])
diagrams['routing']=diagram('department_routing','Department Suggestion and Assignment',[
('cat','Complaint category',60,310,240,100),('map','Active category map\nfrom department registry',390,310,300,100),('sug','Suggested department\nrecorded separately',800,160,300,100),('unmap','Unmapped category\nadmin review queue',800,470,300,100),('admin','Admin chooses active\ndepartment + reason',1200,310,260,100)],
[('cat','map',''),('map','sug','mapped'),('map','unmap','unmapped'),('sug','admin','override possible'),('unmap','admin','')])
diagrams['geo']=diagram('geo_architecture','Geographic Intelligence Data Flow',[
('raw','Stored complaint points\nGeoJSON [longitude, latitude]',40,300,300,110),('valid','Shared validator\nfinite + geographic ranges',410,300,300,110),('scope','Approved versioned region\nPolygon / MultiPolygon',780,120,330,110),('filter','Point-in-polygon filter\nPython current implementation',780,480,330,110),('agg','Aggregate counts + hotspots\nminimum-size suppression',1190,300,280,110)],
[('raw','valid',''),('valid','scope','region lookup'),('valid','filter','valid points'),('scope','filter','boundary'),('filter','agg','')])
diagrams['roles']=diagram('role_access','Role-Based Access Boundaries',[
('cit','Citizen\nOwn complaints only',70,150,270,120),('off','Verified active official\nAssigned or authorized department',70,350,300,130),('adm','Administrator\nManagement and review',70,570,270,110),('gate','Flask session, CSRF,\nrole + object authorization',540,340,350,150),('res','Complaint / evidence /\nadmin routes',1100,340,330,150)],
[('cit','gate',''),('off','gate',''),('adm','gate',''),('gate','res','allow or deny')])
diagrams['usecases']=diagram('use_case_model','Primary NODAL Use Cases',[
('cit','Citizen actor',35,210,220,100),('off','Verified official actor',35,400,240,100),('adm','Administrator actor',35,590,220,100),('uc1','Register, submit report,\ntrack, dispute',430,140,330,105),('uc2','Request official access',430,280,330,95),('uc3','View authorized work,\nupdate progress, submit resolution',850,300,360,115),('uc4','Verify access, assign work,\nreview resolution, manage departments',850,540,390,120)],
[('cit','uc1',''),('cit','uc2',''),('off','uc3',''),('adm','uc4','')])
diagrams['swimlane']=diagram('complaint_swimlane','Complaint Workflow Swimlanes',[
('c1','CITIZEN\nSubmit report',40,150,280,95),('c2','CITIZEN\nTrack / dispute',1100,150,280,95),('b1','SYSTEM\nValidate + suggest department',390,330,320,105),('b2','SYSTEM\nEnforce role and transition rules',820,330,330,105),('a1','ADMIN\nAssign department / official',390,540,320,105),('o1','VERIFIED OFFICIAL\nProgress + resolution submission',820,540,350,105)],
[('c1','b1',''),('b1','a1','mapped or review'),('a1','o1','authorized assignment'),('o1','b2','submitted action'),('b2','c2','history visible')])

doc=Document(); sec=doc.sections[0]
sec.top_margin=Inches(.78); sec.bottom_margin=Inches(.72); sec.left_margin=Inches(1); sec.right_margin=Inches(1)
sec.header_distance=Inches(.35); sec.footer_distance=Inches(.35)
styles=doc.styles
for s in ['Normal','Body Text']:
 st=styles[s]; st.font.name='Times New Roman'; st._element.rPr.rFonts.set(qn('w:eastAsia'),'Times New Roman'); st.font.size=Pt(11.5); st.paragraph_format.line_spacing=1.15; st.paragraph_format.space_after=Pt(6); st.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY
for name,size,color in [('Title',22,'263F35'),('Heading 1',16,'263F35'),('Heading 2',13,'263F35'),('Heading 3',11.5,'343A40')]:
 st=styles[name]; st.font.name='Times New Roman'; st._element.rPr.rFonts.set(qn('w:eastAsia'),'Times New Roman'); st.font.size=Pt(size); st.font.bold=True; st.font.color.rgb=RGBColor.from_string(color); st.paragraph_format.keep_with_next=True; st.paragraph_format.space_before=Pt(10); st.paragraph_format.space_after=Pt(5)

def page_num(p):
 fld=OxmlElement('w:fldSimple'); fld.set(qn('w:instr'),'PAGE'); p._p.append(fld)
header=sec.header.paragraphs[0]; header.alignment=WD_ALIGN_PARAGRAPH.CENTER
r=header.add_run('NODAL  |  ACADEMIC PROJECT REPORT'); r.font.name='Times New Roman'; r.font.size=Pt(9); r.font.color.rgb=RGBColor(100,100,100)
footer=sec.footer.paragraphs[0]; footer.alignment=WD_ALIGN_PARAGRAPH.CENTER; page_num(footer)

def p(txt='',boldlead=None,align=None,italic=False):
 para=doc.add_paragraph();
 if align is not None: para.alignment=align
 if boldlead and txt.startswith(boldlead):
  para.add_run(boldlead).bold=True; para.add_run(txt[len(boldlead):])
 else:
  run=para.add_run(txt); run.italic=italic
 return para
def h(txt,level=1): doc.add_heading(txt,level=level)
def bullet(txt): doc.add_paragraph(txt,style='List Bullet')
def numbered(txt): doc.add_paragraph(txt,style='List Number')
def caption(txt):
 para=doc.add_paragraph(); para.alignment=WD_ALIGN_PARAGRAPH.CENTER; para.paragraph_format.space_before=Pt(2); para.paragraph_format.space_after=Pt(8); r=para.add_run(txt); r.italic=True; r.font.size=Pt(10)
def table(headers,rows,widths=None,fontsize=9):
 t=doc.add_table(rows=1,cols=len(headers)); t.alignment=WD_TABLE_ALIGNMENT.CENTER; t.style='Table Grid'
 for i,x in enumerate(headers):
  c=t.rows[0].cells[i]; c.text=str(x); c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
  sh=OxmlElement('w:shd'); sh.set(qn('w:fill'),'263F35'); c._tc.get_or_add_tcPr().append(sh)
  for rr in c.paragraphs[0].runs: rr.font.bold=True; rr.font.color.rgb=RGBColor(255,255,255); rr.font.size=Pt(fontsize)
 for row in rows:
  cells=t.add_row().cells
  for i,x in enumerate(row):
   cells[i].text=str(x); cells[i].vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
   for para in cells[i].paragraphs:
    para.paragraph_format.space_after=Pt(2); para.paragraph_format.line_spacing=1.0
    for rr in para.runs: rr.font.size=Pt(fontsize)
 if widths:
  for row in t.rows:
   for i,w in enumerate(widths): row.cells[i].width=Inches(w)
 doc.add_paragraph().paragraph_format.space_after=Pt(2)
 return t
def figure(key,cap,width=6.25):
 para=doc.add_paragraph(); para.alignment=WD_ALIGN_PARAGRAPH.CENTER; para.add_run().add_picture(str(diagrams[key]),width=Inches(width)); caption(cap)
def chapter(n,title):
 doc.add_page_break(); q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; q.paragraph_format.space_before=Pt(130); r=q.add_run(f'CHAPTER {n}'); r.bold=True; r.font.size=Pt(18); r.font.color.rgb=RGBColor.from_string('263F35')
 q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=q.add_run(title.upper()); r.bold=True; r.font.size=Pt(18); r.font.color.rgb=RGBColor.from_string('263F35'); doc.add_page_break()

# Cover
for _ in range(2): doc.add_paragraph()
q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=q.add_run('M S RAMAIAH INSTITUTE OF TECHNOLOGY'); r.bold=True; r.font.size=Pt(16)
p('Bengaluru, Karnataka',align=WD_ALIGN_PARAGRAPH.CENTER)
p('Department of Artificial Intelligence and Machine Learning',align=WD_ALIGN_PARAGRAPH.CENTER)
for _ in range(2): doc.add_paragraph()
q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=q.add_run('PROJECT REPORT'); r.bold=True; r.font.size=Pt(18); r.font.color.rgb=RGBColor.from_string('263F35')
q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=q.add_run('NODAL'); r.bold=True; r.font.size=Pt(30); r.font.color.rgb=RGBColor.from_string('263F35')
q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; q.paragraph_format.left_indent=Inches(.7); q.paragraph_format.right_indent=Inches(.7); r=q.add_run('An AI-Assisted Public Infrastructure Intelligence and Civic Complaint Management Platform'); r.bold=True; r.font.size=Pt(16)
p('“Connecting the systems that matter.”',align=WD_ALIGN_PARAGRAPH.CENTER,italic=True)
for _ in range(2): doc.add_paragraph()
p('Submitted in partial fulfilment of the requirements for the degree of',align=WD_ALIGN_PARAGRAPH.CENTER)
q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=q.add_run('BACHELOR OF ENGINEERING'); r.bold=True
p('in Artificial Intelligence and Machine Learning',align=WD_ALIGN_PARAGRAPH.CENTER)
table(['Project role','Name','USN'],[
['Project Coordinator','[TEAM MEMBER 1]','[USN 1]'],['Frontend Developer','[TEAM MEMBER 2]','[USN 2]'],['Backend Developer','[TEAM MEMBER 3]','[USN 3]'],['AI/ML and Testing','[TEAM MEMBER 4]','[USN 4]']],fontsize=10)
p('Project Guide: [GUIDE NAME]  |  [DESIGNATION]',align=WD_ALIGN_PARAGRAPH.CENTER)
p('Academic Year: [ACADEMIC YEAR]  |  Submission Date: [DATE]',align=WD_ALIGN_PARAGRAPH.CENTER)
doc.add_page_break()

# Certificate / declaration / acknowledgement / abstract / contents
h('CERTIFICATE',1)
p('This is to certify that the project report entitled “NODAL: An AI-Assisted Public Infrastructure Intelligence and Civic Complaint Management Platform” is a record of work prepared for the Bachelor of Engineering in Artificial Intelligence and Machine Learning at M S Ramaiah Institute of Technology, Bengaluru. The report describes the implementation evidenced in the project repository as inspected for this document. Student names, USNs, guide details, academic year and submission date remain editable placeholders and must be completed and approved by the institution before submission.')
p('Project Guide: [GUIDE NAME]                         Head of Department: [HOD NAME]')
p('Signature: _______________________                   Signature: _______________________')
p('Date: [DATE]                                              Place: Bengaluru')
doc.add_page_break(); h('DECLARATION',1)
p('We declare that this report is prepared for academic documentation of the NODAL repository and that implementation claims are based on source code, tests and project documentation inspected for this report. Any limitations, planned features, synthetic records and unverified results are identified as such. No real-world accuracy claim is made for a civic image classifier, and no government integration is claimed.')
p('Names and signatures: [TEAM MEMBER 1–4]')
p('Date: [DATE]                                               Place: Bengaluru')
doc.add_page_break(); h('ACKNOWLEDGEMENT',1)
p('The project team gratefully acknowledges the guidance of [GUIDE NAME], [DESIGNATION], and the support of the Department of Artificial Intelligence and Machine Learning at M S Ramaiah Institute of Technology. The team also acknowledges the open technical documentation and research publications cited in this report. The acknowledgements must be reviewed and personalized by the authors before formal submission.')
doc.add_page_break(); h('ABSTRACT',1)
p('NODAL is a web-based platform intended to connect citizens, public-infrastructure work teams and administrators through a traceable complaint lifecycle. Its repository contains a React single-page interface, a Flask API, MongoDB persistence, protected image evidence storage, role-scoped access controls, department suggestions and assignment workflows, map views, hotspot aggregation, a versioned geographic-region registry, and an optional image-analysis service. Bengaluru is described as the initial pilot, while the user-facing platform is positioned for Indian cities more broadly.')
p('Citizens can register as citizens, submit a category, description and location, optionally attach image evidence, and track their own records. The backend stores GeoJSON points in longitude-latitude order, suggests a department from configurable category mappings, and leaves actual assignment to an authorized administrator. Verified officials may work on complaints within individual or department scope; administrators review assignments, official access requests and submitted resolutions. Evidence is stored outside MongoDB and retrieved through permission-checked endpoints. Public overview and hotspot responses aggregate data without returning individual complaint identifiers.')
p('Image assistance currently uses a generic MobileNetV2 ImageNet demonstration. It is explicitly not a trained civic-issue classifier. A separate training pipeline is present, but the repository contains no curated civic training dataset or trained civic model artifacts. Geographic regional APIs are implemented, but the Greater Bengaluru Area remains a draft with no approved boundary, so no GBA-specific intelligence is available. Automated test suites passed during report preparation; these results are not substitutes for production integration, independently verified officials, curated-model evaluation or field validation.')
p('The report documents architecture, requirements, management, design, implementation, test evidence, limitations and future work. Team and guide identity fields remain placeholders because the repository does not establish them.')
h('Keywords',2); p('Civic technology, complaint lifecycle, role-based access control, department routing, geospatial analysis, GeoJSON, hotspot clustering, MobileNetV2, Flask, React, MongoDB.')
doc.add_page_break(); h('TABLE OF CONTENTS',1)
toc=[('Front Matter','Certificate, Declaration, Acknowledgement, Abstract, Lists','2–8'),('1','Introduction','9'),('2','Project Organization','12'),('3','Literature Survey','15'),('4','Project Management Plan','18'),('5','Software Requirement Specifications','21'),('6','Design','27'),('7','Implementation','32'),('8','Testing','37'),('9','Results and Performance Analysis','40'),('10','Conclusion and Scope for Future Work','43'),('11','References','45'),('12','Appendix','47')]
table(['Section','Title','Page'],toc,widths=[1.0,4.8,.7],fontsize=9)
p('Page numbers correspond to the accompanying PDF export. Repaginate and update this table after substantial edits in Word.',italic=True)
doc.add_page_break(); h('LIST OF FIGURES',1)
for x in ['Figure 2.1 Role-based authorization boundary','Figure 5.1 Complaint activity','Figure 5.2 Use-case model','Figure 5.3 Complaint workflow swimlanes','Figure 6.1 System architecture','Figure 6.2 Role-based access boundaries','Figure 6.3 Complaint lifecycle and review','Figure 6.4 Department suggestion and assignment','Figure 6.5 Geographic intelligence data flow','Figure 9.1 Landing-page hero asset (illustrative asset, not a runtime screenshot)','Figure 9.2–9.8 Runtime screenshot placeholders (to be captured from a verified local environment)'] : p(x)
doc.add_page_break(); h('LIST OF TABLES',1)
for x in ['Table 2.1 Project roles','Table 3.1 Comparison of related approaches','Table 4.1 Illustrative project stages','Table 4.2 Risk register','Table 5.1 External interfaces','Table 5.2 Functional requirements','Table 5.3 Non-functional requirements','Table 5.4 Use-case summaries','Table 7.1 Important API groups','Table 8.1 Automated test summary','Table 8.2 Representative test cases','Table 9.1 Evidence and performance limits','Table 12.1 Environment and operational checklist'] : p(x)

# Chapter 1
chapter(1,'Introduction')
h('1.1 General Introduction',2)
p('Public infrastructure services involve many actors, places and operational hand-offs. A citizen may observe a damaged road, waste accumulation, a blocked drain, water leakage or a failed streetlight, yet the report can be difficult to route, track and verify. NODAL is designed as a digital coordination layer: it records a report with structured information, provides role-specific views, routes categories toward suggested departments, and preserves status and assignment history. The word “intelligence” in the platform name refers to organizing and aggregating available platform records; it should not be read as evidence of a live government feed or validated prediction system.')
p('The application is developed as an India-wide concept with Bengaluru as the initial pilot context. This distinction matters in the implementation: the landing page includes several selectable map centres, but this control changes the geographic camera only. The current platform-wide public overview and hotspot APIs are not city-filtered. The Greater Bengaluru Area boundary registry entry is a draft without geometry or approval. Therefore, a Bengaluru map view does not establish that every visible statistic belongs to Bengaluru.')
h('1.2 Problem Statement',2)
p('A complaint channel needs more than a submission form. It must preserve ownership and privacy, distinguish a suggested route from an authorized assignment, support staff work without granting public privileges, and make resolution review accountable. Legacy records may be incomplete or unverified, images may contain sensitive details, and coordinates may be invalid. A trustworthy platform must represent these states honestly rather than hide uncertainty or infer missing facts.')
p('NODAL addresses this software problem through an auditable lifecycle and role-based portal design. It does not itself establish governmental authority, prove a report is true, guarantee a response time, or replace official grievance channels. Those are governance and operational matters beyond the current repository implementation.')
h('1.3 Objectives of the Project',2)
for x in ['Provide citizen registration, session-based login and personal complaint tracking.','Collect complaint category, description, location and optional image evidence.','Suggest a department from administrator-managed category mappings while keeping assignment as a separate authorized action.','Allow independently verified officials to work only within their authorized assignment or department scope.','Require administrator review for resolution outcomes and preserve history.','Offer platform-wide map and hotspot summaries without leaking individual complaint data.','Establish a versioned region registry so future geographic analytics depend on approved boundaries.','Document operational safety, deployment configuration and test limitations accurately.']: bullet(x)
h('1.4 Project Deliverables',2)
p('The repository delivers frontend and backend source, API services, tests, local startup scripts, deployment and workflow documentation, a vision training pipeline, and geographic registry code. The actual deliverable is source code rather than a deployed government service. No live department integration, verified public department contact directory, approved GBA boundary, production-trained civic vision model, or guaranteed service-level estimate is present in the inspected repository.')
h('1.5 Current Scope',2)
p('The implemented scope includes authentication, complaint creation and role-scoped retrieval, controlled status changes, department registry and routing, official access requests and administrator-led verification, evidence storage, citizen/official/admin portal interfaces, map selection, public platform-wide aggregates, regional API foundations and audit-mode database safeguards. Testing infrastructure includes backend unit tests, vision pipeline tests, frontend lint and production build scripts. The current report uses source and test evidence rather than asserting an active production deployment.')
h('1.6 Future Scope',2)
p('Future work can include obtaining and licensing authoritative administrative boundaries; enabling a validated region-level query plan; curating consented, balanced and independently labeled civic images; model evaluation under field conditions; accessible multilingual reporting; and operational agreements with participating authorities. Each requires separate legal, data, security and governance approval.')

# Chapter 2
chapter(2,'Project Organization')
h('2.1 Software Process Models',2)
p('The implementation history is organized into approval-gated phases: authentication and access control, complaint lifecycle and routing, image-assisted reporting, role portals, department routing, citizen and official/admin portal refinement, integration audits, deployment safety, frontend redesign, and geographic intelligence. This resembles an incremental and risk-driven process. Each phase narrows scope, preserves previously working functionality, and requires a review or audit before the next phase. It is not possible to infer a formal Scrum cadence, sprint velocity or project calendar from the repository; the schedule in Chapter 4 is consequently an editable planning template rather than a retrospective claim.')
p('Incremental delivery is appropriate because permissions, evidence, lifecycle transitions and geographic aggregation have cross-cutting risk. A change to a visual component must not silently loosen an API permission check. A new boundary must not silently reclassify old complaints. A model prediction must not submit or resolve a report. These constraints motivate small changes, tests at service boundaries, and explicit user approval gates.')
h('2.2 Roles and Responsibilities',2)
table(['Role','Responsibility represented in project','Editable identity'],[
['Project Coordinator','Coordinate scope, documentation and review','[TEAM MEMBER 1] / [USN 1]'],['Frontend Developer','React portals, forms, maps and responsive styling','[TEAM MEMBER 2] / [USN 2]'],['Backend Developer','Flask APIs, MongoDB access, lifecycle and authorization','[TEAM MEMBER 3] / [USN 3]'],['AI/ML and Testing','Vision pipeline, data checks and test evidence','[TEAM MEMBER 4] / [USN 4]'],['Project Guide','Academic supervision and approval','[GUIDE NAME] / [DESIGNATION]']],fontsize=9)
p('These are role placeholders supplied in the report brief. They are not repository-derived identities. The project team must replace placeholders and confirm actual contribution attribution before submission.')
h('2.3 Stakeholders and Operational Roles',2)
p('The product model distinguishes citizens, independently verified officials, and administrators. Citizens own their submissions and may dispute an incorrect resolution. Officials receive work only through department and/or individual assignment rules. Administrators configure departments, review access requests, assign work and decide resolution submissions. A synthetic demonstration identity is not a verified public official, and a demonstration complaint is not a verified civic report.')
figure('roles','Figure 2.1 Role-based authorization boundary')

# Chapter 3
chapter(3,'Literature Survey')
h('3.1 Introduction',2)
p('NODAL combines established ideas from digital grievance handling, geospatial information systems, access control, image classification and density-based spatial clustering. This literature survey provides technical context; it does not claim that the repository implements every approach at research-grade scale. The sources below are identifiable publications or official documentation, and each is listed in Chapter 11.')
h('3.2 Related Works',2)
h('3.2.1 Smart-city platforms and citizen participation',3)
p('Smart-city literature treats digital systems as socio-technical arrangements rather than technology alone. Participation quality depends on institutional response, transparency, accessibility and trust. NODAL implements a record lifecycle and role-specific interfaces, but the repository does not establish a formal municipal partnership or measure participation outcomes. Public grievance platforms such as India’s CPGRAMS provide a national context for structured submission and tracking; NODAL is not integrated with CPGRAMS and should not be represented as an official government channel.')
h('3.2.2 GIS and spatial complaint management',3)
p('GeoJSON standardizes spatial objects and defines geographic coordinates in longitude-latitude order. MongoDB provides geospatial indexes and query operators such as $geoWithin. NODAL stores complaint points as GeoJSON Point objects and creates a 2dsphere index. Its regional filtering helper currently validates and filters records in application code, which provides explicit handling of malformed legacy coordinates but has linear-scan cost. The region-aware API must use approved geometry and preserve data-quality semantics before adopting an indexed query optimization.')
h('3.2.3 Image classification and transfer learning',3)
p('MobileNetV2 uses inverted residual blocks and linear bottlenecks to support efficient convolutional inference. Keras exposes a MobileNetV2 preprocessing function that scales image values to the range expected by pretrained weights. In NODAL, the user-facing image predictor is a general ImageNet demonstration. ImageNet labels describe broad object categories and are not equivalent to road damage, drainage failure or other civic labels. The separate civic training pipeline includes dataset preparation and threshold configuration, but no curated dataset/model artifact was present in the inspected repository.')
h('3.2.4 Hotspot detection',3)
p('DBSCAN groups points by density and labels sparse points as noise. The NODAL hotspot implementation converts valid coordinates to the order required by haversine distance, uses a distance radius of 0.4 km and minimum cluster size of five, and reports cluster-level aggregates. The outputs are coarsened and omit complaint identifiers. These measures reduce direct exposure but do not constitute formal anonymity or prevent all inference from repeated queries and auxiliary data.')
h('3.2.5 Authorization and web security',3)
p('Role-based authorization is strengthened when identity, role, account state, object ownership and organizational scope are checked on the server. NODAL uses cookie sessions, CSRF tokens for mutating requests, explicit role decorators and additional verification requirements for officials. Public registration creates citizens; the official workflow requires an administrator decision and verification evidence. The frontend controls presentation, but the backend is the authority for permitted operations.')
h('3.3 Comparison of Existing Approaches',2)
table(['Area','Common system pattern','NODAL implementation','Limit'],[
['Grievance intake','Unstructured portal/email','Structured category, description, location and optional evidence','No verified authority integration'],['Routing','Manual department hand-off','Category-based suggested department plus admin assignment','Mapping is prototype/configurable, not government-verified'],['Image AI','Task-specific labeled classifier','ImageNet demo; optional civic pipeline code','No trained civic artifact or accuracy evidence'],['Map intelligence','Individual markers or regional aggregates','Leaflet maps and privacy-oriented hotspot aggregates','Public APIs remain platform-wide unless approved region exists'],['Workflow','Status field only','Controlled transitions and append-only histories','Operational workflow still needs participating departments'],['Identity','Public registration','Citizen registration; official verification by admin','No external identity proofing integration']],fontsize=8)
h('3.4 Conclusion of Survey',2)
p('The literature supports a modular design in which identity, workflow, geospatial data and model inference are separate concerns. NODAL’s strongest implementation choices are the separation of suggested and actual assignment, server-enforced scopes, protected evidence references, conservative treatment of unverified boundaries, and explicit labeling of generic vision. The principal research and operational gaps are real-world validation, boundary evidence, privacy evaluation beyond simple suppression, and verified institutional participation.')

# Chapter 4
chapter(4,'Project Management Plan')
h('4.1 Schedule of the Project',2)
p('The following stage sequence summarizes the project architecture and is intended as an editable planning view. Repository content confirms that the implementation was developed incrementally, but it does not establish dates or durations. Replace the relative stage labels with the team’s verified academic schedule.')
table(['Stage','Work package','Evidence/deliverable','Timing'],[
['A','Foundation and authentication','Session, CSRF, roles, authorization tests','[WEEK / DATE]'],['B','Complaint lifecycle and department routing','Transitions, assignment history, registry APIs','[WEEK / DATE]'],['C','Image-assisted reporting and evidence','Upload, protected retrieval, ImageNet demo','[WEEK / DATE]'],['D','Citizen, official and admin portals','Role-specific React workspaces','[WEEK / DATE]'],['E','Integration audits and remediation','API/browser audit evidence and fixes','[WEEK / DATE]'],['F','Production readiness','WSGI, safe CLI/configuration, documentation','[WEEK / DATE]'],['G','Frontend refinement and geography','Design refinements, region registry and APIs','[WEEK / DATE]']],fontsize=8)
gantt=doc.add_table(rows=1,cols=8); gantt.style='Table Grid'; gantt.alignment=WD_TABLE_ALIGNMENT.CENTER
for i,x in enumerate(['Stage','1','2','3','4','5','6','7']): gantt.rows[0].cells[i].text=x
for label,start,end in [('Foundation',1,2),('Lifecycle',2,3),('Portals',3,5),('Integration',4,6),('Deployment safety',5,6),('Geographic APIs',6,7)]:
 cells=gantt.add_row().cells; cells[0].text=label
 for j in range(1,8):
  cells[j].text='■' if start<=j<=end else ''
  if start<=j<=end:
   sh=OxmlElement('w:shd'); sh.set(qn('w:fill'),'D8B978'); cells[j]._tc.get_or_add_tcPr().append(sh)
caption('Figure 4.1 Illustrative phase sequence only; numbered columns are not calendar dates.')
h('4.2 Risk Identification',2)
table(['Risk','Effect','Mitigation in design','Residual issue'],[
['Unverified official identity','Unauthorized access or false public trust','Admin-led verification; verified timestamp and actor required','Manual evidence quality depends on administrator'],['Misrouted report','Delay or incorrect operational ownership','Suggestion is separate from actual assignment; admin override reason','Category map still requires governance review'],['Sensitive evidence exposure','Personal or location privacy harm','Generated storage names, protected retrieval, role/ownership checks','Storage permissions/backup must be secured in deployment'],['Malformed legacy coordinates','Hotspot/API failure or wrong geography','Shared validator excludes invalid points from spatial analysis','Old records remain as stored; exclusion affects eligible counts'],['False civic AI interpretation','Misleading category or automated action','ImageNet banner and user confirmation; no auto-submit/resolve','Generic labels may still confuse users'],['Boundary misclassification','Incorrect city totals','Versioned registry, draft state and approval gate','GBA boundary and license remain unresolved'],['Database target mistake','Data loss or cross-environment contamination','Audit mode, explicit DB config, safe bootstrap/seed guards','Operators must verify runtime environment'],['Sparse hotspot inference','Re-identification from aggregates','Minimum cluster size, coarsened centers, suppression','No formal anonymity guarantee']],fontsize=8)
p('Risk review should be repeated before deployment, especially for evidence retention, identity verification, incident response, boundary provenance and the data protection obligations applicable to the operating organization.')

# Chapter 5
chapter(5,'Software Requirement Specifications')
h('5.1 Purpose',2)
p('This SRS describes repository-backed behavior and the constraints required to operate it safely. It is intended for academic review and is not a service contract with a municipality. Requirements labeled implemented are supported by source-level routes/components and tests; they do not imply every end-to-end production condition has been independently validated.')
h('5.2 Project Scope',2)
p('NODAL supports citizen intake, role-specific record access, department suggestion and administrative assignment, official progress updates, resolution review, evidence upload/retrieval, platform-wide mapping and a geographic registry foundation. It is designed to run as a React/Vite frontend with a Flask API and MongoDB. Production deployment requires explicit secrets, MongoDB URI/database, CORS origin configuration, evidence persistence and a production WSGI server.')
h('5.3 Overall Description',2)
h('5.3.1 Product Perspective',3)
p('The frontend uses a same-origin or configured API base with credentialed requests and CSRF-token handling. The Flask application factory registers authentication, complaint, department, vision, public/geographic and admin routes. PyMongo accesses collections lazily through the configured database. Evidence files are stored in a filesystem directory outside MongoDB; MongoDB stores metadata and references. The public map uses Leaflet with OpenStreetMap tiles.')
h('5.3.2 Product Features',3)
for x in ['Public landing experience and map navigation.','Citizen registration, login, profile and personal complaint dashboard.','Complaint submission with location and optional image-assisted prediction.','Department suggestion from active category mappings.','Admin assignment/reassignment with reasons and audit history.','Verified official worklist, progress update and resolution submission.','Admin official verification and resolution review.','Protected evidence access.','Platform overview/hotspots and read-only versioned region registry.','Local development/audit safeguards and production configuration validation.']: bullet(x)
h('5.3.3 Operating Environment',3)
table(['Layer','Verified repository technology','Operational note'],[
['Frontend','React 19, Vite 8, JavaScript, CSS','Browser SPA; package lock defines exact packages'],['Mapping','Leaflet 1.9, React-Leaflet 5, OpenStreetMap tiles','Tile service/network availability is external'],['Backend','Python, Flask, PyMongo','Application factory in backend/app.py'],['Database','MongoDB','Database selected by NODAL_DB_NAME, nodal default outside audit restrictions'],['Vision','TensorFlow/Keras MobileNetV2; Pillow','ImageNet demo; civic artifacts absent'],['Text category helper','scikit-learn, joblib','Repository has classifier.joblib; training script uses complaint descriptions']],fontsize=8)
h('5.4 External Interface Requirements',2)
h('5.4.1 User Interfaces',3)
p('The single React application conditionally renders public, authentication, citizen, official and administrator experiences. The primary portal composition is in frontend/src/App.jsx, with shared application and global styles in App.css and index.css. VisionPanel.jsx/css exist as a separate component, while citizen reporting also has integrated image-assistance UI. The interface includes interactive maps, filters, complaint worklists, timelines, evidence panels, department forms, verification queues and role-specific actions.')
h('5.4.2 Hardware Interfaces',3); p('No specialized hardware is required by the source. A standard client browser, network connection and server capable of running Python/Flask, MongoDB and Vite or a built static frontend are expected. Image capture is provided by the user’s device and browser file input; the server validates accepted formats and size.')
h('5.4.3 Software Interfaces',3)
table(['Interface','Use','Known contract'],[
['MongoDB','Users, complaints, department registry, audit and region records','PyMongo through configured URI and database'],['OpenStreetMap','Basemap tiles','Leaflet tile layer; external service'],['Vision service','Image prediction','POST /vision/predict, multipart image'],['Evidence filesystem','Image persistence','NODAL_EVIDENCE_DIR, generated identifiers'],['WSGI server','Production HTTP serving','Waitress dependency/documented command']],fontsize=8)
h('5.4.4 Communication Interfaces',3)
p('The API uses HTTP JSON for most operations, cookie-based sessions for identity, CSRF tokens on state-changing methods and multipart/form-data for uploads. Production configuration expects explicit allowed HTTPS CORS origins; development origin configuration is explicit. The source does not claim end-to-end encryption between every possible deployment component unless the deployment terminates HTTPS correctly.')
h('5.5 System Features',2)
h('5.5.1 Functional Requirements',3)
table(['ID','Requirement','Current implementation evidence'],[
['FR-01','Register/login as citizen','/auth/register and /auth/login; registration role is citizen'],['FR-02','Submit complaint with required narrative and location','POST /complaints; GeoJSON Point [longitude, latitude]'],['FR-03','Track own reports','Role-scoped GET /complaints and detail'],['FR-04','Suggest department by category','Department registry category mapping; suggestion separate from assignment'],['FR-05','Authorize officials','Active official plus independent verification markers; assignment/department scope'],['FR-06','Update progress and submit resolution','Controlled transition route, notes and evidence references'],['FR-07','Admin review assignment and resolution','Admin-only assignment/decision actions with reasons'],['FR-08','Protect evidence','Generated storage names; owner/admin/authorized official checks'],['FR-09','Aggregate public map data','/public/overview and /hotspots aggregate responses'],['FR-10','Provide region API foundation','Approved boundary required; GBA remains draft/no geometry']],fontsize=8)
h('5.5.2 Non-Functional Requirements',3)
table(['Quality','Requirement','Verification/limitation'],[
['Security','Enforce role, owner, department, verification and CSRF server-side','Backend unit tests cover key rules; deployment review still required'],['Privacy','Avoid public individual identifiers/evidence references','Aggregate serializers and protected evidence; no formal anonymity guarantee'],['Integrity','Append-only status/assignment history; reasons for sensitive changes','Application logic and tests; DB-level immutability is not claimed'],['Reliability','Invalid coordinates should not crash public hotspots','Shared geographic validator and regression tests'],['Usability','Responsive role portals and clear uncertainty labels','Frontend lint/build; browser audit evidence is environment-specific'],['Maintainability','Reusable app factory, services, tests, docs','Repository modules and tests'],['Portability','Configurable runtime, explicit production settings','WSGI/config validation; operator setup remains required']],fontsize=8)
h('5.5.3 Use Case Description',3)
table(['Use case','Actor','Precondition','Main outcome'],[
['Submit report','Citizen','Authenticated session','Owned complaint with status submitted and suggested department if mapped'],['Track report','Citizen','Complaint belongs to citizen','Details/history and permitted evidence shown'],['Request official access','Citizen','Citizen account','Pending request; no privilege granted'],['Review access request','Admin','Admin authenticated','Approved/rejected with verification method/reason; role state updated only through workflow'],['Work assigned case','Verified official','Individual or department scope permits access','Progress event and status history appended'],['Review resolution','Admin','Resolution submitted','Decision note and transition to resolved or further work'],['Configure department','Admin','Admin authenticated','Registry configuration updated with uniqueness/active checks'],['Review public intelligence','Public user','None','Platform-level aggregates; regional values only for approved boundary']],fontsize=8)
h('5.5.4 Use Case, Activity and Swimlane Diagrams',3)
figure('usecases','Figure 5.1 Primary role-oriented use cases')
figure('flow','Figure 5.2 Complaint submission, routing and review activity')
figure('swimlane','Figure 5.3 Complaint workflow swimlanes')
p('The swimlane assigns submission and dispute actions to the citizen, validation and transition checks to the backend, administrative assignment/review to administrators, and progress/resolution submission to verified officials. The backend checks every transition and object scope. AI output is advisory; it neither chooses an official nor changes complaint status.')

# Chapter 6
chapter(6,'Design')
h('6.1 Introduction',2)
p('The system is organized around explicit trust boundaries. The web client provides affordances and data presentation, but the Flask server decides whether an identity may act on a record. The database persists complaint and history data, while the evidence store keeps image bytes separate. Vision prediction is an optional service with a distinct purpose and limitations.')
h('6.2 Architecture Design',2)
figure('arch','Figure 6.1 NODAL system architecture')
p('The application factory in backend/app.py assembles configuration and route registration. Authentication helpers in backend/auth.py manage sessions, CSRF support and role decorators. Supporting modules handle departments, evidence, regions, geography and vision. frontend/src/api.js adds credentialed requests and CSRF behavior, while App.jsx orchestrates public and role-based screens. MongoDB documents hold users and complaints; evidence binaries remain on the configured filesystem path.')
h('6.2.1 Role-based architecture',3); figure('roles','Figure 6.2 Role-based access boundaries')
h('6.2.2 Complaint lifecycle design',3); figure('flow','Figure 6.3 Complaint lifecycle and review')
p('Status history records actor role, timestamp and action. Assignment history records the suggested and actual department, previous assignment on reassignment, administrator, reason and timestamp. Citizens cannot arbitrarily edit or resolve records. Officials cannot review their own resolution as administrators. Citizens may ask for reopening through the implemented dispute path after resolution.')
h('6.2.3 Department routing design',3); figure('routing','Figure 6.4 Department suggestion and administrative assignment')
h('6.2.4 Geographic intelligence design',3); figure('geo','Figure 6.5 Geographic intelligence data flow')
h('6.3 User Interface Design',2)
p('The frontend follows the NODAL palette: warm ivory, forest green, terracotta, muted sand, charcoal and muted sage. It uses serif display typography with sans-serif interface text, CSS tokens and responsive styles. The public landing page preserves its hero asset and India-wide positioning. Citizen workflows emphasize reporting and personal tracking; the official workspace emphasizes assigned work; the admin workspace supports verification, assignment, resolution review and department management. The interface labels ImageNet as general image recognition and demo complaints as demonstration data.')
h('6.4 Low-Level Design',2)
h('6.4.1 Complaint document and coordinate representation',3)
p('Complaint location is represented as GeoJSON Point coordinates [longitude, latitude]. Leaflet consumes [latitude, longitude] when constructing a display coordinate pair, so the frontend reverses the GeoJSON pair deliberately. The backend validator rejects absent, malformed, non-finite and out-of-range coordinate values. Legacy documents are not rewritten by this validation; invalid points are excluded from geographic analysis.')
h('6.4.2 Evidence metadata and retrieval',3)
p('An uploaded image passes format, byte-size and decoded-pixel checks. The service generates a storage identifier rather than trusting an uploaded filename, computes metadata such as content type, size and hash, writes bytes outside MongoDB, and stores metadata/reference on the complaint. Retrieval routes first authorize the requester against the complaint and then stream the file. Public aggregate endpoints do not return evidence storage keys.')
h('6.4.3 Region versioning',3)
p('A region record includes stable ID, name, type, parent, boundary geometry, version, source/provenance, license and approval state. Boundary changes are represented as new versions, not silent updates to an approved boundary. Public regional APIs resolve approved boundaries only. Geometry validation is dependency-free and validates structure, coordinate ranges, ring closure and non-zero area; it does not constitute a full GIS topology engine. No boundary is currently approved for the GBA pilot.')
h('6.5 Conclusion',2)
p('The design keeps suggestion separate from authorization, model output separate from action, and platform-wide aggregates separate from region-scoped claims. These separations reduce accidental authority escalation and data misrepresentation. Future scaling should preserve these boundaries while improving spatial query efficiency and operational observability.')

# Chapter 7
chapter(7,'Implementation')
h('7.1 Tools Introduction',2)
p('The implementation uses React and Vite for the browser application, Flask for the Python API, PyMongo for database access, MongoDB for persistence, Leaflet and React-Leaflet for maps, Pillow for image validation/preprocessing, TensorFlow/Keras for MobileNetV2 inference, scikit-learn for text category assistance and DBSCAN, and unittest-based Python tests. The inspected frontend package does not use Tailwind CSS or Firebase; those technologies are not listed as implemented.')
h('7.2 Technology Introduction',2)
p('React components represent interactive views and local state; Vite provides the development server and production bundler. Flask routes are registered in an application factory, while reusable modules isolate authentication, evidence, geographic filtering, department logic and vision service operations. MongoDB stores flexible document records and a 2dsphere index supports geographic operations. Python configuration distinguishes development, audit and production settings.')
h('7.3 Overall View of the Project in Terms of Implementation',2)
h('7.3.1 Frontend modules',3)
p('frontend/src/main.jsx mounts the React application. frontend/src/App.jsx contains the landing, authentication state and citizen/official/admin workspace behavior. frontend/src/api.js centralizes API base selection, cookies and CSRF. App.css and index.css implement shared and portal styling. VisionPanel.jsx/css provide a reusable vision panel, while the complaint reporting experience also integrates image assistance directly. The interface fetches public overview/hotspots and authenticated complaint/admin/official data through existing API calls.')
h('7.3.2 Backend modules',3)
table(['Module','Responsibility'],[
['backend/app.py','Application factory, API routes, complaint workflows, aggregates and startup'],['backend/auth.py','Registration, login, sessions, profile, official request workflow, role checks'],['backend/departments.py','Department registry validation and category suggestion utilities'],['backend/evidence.py','Image validation, secure filesystem persistence and access support'],['backend/geography.py','Coordinate validation and point/polygon membership/aggregate helpers'],['backend/regions.py','Versioned region document validation and resolution'],['backend/api/vision.py','Vision prediction endpoint'],['backend/services/vision_service.py','ImageNet model loading/inference and optional civic artifact path'],['backend/wsgi.py / deployment_config.py','Production WSGI configuration safeguards'],['backend/bootstrap_admin.py / seed.py','Guarded administrative bootstrap and destructive development seed utility']],fontsize=8)
h('7.3.3 Authentication and role management',3)
p('Citizen registration through POST /auth/register creates only citizen accounts. Login establishes a server-side session cookie. The frontend requests a CSRF token and includes it for state-changing requests. Official access begins with a citizen-submitted request; an administrator inspects the request and records the verification method and notes. Protected official access requires authentication, official role, active state and independent verification metadata. Admin actions remain role-gated.')
h('7.3.4 Citizen portal and complaint submission',3)
p('The citizen form gathers category, description and map location; coordinates are synchronized with the map selection and numeric location fields. Optional image assistance calls POST /vision/predict and displays a generic ImageNet prediction. The user confirms or changes category and chooses whether to attach evidence to the complaint. Complaint creation requires valid location and description, and the owner can retrieve their records through role-scoped list/detail routes. Filters use existing category, priority and status data.')
h('7.3.5 Department suggestion and assignment',3)
p('The department registry stores unique department identifiers, names, active status, descriptions and category mappings. A category match adds a suggested department to a new complaint. It does not assign an official or alter submitted status. An administrator selects an active department and, where appropriate, a verified official whose department matches. Reassignment and overrides require a reason and append history rather than silently replacing prior context.')
h('7.3.6 Official and admin portals',3)
p('The official portal retrieves only authorized assignments and permits status updates under backend transition rules. Officials submit progress notes and a resolution with notes/evidence reference; the resolution remains pending review until an administrator makes a decision. The admin portal surfaces overview metrics, department workload, official access requests, complaints, assignment controls, resolution review and department management. Frontend visibility supplements, but does not replace, server-side permission enforcement.')
h('7.3.7 Vision and training pipeline',3)
p('The generic vision endpoint validates an uploaded image and lazily loads MobileNetV2 pretrained on ImageNet. Its output is a general object label with confidence; it is not a civic defect classification. The separate ml/vision pipeline contains dataset manifest/split preparation, duplicate and group checks, a shared RGB 224×224 preprocessing helper, MobileNetV2 fine-tuning, validation-based threshold selection, evaluation and CLI prediction. Artifact validation checks labels, dimensions and threshold configuration. No trained civic artifacts or dataset were found in ml/vision/artifacts and datasets beyond placeholder files, so training results and real-world accuracy cannot be claimed.')
h('7.3.8 Maps, hotspots and regions',3)
p('The public frontend renders maps with Leaflet. Complaint GeoJSON coordinates are converted for Leaflet display. The platform-wide /hotspots endpoint filters valid coordinates, excludes ineligible records according to its status logic, and applies DBSCAN using haversine distance. Hotspot centers are coarsened; individual complaint IDs and evidence are not returned. The regional APIs require an approved region boundary and suppress sparse aggregates below the configured minimum. GBA currently has a draft template only, with boundary null and no approved statistics.')
h('7.4 Explanation of Algorithms and Their Implementation',2)
h('7.4.1 Text-based complaint category helper',3)
p('ml/train_classifier.py reads complaint descriptions and labels from MongoDB, excludes unclassified labels, uses a stratified train_test_split with a fixed random seed, fits a TF-IDF vectorizer with unigram/bigram features and logistic regression, reports a classification report, refits on all records and saves ml/classifier.joblib. This script’s direct MongoDB use and nodal default are operationally sensitive; it is not the same model as the vision pipeline. The repository alone does not provide a fresh reproducible metric for the current classifier, and the report does not claim its accuracy.')
h('7.4.2 Priority heuristic and duplicate signal',3)
p('Complaint creation derives a priority from keyword rules and duplicate-count signals. Near-duplicate candidates are limited by geographic proximity and textual similarity. Such heuristics are workflow aids rather than validated severity assessments. The user-visible priority should not be interpreted as an official service commitment or a prediction of response time.')
h('7.4.3 DBSCAN hotspot algorithm',3)
p('For valid eligible complaints, coordinates are converted to radians in latitude-longitude order for haversine distance. DBSCAN uses eps = 0.4/6371 radians, corresponding to approximately 0.4 km on the assumed Earth-radius constant, and min_samples = 5. Noise points do not form clusters. Cluster summaries count points, choose a dominant category and indicate high-priority presence. Centers are rounded and checked not to reproduce an exact input point. This is a descriptive snapshot, not historical trend analysis.')
h('7.4.4 Threshold selection in the optional civic model pipeline',3)
p('The vision threshold helper uses validation predictions only, selecting the lowest qualifying threshold subject to the implementation’s coverage and confidence-bound criteria, rather than choosing the highest qualifying value by mistake. The selected threshold and class labels are serialized into inference configuration. Test data is reserved for evaluation. If validation data is too small or unsuitable, the configured conservative fallback is reported. This process is present in code/tests; there is no trained civic artifact in the repository to demonstrate operational model quality.')
h('7.5 Implementation of Modules',2)
h('7.5.1 API groups and workflow',3)
table(['API group','Representative routes','Purpose / authorization'],[
['Authentication','/auth/csrf, /auth/register, /auth/login, /auth/me, /auth/profile','Public registration/login; authenticated profile; CSRF for mutations'],['Complaints','/complaints, /complaints/<id>','Role-scoped create/list/detail; unsupported arbitrary patch/delete rejected'],['Lifecycle','/complaints/<id>/transition','Role and state transition checks; notes/evidence requirements'],['Assignment','/complaints/<id>/assign','Admin-only department/official assignment with mandatory reason rules'],['Official access','/auth/official-access-requests, /admin/official-access-requests','Citizen request; admin review and independent verification'],['Departments','/admin/departments','Admin-managed registry, mapping, activation/deactivation'],['Evidence','complaint evidence subroutes','Protected image retrieval based on ownership/admin/authorized official'],['Vision','/vision/predict','Validated image prediction; generic demo warning'],['Public geography','/public/overview, /hotspots, /public/regions/...','Platform aggregates and approved-boundary regional aggregates'],['Admin overview','/admin/overview','Admin-only workload and review metrics']],fontsize=7.5)
h('7.5.2 Data integrity and audit history',3)
p('The application preserves original records when displaying synthetic complaints; frontend presentation strips known markers from visible text and shows a demo badge. Legacy records without an owner are read-only samples. Complaint status and assignment histories are append-only at the application level. The model does not claim database-level immutable storage or tamper-proof audit logging.')
h('7.6 Conclusion',2)
p('The implementation realizes the primary reporting, routing, verification, evidence and role portal workflows. It also includes a substantial architecture for civic image training and geographic intelligence, but those code paths are not equivalent to verified operational data products. Model artifacts, approved boundaries, institutional connections and live operational data remain prerequisites for those claims.')

# Chapter 8
chapter(8,'Testing')
h('8.1 Introduction',2)
p('Testing evidence is separated into automated repository tests, static/frontend checks, and live integration or browser validation. During preparation of this report, the available local automated suites were freshly executed. No production database was accessed, no seed/bootstrap script was run and no real civic model training was performed. Automated test success establishes behavior covered by those tests only.')
h('8.2 Testing Tools and Environment',2)
table(['Check','Command/environment','Fresh result during report preparation'],[
  ['Backend tests','.venv-vision Python; unittest discover backend/tests','71 tests passed'],['Vision tests','.venv-vision Python; unittest discover ml/vision/tests','12 tests passed'],['Frontend lint','VITE_API_BASE set; npm run lint','Passed, exit code 0'],['Frontend production build','VITE_API_BASE set; npm run build','Passed, Vite 8.3.8, 2,194 modules transformed'],['Python compilation','Compile all repository Python source files','24 files compiled successfully'],['Git whitespace check','git diff --check','Not freshly recorded for this report run; do not claim'],['Live browser integration','No browser/API workflow performed for report authoring','Not tested in this report run'],['MongoDB integration','No database connection performed for report authoring','Not tested in this report run']],fontsize=8)
h('8.3 Test Cases',2)
table(['ID','Description','Input / condition','Expected result','Actual result','Status'],[
['AUTH-01','Citizen registration role','Registration payload','Citizen account only','Covered by backend suite','PASS'],['AUTH-02','Unverified official access','Active official without verification markers','403/denial on protected official routes','Covered by regression tests','PASS'],['AUTH-03','CSRF/session flow','Mutation without valid token','Rejected by middleware','Covered by backend suite','PASS'],['CMP-01','Complaint coordinates','Valid GeoJSON point','Stored [lon,lat] and accepted','Covered by backend suite','PASS'],['CMP-02','Ownership filtering','Citizen requests another owner record','Not found/denied','Covered by backend suite','PASS'],['ROUTE-01','Category suggestion','Mapped category','Suggested department, still submitted','Covered by backend suite','PASS'],['ROUTE-02','Reassignment reason','Admin changes actual department','Reason and history required','Covered by backend suite','PASS'],['OFF-01','Official scope','Verified user outside permitted scope','Denied','Covered by backend suite','PASS'],['LIFE-01','Resolution submission','Notes/evidence reference','Pending admin review','Covered by backend suite','PASS'],['EVD-01','Evidence access','Owner/authorized official vs unrelated user','Allow permitted, deny unrelated','Covered by backend suite','PASS'],['GEO-01','Malformed legacy coordinates','Missing/non-finite/out of range','Exclude without hotspot crash','Covered by backend suite','PASS'],['REG-01','Draft region','Region has no approved boundary','Regional stats unavailable/denied','Covered by region suite','PASS'],['VIS-01','ImageNet endpoint','Valid image file','Generic label/confidence warning','Vision unit suite only; live browser not tested','AUTOMATED ONLY'],['VIS-02','Civic model artifact','No trained artifact present','Clear unavailable error','Artifact validation tests; no model accuracy','LIMITED'],['UI-01','Responsive portal behavior','Five requested viewport sizes','Readable/no overflow','No fresh browser inspection in report run','NOT TESTED']],fontsize=6.8)
h('8.3.1 Suite results and interpretation',3)
p('The backend unittest run completed 71 tests with no failures. The vision unittest run completed 12 tests with no failures. Frontend lint and production build exited successfully with an explicit VITE_API_BASE. Python compilation passed for 24 source files. The vision suite uses temporary/synthetic fixtures and validates pipeline behavior, not civic classification accuracy. Test totals are the run evidence collected for this report, not a statement of test coverage percentage.')
p('Browser sessions, exact HTTP behavior against a running server, MongoDB integration, accessibility assessment and performance/load testing were not freshly executed during report creation. Prior project audit history contains such efforts, but this report does not present historical checks as current fresh results.')

# Chapter 9
chapter(9,'Results and Performance Analysis')
h('9.1 Result Snapshots',2)
p('The repository did not contain a verified set of full-application screenshots for the current runtime, and no browser capture was performed during report preparation. The placeholders below are deliberate. Replace each with a genuine screenshot captured from the intended build and environment; include date, viewport and database/runtime context. The existing hero image is included separately only as a source asset, not as evidence that the site rendered successfully.')
hero=ROOT.parent/'frontend'/'src'/'assets'/'nodal-bengaluru-hero.png'
if hero.exists():
 para=doc.add_paragraph(); para.alignment=WD_ALIGN_PARAGRAPH.CENTER; para.add_run().add_picture(str(hero),width=Inches(5.7)); caption('Figure 9.1 Existing landing-page hero image asset. The asset is illustrative and is not a documentary photograph or runtime screenshot.')
for i,title in enumerate(['Landing page and public intelligence','Login and citizen registration','Citizen dashboard and complaint worklist','Citizen complaint reporting with map and image assistance','Complaint details, history and evidence','Official dashboard and authorized worklist','Administrator dashboard and verification queue','Department registry and assignment controls'],start=2):
 h(f'9.1.{i-1} {title}',3)
 p(f'[SCREENSHOT PLACEHOLDER — insert an authentic capture for {title}. Record build/version, viewport, user role and isolated test database. Do not include credentials, personal data, internal identifiers or production records.]')
h('9.2 Comparison Results Tables',2)
table(['Evaluation dimension','Repository-supported result','Evidence boundary'],[
['Automated backend logic','71 tests passed','Unit tests; not live production verification'],['Vision pipeline utilities','12 tests passed','Synthetic/temp test images; no curated civic model'],['Frontend static quality','Lint and production build passed','Build success does not prove browser workflow'],['Geographic robustness','Coordinate and region logic tested','No approved GBA geometry; no regional production metrics'],['Hotspot output','DBSCAN aggregation implemented','No measured field accuracy or performance benchmark'],['User-facing accessibility','Semantic controls and responsive styles exist','No formal WCAG audit performed']],fontsize=8)
h('9.3 Performance Analysis',2)
p('No reproducible latency, throughput, memory, model accuracy or load benchmark is included in the repository evidence inspected for this report. Accordingly, no numerical performance graph or fabricated comparison is presented. Some architectural observations can be made from code: region filtering currently iterates over platform complaint records in Python and is O(N); the repository already defines a 2dsphere index, and a future approved-boundary implementation may use MongoDB $geoWithin to reduce candidates before aggregation. Any such optimization must preserve malformed-coordinate safety and be tested against the MongoDB version and data shape in use.')
p('ImageNet inference requires loading a pretrained model and image decode/resize operations; the service lazily initializes and reuses the model. Actual startup latency and throughput depend on hardware and library configuration and have not been measured here. Evidence size limits and decoded-pixel checks bound some resource exposure, but deployment should still monitor request rates, storage growth, filesystem capacity and model initialization failures.')

# Chapter 10
chapter(10,'Conclusion and Scope for Future Work')
h('10.1 Findings and Suggestions',2)
p('NODAL provides an implemented foundation for structured citizen reporting, controlled complaint workflows, department suggestions, independently verified official access, protected image evidence and role-specific portals. Its most important architectural property is that recommendations and data collection do not themselves trigger authority-bearing actions: department suggestions do not assign officials, image predictions do not submit complaints, and official resolution submissions await administrative review.')
p('The report also identifies explicit boundaries between current implementation and future operational claims. Generic ImageNet predictions are not civic issue detection. The training pipeline does not prove a trained civic classifier exists. A map centre is not a geographic filter. The GBA registry is not an approved polygon. A department prototype is not a verified government assignment. Public aggregate suppression is not a formal anonymity guarantee. These distinctions should remain visible in product language and demonstrations.')
h('10.2 Significance of the Proposed Project',2)
p('The platform’s potential significance is a traceable interface connecting reports to accountable work stages and making aggregate infrastructure patterns easier to inspect. That potential depends on accessibility, trustworthy data, fair routing, privacy, verified staff participation and institutional response. The software can support those processes; it cannot by itself ensure them.')
h('10.3 Limitations',2)
for x in ['No production deployment or government integration was verified for this report.','No curated civic image dataset or trained civic model artifact was present.','No model accuracy or real-world field performance can be stated.','The GBA Section 3 extent, machine-readable boundary and redistribution permission remain unresolved; regional GBA outputs are unavailable.','Platform-wide public data may include legacy or synthetic records and must retain quality notices.','The department registry is configurable but prototype mappings are not confirmed government jurisdiction assignments.','No formal load, latency, accessibility or privacy re-identification study is included.','MongoDB data was not inspected or queried during report preparation.']: bullet(x)
h('10.4 Future Work',2)
table(['Work item','Prerequisite','Acceptance evidence'],[
['Approve GBA boundary','Authoritative territorial notification, geometry, license and GIS validation','Versioned source packet, checksum, topology report and admin approval'],['Enable efficient region queries','Approved geometry and MongoDB query plan','Integration tests against isolated MongoDB, including malformed legacy rows'],['Train civic image classifier','Curated, consented, representative and independently labeled dataset','Data card, split/group integrity, held-out evaluation, calibration and field validation'],['Improve privacy assurance','Threat model and release policy','Review of small-cell inference, query controls, coarsening and suppression'],['Operational department onboarding','Written agreements and verified contacts','Admin-reviewed registry and audited access procedures'],['Performance and accessibility','Defined production-like environment','Load tests, telemetry and accessibility audit']],fontsize=8)

# Chapter 11 references
chapter(11,'References')
refs=[
'[1] M. Ester, H.-P. Kriegel, J. Sander, and X. Xu, “A Density-Based Algorithm for Discovering Clusters in Large Spatial Databases with Noise,” in Proc. 2nd Int. Conf. Knowledge Discovery and Data Mining (KDD-96), Portland, OR, USA, 1996, pp. 226–231. [Online]. Available: https://file.biolab.si/papers/1996-DBSCAN-KDD.pdf. Accessed: 26-Nov-2026.',
'[2] M. Sandler, A. Howard, M. Zhu, A. Zhmoginov, and L.-C. Chen, “MobileNetV2: Inverted Residuals and Linear Bottlenecks,” in Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR), 2018, pp. 4510–4520, doi: 10.1109/CVPR.2018.00474. [Online]. Available: https://openaccess.thecvf.com/content_cvpr_2018/papers/Sandler_MobileNetV2_Inverted_Residuals_CVPR_2018_paper.html.',
'[3] H. Butler, M. Daly, A. Doyle, S. Gillies, S. Hagen, and T. Schaub, “The GeoJSON Format,” RFC 7946, Internet Engineering Task Force, Aug. 2016. [Online]. Available: https://www.rfc-editor.org/info/rfc7946.',
'[4] MongoDB, “Geospatial Queries,” MongoDB Manual. [Online]. Available: https://www.mongodb.com/docs/manual/geospatial-queries/. Accessed: 26-Nov-2026.',
'[5] MongoDB, “Geospatial Indexes,” MongoDB Manual. [Online]. Available: https://www.mongodb.com/docs/manual/core/indexes/index-types/index-geospatial/. Accessed: 26-Nov-2026.',
'[6] Keras, “MobileNet preprocessing,” Keras API documentation. [Online]. Available: https://keras.io/api/applications/mobilenet/mobilenet_preprocessing/. Accessed: 26-Nov-2026.',
'[7] Pallets Projects, “Application Factories,” Flask Documentation. [Online]. Available: https://flask.palletsprojects.com/en/stable/patterns/appfactories/. Accessed: 26-Nov-2026.',
'[8] OWASP Foundation, “Cross-Site Request Forgery Prevention Cheat Sheet.” [Online]. Available: https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html. Accessed: 26-Nov-2026.',
'[9] Department of Administrative Reforms and Public Grievances, Government of India, “Centralized Public Grievance Redress and Monitoring System (CPGRAMS): About Us.” [Online]. Available: https://pgportal.gov.in/Home/AboutUs. Accessed: 26-Nov-2026. NODAL is not integrated with CPGRAMS.',
'[10] Department of Administrative Reforms and Public Grievances, Government of India, “CPGRAMS Annual Report 2024.” [Online]. Available: https://www.darpg.gov.in/static/uploads/2025/10/3ee7b2dd922624371c82df2c1d91e2a5.pdf. Accessed: 26-Nov-2026.',
'[11] React, “Quick Start,” React Documentation. [Online]. Available: https://react.dev/learn. Accessed: 26-Nov-2026.',
'[12] Government of India, India Code, “The Greater Bengaluru Governance Act, 2024 (Karnataka Act 36 of 2025).” [Online]. Available: https://www.indiacode.nic.in/bitstream/123456789/21664/1/36_of_2025_%28e%29.pdf. Accessed: 26-Nov-2026. The Act provides for notification of the GBA extent; the approved boundary is not present in NODAL.',
'[13] Government of Karnataka, Urban Development Department, “Greater Bengaluru Authority / corporation delimitation resources,” BBMP/GBA maps portal. [Online]. Available: https://www.bbmp.gov.in/maps/ and https://bbmp.gov.in/gba-corporations-delimitation-2025/index.html. Accessed: 26-Nov-2026. These are leads, not evidence that NODAL has an approved redistributable GBA polygon.',
'[14] scikit-learn developers, “DBSCAN,” scikit-learn User Guide. [Online]. Available: https://scikit-learn.org/stable/modules/generated/sklearn.cluster.DBSCAN.html. Accessed: 26-Nov-2026.',
'[15] NODAL project repository, source code and documentation, including backend/app.py, backend/auth.py, backend/departments.py, backend/evidence.py, backend/geography.py, backend/regions.py, backend/services/vision_service.py, frontend/src/App.jsx, frontend/src/api.js, ml/vision and docs. Inspected 26-Nov-2026.'
]
for ref in refs: p(ref)

# Chapter 12 Appendix
chapter(12,'Appendix')
h('12.1 Repository Map',2)
table(['Path','Purpose'],[
['backend/app.py','Flask app factory and principal route/workflow implementation'],['backend/auth.py','Authentication and role/verification helpers'],['backend/departments.py','Department registry and category mapping logic'],['backend/evidence.py','Evidence validation and storage/access logic'],['backend/geography.py / regions.py','Coordinate and region services'],['backend/api/vision.py / services/vision_service.py','Prediction API and model service'],['backend/tests/','Backend auth, operational safety and region suites'],['frontend/src/App.jsx','Landing and role portal React implementation'],['frontend/src/api.js','Frontend HTTP, session and CSRF helper'],['frontend/src/App.css / index.css','Portal and global styles'],['ml/vision/','Dataset preparation, preprocessing, training, evaluation and CLI'],['docs/','Deployment, workflow, geographic and showcase documentation'],['scripts/','Guarded local showcase/setup utilities']],fontsize=8)
h('12.2 Selected Runtime and Data Rules',2)
table(['Concern','Repository rule / behavior'],[
['Coordinates','GeoJSON Point order [longitude, latitude]; reject invalid ranges/non-finite values'],['Complaint ownership','Citizen query paths are owner-scoped; legacy ownerless samples are read-only'],['Official verification','Active official role plus independent verification metadata from admin flow'],['Department routing','Suggested department is distinct from actual assignment'],['Resolution','Official submits notes/evidence; administrator decides outcome'],['Evidence','Generated filename and protected access; bytes outside MongoDB'],['Vision','ImageNet demo is general object recognition; civic model unavailable without artifacts'],['Regional metrics','Only approved boundary versions; GBA draft has no geometry/statistics']],fontsize=8)
h('12.3 API Contract Summary',2)
table(['Method / route','Purpose','Notes'],[
['GET /health','Health check','Does not imply database or service readiness unless implementation checks it'],['GET /auth/csrf','Obtain CSRF token','Session-bound frontend support'],['POST /auth/register','Register citizen','No public role selection'],['POST /auth/login','Authenticate','Cookie session'],['GET /complaints','List scoped complaints','Role-aware filters'],['POST /complaints','Create complaint','Description/location; optional multipart evidence'],['POST /complaints/<id>/assign','Assign work','Admin authorization and reason constraints'],['POST /complaints/<id>/transition','Lifecycle action','Role-specific state machine'],['POST /vision/predict','Image prediction','Generic ImageNet demo label/confidence'],['GET /public/overview','Platform overview','Platform-wide, not city-specific'],['GET /hotspots','Platform hotspot clusters','Aggregated/coarsened output'],['GET /public/regions/<region_id>/overview','Regional metrics','Approved version/boundary required'],['GET /public/regions/<region_id>/hotspots','Regional hotspots','Sparse output suppression'],['GET /admin/overview','Admin metrics','Admin-only'],['GET/POST/PATCH /admin/departments','Department management','Admin-only']],fontsize=7.5)
h('12.4 Environment and Operations Checklist',2)
table(['Item','Required handling'],[
['NODAL_ENV','Set production explicitly for deployment'],['NODAL_SECRET_KEY','Strong secret; never commit or print'],['MONGO_URI','Explicit server/cluster URI; protect credentials'],['NODAL_DB_NAME','Explicit production database for deployment; audit mode allowlists audit DBs'],['NODAL_AUDIT_MODE','Must be disabled for production WSGI'],['CORS_ALLOWED_ORIGINS','Explicit HTTPS frontend origins; no wildcard with credentials'],['NODAL_EVIDENCE_DIR','Persistent, backed-up path outside web root'],['WSGI','waitress-serve --listen=127.0.0.1:8000 backend.wsgi:app per docs; reverse proxy/TLS deployment-specific'],['Frontend','Set VITE_API_BASE explicitly for production build'],['Backups','Back up database and evidence files consistently; test restoration']],fontsize=8)
h('12.5 Manual Screenshot Checklist',2)
for x in ['Capture public landing page with date and viewport; verify no secret or production identifiers.','Capture login and citizen registration with no populated personal fields.','Capture citizen worklist and detail using an isolated synthetic account.','Capture reporting form, map selection and ImageNet disclaimer.','Capture verified official workbench only if a legitimately verified test identity exists.','Capture admin overview, request queue and department registry using isolated audit data.','Capture responsive views at 375×812, 390×844, 430×932, 768×1024 and 1366×768.','Record environment, test database and test identity role in figure notes; exclude passwords and private IDs.']: bullet(x)
h('12.6 Report Completion Fields',2)
p('Before academic submission, complete: [TEAM MEMBER 1–4], [USN 1–4], [GUIDE NAME], [DESIGNATION], [ACADEMIC YEAR], [DATE], [HOD NAME], verified project schedule, and genuine runtime screenshots. The final report should be reviewed by the guide and checked against the institution’s formatting and academic-integrity requirements.')

# Core document metadata and save
doc.core_properties.title='NODAL Academic Project Report'
doc.core_properties.subject='Repository-grounded report on the NODAL civic infrastructure platform'
doc.core_properties.author='[TEAM MEMBERS — EDITABLE PLACEHOLDERS]'
doc.core_properties.keywords='NODAL, civic technology, infrastructure, Flask, React, geospatial'
doc.save(OUT)
print(OUT)
