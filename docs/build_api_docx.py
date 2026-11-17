"""Build the bilingual class/interface reference DOCX from its Markdown source."""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BASE_DIR = Path(__file__).resolve().parent
SOURCE = BASE_DIR / "项目类与接口说明_中英对照.md"
OUTPUT = BASE_DIR / "项目类与接口说明_中英对照.docx"

GREEN = "173D32"
GREEN_2 = "216B52"
GOLD = "B4874A"
INK = RGBColor(0x1B, 0x35, 0x2B)
MUTED = RGBColor(0x6F, 0x76, 0x6E)
CREAM = "F7F5ED"
TABLE_ALT = "FAF8F1"
CODE_BG = "F3F1E8"
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT_CN = "Microsoft YaHei"
FONT_CODE = "Consolas"


def set_run_font(run, name=FONT_CN, size=None, bold=None, color=None):
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.rFonts
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def shade_cell(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_margins(cell, top=70, bottom=70, left=80, right=80):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for tag, value in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = tc_mar.find(qn(f"w:{tag}"))
        if node is None:
            node = OxmlElement(f"w:{tag}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def keep_row_together(row):
    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:cantSplit"))


def add_runs(paragraph, text, size=9.8, bold=False, color=None, italic=False):
    """Render **bold** and `code` inline segments."""
    pattern = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")
    pos = 0
    for match in pattern.finditer(text):
        if match.start() > pos:
            run = paragraph.add_run(text[pos:match.start()])
            set_run_font(run, size=size, bold=bold, color=color)
            run.italic = italic
        token = match.group(0)
        if token.startswith("**"):
            run = paragraph.add_run(token[2:-2])
            set_run_font(run, size=size, bold=True, color=color)
            run.italic = italic
        else:
            run = paragraph.add_run(token[1:-1])
            set_run_font(run, name=FONT_CODE, size=max(7.4, size - 0.7), color=RGBColor(0x6A, 0x4E, 0x2A), bold=False)
        pos = match.end()
    if pos < len(text):
        run = paragraph.add_run(text[pos:])
        set_run_font(run, size=size, bold=bold, color=color)
        run.italic = italic


def style_document(doc):
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.7)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = FONT_CN
    normal.font.size = Pt(10)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(3.5)
    normal.paragraph_format.line_spacing = 1.2
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CN)

    for name, size, color, before, after in (
        ("Heading 1", 16, INK, 16, 7),
        ("Heading 2", 12.5, RGBColor(0x21, 0x5E, 0x48), 12, 5),
        ("Heading 3", 10.8, RGBColor(0x2E, 0x4A, 0x3F), 9, 4),
    ):
        style = doc.styles[name]
        style.font.name = FONT_CN
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = color
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True
        style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CN)


def add_page_number(paragraph):
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(text)
    run._r.append(fld_end)
    set_run_font(run, size=8, color=MUTED)


def add_header_footer(section):
    section.different_first_page_header_footer = True
    header = section.header
    hp = header.paragraphs[0]
    hp.text = ""
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = hp.add_run("本草仓 · 类、接口与方法说明  /  Classes, Interfaces and Methods")
    set_run_font(run, size=8, color=MUTED)
    bottom = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), "4")
    b.set(qn("w:space"), "4")
    b.set(qn("w:color"), "D8D2C2")
    bottom.append(b)
    hp._p.get_or_add_pPr().append(bottom)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.text = ""
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = fp.add_run("本草仓中药仓储库位管理系统  ·  Version 1.0  ·  ")
    set_run_font(run, size=8, color=MUTED)
    add_page_number(fp)


