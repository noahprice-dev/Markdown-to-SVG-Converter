#!/usr/bin/env python3
"""
md_to_svg.py - Convert a Markdown document to an SVG image.

Supports:
  - # / ## / ### headers (bold, scaled sizes)
  - Bullet points (- or * or +), including nested bullets
  - Numbered lists (1. 2. etc.), including nested
  - Bold (**text**) and italic (*text*) inline formatting
  - Paragraphs with automatic word-wrapping
  - Code spans (`code`)

Usage:
  python md_to_svg.py input.md -o output.svg
  python md_to_svg.py input.md --width 900 --font-size 16
  cat input.md | python md_to_svg.py - -o output.svg
"""

import argparse
import re
import sys
import html


# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 600
DEFAULT_FONT_SIZE = 16
DEFAULT_FONT_FAMILY = "sans-serif"
PADDING = 40
LINE_HEIGHT_FACTOR = 1.5
HEADER_MARGIN_TOP = 0.6   # extra em above headers
HEADER_MARGIN_BOT = 0.2   # extra em below headers
PARAGRAPH_SPACING = 0.8   # em between paragraphs
BULLET_INDENT = 24        # px per indent level
BULLET_CHAR = "•"

HEADER_SCALES = {1: 2.0, 2: 1.6, 3: 1.3}  # font-size multipliers


# ── Inline formatting helpers ─────────────────────────────────────────────────

def _parse_inline(text: str):
    """
    Yield (style, content) tuples for inline markdown:
      style is a set that may contain 'bold', 'italic', 'code'.
    """
    # Order matters: bold+italic first, then bold, italic, code
    token_re = re.compile(
        r"(\*\*\*(.+?)\*\*\*)"   # bold+italic
        r"|(\*\*(.+?)\*\*)"      # bold
        r"|(\*(.+?)\*)"          # italic
        r"|(`(.+?)`)"            # code
    )
    pos = 0
    for m in token_re.finditer(text):
        if m.start() > pos:
            yield (set(), text[pos:m.start()])
        if m.group(2) is not None:
            yield ({"bold", "italic"}, m.group(2))
        elif m.group(4) is not None:
            yield ({"bold"}, m.group(4))
        elif m.group(6) is not None:
            yield ({"italic"}, m.group(6))
        elif m.group(8) is not None:
            yield ({"code"}, m.group(8))
        pos = m.end()
    if pos < len(text):
        yield (set(), text[pos:])


def _tspan_for(style: set, content: str, is_header_bold: bool = False) -> str:
    """Return a <tspan> element with the right styling."""
    attrs = []
    content = html.escape(content)
    if "bold" in style or is_header_bold:
        attrs.append('font-weight="bold"')
    if "italic" in style:
        attrs.append('font-style="italic"')
    if "code" in style:
        attrs.append('font-family="monospace"')
        attrs.append('fill="#c7254e"')
    
    attr_str = (" "  + " ".join(attrs)) if attrs else ""

    return f"<tspan{attr_str}>{content}</tspan>"


# ── Word-wrap helper ──────────────────────────────────────────────────────────

