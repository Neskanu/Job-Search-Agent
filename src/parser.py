import os
import re
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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def register_unicode_pdf_fonts():
    """
    Registers TrueType Unicode fonts in ReportLab to properly render extended UTF-8 characters 
    (such as Lithuanian ė, ų, š, ž, č, ę, į, Ū) without black box artifacts (■).
    """
    font_candidates = [
        ("ArialUnicode", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
        ("CalibriUnicode", "C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf", "C:/Windows/Fonts/calibrii.ttf"),
        ("SegoeUnicode", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeuii.ttf"),
        ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf")
    ]
    
    for family, reg_path, bold_path, ital_path in font_candidates:
        if os.path.exists(reg_path):
            try:
                pdfmetrics.registerFont(TTFont(family, reg_path))
                b_name = family + "-Bold" if os.path.exists(bold_path) else family
                i_name = family + "-Italic" if os.path.exists(ital_path) else family
                if os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont(b_name, bold_path))
                if os.path.exists(ital_path):
                    pdfmetrics.registerFont(TTFont(i_name, ital_path))
                return family, b_name, i_name
            except Exception:
                pass
                
    return 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'

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

def parse_raw_cv_to_json(cv_text: str, filename: str = "") -> Dict[str, Any]:
    """
    Parse raw extracted CV text into structured cv_data dictionary for immediate WYSIWYG rendering.
    """
    lines = [line.strip() for line in cv_text.split('\n') if line.strip()]
    if not lines:
        return {
            "name": "Candidate Name",
            "contact_info": "email@example.com | Phone",
            "sections": [
                {"title": "Summary", "type": "text", "content": "Uploaded CV document."}
            ]
        }
        
    name = lines[0]
    if len(name) > 40 or '@' in name or 'http' in name.lower():
        base = os.path.splitext(filename)[0] if filename else "Candidate"
        name = base.replace('_', ' ').replace('-', ' ').title()
        
    contact_parts = []
    for line in lines[1:5]:
        if '@' in line or re.search(r'\d{3}', line) or 'http' in line.lower() or 'linkedin' in line.lower():
            contact_parts.append(line)
            
    contact_info = " | ".join(contact_parts) if contact_parts else (lines[1] if len(lines) > 1 else "")
    
    sections = []
    current_section = None
    
    section_keywords = {
        'summary': 'Summary',
        'profile': 'Summary',
        'experience': 'Professional Experience',
        'employment': 'Professional Experience',
        'work history': 'Professional Experience',
        'education': 'Education',
        'skills': 'Skills',
        'projects': 'Projects',
        'certifications': 'Certifications'
    }
    
    body_lines = lines[1:] if len(lines) > 1 else lines
    current_bullets = []
    
    for line in body_lines:
        line_lower = line.lower()
        matched_title = None
        for kw, title in section_keywords.items():
            if line_lower == kw or line_lower == f"{kw}:" or line_lower.startswith(f"{kw} "):
                matched_title = title
                break
                
        if matched_title:
            if current_section:
                if current_bullets:
                    current_section["content"] = current_bullets
                sections.append(current_section)
            current_bullets = []
            sec_type = "list" if matched_title == "Skills" else "text"
            current_section = {"title": matched_title, "type": sec_type, "content": ""}
        else:
            if not current_section:
                current_section = {"title": "Summary", "type": "text", "content": ""}
                
            if current_section["type"] == "text":
                if current_section["content"]:
                    current_section["content"] += " " + line
                else:
                    current_section["content"] = line
            else:
                current_bullets.append(line)
                
    if current_section:
        if current_bullets:
            current_section["content"] = current_bullets
        sections.append(current_section)
        
    if not sections:
        sections = [{"title": "CV Content", "type": "text", "content": cv_text[:1000]}]
        
    return {
        "name": name,
        "contact_info": contact_info,
        "sections": sections
    }

def save_cv_as_docx(cv_data: Dict[str, Any], output_path: str, theme: str = "minimalist") -> None:
    """Save CV JSON data to a styled DOCX file."""
    doc = docx.Document()
    
    # Set margins
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)
        
    # Styles config default values
    font_name = 'Calibri'
    heading_font_name = 'Calibri'
    heading_color = docx.shared.RGBColor(26, 26, 26)
    name_color = docx.shared.RGBColor(26, 26, 26)
    line_color = docx.shared.RGBColor(180, 180, 180)
    meta_color = docx.shared.RGBColor(100, 100, 100)
    name_size = Pt(20)
    heading_size = Pt(12)
    body_size = Pt(11)
    meta_size = Pt(9.5)
    name_align = WD_ALIGN_PARAGRAPH.CENTER
    contact_align = WD_ALIGN_PARAGRAPH.CENTER
    headings_align = WD_ALIGN_PARAGRAPH.LEFT
    
    # Theme overrides
    if theme == "executive":
        font_name = 'Calibri'
        heading_font_name = 'Georgia'
        heading_color = docx.shared.RGBColor(30, 58, 138) # Dark Navy
        name_color = docx.shared.RGBColor(30, 58, 138)
        line_color = docx.shared.RGBColor(59, 130, 246) # Blue accent line
        name_align = WD_ALIGN_PARAGRAPH.LEFT
        contact_align = WD_ALIGN_PARAGRAPH.LEFT
    elif theme == "creative":
        font_name = 'Arial'
        heading_font_name = 'Arial'
        heading_color = docx.shared.RGBColor(15, 118, 110) # Teal
        name_color = docx.shared.RGBColor(15, 118, 110)
        line_color = docx.shared.RGBColor(13, 148, 136) # Teal accent line
        name_align = WD_ALIGN_PARAGRAPH.LEFT
        contact_align = WD_ALIGN_PARAGRAPH.LEFT
    elif theme == "tech":
        font_name = 'Consolas'
        heading_font_name = 'Consolas'
        heading_color = docx.shared.RGBColor(15, 23, 42) # Charcoal
        name_color = docx.shared.RGBColor(15, 23, 42)
        line_color = docx.shared.RGBColor(100, 116, 139) # Slate line
        name_align = WD_ALIGN_PARAGRAPH.LEFT
        contact_align = WD_ALIGN_PARAGRAPH.LEFT
        name_size = Pt(18)
        heading_size = Pt(11)
        body_size = Pt(10)
    elif theme == "academic":
        font_name = 'Times New Roman'
        heading_font_name = 'Times New Roman'
        heading_color = docx.shared.RGBColor(26, 26, 26)
        name_color = docx.shared.RGBColor(26, 26, 26)
        line_color = docx.shared.RGBColor(80, 80, 80)
        name_align = WD_ALIGN_PARAGRAPH.CENTER
        contact_align = WD_ALIGN_PARAGRAPH.CENTER
        headings_align = WD_ALIGN_PARAGRAPH.CENTER
        body_size = Pt(10.5)

    # Set default font on Normal style
    style = doc.styles['Normal']
    font = style.font
    font.name = font_name
    font.size = body_size
    
    # 1. Header (Name, Contact, Photo)
    photo_data = cv_data.get("photo")
    image_buf = None
    if photo_data and "," in photo_data:
        try:
            import base64
            import io
            header, encoded = photo_data.split(",", 1)
            img_bytes = base64.b64decode(encoded)
            image_buf = io.BytesIO(img_bytes)
        except Exception as img_err:
            print(f"Error parsing DOCX photo: {img_err}")

    # Process contact info text
    contact_info = cv_data.get("contact_info", "")
    if isinstance(contact_info, list):
        contact_text = "  |  ".join(contact_info)
    else:
        contact_text = str(contact_info)

    # Build Header Layout in Word
    if theme in ["minimalist", "academic"]:
        if image_buf:
            photo_p = doc.add_paragraph()
            photo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = photo_p.add_run()
            run.add_picture(image_buf, width=Inches(0.9), height=Inches(0.9))
            
        name_p = doc.add_paragraph()
        name_p.alignment = name_align
        name_run = name_p.add_run(cv_data.get("name", "Your Name"))
        name_run.font.name = heading_font_name
        name_run.font.size = name_size
        name_run.font.bold = True
        name_run.font.color.rgb = name_color
        
        contact_p = doc.add_paragraph()
        contact_p.alignment = contact_align
        contact_run = contact_p.add_run(contact_text)
        contact_run.font.name = font_name
        contact_run.font.size = meta_size
        contact_run.font.italic = False
    else:
        # Left-aligned themes with 2-column table grid for photo next to text
        if image_buf:
            header_table = doc.add_table(rows=1, cols=2)
            header_table.autofit = False
            header_table.columns[0].width = Inches(1.2)
            
            cell_photo = header_table.cell(0, 0)
            photo_p = cell_photo.paragraphs[0]
            photo_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            run = photo_p.add_run()
            run.add_picture(image_buf, width=Inches(0.9), height=Inches(0.9))
            
            cell_text = header_table.cell(0, 1)
            name_p = cell_text.paragraphs[0]
            name_p.alignment = name_align
            name_run = name_p.add_run(cv_data.get("name", "Your Name"))
            name_run.font.name = heading_font_name
            name_run.font.size = name_size
            name_run.font.bold = True
            name_run.font.color.rgb = name_color
            
            contact_p = cell_text.add_paragraph()
            contact_p.alignment = contact_align
            contact_run = contact_p.add_run(contact_text)
            contact_run.font.name = font_name
            contact_run.font.size = meta_size
            contact_run.font.italic = False
        else:
            name_p = doc.add_paragraph()
            name_p.alignment = name_align
            name_run = name_p.add_run(cv_data.get("name", "Your Name"))
            name_run.font.name = heading_font_name
            name_run.font.size = name_size
            name_run.font.bold = True
            name_run.font.color.rgb = name_color
            
            contact_p = doc.add_paragraph()
            contact_p.alignment = contact_align
            contact_run = contact_p.add_run(contact_text)
            contact_run.font.name = font_name
            contact_run.font.size = meta_size
            contact_run.font.italic = False
    
    # Add spacing under header
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
        head_p.alignment = headings_align
        head_p.paragraph_format.space_before = Pt(12)
        head_p.paragraph_format.space_after = Pt(4)
        head_p.paragraph_format.keep_with_next = True
        
        head_run = head_p.add_run(title.upper())
        head_run.font.name = heading_font_name
        head_run.font.size = heading_size
        head_run.font.bold = True
        head_run.font.color.rgb = heading_color
        
        # Add border divider bottom
        p_line = doc.add_paragraph()
        p_line.alignment = headings_align
        p_line.paragraph_format.space_after = Pt(6)
        line_chars = "―" * (45 if headings_align == WD_ALIGN_PARAGRAPH.CENTER else 60)
        p_line_run = p_line.add_run(line_chars)
        p_line_run.font.size = Pt(6)
        p_line_run.font.color.rgb = line_color
        
        if sec_type == "text":
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(8)
            p.paragraph_format.line_spacing = 1.15
            run = p.add_run(str(content))
            run.font.name = font_name
            run.font.size = body_size
            
        elif sec_type == "list":
            if isinstance(content, list):
                skills_text = ", ".join(str(item) for item in content)
            else:
                skills_text = str(content)
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(8)
            p.paragraph_format.line_spacing = 1.15
            run = p.add_run(skills_text)
            run.font.name = font_name
            run.font.size = body_size
                
        elif sec_type == "experience" or sec_type == "education":
            if isinstance(content, list):
                for idx, item in enumerate(content):
                    exp_p = doc.add_paragraph()
                    exp_p.paragraph_format.space_before = Pt(4) if idx > 0 else Pt(0)
                    exp_p.paragraph_format.space_after = Pt(2)
                    exp_p.paragraph_format.keep_with_next = True
                    
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
                    r_title.font.name = font_name
                    r_title.font.size = body_size
                    r_title.bold = True
                    
                    r_comp = exp_p.add_run(company_str)
                    r_comp.font.name = font_name
                    r_comp.font.size = body_size
                    r_comp.italic = True
                    
                    meta_parts = []
                    if location:
                        meta_parts.append(location)
                    if period:
                        meta_parts.append(period)
                        
                    if meta_parts:
                        meta_str = f" ({', '.join(meta_parts)})"
                        r_meta = exp_p.add_run(meta_str)
                        r_meta.font.name = font_name
                        r_meta.font.size = meta_size
                        r_meta.font.color.rgb = meta_color
                        
                    bullets = item.get("bullets", [])
                    if isinstance(bullets, list):
                        for bullet in bullets:
                            bp = doc.add_paragraph(style='List Bullet')
                            bp.paragraph_format.space_after = Pt(2)
                            bp.paragraph_format.line_spacing = 1.1
                            brun = bp.add_run(str(bullet))
                            brun.font.name = font_name
                            brun.font.size = body_size - Pt(1) # slightly smaller bullets
            else:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(8)
                run = p.add_run(str(content))
                run.font.name = font_name
                run.font.size = body_size
                
    doc.save(output_path)

