"""Read-only Phase 3.2.1 correction layer. Never changes original source blocks."""
from __future__ import annotations
import copy
import re
from .layout32_refine import refine_layout

NUMBER = re.compile(r'^[−+\-]?\d+(?:\.\d+)?$')
AXIS = re.compile(r'^(?:Year|Lag|ACF|PACF|Partial ACF|H02 sales \(million scripts\))$', re.I)

def _near(a, b, margin=0):
    return a[1] <= b[3]+margin and b[1] <= a[3]+margin

def correct_layout(data: dict) -> dict:
    """Adds conservative chart classifications and review flags to refined output.

    Formula fragments are marked for visual review rather than mathematically guessed.
    Source text and bounding boxes remain in `segments` and `source_blocks`.
    """
    result = refine_layout(data)
    result['source_blocks'] = copy.deepcopy(data.get('blocks', []))
    segments = result['segments']
    warnings = list(result['warnings'])
    page = data.get('page_number')

    # A region is credible only when several nearby numeric tick labels coexist
    # with an explicit axis title. This is not page-number-specific.
    numeric = [s for s in segments if NUMBER.fullmatch(s['text'].strip())]
    axes = [s for s in segments if AXIS.fullmatch(s['text'].strip())]
    chart_y_ranges = []
    for axis in axes:
        y = (axis['bbox'][1] + axis['bbox'][3]) / 2
        ticks = [s for s in numeric if abs((s['bbox'][1]+s['bbox'][3])/2-y) <= 170]
        if len(ticks) >= 5:
            low = min([axis['bbox'][1]] + [s['bbox'][1] for s in ticks]) - 8
            high = max([axis['bbox'][3]] + [s['bbox'][3] for s in ticks]) + 8
            chart_y_ranges.append((low, high))
    # Avoid changing previously classified plot-marker blocks.
    added = 0
    for s in segments:
        if s['kind'] != 'prose':
            continue
        t = s['text'].strip()
        if (NUMBER.fullmatch(t) or AXIS.fullmatch(t)) and any(lo <= s['bbox'][1] <= hi for lo,hi in chart_y_ranges):
            s['kind'] = 'chart_text'
            added += 1
    if added:
        warnings.append('axis_tick_text_separated_from_prose')

    # Formula reconstruction is unsafe if math is broken across independent blocks.
    # Flag it for a later formula/vision stage; never silently manufacture a formula.
    fragments = []
    for i,s in enumerate(segments):
        if s['text'].strip() in {'√', '∑', '∫'}:
            fragments.append({'segment_index':i, 'text':s['text'], 'bbox':s['bbox']})
    if fragments:
        warnings.append('formula_fragments_visual_review_required')
    result['formula_fragments'] = fragments

    flow = result['diagnostics'].get('flowchart_candidate', False)
    result['visual_review_required'] = bool(flow or fragments)
    result['indexing_safe'] = not flow and not fragments
    if flow:
        # Keep original prose for inspection, but provide no safe-to-index prose.
        result['indexable_prose_text'] = ''
        warnings.append('flowchart_prose_indexing_blocked')
    else:
        result['indexable_prose_text'] = '\n\n'.join(s['text'] for s in segments if s['kind'] != 'chart_text')
    result['prose_text'] = '\n\n'.join(s['text'] for s in segments if s['kind'] != 'chart_text')
    result['warnings'] = list(dict.fromkeys(warnings))
    result['diagnostics']['axis_chart_text_blocks_added'] = added
    result['diagnostics']['formula_fragments'] = len(fragments)
    return result
