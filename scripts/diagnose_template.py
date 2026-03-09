#!/usr/bin/env python3
"""Diagnose the Google Docs resume template structure.

Reads the template document via the Docs API and dumps a full structural
breakdown: element types, indices, text, bullet/list properties, paragraph
styles, tables, and placeholder patterns.

Usage (from repo root):
    source .venv/bin/activate
    python scripts/diagnose_template.py
"""

import json
import os
import re
import sys

from jj.google_docs import GoogleDocsClient

TEMPLATE_ID = os.environ.get("JJ_TEMPLATE_ID", "YOUR_TEMPLATE_ID_HERE")


def fmt_index(element: dict) -> str:
    """Return 'startIndex-endIndex' from an element."""
    start = element.get("startIndex", "?")
    end = element.get("endIndex", "?")
    return f"{start}-{end}"


def describe_paragraph_style(style: dict) -> str:
    """Summarise the interesting parts of a ParagraphStyle."""
    parts = []
    if named := style.get("namedStyleType"):
        parts.append(f"style={named}")
    if align := style.get("alignment"):
        parts.append(f"align={align}")
    if indent_start := style.get("indentStart"):
        parts.append(f"indentStart={indent_start.get('magnitude', '?')}{indent_start.get('unit', '')}")
    if indent_first := style.get("indentFirstLine"):
        parts.append(f"indentFirst={indent_first.get('magnitude', '?')}{indent_first.get('unit', '')}")
    if spacing := style.get("spaceAbove"):
        parts.append(f"spaceAbove={spacing.get('magnitude', '?')}")
    if spacing := style.get("spaceBelow"):
        parts.append(f"spaceBelow={spacing.get('magnitude', '?')}")
    if style.get("keepLinesTogether"):
        parts.append("keepLines")
    if style.get("keepWithNext"):
        parts.append("keepWithNext")
    if direction := style.get("direction"):
        parts.append(f"dir={direction}")
    return ", ".join(parts) if parts else "(default)"


def describe_text_style(style: dict) -> str:
    """Summarise a TextStyle."""
    parts = []
    if style.get("bold"):
        parts.append("BOLD")
    if style.get("italic"):
        parts.append("ITALIC")
    if style.get("underline"):
        parts.append("UNDERLINE")
    if fs := style.get("fontSize"):
        parts.append(f"size={fs.get('magnitude', '?')}{fs.get('unit', '')}")
    if ff := style.get("weightedFontFamily"):
        parts.append(f"font={ff.get('fontFamily', '?')}")
    if link := style.get("link"):
        parts.append(f"link={link.get('url', '?')}")
    return ", ".join(parts) if parts else ""


def dump_paragraph(para: dict, idx: int, element: dict) -> None:
    """Print details of a paragraph element."""
    p_style = para.get("paragraphStyle", {})
    bullet = para.get("bullet")
    elements = para.get("elements", [])

    # Collect full text of the paragraph
    full_text = ""
    for el in elements:
        if tr := el.get("textRun"):
            full_text += tr.get("content", "")

    text_preview = full_text.rstrip("\n")
    if len(text_preview) > 120:
        text_preview = text_preview[:117] + "..."

    # Check for placeholders
    placeholders = re.findall(r"\{\{[^}]+\}\}", full_text)

    # Header
    print(f"\n  [{idx}] PARAGRAPH  indices={fmt_index(element)}")
    print(f"       paragraphStyle: {describe_paragraph_style(p_style)}")

    if bullet:
        list_id = bullet.get("listId", "?")
        nesting = bullet.get("nestingLevel", 0)
        print(f"       BULLET  listId={list_id}  nestingLevel={nesting}")

    if text_preview:
        print(f"       text: \"{text_preview}\"")
    else:
        print("       text: (empty)")

    if placeholders:
        print(f"       PLACEHOLDERS: {placeholders}")

    # Show individual text runs if there are multiple or interesting styling
    if len(elements) > 1 or any(describe_text_style(e.get("textRun", {}).get("textStyle", {})) for e in elements if "textRun" in e):
        for j, el in enumerate(elements):
            if tr := el.get("textRun"):
                content = tr.get("content", "").rstrip("\n")
                ts = describe_text_style(tr.get("textStyle", {}))
                if ts or len(elements) > 1:
                    run_preview = content[:80] + "..." if len(content) > 80 else content
                    print(f"         run[{j}]: \"{run_preview}\"  {ts}")


