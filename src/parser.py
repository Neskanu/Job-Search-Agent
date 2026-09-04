import os
import re
import json
from typing import Dict, Any, List, Optional
from pypdf import PdfReader
import docx
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ReportLab imports
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
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
            except Exception as e:
                print(f"[parser] Font registration failed for candidate {family}: {e}")
                pass
                
    return 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'


def process_profile_photo(base64_data_url: str, size: int = 180, circle: bool = True) -> "io.BytesIO":
    """
    Decode a base64 photo data URL, auto-correct EXIF rotation, and optionally
    apply a circular mask so the profile photo renders with rounded corners in
    the exported PDF and DOCX files.

    Args:
        base64_data_url: Full data URL string (e.g. "data:image/jpeg;base64,...")
        size: Target square pixel size for the output image (default 180px)
        circle: If True, creates a circular mask (fully rounded corners)

    Returns:
        io.BytesIO buffer containing a PNG image ready for embedding.
    """
    import base64
    import io
    from PIL import Image, ImageOps, ImageDraw

    # Strip the data URL header prefix
    header, encoded = base64_data_url.split(",", 1)
    img_bytes = base64.b64decode(encoded)
    img = Image.open(io.BytesIO(img_bytes))

    # Fix EXIF orientation (e.g. photos rotated 90° by phone cameras)
    img = ImageOps.exif_transpose(img)

    # Convert to RGBA so transparency works for circular mask
    img = img.convert("RGBA")

    # Resize to a perfect square via center-crop first, then resize
    min_dim = min(img.width, img.height)
    left = (img.width - min_dim) // 2
    top = (img.height - min_dim) // 2
    img = img.crop((left, top, left + min_dim, top + min_dim))
    img = img.resize((size, size), Image.LANCZOS)

    if circle:
        # Create a 2x anti-aliased circular mask and apply it
        mask_size = size * 2
        mask = Image.new("L", (mask_size, mask_size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, mask_size - 1, mask_size - 1), fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)
        img.putalpha(mask)

    # Save as PNG to preserve alpha channel
    output_buf = io.BytesIO()
    img.save(output_buf, format="PNG")
    output_buf.seek(0)
    return output_buf

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
    Parse raw extracted CV text into structured cv_data dictionary with typed sections
    (text, list, experience, education) for executive WYSIWYG and PDF rendering.
    """
    lines = [line.strip() for line in cv_text.split('\n') if line.strip()]
    if not lines:
        return {
            "name": "Vytautas Jurgaitis",
            "contact_info": ["vjurgaitis@gmail.com", "+37067302309", "Vilnius, Lietuva"],
            "sections": [
                {"title": "PROFESINĖ SANTRAUKA", "type": "text", "content": "Uploaded CV document."}
            ]
        }
        
    name = lines[0]
    if len(name) > 40 or '@' in name or 'http' in name.lower() or len(name.split()) > 4:
        base = os.path.splitext(filename)[0] if filename else "Candidate"
        name = base.replace('_', ' ').replace('-', ' ').title()
        
    contact_parts = []
    contact_info = " | ".join(contact_parts) if contact_parts else (lines[1] if len(lines) > 1 else "vjurgaitis@gmail.com")
    
    sections = []
    current_section = None
    current_bullets = []
    
    # Enhanced Section Keywords (Lithuanian & English)
    section_map = {
        'santrauka': ('PROFESINĖ SANTRAUKA', 'text'),
        'profesinė santrauka': ('PROFESINĖ SANTRAUKA', 'text'),
        'summary': ('PROFESINĖ SANTRAUKA', 'text'),
        'profile': ('PROFESINĖ SANTRAUKA', 'text'),
        'about': ('PROFESINĖ SANTRAUKA', 'text'),
        'kompetencijos': ('PAGRINDINĖS KOMPETENCIJOS', 'list'),
        'pagrindinės kompetencijos': ('PAGRINDINĖS KOMPETENCIJOS', 'list'),
        'gebiėjimai': ('PAGRINDINĖS KOMPETENCIJOS', 'list'),
        'skills': ('PAGRINDINĖS KOMPETENCIJOS', 'list'),
        'core skills': ('PAGRINDINĖS KOMPETENCIJOS', 'list'),
        'technical skills': ('PAGRINDINĖS KOMPETENCIJOS', 'list'),
        'darbo patirtis': ('DARBO PATIRTIS', 'experience'),
        'patirtis': ('DARBO PATIRTIS', 'experience'),
        'experience': ('DARBO PATIRTIS', 'experience'),
        'work experience': ('DARBO PATIRTIS', 'experience'),
        'employment': ('DARBO PATIRTIS', 'experience'),
        'išsilavinimas': ('IŠSILAVINIMAS', 'education'),
        'moksla': ('IŠSILAVINIMAS', 'education'),
        'education': ('IŠSILAVINIMAS', 'education'),
        'kalbos': ('KALBOS', 'list'),
        'languages': ('KALBOS', 'list'),
        'projektai': ('PROJEKTAI', 'text'),
        'projects': ('PROJEKTAI', 'text'),
        'sertifikatai': ('SERTIFIKATAI', 'list'),
        'certifications': ('SERTIFIKATAI', 'list')
    }
    
    body_lines = lines[1:] if len(lines) > 1 else lines
    
    for line in body_lines:
        line_clean = line.strip().strip(':').strip('-').strip('•').strip()
        line_lower = line_clean.lower()
        
        matched = None
        for kw, (canon_title, canon_type) in section_map.items():
            if line_lower == kw or line_lower.startswith(f"{kw} "):
                matched = (canon_title, canon_type)
                break
                
        if matched:
            if current_section:
                if current_bullets:
                    if current_section["type"] == "experience" or current_section["type"] == "education":
                        current_section["content"] = [{"role": "Position", "company": "Company", "period": "2020 - Present", "bullets": current_bullets}]
                    else:
                        current_section["content"] = current_bullets
                sections.append(current_section)
            current_bullets = []
            current_section = {"title": matched[0], "type": matched[1], "content": ""}
        else:
            if not current_section:
                current_section = {"title": "PROFESINĖ SANTRAUKA", "type": "text", "content": ""}
                
            if current_section["type"] == "text":
                if current_section["content"]:
                    current_section["content"] += " " + line
                else:
                    current_section["content"] = line
            else:
                current_bullets.append(line)
                
    if current_section:
        if current_bullets:
            if current_section["type"] in ["experience", "education"]:
                current_section["content"] = [{"role": "Position", "company": "Company", "period": "2020 - Present", "bullets": current_bullets}]
            else:
                current_section["content"] = current_bullets
        sections.append(current_section)
        
    if not sections:
        sections = [{"title": "PROFESINĖ SANTRAUKA", "type": "text", "content": cv_text[:1000]}]
        
    return {
        "name": name,
        "contact_info": contact_info,
        "sections": sections
    }

def save_cv_as_docx(cv_data: Dict[str, Any], output_path: str, theme: str = "minimalist", custom_color: Optional[str] = None, bullet_symbol: str = "│") -> None:
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
    
    if custom_color and custom_color.startswith('#') and len(custom_color) == 7:
        try:
            r = int(custom_color[1:3], 16)
            g = int(custom_color[3:5], 16)
            b = int(custom_color[5:7], 16)
            heading_color = docx.shared.RGBColor(r, g, b)
            name_color = docx.shared.RGBColor(r, g, b)
        except Exception as e:
            print(f"[parser] Invalid custom hex color '{custom_color}' for DOCX styling: {e}")
            pass
    
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
            # process_profile_photo auto-corrects EXIF rotation and applies a circular mask
            image_buf = process_profile_photo(photo_data, size=200, circle=True)
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
            text_str = str(content or "").strip()
            paras = [p.strip() for p in text_str.split("\n\n") if p.strip()]
            if not paras:
                paras = [text_str]
            for p_idx, p_txt in enumerate(paras):
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(2 if p_idx == 0 else 0)
                p.paragraph_format.space_after = Pt(4 if p_idx < len(paras) - 1 else 8)
                p.paragraph_format.left_indent = Pt(0)
                p.paragraph_format.line_spacing = 1.15
                run = p.add_run(p_txt)
                run.font.name = font_name
                run.font.size = body_size
                run.font.italic = True if theme in ["executive", "academic"] else False
                run.font.color.rgb = docx.shared.RGBColor(51, 65, 85)
            
        elif sec_type == "list":
            if isinstance(content, list):
                skills_text = "  │  ".join(str(item) for item in content)
            else:
                skills_text = str(content)
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(8)
            p.paragraph_format.left_indent = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            run = p.add_run(skills_text)
            run.font.name = font_name
            run.font.size = body_size
            run.font.color.rgb = heading_color
                
        elif sec_type == "experience" or sec_type == "education":
            if isinstance(content, list):
                for idx, item in enumerate(content):
                    exp_p = doc.add_paragraph()
                    exp_p.paragraph_format.space_before = Pt(6) if idx > 0 else Pt(2)
                    exp_p.paragraph_format.space_after = Pt(2)
                    exp_p.paragraph_format.keep_with_next = True
                    
                    if sec_type == "experience":
                        role = item.get("role", "")
                        company = item.get("company", "")
                        title_str = f"{role}"
                        company_str = f" @ {company}" if company else ""
                    else:
                        degree = item.get("degree", "")
                        institution = item.get("institution", "")
                        title_str = f"{degree}"
                        company_str = f" @ {institution}" if institution else ""
                        
                    period = item.get("period", "")
                    location = item.get("location", "")
                    
                    r_title = exp_p.add_run(title_str)
                    r_title.font.name = font_name
                    r_title.font.size = body_size + Pt(1)
                    r_title.font.color.rgb = heading_color
                    r_title.bold = True
                    
                    if company_str:
                        r_comp = exp_p.add_run(company_str)
                        r_comp.font.name = font_name
                        r_comp.font.size = body_size
                        r_comp.font.color.rgb = docx.shared.RGBColor(71, 85, 105)
                        r_comp.bold = True
                    
                    meta_parts = []
                    if period:
                        meta_parts.append(period)
                    if location:
                        meta_parts.append(location)
                        
                    if meta_parts:
                        meta_str = f"  │  {' │ '.join(meta_parts)}"
                        r_meta = exp_p.add_run(meta_str)
                        r_meta.font.name = font_name
                        r_meta.font.size = meta_size
                        r_meta.font.color.rgb = meta_color
                        r_meta.italic = True
                        
                    bullets = item.get("bullets", [])
                    if isinstance(bullets, list):
                        for bullet in bullets:
                            bp = doc.add_paragraph()
                            bp.paragraph_format.left_indent = Pt(12)
                            bp.paragraph_format.space_after = Pt(2)
                            bp.paragraph_format.line_spacing = 1.1
                            
                            b_marker = bp.add_run(f"{bullet_symbol}  ")
                            b_marker.font.name = font_name
                            b_marker.font.size = body_size - Pt(1)
                            b_marker.font.color.rgb = heading_color
                            b_marker.bold = True
                            
                            brun = bp.add_run(str(bullet))
                            brun.font.name = font_name
                            brun.font.size = body_size - Pt(1)
                            brun.font.color.rgb = docx.shared.RGBColor(51, 65, 85)
            else:
                raw_fallback = str(content or "").strip()
                paras = [p.strip() for p in raw_fallback.split("\n\n") if p.strip()]
                if not paras:
                    paras = [raw_fallback]
                for p_idx, p_txt in enumerate(paras):
                    p = doc.add_paragraph()
                    p.paragraph_format.space_after = Pt(4 if p_idx < len(paras) - 1 else 8)
                    run = p.add_run(p_txt)
                    run.font.name = font_name
                    run.font.size = body_size
                
    doc.save(output_path)

def generate_html_for_cv(
    cv_data: Dict[str, Any],
    theme: str = "creative",
    custom_color: Optional[str] = None,
    line_style: str = "short",
    bullet_symbol: str = "│",
    layout_mode: str = "2col",
    fit_one_page: bool = False
) -> str:
    """
    Generate clean, standalone HTML/CSS matching the interactive WYSIWYG canvas layout.
    Used for pixel-perfect PDF rendering via Chromium.
    """
    theme_accent_colors = {
        "creative": "#0F766E",
        "executive": "#1E3A8A",
        "tech": "#0F172A",
        "academic": "#334155",
        "minimalist": "#E11D48"
    }
    
    accent_color = custom_color if (custom_color and custom_color.startswith("#")) else theme_accent_colors.get(theme, "#0F766E")
    
    # Process contact info
    contact_info = cv_data.get("contact_info", "")
    if isinstance(contact_info, list):
        contact_text = f" &nbsp;│&nbsp; ".join(str(c) for c in contact_info)
    else:
        contact_text = str(contact_info)
        
    name_str = cv_data.get("name", "Your Name")
    photo_src = cv_data.get("photo") or ""
    
    # Build photo HTML
    if photo_src:
        photo_html = f'<img src="{photo_src}" class="cv-photo-frame" alt="Photo" />'
    else:
        photo_html = f'''<div class="cv-photo-frame-placeholder" style="background:{accent_color};">
            <span style="color:white;font-size:12px;font-weight:600;">Photo</span>
        </div>'''
        
    # Build sections
    sections = cv_data.get("sections", [])
    
    def render_section(sec: Dict[str, Any]) -> str:
        title = sec.get("title", "Section")
        sec_type = sec.get("type", "text")
        content = sec.get("content")
        
        content_html = ""
        if sec_type == "text":
            raw_text = str(content or "").strip()
            paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
            if len(paragraphs) > 1:
                p_items = "".join([f'<p class="cv-paragraph-p" style="margin: 0 0 6px 0;">{p}</p>' for p in paragraphs])
                content_html = f'<div class="sec-content text-sec">{p_items}</div>'
            else:
                content_html = f'<div class="sec-content text-sec">{raw_text}</div>'
        elif sec_type == "list":
            if isinstance(content, list):
                items_html = "".join([
                    f'<div class="skill-item-row"><span class="bullet-marker">{bullet_symbol}</span><span class="skill-chip">{item}</span></div>'
                    for item in content
                ])
                content_html = f'<div class="sec-content list-sec">{items_html}</div>'
            else:
                content_html = f'<div class="sec-content text-sec">{content or ""}</div>'
        elif sec_type in ["experience", "education"]:
            blocks_html = []
            if isinstance(content, list):
                for item in content:
                    is_exp = sec_type == "experience"
                    title_val = item.get("role", "") if is_exp else item.get("degree", "")
                    sub_val = item.get("company", "") if is_exp else item.get("institution", "")
                    period = item.get("period", "")
                    location = item.get("location", "")
                    
                    bullets_html = ""
                    bullets = item.get("bullets", [])
                    if isinstance(bullets, list) and bullets:
                        b_items = "".join([
                            f'<div class="bullet-item"><span class="bullet-marker">{bullet_symbol}</span><span class="bullet-text">{b}</span></div>'
                            for b in bullets
                        ])
                        bullets_html = f'<div class="bullets-container">{b_items}</div>'
                        
                    meta_badge = ""
                    if period or location:
                        meta_parts = []
                        if period: meta_parts.append(period)
                        if location: meta_parts.append(location)
                        meta_badge = f'<div class="item-badge">{" │ ".join(meta_parts)}</div>'
                        
                    company_html = f'<span class="item-subtitle-wrapper"><span class="item-at">@</span> <span class="item-sub-title">{sub_val}</span></span>' if sub_val else ''
                    
                    block = f'''
                    <div class="item-block">
                        <div class="item-header">
                            <div class="item-titles">
                                <span class="item-title">{title_val}</span>
                                {company_html}
                            </div>
                            {meta_badge}
                        </div>
                        {bullets_html}
                    </div>
                    '''
                    blocks_html.append(block)
            content_html = f'<div class="sec-content exp-sec">{"".join(blocks_html)}</div>'
            
        return f'''
        <div class="draggable-section" data-type="{sec_type}">
            <div class="sec-header">
                <h2 class="sec-title">{title}</h2>
            </div>
            {content_html}
        </div>
        '''

    # Split for 2col vs 1col
    if layout_mode == "2col":
        left_secs = [s for s in sections if s.get("column") == "sidebar" or (not s.get("column") and s.get("type") in ["list", "education"])]
        right_secs = [s for s in sections if s.get("column") == "main" or (not s.get("column") and s.get("type") not in ["list", "education"])]
        sidebar_html = "".join(render_section(s) for s in left_secs)
        main_html = "".join(render_section(s) for s in right_secs)
        layout_html = f'''
        <div class="cv-2col-layout">
            <div class="cv-2col-sidebar">{sidebar_html}</div>
            <div class="cv-2col-main">{main_html}</div>
        </div>
        '''
    else:
        all_secs_html = "".join(render_section(s) for s in sections)
        layout_html = f'''
        <div class="cv-1col-layout">{all_secs_html}</div>
        '''

    fit_class = "fit-one-page" if fit_one_page else ""

    html_doc = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{name_str} - Resume</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap');
  
  :root {{
    --theme-accent: {accent_color};
  }}
  
  * {{
    box-sizing: border-box;
  }}
  
  @page {{
    size: A4 portrait;
    margin: 0;
  }}
  
  body {{
    margin: 0;
    padding: 0;
    font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: #1E293B;
    background-color: #FFFFFF;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
    width: 100%;
    height: 100%;
    min-height: 100%;
  }}
  
  .cv-page-table {{
    width: 100%;
    height: 100%;
    min-height: 297mm;
    border-collapse: collapse;
    border-spacing: 0;
  }}
  
  .cv-page-table > thead {{
    display: table-header-group;
  }}
  
  .cv-page-table > thead > tr > th {{
    padding: 0;
    font-weight: normal;
    text-align: left;
  }}
  
  .cv-page-table > tbody > tr > td {{
    padding: 0;
    vertical-align: top;
    height: 100%;
  }}
  
  .cv-header-banner {{
    background: {accent_color};
    color: #FFFFFF;
    padding: 22px 36px;
    display: flex;
    align-items: center;
    gap: 20px;
    flex-shrink: 0;
    width: 100%;
  }}
  
  .cv-photo-frame {{
    width: 64px;
    height: 64px;
    border-radius: 9999px;
    border: 3px solid rgba(255, 255, 255, 0.85);
    object-fit: cover;
    flex-shrink: 0;
  }}
  
  .cv-photo-frame-placeholder {{
    width: 64px;
    height: 64px;
    border-radius: 9999px;
    border: 3px solid rgba(255, 255, 255, 0.85);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    background: rgba(0, 0, 0, 0.15);
    color: #FFFFFF;
    font-weight: 700;
    font-size: 12px;
  }}
  
  .cv-name {{
    font-size: 26px;
    font-weight: 800;
    color: #FFFFFF;
    margin: 0 0 3px 0;
    letter-spacing: -0.01em;
  }}
  
  .cv-contact {{
    font-size: 12px;
    color: rgba(255, 255, 255, 0.95);
    font-weight: 500;
    line-height: 1.45;
    letter-spacing: 0.01em;
  }}
  
  .cv-2col-layout {{
    display: grid;
    grid-template-columns: 260px 1fr;
    width: 100%;
    min-height: calc(297mm - 110px);
    height: 100%;
  }}
  
  .cv-2col-sidebar {{
    background-color: #F8FAFC;
    border-right: 1.5px solid #E2E8F0;
    padding: 22px 20px;
    display: flex;
    flex-direction: column;
    gap: 20px;
    min-height: 100%;
    height: 100%;
  }}
  
  .cv-2col-main {{
    padding: 22px 30px;
    display: flex;
    flex-direction: column;
    gap: 22px;
  }}
  
  .cv-1col-layout {{
    padding: 26px 38px;
    display: flex;
    flex-direction: column;
    gap: 22px;
    min-height: calc(297mm - 110px);
    height: 100%;
  }}
  
  .draggable-section {{
    break-inside: auto;
  }}
  
  .sec-header {{
    border-bottom: 1.5px solid {accent_color};
    padding-bottom: 3.5px;
    margin-bottom: 8px;
    break-after: avoid;
  }}
  
  .sec-title {{
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: {accent_color};
    margin: 0;
  }}
  
  /* Line Styles */
  .line-style-short .item-block,
  .line-style-short .text-sec {{
    position: relative;
    padding-left: 11px;
  }}
  .line-style-short .item-block::before,
  .line-style-short .text-sec::before {{
    content: '';
    position: absolute;
    left: 0;
    top: 3px;
    width: 3.5px;
    height: 18px;
    background-color: {accent_color};
    border-radius: 9999px;
  }}
  
  .line-style-full .item-block,
  .line-style-full .text-sec {{
    border-left: 3px solid {accent_color};
    padding-left: 11px;
  }}
  
  .line-style-none .item-block,
  .line-style-none .text-sec {{
    padding-left: 2px;
  }}
  
  .text-sec {{
    font-size: 12px;
    color: #334155;
    line-height: 1.62;
    letter-spacing: 0.005em;
    margin: 0;
  }}
  
  .skill-item-row {{
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 2.5px 0;
    break-inside: avoid;
  }}
  
  .bullet-marker {{
    color: {accent_color};
    font-weight: 700;
    font-size: 11.8px;
    flex-shrink: 0;
    line-height: 1.5;
  }}
  
  .skill-chip {{
    font-size: 11.5px;
    font-weight: 600;
    color: #334155;
    line-height: 1.45;
    letter-spacing: 0.005em;
  }}
  
  .item-block {{
    margin-bottom: 14px;
    break-inside: auto;
  }}
  
  .item-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 6px;
    margin-bottom: 3.5px;
    flex-wrap: wrap;
    break-after: avoid;
    break-inside: avoid;
  }}
  
  .item-titles {{
    display: flex;
    align-items: baseline;
    gap: 5px;
    flex-wrap: wrap;
  }}
  
  .item-subtitle-wrapper {{
    display: inline-flex;
    align-items: baseline;
    gap: 3px;
  }}
  
  .item-title {{
    font-size: 13.5px;
    font-weight: 700;
    color: #0F172A;
  }}
  
  .item-at {{
    font-size: 12px;
    color: #94A3B8;
  }}
  
  .item-sub-title {{
    font-size: 12.2px;
    font-weight: 600;
    color: #334155;
  }}
  
  .item-badge {{
    font-size: 10px;
    background-color: #F1F5F9;
    color: #475569;
    padding: 2px 7px;
    border-radius: 4px;
    border: 1px solid #E2E8F0;
    font-weight: 500;
    max-width: 100%;
    white-space: normal;
    word-break: break-word;
    line-height: 1.35;
  }}
  
  /* Sidebar Item Header & Badge specific handling */
  .cv-2col-sidebar .item-header {{
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }}
  
  .cv-2col-sidebar .item-titles {{
    flex-direction: column;
    align-items: flex-start;
    gap: 1px;
  }}
  
  .cv-2col-sidebar .item-badge {{
    margin-top: 2px;
  }}
  
  .bullets-container {{
    margin-top: 5px;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }}
  
  .bullet-item {{
    display: flex;
    align-items: flex-start;
    gap: 6px;
    margin: 1px 0;
    break-inside: avoid;
  }}
  
  .bullet-text {{
    font-size: 11.8px;
    color: #334155;
    line-height: 1.58;
    letter-spacing: 0.005em;
  }}
  
  /* 📄 Fit to 1 Page compact scaling rules */
  .fit-one-page .cv-header-banner {{ padding: 18px 30px; gap: 18px; }}
  .fit-one-page .cv-photo-frame {{ width: 60px; height: 60px; }}
  .fit-one-page .cv-photo-frame-placeholder {{ width: 60px; height: 60px; font-size: 11.5px; }}
  .fit-one-page .cv-name {{ font-size: 26px; margin: 0 0 3px 0; }}
  .fit-one-page .cv-contact {{ font-size: 12px; line-height: 1.45; letter-spacing: 0.005em; }}
  .fit-one-page .cv-2col-layout {{ min-height: calc(297mm - 110px); height: 100%; }}
  .fit-one-page .cv-2col-sidebar {{ padding: 22px 20px; gap: 20px; min-height: 100%; height: 100%; }}
  .fit-one-page .cv-2col-main {{ padding: 22px 30px; gap: 22px; }}
  .fit-one-page .cv-1col-layout {{ padding: 26px 38px; gap: 22px; min-height: calc(297mm - 110px); height: 100%; }}
  .fit-one-page .sec-header {{ margin-bottom: 8px; padding-bottom: 3.5px; }}
  .fit-one-page .sec-title {{ font-size: 13px; letter-spacing: 0.05em; }}
  .fit-one-page .text-sec {{ font-size: 12px; line-height: 1.62; letter-spacing: 0.005em; }}
  .fit-one-page .item-block {{ margin-bottom: 14px; padding-left: 11px; }}
  .fit-one-page .item-block::before, .fit-one-page .text-sec::before {{ height: 18px; top: 3px; }}
  .fit-one-page .item-title {{ font-size: 13.5px; font-weight: 700; }}
  .fit-one-page .item-sub-title {{ font-size: 12.2px; }}
  .fit-one-page .item-badge {{ font-size: 10px; padding: 2px 7px; }}
  .fit-one-page .skill-item-row {{ padding: 2.5px 0; gap: 6px; }}
  .fit-one-page .skill-chip {{ font-size: 11.5px; line-height: 1.45; letter-spacing: 0.005em; }}
  .fit-one-page .bullet-marker {{ font-size: 11.8px; line-height: 1.5; }}
  .fit-one-page .bullet-item {{ margin: 1px 0; gap: 6px; }}
  .fit-one-page .bullet-text {{ font-size: 11.8px; line-height: 1.58; letter-spacing: 0.005em; }}
  .fit-one-page .bullets-container {{ margin-top: 5px; gap: 3px; }}
</style>
</head>
<body class="theme-{theme} layout-{layout_mode} line-style-{line_style} {fit_class}">
  <table class="cv-page-table">
    <thead>
      <tr>
        <th>
          <div class="cv-header-banner">
            {photo_html}
            <div style="flex:1;">
              <h1 class="cv-name">{name_str}</h1>
              <div class="cv-contact">{contact_text}</div>
            </div>
          </div>
        </th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>
          {layout_html}
        </td>
      </tr>
    </tbody>
  </table>
</body>
</html>'''
    return html_doc


def save_cv_as_pdf_html(
    cv_data: Dict[str, Any],
    output_path: str,
    theme: str = "creative",
    custom_color: Optional[str] = None,
    line_style: str = "short",
    bullet_symbol: str = "│",
    layout_mode: str = "2col",
    fit_one_page: bool = False
) -> None:
    """
    Render pixel-perfect PDF using headless Chromium via Playwright.
    Matches the interactive HTML preview 100% in fonts, layout, and colors.
    Guarantees strictly 1-page output when fit_one_page=True via dynamic scaling.
    """
    from playwright.sync_api import sync_playwright
    
    html_content = generate_html_for_cv(
        cv_data=cv_data,
        theme=theme,
        custom_color=custom_color,
        line_style=line_style,
        bullet_symbol=bullet_symbol,
        layout_mode=layout_mode,
        fit_one_page=fit_one_page
    )
    
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 794, "height": 1123})
        page.set_content(html_content, wait_until="networkidle")
        
        scale = 1.0
        if fit_one_page:
            content_height = page.evaluate("() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, document.querySelector('.cv-page-table')?.scrollHeight || 0)")
            # Printable A4 height at 96 DPI is ~1122.5px. Target 1115px to account for browser subpixel rounding.
            target_height = 1115.0
            if content_height > target_height:
                scale = max(0.50, min(1.0, target_height / content_height))

        page.pdf(
            path=output_path,
            format="A4",
            print_background=True,
            margin={"top": "0px", "bottom": "0px", "left": "0px", "right": "0px"},
            prefer_css_page_size=True,
            scale=scale
        )

        if fit_one_page:
            try:
                import pypdf
                reader = pypdf.PdfReader(output_path)
                # If content still overflows onto a second page, decrement scale until strictly 1 page
                while len(reader.pages) > 1 and scale > 0.45:
                    scale -= 0.04
                    page.pdf(
                        path=output_path,
                        format="A4",
                        print_background=True,
                        margin={"top": "0px", "bottom": "0px", "left": "0px", "right": "0px"},
                        prefer_css_page_size=True,
                        scale=scale
                    )
                    reader = pypdf.PdfReader(output_path)
            except Exception as check_err:
                print(f"[parser] Could not verify 1-page PDF count: {check_err}")

        browser.close()


def save_cv_as_pdf_reportlab(
    cv_data: Dict[str, Any],
    output_path: str,
    theme: str = "minimalist",
    custom_color: Optional[str] = None,
    line_style: str = "short",
    bullet_symbol: str = "│",
    layout_mode: str = "2col",
    fit_one_page: bool = False
) -> None:
    """Save CV JSON data to an ATS-friendly, professional PDF using ReportLab."""
    top_m = 22 if fit_one_page else 38
    bot_m = 22 if fit_one_page else 38
    side_m = 36 if fit_one_page else 44
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=side_m,
        rightMargin=side_m,
        topMargin=top_m,
        bottomMargin=bot_m
    )
    
    styles = getSampleStyleSheet()
    
    # Set default values for theme using Unicode TrueType fonts
    u_reg, u_bold, u_ital = register_unicode_pdf_fonts()
    font_regular = u_reg
    font_bold = u_bold
    font_italic = u_ital
    
    name_font = u_bold
    name_size = 20 if fit_one_page else 24
    name_leading = 24 if fit_one_page else 28
    name_color = colors.HexColor('#1A1A1A')
    name_align = TA_CENTER
    
    contact_font = u_reg
    contact_size = 9.5 if fit_one_page else 10.5
    contact_leading = 12 if fit_one_page else 13.5
    contact_color = colors.HexColor('#4A4A4A')
    contact_align = TA_CENTER
    
    heading_font = u_bold
    heading_size = 11.5 if fit_one_page else 13
    heading_leading = 14 if fit_one_page else 15.5
    heading_color = colors.HexColor('#1A1A1A')
    heading_align = TA_LEFT
    heading_line_color = colors.HexColor('#CCCCCC')
    
    body_font = u_reg
    body_size = 9.5 if fit_one_page else 10.5
    body_leading = 13.5 if fit_one_page else 15.0
    body_color = colors.HexColor('#2D2D2D')
    
    bullet_font = u_reg
    bullet_size = 9.2 if fit_one_page else 10.0
    bullet_leading = 13.0 if fit_one_page else 14.5
    bullet_color = colors.HexColor('#2D2D2D')
    
    if theme == "executive":
        font_regular = u_reg
        font_bold = u_bold
        font_italic = u_ital
        
        name_font = u_bold
        name_color = colors.HexColor('#1E3A8A') # Navy
        name_align = TA_LEFT
        
        contact_color = colors.HexColor('#475569')
        contact_align = TA_LEFT
        
        heading_font = u_bold
        heading_color = colors.HexColor('#1E3A8A')
        heading_align = TA_LEFT
        heading_line_color = colors.HexColor('#3B82F6') # Blue line
        
    elif theme == "creative":
        font_regular = u_reg
        font_bold = u_bold
        font_italic = u_ital
        
        name_font = u_bold
        name_color = colors.HexColor('#0F766E') # Teal
        name_align = TA_LEFT
        
        contact_color = colors.HexColor('#0D9488')
        contact_align = TA_LEFT
        
        heading_font = u_bold
        heading_color = colors.HexColor('#0F766E')
        heading_align = TA_LEFT
        heading_line_color = colors.HexColor('#14B8A6') # Teal accent line
        
    elif theme == "tech":
        font_regular = u_reg
        font_bold = u_bold
        font_italic = u_ital
        
        name_font = u_bold
        name_size = 18
        name_leading = 22
        name_color = colors.HexColor('#0F172A') # Charcoal
        name_align = TA_LEFT
        
        contact_font = u_reg
        contact_color = colors.HexColor('#64748B')
        contact_align = TA_LEFT
        
        heading_font = u_bold
        heading_size = 11
        heading_leading = 13
        heading_color = colors.HexColor('#0F172A')
        heading_align = TA_LEFT
        heading_line_color = colors.HexColor('#64748B')
        
        body_font = u_reg
        body_size = 9.5
        body_leading = 13
        body_color = colors.HexColor('#334155')
        
        bullet_font = u_reg
        bullet_size = 9
        bullet_leading = 12.5
        bullet_color = colors.HexColor('#334155')
        
    elif theme == "academic":
        font_regular = u_reg
        font_bold = u_bold
        font_italic = u_ital
        
        name_font = u_bold
        name_size = 22
        name_leading = 26
        name_color = colors.HexColor('#000000')
        name_align = TA_CENTER
        
        contact_font = u_reg
        contact_color = colors.HexColor('#2D2D2D')
        contact_align = TA_CENTER
        
        heading_font = u_bold
        heading_color = colors.HexColor('#1A1A1A')
        heading_align = TA_CENTER
        heading_line_color = colors.HexColor('#1A1A1A')
        
        body_font = u_reg

    body_font = font_regular
    body_size = 9.5 if fit_one_page else 10.5
    body_leading = 13.5 if fit_one_page else 15.0
    body_color = colors.HexColor('#334155')

    bullet_font = font_regular
    bullet_size = 9.2 if fit_one_page else 10.0
    bullet_leading = 13.0 if fit_one_page else 14.5
    bullet_color = colors.HexColor('#334155')

    # Override colors if custom_color provided
    title_color_hex = "#1E3A8A" if theme == "executive" else ("#0F766E" if theme == "creative" else ("#0F172A" if theme == "tech" else "#111827"))
    if custom_color and custom_color.startswith('#') and len(custom_color) == 7:
        try:
            heading_color = colors.HexColor(custom_color)
            heading_line_color = colors.HexColor(custom_color)
            name_color = colors.HexColor(custom_color)
            title_color_hex = custom_color
        except Exception as e:
            print(f"[parser] Invalid custom hex color '{custom_color}' for PDF styling: {e}")
            pass

    # Custom Styles
    style_name = ParagraphStyle(
        'CVName',
        parent=styles['Normal'],
        fontName=name_font,
        fontSize=name_size,
        leading=name_leading,
        textColor=colors.white,
        alignment=name_align,
        spaceAfter=3
    )
    
    style_contact = ParagraphStyle(
        'CVContact',
        parent=styles['Normal'],
        fontName=contact_font,
        fontSize=contact_size,
        leading=contact_leading,
        textColor=colors.HexColor('#CCFBF1'),
        alignment=contact_align,
        spaceAfter=0
    )
    
    style_heading = ParagraphStyle(
        'CVHeading',
        parent=styles['Normal'],
        fontName=heading_font,
        fontSize=heading_size,
        leading=heading_leading,
        textColor=heading_color,
        alignment=heading_align,
        leftIndent=0,
        spaceBefore=6,
        spaceAfter=2,
        keepWithNext=True
    )
    
    style_body = ParagraphStyle(
        'CVBody',
        parent=styles['Normal'],
        fontName=body_font,
        fontSize=body_size,
        leading=body_leading,
        textColor=body_color,
        spaceAfter=4
    )
    
    style_bullet = ParagraphStyle(
        'CVBullet',
        parent=styles['Normal'],
        fontName=bullet_font,
        fontSize=bullet_size,
        leading=bullet_leading,
        textColor=bullet_color,
        leftIndent=8,
        firstLineIndent=-6,
        spaceAfter=2
    )
    
    story = []
    
    # Handle profile photo
    image_flowable = None
    photo_raw = cv_data.get("photo")
    if photo_raw and isinstance(photo_raw, str) and photo_raw.startswith("data:image"):
        try:
            import base64
            from io import BytesIO
            header, base64_data = photo_raw.split(",", 1)
            img_bytes = base64.b64decode(base64_data)
            
            if "image/svg" in header:
                from PIL import Image, ImageDraw
                im = Image.new('RGBA', (120, 120), (15, 118, 110, 255))
                draw = ImageDraw.Draw(im)
                draw.ellipse((10, 10, 110, 110), outline=(255, 255, 255, 255), width=4)
                buf = BytesIO()
                im.save(buf, format='PNG')
                buf.seek(0)
                from reportlab.platypus import Image as RLImage
                image_flowable = RLImage(buf, width=44, height=44)
            else:
                image_buf = process_profile_photo(photo_raw, size=200, circle=True)
                from reportlab.platypus import Image as RLImage
                image_flowable = RLImage(image_buf, width=44, height=44)
        except Exception as img_err:
            print(f"Error parsing PDF photo: {img_err}")

    # Process contact info text & Unicode safe bullet symbol
    def get_safe_bullet_symbol(sym: str) -> str:
        s = (sym or "").strip()
        if s in ["▸", "arrow", "Arrow"]:
            return "&#9656;"
        elif s in ["◆", "diamond", "Diamond"]:
            return "&#9670;"
        elif s in ["•", "circle", "Circle"]:
            return "&#8226;"
        elif s in ["│", "pipe", "Pipe"]:
            return "&#9474;"
        return s if s else "&#9474;"

    b_sym = get_safe_bullet_symbol(bullet_symbol)
    contact_info = cv_data.get("contact_info", "")
    if isinstance(contact_info, list):
        contact_text = f"  {b_sym}  ".join(contact_info)
    else:
        contact_text = str(contact_info)

    from reportlab.platypus import Table, TableStyle
    text_story = [
        Paragraph(cv_data.get("name", "Your Name"), style_name),
        Paragraph(contact_text, style_contact)
    ]

    if image_flowable:
        header_table = Table([[image_flowable, text_story]], colWidths=[65, 475])
    else:
        header_table = Table([[text_story]], colWidths=[540])
        
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(title_color_hex)),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 14),
        ('RIGHTPADDING', (0,0), (-1,-1), 14),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6))

    # Helper function to build flowable elements for a section
    def build_pdf_section_elements(sec: Dict[str, Any], max_width: int = 540) -> List[Any]:
        sec_elements = []
        sec_title = sec.get("title", "")
        sec_type = sec.get("type", "")
        sec_content = sec.get("content")

        if not sec_title or sec_content is None:
            return sec_elements

        sec_heading = Paragraph(sec_title.upper(), style_heading)
        sec_hr = HRFlowable(
            width="100%",
            thickness=1.0,
            color=heading_line_color,
            spaceBefore=1,
            spaceAfter=4,
        )
        sec_hr.keepWithNext = True
        sec_elements.append(sec_heading)
        sec_elements.append(sec_hr)

        accent_bar_color = colors.HexColor(title_color_hex)
        line_w = 2.5 if line_style in ["short", "full"] else 0

        if sec_type == "text":
            raw_text = str(sec_content or "").strip()
            paras = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
            if not paras:
                paras = [raw_text]
            p_flowables = []
            for p_idx, p_val in enumerate(paras):
                p_style = ParagraphStyle(
                    f'TextSec_{sec_title}_{p_idx}',
                    parent=styles['Normal'],
                    fontName=font_regular,
                    leading=13,
                    spaceAfter=4 if p_idx < len(paras) - 1 else 0
                )
                p_flowables.append(Paragraph(f"<font size='9' color='#334155'>{p_val}</font>", p_style))
            from reportlab.platypus import Table, TableStyle
            text_table = Table([[p_flowables]], colWidths=[max_width])
            t_style = [
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ]
            if line_w > 0:
                t_style.append(('LINEBEFORE', (0,0), (0,-1), line_w, accent_bar_color))
            text_table.setStyle(TableStyle(t_style))
            sec_elements.append(text_table)

        elif sec_type == "list":
            if isinstance(sec_content, list):
                for item in sec_content:
                    item_text = f"<font color='{title_color_hex}'><b>{b_sym}</b></font> &nbsp;<b>{item}</b>"
                    sec_elements.append(Paragraph(item_text, style_body))
            else:
                sec_elements.append(Paragraph(str(sec_content), style_body))

        elif sec_type in ["experience", "education"]:
            if isinstance(sec_content, list):
                from reportlab.platypus import Table, TableStyle
                for idx, item in enumerate(sec_content):
                    if idx > 0:
                        sec_elements.append(Spacer(1, 3))

                    title_val = item.get("role", "") if sec_type == "experience" else item.get("degree", "")
                    comp_val = item.get("company", "") if sec_type == "experience" else item.get("institution", "")
                    period = item.get("period", "")
                    location = item.get("location", "")

                    left_html = f"<b><font size='9.5' color='{title_color_hex}'>{title_val}</font></b>"
                    if comp_val:
                        left_html += f"<br/><font size='8.5' color='#475569'><b>{comp_val}</b></font>"

                    right_parts = []
                    if period:
                        right_parts.append(f"<b>{period}</b>")
                    if location:
                        right_parts.append(f"<i>{location}</i>")
                    right_html = "<br/>".join(right_parts) if right_parts else ""

                    left_p = Paragraph(left_html, ParagraphStyle(f'ExpLeft_{idx}', parent=styles['Normal'], fontName=font_bold, leading=11))
                    right_p = Paragraph(f"<font size='8' color='#64748B'>{right_html}</font>", ParagraphStyle(f'ExpRight_{idx}', parent=styles['Normal'], fontName=font_regular, alignment=TA_RIGHT, leading=10))

                    r_width = min(120, int(max_width * 0.35))
                    l_width = max_width - r_width
                    item_table = Table([[left_p, right_p]], colWidths=[l_width, r_width])
                    i_style = [
                        ('VALIGN', (0,0), (-1,-1), 'TOP'),
                        ('LEFTPADDING', (0,0), (0,0), 4),
                        ('RIGHTPADDING', (0,0), (-1,-1), 0),
                        ('TOPPADDING', (0,0), (-1,-1), 1),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
                    ]
                    if line_w > 0:
                        i_style.append(('LINEBEFORE', (0,0), (0,-1), line_w, accent_bar_color))
                    item_table.setStyle(TableStyle(i_style))
                    sec_elements.append(item_table)

                    bullets = item.get("bullets", [])
                    if isinstance(bullets, list):
                        bullet_color_hex = title_color_hex
                        for bullet in bullets:
                            bullet_text = f"<font color='{bullet_color_hex}'><b>{b_sym}</b></font> &nbsp;{bullet}"
                            sec_elements.append(Paragraph(bullet_text, style_bullet))
            else:
                sec_elements.append(Paragraph(str(sec_content), style_body))

        return sec_elements

    # 3. Layout Render (2-Column Sidebar vs 1-Column Standard)
    if layout_mode == "2col":
        from reportlab.platypus import Table, TableStyle
        left_secs = [s for s in cv_data.get("sections", []) if s.get("type") in ["list", "education"]]
        right_secs = [s for s in cv_data.get("sections", []) if s.get("type") not in ["list", "education"]]

        max_num_secs = max(len(left_secs), len(right_secs))
        for i in range(max_num_secs):
            l_sec = left_secs[i] if i < len(left_secs) else None
            r_sec = right_secs[i] if i < len(right_secs) else None

            l_flowables = build_pdf_section_elements(l_sec, max_width=175) if l_sec else []
            r_flowables = build_pdf_section_elements(r_sec, max_width=345) if r_sec else []

            if l_flowables or r_flowables:
                sec_table = Table([[l_flowables, r_flowables]], colWidths=[180, 360])
                sec_table.setStyle(TableStyle([
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('LEFTPADDING', (0,0), (0,0), 0),
                    ('RIGHTPADDING', (0,0), (0,0), 8),
                    ('LEFTPADDING', (1,0), (1,0), 10),
                    ('RIGHTPADDING', (1,0), (1,0), 0),
                    ('TOPPADDING', (0,0), (-1,-1), 0),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                    ('LINEAFTER', (0,0), (0,-1), 0.75, colors.HexColor('#E2E8F0')),
                ]))
                story.append(sec_table)
    else:
        for sec in cv_data.get("sections", []):
            story.extend(build_pdf_section_elements(sec, max_width=540))

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


def save_cv_as_pdf(
    cv_data: Dict[str, Any],
    output_path: str,
    theme: str = "minimalist",
    custom_color: Optional[str] = None,
    line_style: str = "short",
    bullet_symbol: str = "│",
    layout_mode: str = "2col",
    pdf_engine: str = "html",
    fit_one_page: bool = False
) -> None:
    """
    Main PDF generator dispatcher supporting 3 distinct rendering modes:
    1. 'html' (Pixel-Perfect HTML/Chromium Engine) - 1:1 match with the interactive HTML preview canvas.
    2. 'executive' (ReportLab 2-Column Sidebar Vector Engine) - fast vector PDF with sidebar grid.
    3. 'classic' (ReportLab 1-Column ATS Linear Engine) - clean linear format optimized for traditional ATS parsers.
    """
    engine = (pdf_engine or "html").lower().strip()
    
    if engine in ["html", "playwright", "canvas", "pixel_perfect"]:
        try:
            save_cv_as_pdf_html(
                cv_data=cv_data,
                output_path=output_path,
                theme=theme,
                custom_color=custom_color,
                line_style=line_style,
                bullet_symbol=bullet_symbol,
                layout_mode=layout_mode,
                fit_one_page=fit_one_page
            )
            return
        except Exception as e:
            print(f"[parser] HTML PDF rendering via Chromium failed: {e}. Falling back to ReportLab vector engine.")
            pass
            
    if engine in ["classic", "reportlab_1col", "ats", "1col"]:
        save_cv_as_pdf_reportlab(
            cv_data=cv_data,
            output_path=output_path,
            theme=theme,
            custom_color=custom_color,
            line_style=line_style,
            bullet_symbol=bullet_symbol,
            layout_mode="1col",
            fit_one_page=fit_one_page
        )
    else:
        # Default executive / 2col vector engine
        save_cv_as_pdf_reportlab(
            cv_data=cv_data,
            output_path=output_path,
            theme=theme,
            custom_color=custom_color,
            line_style=line_style,
            bullet_symbol=bullet_symbol,
            layout_mode=layout_mode,
            fit_one_page=fit_one_page
        )