def _wrap_text(text: str, max_chars: int) -> list[str]:
    """Simple word-wrap to roughly max_chars per line."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for w in words:
        if current and len(current) + 1 + len(w) > max_chars:
            lines.append(current)
            current = w
        else:
            current = f"{current} {w}" if current else w
    if current:
        lines.append(current)
    return lines or [""]


# ── Markdown line parser ─────────────────────────────────────────────────────

def _parse_md_lines(md: str):
    """
    Yield block descriptors:
      ("header", level, text)
      ("bullet", indent_level, text)
      ("number_list", indent_level, text)
      ("paragraph", text)
      ("blank",)
    """
    for raw_line in md.splitlines():
        line = raw_line.rstrip()

        # blank
        if not line.strip():
            yield ("blank",)
            continue

        # header
        hm = re.match(r"^(#{1,3})\s+(.*)", line)
        if hm:
            yield ("header", len(hm.group(1)), hm.group(2))
            continue

        # numbered list (1. 2. etc.), with nesting via leading spaces
        nm = re.match(r"^(\s*)(\d+)\.\s+(.*)", line)
        if nm:
            indent = len(nm.group(1)) // 2  # every 2 spaces = 1 level
            yield ("number_list", indent, nm.group(3))
            continue

        # bullet  (- or * or +), with nesting via leading spaces
        bm = re.match(r"^(\s*)([-*+])\s+(.*)", line)
        if bm:
            indent = len(bm.group(1)) // 2  # every 2 spaces = 1 level
            yield ("bullet", indent, bm.group(3))
            continue

        # paragraph text
        yield ("paragraph", line)


# ── SVG generation ────────────────────────────────────────────────────────────

def md_to_svg(
    md_text: str,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    inner_width: int = None,
    base_font_size: int = DEFAULT_FONT_SIZE,
    font_family: str = DEFAULT_FONT_FAMILY,
    padding: int | list[int] = PADDING,
    bg_color: str = "none",
    text_color: str = "#222222",
    debug: bool = False,
) -> str:
    # * Handle padding assignment.
    if isinstance(padding, int):
        _top_pad = padding
        _bottom_pad = padding
        _left_pad =  padding
        _right_pad = padding
    # ? CSS rules
    if isinstance(padding, list):
        match len(padding):
            case 1: 
                _top_pad = padding[0]
                _bottom_pad = padding[0]
                _left_pad =  padding[0]
                _right_pad = padding[0]
            case 2:
                _top_pad = padding[0]
                _bottom_pad = padding[0]
                _left_pad =  padding[1]
                _right_pad = padding[1]
            case 3:
                _top_pad = padding[0]
                _left_pad =  padding[1]
                _right_pad = padding[1]
                _bottom_pad = padding[2]
            case 4:
                _top_pad = padding[0]
                _left_pad =  padding[1]
                _right_pad = padding[2]
                _bottom_pad = padding[3]
            case _: _top_pad = padding
    
    # * Define max sizes
    content_width = inner_width if inner_width is not None else width - _left_pad - _right_pad
    avg_char_width = base_font_size  * 0.45 # rough estimate for wrapping
    max_chars = int(content_width / avg_char_width)

    elements: list[str] = []
    y = _top_pad + base_font_size  # starting y

    def _emit_text_line(x, y_pos, font_size, spans_xml, anchor="start"):
        elements.append(
            f'<text x="{x}" y="{y_pos}" '
            f'font-family="{font_family}" font-size="{font_size}" '
            f'fill="{text_color}" text-anchor="{anchor}">'
            f'{"".join(spans_xml)}</text>'
        )

    prev_block = None
    number_counters = {}    # indent_level -> current count
    last_number_indent = -1

    for block in _parse_md_lines(md_text):
        btype = block[0]

        # Reset number counters when we leave a numbered list
        if btype != "number_list":
            number_counters.clear()
            last_number_indent = -1

        # ── Blank line ────────────────────────────────────────────────
        if btype == "blank":
            prev_block = btype
            continue

        # ── Header ────────────────────────────────────────────────────
        if btype == "header":
            level = block[1]
            text = block[2]
            scale = HEADER_SCALES.get(level, 1.0)
            fs = base_font_size * scale
            line_h = fs * LINE_HEIGHT_FACTOR

            y += fs * HEADER_MARGIN_TOP
            spans = [_tspan_for(style, chunk, is_header_bold=True)
                     for style, chunk in _parse_inline(text)]
            _emit_text_line(_left_pad, y, fs, spans)
            y += line_h * 0.4 + fs * HEADER_MARGIN_BOT
            prev_block = btype
            continue

        # ── Bullet ────────────────────────────────────────────────────
        if btype == "bullet":
            indent_level = block[1]
            text = block[2]
            if prev_block in ("blank", "header", "paragraph", "number_list", None):
                y += base_font_size * 0.3
            fs = base_font_size
            line_h = fs * LINE_HEIGHT_FACTOR
            x_offset = _left_pad + indent_level * BULLET_INDENT
            
            bullet_chars = max_chars - int((indent_level * BULLET_INDENT) / avg_char_width) - 2
            wrapped = _wrap_text(text, max(bullet_chars, 20))

            for i, wline in enumerate(wrapped):
                prefix = f"{BULLET_CHAR}  " if i == 0 else "   "
                spans = [_tspan_for(set(), prefix)] + [
                    _tspan_for(style, chunk)
                    for style, chunk in _parse_inline(wline)
                ]
                _emit_text_line(x_offset, y, fs, spans)
                y += line_h

            prev_block = btype
            continue

        # ── Numbered list ─────────────────────────────────────────────
        if btype == "number_list":
            indent_level = block[1]
            text = block[2]

            # Increment or initialize counter for this indent level
            if indent_level not in number_counters:
                number_counters[indent_level] = 1
            elif indent_level <= last_number_indent:
                # Continuing or returning to this level — increment
                number_counters[indent_level] += 1
            else:
                # Dropping into a new deeper level — start at 1
                number_counters[indent_level] = 1
            last_number_indent = indent_level
            # Clear counters for deeper levels when we go back up
            for lvl in list(number_counters):
                if lvl > indent_level:
                    del number_counters[lvl]

            count = number_counters[indent_level]

            if prev_block in ("blank", "header", "paragraph", "bullet", None):
                y += base_font_size * 0.3
            fs = base_font_size
            line_h = fs * LINE_HEIGHT_FACTOR
            x_offset = _left_pad + indent_level * BULLET_INDENT

            num_prefix = f"{count}.  "
            pad_prefix = " " * len(num_prefix)
            avail_chars = max_chars - int((indent_level * BULLET_INDENT) / avg_char_width) - len(num_prefix)
            wrapped = _wrap_text(text, max(avail_chars, 20))

            for i, wline in enumerate(wrapped):
                prefix = num_prefix if i == 0 else pad_prefix
                spans = [_tspan_for(set(), prefix)] + [
                    _tspan_for(style, chunk)
                    for style, chunk in _parse_inline(wline)
                ]
                _emit_text_line(x_offset, y, fs, spans)
                y += line_h

            prev_block = btype
            continue

        # ── Paragraph ─────────────────────────────────────────────────
        if btype == "paragraph":
            text = block[1]
            if prev_block in ("blank", "header", None):
                y += base_font_size * PARAGRAPH_SPACING * 0.3
            fs = base_font_size
            line_h = fs * LINE_HEIGHT_FACTOR

            wrapped = _wrap_text(text, max_chars)
            for wline in wrapped:
                spans = [_tspan_for(style, chunk)
                         for style, chunk in _parse_inline(wline)]
                _emit_text_line(_left_pad, y, fs, spans)
                y += line_h

            prev_block = btype
            continue

    total_height = height if height is not DEFAULT_HEIGHT else int(y + _bottom_pad)

    bg_rect = "" if bg_color == "none" else f'\n  <rect width="100%" height="100%" fill="{bg_color}"/>'
    debug_lines = "" if not debug else f"""
        <rect x="{_left_pad}" y="{_top_pad}" width="{content_width}" height="{y -_bottom_pad}" fill="none" stroke="#008000" stroke-width="1"/>
        <line x1="{avg_char_width * max_chars + _right_pad}" y1="{_top_pad}" x2="{avg_char_width * max_chars+ _right_pad}" y2="{y}" stroke="#800000" stroke-width="1"/>
        """
    
    svg = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
    width="{width}" height="{total_height}"
    viewBox="0 0 {width} {total_height}">
    {bg_rect}
    {debug_lines}
{"  ".join(el + chr(10) for el in elements)}</svg>
"""
    
    if debug:
        print(f"Inner Width: " + str(inner_width))
        print(f"Width: " + str(width))
        print(f"Content Width: " + str(content_width))
        print(f"Max Chars per line: " + str(max_chars))
        print(f"Total Height: " + str(y))
        print(f"Default Height: " + str(height))
    return svg