def dump_table(table: dict, idx: int, element: dict) -> None:
    """Print details of a table element."""
    rows = table.get("rows", 0)
    cols = table.get("columns", 0)
    print(f"\n  [{idx}] *** TABLE ***  indices={fmt_index(element)}  rows={rows}  cols={cols}")
    print("       WARNING: Tables can break ATS parsing!")

    table_rows = table.get("tableRows", [])
    for r, row in enumerate(table_rows):
        cells = row.get("tableCells", [])
        for c, cell in enumerate(cells):
            cell_text = ""
            for content_el in cell.get("content", []):
                if p := content_el.get("paragraph"):
                    for el in p.get("elements", []):
                        if tr := el.get("textRun"):
                            cell_text += tr.get("content", "")
            cell_text = cell_text.strip()
            if cell_text:
                preview = cell_text[:100] + "..." if len(cell_text) > 100 else cell_text
                print(f"       cell[{r},{c}]: \"{preview}\"")


def dump_section_break(sb: dict, idx: int, element: dict) -> None:
    """Print details of a section break."""
    sb_style = sb.get("sectionStyle", {})
    col_type = sb_style.get("columnSeparatorStyle", "")
    sec_type = sb_style.get("sectionType", "")
    print(f"\n  [{idx}] SECTION_BREAK  indices={fmt_index(element)}  type={sec_type}  colSep={col_type}")


def dump_toc(toc: dict, idx: int, element: dict) -> None:
    """Print details of a table of contents."""
    print(f"\n  [{idx}] TABLE_OF_CONTENTS  indices={fmt_index(element)}")


def main() -> None:
    print("=" * 80)
    print("GOOGLE DOCS TEMPLATE STRUCTURE DIAGNOSIS")
    print(f"Template ID: {TEMPLATE_ID}")
    print("=" * 80)

    # Authenticate
    print("\nAuthenticating with Google Docs API...")
    client = GoogleDocsClient()
    client.authenticate()
    print("Authenticated successfully.\n")

    # Fetch the full document
    print("Fetching document...")
    doc = client.docs_service.documents().get(documentId=TEMPLATE_ID).execute()

    title = doc.get("title", "(untitled)")
    doc_id = doc.get("documentId", "?")
    print(f"Title: {title}")
    print(f"Document ID: {doc_id}")

    # Named styles summary
    named_styles = doc.get("namedStyles", {}).get("styles", [])
    if named_styles:
        print(f"\nNamed styles defined: {[s.get('namedStyleType') for s in named_styles]}")

    # Lists (bullet/numbered list definitions)
    lists = doc.get("lists", {})
    if lists:
        print(f"\nLists defined: {len(lists)}")
        for list_id, list_def in lists.items():
            props = list_def.get("listProperties", {})
            nesting_levels = props.get("nestingLevels", [])
            glyphs = []
            for level in nesting_levels:
                glyph_type = level.get("glyphType", level.get("glyphSymbol", "?"))
                glyphs.append(str(glyph_type))
            print(f"  listId={list_id}  nestingLevels={len(nesting_levels)}  glyphs={glyphs}")

    # Body content
    body = doc.get("body", {})
    content = body.get("content", [])
    print(f"\nBody elements: {len(content)}")
    print("-" * 80)

    # Counters
    counts = {"paragraph": 0, "table": 0, "sectionBreak": 0, "tableOfContents": 0, "other": 0}
    all_placeholders = []

    for idx, element in enumerate(content):
        if "paragraph" in element:
            counts["paragraph"] += 1
            para = element["paragraph"]
            dump_paragraph(para, idx, element)

            # Collect placeholders
            for el in para.get("elements", []):
                if tr := el.get("textRun"):
                    found = re.findall(r"\{\{[^}]+\}\}", tr.get("content", ""))
                    all_placeholders.extend(found)

        elif "table" in element:
            counts["table"] += 1
            dump_table(element["table"], idx, element)

        elif "sectionBreak" in element:
            counts["sectionBreak"] += 1
            dump_section_break(element.get("sectionBreak", {}), idx, element)

        elif "tableOfContents" in element:
            counts["tableOfContents"] += 1
            dump_toc(element.get("tableOfContents", {}), idx, element)

        else:
            counts["other"] += 1
            print(f"\n  [{idx}] UNKNOWN  indices={fmt_index(element)}  keys={list(element.keys())}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"  Paragraphs:       {counts['paragraph']}")
    print(f"  Tables:           {counts['table']}")
    print(f"  Section breaks:   {counts['sectionBreak']}")
    print(f"  TOC elements:     {counts['tableOfContents']}")
    print(f"  Other:            {counts['other']}")

    if counts["table"] > 0:
        print(f"\n  *** WARNING: {counts['table']} TABLE(S) FOUND -- these can break ATS parsing! ***")

    # Unique placeholders
    unique_placeholders = sorted(set(all_placeholders))
    print(f"\n  Unique placeholders ({len(unique_placeholders)}):")
    for p in unique_placeholders:
        print(f"    {p}")

    # Dump raw JSON for deep inspection (optional, to file)
    raw_path = "scripts/template_raw.json"
    with open(raw_path, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"\n  Full raw JSON saved to: {raw_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
