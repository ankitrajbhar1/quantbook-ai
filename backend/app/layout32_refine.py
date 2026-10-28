"""Phase 3.2.1 refinement: read-only conservative interpretation of layout JSON.

No OCR, no model inference, no changes to source text or indexed chunks.
"""
from __future__ import annotations
import re

BULLET = re.compile(r'^\s*(?:[•●▪]|\d+[.)])\s+')
PLOT_MARKER = re.compile(r'^[Gg]$')
TICK = re.compile(r'^[-−+]?\d+(?:\.\d+)?$')
AXIS = re.compile(r'^(?:Lag|Year|ACF|PACF|Partial ACF)$', re.I)
FLOW = re.compile(r'\b(?:yes|no|select model|auto\.arima\(\)|white noise|calculate forecasts)\b', re.I)


def _chart_regions(blocks):
    """Identify high-confidence plot-marker clusters, never delete chart content."""
    markers = [b for b in blocks if PLOT_MARKER.fullmatch(b['text'].strip())]
    if len(markers) < 12:
        return []
    ys = sorted((b['bbox'][1] + b['bbox'][3]) / 2 for b in markers)
    # Only label a region if dense plot markers are spatially concentrated.
    if ys[-1] - ys[0] > 500:
        return []
    return [{'bbox': [min(b['bbox'][0] for b in markers), min(b['bbox'][1] for b in markers),
                      max(b['bbox'][2] for b in markers), max(b['bbox'][3] for b in markers)],
             'marker_count': len(markers), 'reason': 'dense_single_character_plot_markers'}]


def refine_layout(data: dict) -> dict:
    blocks = data.get('blocks', [])
    if not isinstance(blocks, list):
        raise ValueError('blocks must be a list')
    regions = _chart_regions(blocks)
    flow_matches = sum(bool(FLOW.search(b.get('text', ''))) for b in blocks)
    # The flowchart criterion is intentionally conservative. It marks a page
    # for review; it does not infer arrows or graph topology.
    flow_candidate = flow_matches >= 4 and (data.get('layout') == 'two_column_candidate')
    segments = []
    current = None
    chart_count = 0

    def flush():
        nonlocal current
        if current:
            segments.append(current)
            current = None

    for b in blocks:
        t = b.get('text', '').strip()
        if not t:
            continue
        box = b['bbox']
        in_plot = bool(regions) and (PLOT_MARKER.fullmatch(t) or
                    (TICK.fullmatch(t) or AXIS.fullmatch(t)) and
                    any(r['bbox'][1]-12 <= box[1] <= r['bbox'][3]+24 for r in regions))
        if in_plot:
            flush()
            chart_count += 1
            segments.append({'kind': 'chart_text', 'text': t, 'bbox': box, 'source_orders': [b['original_order']]})
            continue
        is_bullet = bool(BULLET.match(t))
        # Merge only consecutive prose lines in the same approximate left indent.
        # Never merge formula-looking lines or cross large vertical gaps.
        formula = bool(re.search(r'[=√∑∫]', t))
        if (current and current['kind'] == 'prose' and not is_bullet and not formula
            and not current.get('_formula') and
            abs(box[0] - current['_last_left']) <= 32 and
            0 <= box[1] - current['_last_bottom'] <= 5.5 and
            not current['text'].rstrip().endswith((':',))):
            if current['text'].endswith('-') and t[:1].islower():
                current['text'] = current['text'][:-1] + t
            else:
                current['text'] += ' ' + t
            current['bbox'] = [min(current['bbox'][0], box[0]), min(current['bbox'][1], box[1]),
                               max(current['bbox'][2], box[2]), max(current['bbox'][3], box[3])]
            current['source_orders'].append(b['original_order'])
            current['_last_bottom'] = box[3]
            current['_last_left'] = box[0]
        else:
            flush()
            current = {'kind': 'formula_or_symbol' if formula else 'prose', 'text': t,
                       'bbox': list(box), 'source_orders': [b['original_order']],
                       '_last_bottom': box[3], '_last_left': box[0], '_formula': formula}
    flush()
    for s in segments:
        for k in ('_last_bottom', '_last_left', '_formula'):
            s.pop(k, None)
    return {
        'page_number': data.get('page_number'),
        'layout': data.get('layout'),
        'segments': segments,
        'prose_text': '\n\n'.join(s['text'] for s in segments if s['kind'] != 'chart_text'),
        'chart_regions': regions,
        'warnings': (['possible_flowchart_reading_order_unreliable'] if flow_candidate else []) +
                    (['chart_text_separated_from_prose'] if regions else []),
        'diagnostics': {'input_blocks': len(blocks), 'output_segments': len(segments),
                        'chart_text_blocks': chart_count, 'flowchart_candidate': flow_candidate},
    }