def save_cv_as_pdf(cv_data: Dict[str, Any], output_path: str, theme: str = "minimalist") -> None:
    """Save CV JSON data to an ATS-friendly, professional PDF using ReportLab."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=54,  # 0.75 inch
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    
    # Set default values for theme using Unicode TrueType fonts
    u_reg, u_bold, u_ital = register_unicode_pdf_fonts()
    font_regular = u_reg
    font_bold = u_bold
    font_italic = u_ital
    
    name_font = u_bold
    name_size = 20
    name_leading = 24
    name_color = colors.HexColor('#1A1A1A')
    name_align = TA_CENTER
    
    contact_font = u_reg
    contact_size = 9.5
    contact_leading = 12
    contact_color = colors.HexColor('#4A4A4A')
    contact_align = TA_CENTER
    
    heading_font = u_bold
    heading_size = 12
    heading_leading = 14
    heading_color = colors.HexColor('#1A1A1A')
    heading_align = TA_LEFT
    heading_line_color = colors.HexColor('#CCCCCC')
    
    body_font = u_reg
    body_size = 10
    body_leading = 14
    body_color = colors.HexColor('#2D2D2D')
    
    bullet_font = 'Helvetica'
    bullet_size = 9.5
    bullet_leading = 13.5
    bullet_color = colors.HexColor('#2D2D2D')
    
    if theme == "executive":
        font_regular = 'Helvetica'
        font_bold = 'Helvetica-Bold'
        font_italic = 'Helvetica-Oblique'
        
        name_font = 'Times-Bold' # Elegant serif for name
        name_color = colors.HexColor('#1E3A8A') # Navy
        name_align = TA_LEFT
        
        contact_color = colors.HexColor('#475569')
        contact_align = TA_LEFT
        
        heading_font = 'Times-Bold'
        heading_color = colors.HexColor('#1E3A8A')
        heading_align = TA_LEFT
        heading_line_color = colors.HexColor('#3B82F6') # Blue line
        
    elif theme == "creative":
        font_regular = 'Helvetica'
        font_bold = 'Helvetica-Bold'
        font_italic = 'Helvetica-Oblique'
        
        name_font = 'Helvetica-Bold'
        name_color = colors.HexColor('#0F766E') # Teal
        name_align = TA_LEFT
        
        contact_color = colors.HexColor('#0D9488')
        contact_align = TA_LEFT
        
        heading_font = 'Helvetica-Bold'
        heading_color = colors.HexColor('#0F766E')
        heading_align = TA_LEFT
        heading_line_color = colors.HexColor('#14B8A6') # Teal accent line
        
    elif theme == "tech":
        font_regular = 'Courier'
        font_bold = 'Courier-Bold'
        font_italic = 'Courier-Oblique'
        
        name_font = 'Courier-Bold'
        name_size = 18
        name_leading = 22
        name_color = colors.HexColor('#0F172A') # Charcoal
        name_align = TA_LEFT
        
        contact_font = 'Courier'
        contact_color = colors.HexColor('#64748B')
        contact_align = TA_LEFT
        
        heading_font = 'Courier-Bold'
        heading_size = 11
        heading_leading = 13
        heading_color = colors.HexColor('#0F172A')
        heading_align = TA_LEFT
        heading_line_color = colors.HexColor('#64748B')
        
        body_font = 'Courier'
        body_size = 9.5
        body_leading = 13
        body_color = colors.HexColor('#334155')
        
        bullet_font = 'Courier'
        bullet_size = 9
        bullet_leading = 12.5
        bullet_color = colors.HexColor('#334155')
        
    elif theme == "academic":
        font_regular = 'Times-Roman'
        font_bold = 'Times-Bold'
        font_italic = 'Times-Italic'
        
        name_font = 'Times-Bold'
        name_size = 22
        name_leading = 26
        name_color = colors.HexColor('#000000')
        name_align = TA_CENTER
        
        contact_font = 'Times-Roman'
        contact_color = colors.HexColor('#2D2D2D')
        contact_align = TA_CENTER
        
        heading_font = 'Times-Bold'
        heading_color = colors.HexColor('#1A1A1A')
        heading_align = TA_CENTER
        heading_line_color = colors.HexColor('#1A1A1A')
        
        body_font = 'Times-Roman'
        body_size = 10.5
        body_leading = 14.5
        body_color = colors.HexColor('#1A1A1A')
        
        bullet_font = 'Times-Roman'
        bullet_size = 10
        bullet_leading = 14
        bullet_color = colors.HexColor('#1A1A1A')

    # Custom Styles
    style_name = ParagraphStyle(
        'CVName',
        parent=styles['Normal'],
        fontName=name_font,
        fontSize=name_size,
        leading=name_leading,
        textColor=name_color,
        alignment=name_align,
        spaceAfter=6
    )
    
    style_contact = ParagraphStyle(
        'CVContact',
        parent=styles['Normal'],
        fontName=contact_font,
        fontSize=contact_size,
        leading=contact_leading,
        textColor=contact_color,
        alignment=contact_align,
        spaceAfter=15
    )
    
    style_heading = ParagraphStyle(
        'CVHeading',
        parent=styles['Normal'],
        fontName=heading_font,
        fontSize=heading_size,
        leading=heading_leading,
        textColor=heading_color,
        alignment=heading_align,
        spaceBefore=12,
        spaceAfter=4,
        keepWithNext=True
    )
    
    style_body = ParagraphStyle(
        'CVBody',
        parent=styles['Normal'],
        fontName=body_font,
        fontSize=body_size,
        leading=body_leading,
        textColor=body_color,
        spaceAfter=8
    )
    
    style_bullet = ParagraphStyle(
        'CVBullet',
        parent=styles['Normal'],
        fontName=bullet_font,
        fontSize=bullet_size,
        leading=bullet_leading,
        textColor=bullet_color,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=3
    )
    
    story = []
    
    # 1. Header (Name, Contact, Photo)
    photo_data = cv_data.get("photo")
    image_flowable = None
    if photo_data and "," in photo_data:
        try:
            import base64
            import io
            from reportlab.platypus import Image
            header, encoded = photo_data.split(",", 1)
            img_bytes = base64.b64decode(encoded)
            img_buf = io.BytesIO(img_bytes)
            image_flowable = Image(img_buf, width=65, height=65)
            image_flowable.hAlign = 'CENTER'
        except Exception as img_err:
            print(f"Error parsing PDF photo: {img_err}")

    # Process contact info text
    contact_info = cv_data.get("contact_info", "")
    if isinstance(contact_info, list):
        contact_text = "  |  ".join(contact_info)
    else:
        contact_text = str(contact_info)

    # Build Header Layout based on theme and photo
    if theme == "creative":
        from reportlab.platypus import Table, TableStyle
        name_style_white = ParagraphStyle(
            'CreativeName', parent=style_name, textColor=colors.white, alignment=TA_LEFT if image_flowable else TA_CENTER
        )
        contact_style_white = ParagraphStyle(
            'CreativeContact', parent=style_contact, textColor=colors.HexColor('#CCFBF1'), alignment=TA_LEFT if image_flowable else TA_CENTER, spaceAfter=0
        )
        
        if image_flowable:
            image_flowable.hAlign = 'LEFT'
            text_story = [
                Paragraph(cv_data.get("name", "Your Name"), name_style_white),
                Paragraph(contact_text, contact_style_white)
            ]
            header_table = Table([[image_flowable, text_story]], colWidths=[80, 424])
        else:
            text_story = [
                Paragraph(cv_data.get("name", "Your Name"), name_style_white),
                Paragraph(contact_text, contact_style_white)
            ]
            header_table = Table([[text_story]], colWidths=[504])
            
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#0F766E')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 18),
            ('RIGHTPADDING', (0,0), (-1,-1), 18),
            ('TOPPADDING', (0,0), (-1,-1), 18),
            ('BOTTOMPADDING', (0,0), (-1,-1), 18),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 15))
        
    elif theme in ["minimalist", "academic"]:
        if image_flowable:
            story.append(image_flowable)
            story.append(Spacer(1, 6))
        story.append(Paragraph(cv_data.get("name", "Your Name"), style_name))
        story.append(Paragraph(contact_text, style_contact))
    else:
        # executive and tech themes (left-aligned)
        if image_flowable:
            from reportlab.platypus import Table, TableStyle
            image_flowable.hAlign = 'LEFT'
            
            text_story = [
                Paragraph(cv_data.get("name", "Your Name"), ParagraphStyle(
                    'SubName', parent=style_name, alignment=TA_LEFT, spaceAfter=2
                )),
                Paragraph(contact_text, ParagraphStyle(
                    'SubContact', parent=style_contact, alignment=TA_LEFT, spaceAfter=0
                ))
            ]
            
            header_table = Table([[image_flowable, text_story]], colWidths=[80, None])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ]))
            story.append(header_table)
            story.append(Spacer(1, 12))
        else:
            story.append(Paragraph(cv_data.get("name", "Your Name"), style_name))
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
            thickness=0.75 if theme in ["executive", "creative"] else 0.5, 
            color=heading_line_color, 
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
                        fontName=font_regular,
                        fontSize=body_size,
                        leading=body_leading - 1,
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
    if theme == "executive":
        def draw_executive_decorations(canvas, doc):
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor('#1E293B'))
            canvas.setLineWidth(6)
            canvas.line(18, 18, 18, 792 - 18)
            canvas.restoreState()
            
        doc.build(story, onFirstPage=draw_executive_decorations, onLaterPages=draw_executive_decorations)
    else:
        doc.build(story)