# ── CLI ───────────────────────────────────────────────────────────────────────
# * Helps us format the --padding arg where we have a more detailed description required
# * without forcing us to handle all help args with RawTextFormatHelper
class SmartFormatter(argparse.HelpFormatter):

    def _split_lines(self, text, width):
        if text.startswith('R|'):
            return text[2:].splitlines()  
        # this is the RawTextHelpFormatter._split_lines
        return argparse.HelpFormatter._split_lines(self, text, width)

def main():
    parser = argparse.ArgumentParser(
        description="Convert Markdown to SVG",
        formatter_class=SmartFormatter,
    )
    parser.add_argument("input", help="Markdown file (use '-' for stdin)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output SVG file (default: stdout)")
    parser.add_argument("--base-height", type=int, default=DEFAULT_HEIGHT, help="Height of returned image in pixels. Default 600px.")
    parser.add_argument("--base-width", type=int, default=DEFAULT_WIDTH, help="Width of returned image in pixels. Default 800px.")
    parser.add_argument("--inner-width", type=int, default=None, help="Define the full width of the inner bounding box in pixels. Default is Width - 80px (40px Padding both sides).")
    parser.add_argument("--font-size", type=int, default=DEFAULT_FONT_SIZE)
    parser.add_argument("--font-family", default=DEFAULT_FONT_FAMILY)
    parser.add_argument("--padding", nargs='+', default=PADDING, type=int, help="R|Padding around content in px (default: 40).\n"
                        "Accepts 1-4 values, following CSS shorthand:\n"
                        "  1 value:  all sides\n"
                        "  2 values: vertical | horizontal\n"
                        "  3 values: top | horizontal | bottom\n"
                        "  4 values: top | right | bottom | left"
                        )
    parser.add_argument("--bg", default="#FFFFFF", help="Background color (default: White/#FFFFFF) Use with color hex-code prefixed with #. Pass 'none' for transparent background.")
    parser.add_argument("--color", default="#222222", help="Text color")
    parser.add_argument("--debug", default=False, type=bool, help="Enables debug features - Logs various internal param values and draws a box around the Content, as well as a line denoting the location where the text should wrap.")

    args = parser.parse_args()

    if args.input == "-":
        md_text = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            md_text = f.read()



    svg = md_to_svg(
        md_text,
        width=args.base_width,
        height=args.base_height,
        inner_width=args.inner_width,
        base_font_size=args.font_size,
        font_family=args.font_family,
        padding=args.padding,
        bg_color=args.bg,
        text_color=args.color,
        debug=args.debug
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(svg)
    

if __name__ == "__main__":
    main()


