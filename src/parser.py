import os
import json
from typing import Dict, Any, List
from pypdf import PdfReader
import docx
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ReportLab imports
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT

def read_pdf(file_path: str) -> str:
    """Extract raw text from a PDF file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text.strip()

def read_docx(file_path: str) -> str:
    """Extract raw text from a DOCX file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    doc = docx.Document(file_path)
    text_parts = []
    
    # Read paragraphs
    for p in doc.paragraphs:
        if p.text:
            text_parts.append(p.text)
            
    # Read tables
    for table in doc.tables:
        for row in table.rows:
            row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if row_cells:
                text_parts.append(" | ".join(row_cells))
                
    return "\n".join(text_parts).strip()

def read_cv(file_path: str) -> str:
    """Auto-detect format and extract text from CV."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        return read_pdf(file_path)
    elif ext in ['.docx', '.doc']:
        return read_docx(file_path)
    elif ext in ['.txt', '.md']:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        raise ValueError(f"Unsupported file format: {ext}. Only PDF, DOCX, TXT, or MD are supported.")

def save_cv_as_docx(cv_data: Dict[str, Any], output_path: str) -> None:
    """Save CV JSON data to a styled DOCX file."""
    doc = docx.Document()
    
    # Set standard ATS margins (1 inch / 0.75 inch)
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)
        
    # Styles config
    # Set default font
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(11)
    
    # Header: Name
    name_p = doc.add_paragraph()
    name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_run = name_p.add_run(cv_data.get("name", "Your Name"))
    name_run.font.size = Pt(20)
    name_run.font.bold = True
    name_run.font.color.rgb = docx.shared.RGBColor(26, 26, 26)
    
    # Header: Contact Info
    contact_p = doc.add_paragraph()
    contact_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    contact_info = cv_data.get("contact_info", "")
    if isinstance(contact_info, list):
        contact_text = "  |  ".join(contact_info)
    else:
        contact_text = str(contact_info)
    
    contact_run = contact_p.add_run(contact_text)
    contact_run.font.size = Pt(9.5)
    contact_run.font.italic = False
    
    # Add a thin line under header spacing
    p_space = doc.add_paragraph()
    p_space.paragraph_format.space_after = Pt(10)
    
    # Sections
    for sec in cv_data.get("sections", []):
        title = sec.get("title", "")
        sec_type = sec.get("type", "")
        content = sec.get("content")
        
        if not title or content is None:
            continue
            
        # Section Heading
        head_p = doc.add_paragraph()
        head_p.paragraph_format.space_before = Pt(12)
        head_p.paragraph_format.space_after = Pt(4)
        head_p.paragraph_format.keep_with_next = True
        
        head_run = head_p.add_run(title.upper())
        head_run.font.size = Pt(12)
        head_run.font.bold = True
        head_run.font.color.rgb = docx.shared.RGBColor(26, 26, 26)
        
        # Add a border bottom for the heading (ATS friendly divider)
        # Using a horizontal line paragraph is cleaner in Word
        p_line = doc.add_paragraph()
        p_line.paragraph_format.space_after = Pt(6)
        p_line_run = p_line.add_run("―" * 60)
        p_line_run.font.size = Pt(6)
        p_line_run.font.color.rgb = docx.shared.RGBColor(180, 180, 180)
        
        if sec_type == "text":
            p = doc.add_paragraph(str(content))
            p.paragraph_format.space_after = Pt(8)
            p.paragraph_format.line_spacing = 1.15
            
        elif sec_type == "list":
            if isinstance(content, list):
                # Comma separated list for skills is very standard
                skills_text = ", ".join(str(item) for item in content)
                p = doc.add_paragraph(skills_text)
                p.paragraph_format.space_after = Pt(8)
                p.paragraph_format.line_spacing = 1.15
            else:
                p = doc.add_paragraph(str(content))
                p.paragraph_format.space_after = Pt(8)
                
        elif sec_type == "experience" or sec_type == "education":
            if isinstance(content, list):
                for idx, item in enumerate(content):
                    # Experience block
                    exp_p = doc.add_paragraph()
                    exp_p.paragraph_format.space_before = Pt(4) if idx > 0 else Pt(0)
                    exp_p.paragraph_format.space_after = Pt(2)
                    exp_p.paragraph_format.keep_with_next = True
                    
                    # Left side: Role/Degree (Bold) and Company/Institution (Italic)
                    if sec_type == "experience":
                        role = item.get("role", "")
                        company = item.get("company", "")
                        title_str = f"{role}"
                        company_str = f" - {company}" if company else ""
                    else:
                        degree = item.get("degree", "")
                        institution = item.get("institution", "")
                        title_str = f"{degree}"
                        company_str = f" - {institution}" if institution else ""
                        
                    period = item.get("period", "")
                    location = item.get("location", "")
                    
                    r_title = exp_p.add_run(title_str)
                    r_title.bold = True
                    
                    r_comp = exp_p.add_run(company_str)
                    r_comp.italic = True
                    
                    # Right side: Period / Location
                    # We can use tabs or write a clean single line. Word tables or right tab stops are ideal.
                    # For ATS, simple text layout is best. We'll add Period and Location inline.
                    meta_parts = []
                    if location:
                        meta_parts.append(location)
                    if period:
                        meta_parts.append(period)
                        
                    if meta_parts:
                        meta_str = f" ({', '.join(meta_parts)})"
                        r_meta = exp_p.add_run(meta_str)
                        r_meta.font.color.rgb = docx.shared.RGBColor(100, 100, 100)
                        
                    # Bullets
                    bullets = item.get("bullets", [])
                    if isinstance(bullets, list):
                        for bullet in bullets:
                            bp = doc.add_paragraph(style='List Bullet')
                            bp.paragraph_format.space_after = Pt(2)
                            bp.paragraph_format.line_spacing = 1.1
                            bp.add_run(str(bullet))
            else:
                p = doc.add_paragraph(str(content))
                p.paragraph_format.space_after = Pt(8)
                
    doc.save(output_path)

def save_cv_as_pdf(cv_data: Dict[str, Any], output_path: str) -> None:
    """Save CV JSON data to an ATS-friendly, professional PDF using ReportLab."""
    # Letter size page setup (8.5 x 11 inches)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=54,  # 0.75 inch
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    
    # Custom Styles
    style_name = ParagraphStyle(
        'CVName',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1A1A1A'),
        alignment=TA_CENTER,
        spaceAfter=6
    )
    
    style_contact = ParagraphStyle(
        'CVContact',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor('#4A4A4A'),
        alignment=TA_CENTER,
        spaceAfter=15
    )
    
    style_heading = ParagraphStyle(
        'CVHeading',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=14,
        textColor=colors.HexColor('#1A1A1A'),
        alignment=TA_LEFT,
        spaceBefore=12,
        spaceAfter=4,
        keepWithNext=True
    )
    
    style_body = ParagraphStyle(
        'CVBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#2D2D2D'),
        spaceAfter=8
    )
    
    style_bullet = ParagraphStyle(
        'CVBullet',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor('#2D2D2D'),
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=3
    )
    
    story = []
    
    # 1. Header (Name)
    story.append(Paragraph(cv_data.get("name", "Your Name"), style_name))
    
    # 2. Contact Info
    contact_info = cv_data.get("contact_info", "")
    if isinstance(contact_info, list):
        contact_text = "  |  ".join(contact_info)
    else:
        contact_text = str(contact_info)
    story.append(Paragraph(contact_text, style_contact))
    
    # 3. Sections
    for sec in cv_data.get("sections", []):
        title = sec.get("title", "")
        sec_type = sec.get("type", "")
        content = sec.get("content")
        
        if not title or content is None:
            continue
            
        # Section Header
        story.append(Paragraph(title.upper(), style_heading))
        # Thin divider line under header
        story.append(HRFlowable(
            width="100%", 
            thickness=0.5, 
            color=colors.HexColor('#CCCCCC'), 
            spaceBefore=1, 
            spaceAfter=8
        ))
        
        if sec_type == "text":
            story.append(Paragraph(str(content), style_body))
            
        elif sec_type == "list":
            if isinstance(content, list):
                skills_text = ", ".join(str(item) for item in content)
                story.append(Paragraph(skills_text, style_body))
            else:
                story.append(Paragraph(str(content), style_body))
                
        elif sec_type == "experience" or sec_type == "education":
            if isinstance(content, list):
                for idx, item in enumerate(content):
                    # Space out experience blocks
                    if idx > 0:
                        story.append(Spacer(1, 4))
                        
                    if sec_type == "experience":
                        role = item.get("role", "")
                        company = item.get("company", "")
                        title_str = f"<b>{role}</b>"
                        company_str = f" &nbsp;-&nbsp; <i>{company}</i>" if company else ""
                    else:
                        degree = item.get("degree", "")
                        institution = item.get("institution", "")
                        title_str = f"<b>{degree}</b>"
                        company_str = f" &nbsp;-&nbsp; <i>{institution}</i>" if institution else ""
                        
                    period = item.get("period", "")
                    location = item.get("location", "")
                    
                    # Create meta details
                    meta_parts = []
                    if location:
                        meta_parts.append(location)
                    if period:
                        meta_parts.append(period)
                        
                    meta_str = ""
                    if meta_parts:
                        meta_str = f" <font color='#666666'>({', '.join(meta_parts)})</font>"
                        
                    block_header = f"{title_str}{company_str}{meta_str}"
                    
                    # Section block header
                    story.append(Paragraph(block_header, ParagraphStyle(
                        'BlockHeader',
                        parent=styles['Normal'],
                        fontName='Helvetica',
                        fontSize=10,
                        leading=13,
                        spaceAfter=3,
                        keepWithNext=True
                    )))
                    
                    # Bullets
                    bullets = item.get("bullets", [])
                    if isinstance(bullets, list):
                        for bullet in bullets:
                            bullet_text = f"&bull; {bullet}"
                            story.append(Paragraph(bullet_text, style_bullet))
            else:
                story.append(Paragraph(str(content), style_body))
                
    # Build Document
    doc.build(story)