def add_cover(doc):
    section = doc.sections[0]
    band = doc.add_table(rows=1, cols=1)
    band.alignment = WD_TABLE_ALIGNMENT.CENTER
    band.autofit = False
    cell = band.cell(0, 0)
    cell.width = Cm(17)
    shade_cell(cell, GREEN)
    set_cell_margins(cell, 260, 250, 420, 420)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run("本草仓")
    set_run_font(run, size=31, bold=True, color=WHITE)
    p2 = cell.add_paragraph()
    p2.paragraph_format.space_after = Pt(18)
    run = p2.add_run("TCM WAREHOUSE MANAGEMENT SYSTEM")
    set_run_font(run, size=9.5, bold=True, color=RGBColor(0xE7, 0xC4, 0x8F))
    p3 = cell.add_paragraph()
    p3.paragraph_format.space_after = Pt(1)
    run = p3.add_run("中药仓储库位管理系统 · 学生 1-5 完整版")
    set_run_font(run, size=13, color=RGBColor(0xEA, 0xF3, 0xED))
    p4 = cell.add_paragraph()
    run = p4.add_run("Python + Django · 课程实践项目")
    set_run_font(run, size=9, color=RGBColor(0xB9, 0xCC, 0xC1))

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(38)

    title = doc.add_paragraph()
    title.paragraph_format.space_after = Pt(5)
    run = title.add_run("类、接口与方法说明")
    set_run_font(run, size=27, bold=True, color=INK)
    subtitle = doc.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(20)
    run = subtitle.add_run("Classes, Interfaces and Methods Reference")
    set_run_font(run, size=14, color=RGBColor(0x6F, 0x76, 0x6E))

    intro = doc.add_paragraph()
    intro.paragraph_format.space_after = Pt(24)
    run = intro.add_run(
        "面向课程验收与后续维护的双语技术参考，覆盖数据模型、业务服务、表单、"
        "HTTP 接口、权限、后台与测试。\n"
        "A bilingual technical reference for course acceptance and maintenance, "
        "covering models, domain services, forms, HTTP endpoints, permissions, admin and tests."
    )
    set_run_font(run, size=9.5, color=RGBColor(0x4D, 0x5C, 0x54))

    meta = doc.add_table(rows=4, cols=2)
    meta.alignment = WD_TABLE_ALIGNMENT.LEFT
    meta.autofit = False
    meta.style = "Table Grid"
    meta_data = [
        ("Document / 文档", "类、接口与方法说明 / Classes, Interfaces and Methods"),
        ("Project / 项目", "本草仓 · 中药仓储库位管理系统（学生 1-5 完整版）"),
        ("Technology / 技术", "Python 3.14 · Django 6.0 · SQLite / MySQL · Django Template"),
        ("Version / 版本", "Version 1.0  ·  2026-10-30"),
    ]
    for row, (label, value) in zip(meta.rows, meta_data):
        row.cells[0].width = Cm(4)
        row.cells[1].width = Cm(13)
        shade_cell(row.cells[0], "F1EEE3")
        p = row.cells[0].paragraphs[0]
        run = p.add_run(label)
        set_run_font(run, size=8.3, bold=True, color=RGBColor(0x60, 0x55, 0x40))
        p = row.cells[1].paragraphs[0]
        run = p.add_run(value)
        set_run_font(run, size=8.3, color=RGBColor(0x36, 0x47, 0x3E))
        for cell in row.cells:
            set_cell_margins(cell, 70, 70, 100, 100)

    doc.add_paragraph()
    tip = doc.add_paragraph()
    tip.paragraph_format.space_before = Pt(8)
    run = tip.add_run(
        "文档中的代码标识使用等宽字体；权限码使用代码样式；表格同时给出 English 与中文说明。\n"
        "Code identifiers use monospace; permission codes use code style; every table is bilingual."
    )
    set_run_font(run, size=8.5, color=RGBColor(0x7A, 0x7F, 0x78))

    doc.add_page_break()


def parse_table(lines):
    rows = []
    for line in lines:
        text = line.strip()
        if re.match(r"^\|[\s:|-]+\|$", text):
            continue
        if not text.startswith("|"):
            continue
        cells = [cell.strip() for cell in text.strip("|").split("|")]
        rows.append(cells)
    return rows


def add_table(doc, rows):
    if not rows:
        return
    columns = max(len(row) for row in rows)
    table = doc.add_table(rows=len(rows), cols=columns)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.allow_autofit = False
    header = rows[0][0] if rows else ""
    if columns == 2:
        widths = [4.2, 12.7]
    elif columns == 3:
        widths = [4.4, 5.4, 7.1]
    elif columns == 4:
        widths = [4.0, 4.2, 4.4, 4.3]
    elif columns == 5 and header.startswith("URL"):
        widths = [3.9, 1.7, 5.1, 2.9, 3.4]
    elif columns == 5 and header.startswith("Class"):
        widths = [3.2, 2.5, 4.7, 3.5, 3.0]
    elif columns == 5:
        widths = [4.1, 3.1, 3.4, 2.9, 3.4]
    else:
        widths = [3.0, 3.0, 3.0, 2.9, 2.4, 2.2]
    tbl_pr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)
    for idx in range(columns):
        table.columns[idx].width = Cm(widths[idx] if idx < len(widths) else 2.6)
    for r_idx, row in enumerate(rows):
        table_row = table.rows[r_idx]
        keep_row_together(table_row)
        if r_idx == 0:
            repeat_table_header(table_row)
        for c_idx in range(columns):
            cell = table_row.cells[c_idx]
            cell.width = Cm(widths[c_idx] if c_idx < len(widths) else 2.6)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell, 45, 45, 65, 65)
            if r_idx == 0:
                shade_cell(cell, GREEN)
            elif r_idx % 2 == 0:
                shade_cell(cell, TABLE_ALT)
            value = row[c_idx] if c_idx < len(row) else ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = 1.02
            add_runs(
                paragraph,
                value,
                size=7.4 if columns >= 5 and header.startswith("URL") else 8.0,
                bold=(r_idx == 0),
                color=WHITE if r_idx == 0 else RGBColor(0x2B, 0x3D, 0x34),
            )
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(2)


def add_code_block(doc, code):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    cell = table.cell(0, 0)
    cell.width = Cm(17)
    shade_cell(cell, CODE_BG)
    set_cell_margins(cell, 100, 100, 150, 150)
    first = True
    for line in code.splitlines() or [""]:
        p = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.05
        run = p.add_run(line if line else " ")
        set_run_font(run, name=FONT_CODE, size=8.2, color=RGBColor(0x3A, 0x44, 0x3E))
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(2)


def add_quote(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.35)
    p.paragraph_format.right_indent = Cm(0.2)
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(6)
    pPr = p._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "16")
    left.set(qn("w:space"), "8")
    left.set(qn("w:color"), "B4874A")
    borders.append(left)
    pPr.append(borders)
    add_runs(p, text, size=8.8, color=RGBColor(0x6B, 0x5D, 0x4B), italic=True)


def add_heading(doc, text, level):
    paragraph = doc.add_heading("", level=level)
    add_runs(
        paragraph,
        text,
        size={1: 16, 2: 12.5, 3: 10.8}.get(level, 10),
        bold=True,
        color=INK if level == 1 else RGBColor(0x21, 0x5E, 0x48),
    )


def parse_markdown(doc, text):
    lines = text.splitlines()
    headings = [line[3:].strip() for line in lines if line.startswith("## ")]
    # Manual contents page
    add_heading(doc, "目录 / Contents", 1)
    for heading in headings:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.35)
        p.paragraph_format.space_after = Pt(5)
        run = p.add_run("•   ")
        set_run_font(run, size=9, bold=True, color=RGBColor(0xB4, 0x87, 0x4A))
        add_runs(p, heading, size=9.8, color=INK)
    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(12)
    add_runs(
        note,
        "提示：Word 打开后可通过“视图 → 导航窗格”按标题快速跳转；页码见页脚。\n"
        "Tip: use Word's Navigation Pane to jump between headings; page numbers are in the footer.",
        size=8.5,
        color=MUTED,
    )

    glance = doc.add_paragraph()
    glance.paragraph_format.space_before = Pt(22)
    glance.paragraph_format.space_after = Pt(5)
    add_runs(glance, "文档信息 / At a Glance", size=11, bold=True, color=RGBColor(0x21, 0x5E, 0x48))
    add_table(
        doc,
        [
            ["Metric / 项目", "Coverage / 内容"],
            ["Models / 模型", "16 个模型类（含 1 个抽象基类、1 个查询集） / 16 model classes incl. an abstract base and a queryset"],
            ["Forms / 表单", "19 个表单类 + 1 个入库明细 FormSet / 19 form classes + 1 inline formset"],
            ["HTTP endpoints / 接口", "69 个业务/认证/导出端点 / 69 auth, business and export endpoints"],
            ["Permissions / 权限", "24 个权限码，4 种默认角色 / 24 permission codes across 4 default roles"],
            ["Tests / 测试", "13 个测试类，71 条测试 / 13 test classes, 71 tests"],
        ],
    )
    doc.add_page_break()

    i = 0
    section_count = 0
    paragraph_buffer = []

    def flush_paragraph():
        nonlocal paragraph_buffer
        if not paragraph_buffer:
            return
        content = " ".join(part.strip() for part in paragraph_buffer if part.strip())
        if content:
            p = doc.add_paragraph()
            add_runs(p, content)
        paragraph_buffer = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            i += 1
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            if section_count in {1, 7}:
                doc.add_page_break()
            add_heading(doc, stripped[3:].strip(), 1)
            section_count += 1
            i += 1
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            add_heading(doc, stripped[4:].strip(), 2)
            i += 1
            continue
        if stripped.startswith("#### "):
            flush_paragraph()
            add_heading(doc, stripped[5:].strip(), 3)
            i += 1
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            add_code_block(doc, "\n".join(code_lines))
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            add_table(doc, parse_table(table_lines))
            continue
        if stripped.startswith("> "):
            flush_paragraph()
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith("> "):
                quote_lines.append(lines[i].strip()[2:].strip())
                i += 1
            add_quote(doc, " ".join(quote_lines))
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(2)
            add_runs(p, stripped[2:], size=9.5)
            i += 1
            continue
        if re.match(r"^\d+\.\s", stripped):
            flush_paragraph()
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.space_after = Pt(2)
            add_runs(p, re.sub(r"^\d+\.\s*", "", stripped), size=9.5)
            i += 1
            continue
        if stripped == "---":
            flush_paragraph()
            i += 1
            continue
        paragraph_buffer.append(line)
        i += 1
    flush_paragraph()


def main():
    raw = SOURCE.read_text(encoding="utf-8")
    body = raw.split("<!-- DOCX-START -->", 1)[1].strip()
    doc = Document()
    style_document(doc)
    add_header_footer(doc.sections[0])
    add_cover(doc)
    parse_markdown(doc, body)
    doc.core_properties.title = "本草仓 · 类、接口与方法说明（中英对照）"
    doc.core_properties.subject = "Classes, Interfaces and Methods Reference"
    doc.core_properties.author = "本草仓课程项目"
    doc.core_properties.comments = "Bilingual technical reference for the TCM warehouse management system."
    doc.save(OUTPUT)
    print("saved", OUTPUT)
    print("size", OUTPUT.stat().st_size)
    print("paragraphs", len(doc.paragraphs), "tables", len(doc.tables))


if __name__ == "__main__":
    main()

