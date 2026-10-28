"""QuantBook AI local Streamlit research workspace (UI milestone 2.1)."""
from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import UUID

import requests
import streamlit as st

API_BASE = os.getenv("QUANTBOOK_API_URL", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_DOCUMENT = "62539443-b7ef-46a6-b059-ff58a2706fda"
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"

st.set_page_config(page_title="QuantBook AI", page_icon="📚", layout="wide")


def local_pdf_path(document_id: str) -> Path | None:
    """Only allow UUID-based local document paths, never arbitrary user paths."""
    try:
        safe_id = str(UUID(document_id.strip()))
    except (ValueError, AttributeError):
        return None
    path = BACKEND_DIR / "storage" / safe_id / "original.pdf"
    return path if path.is_file() else None


@st.cache_data(show_spinner=False, max_entries=16)
def render_page(pdf_path: str, page_number: int, modified_ns: int) -> tuple[bytes, int]:
    """Render one page on demand; no full-document image loading."""
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        count = len(doc)
        if not 1 <= page_number <= count:
            raise ValueError(f"Page must be between 1 and {count}")
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.35, 1.35), alpha=False)
        return pix.tobytes("png"), count


@st.cache_data(show_spinner=False, max_entries=16)
def pdf_page_count(pdf_path: str, modified_ns: int) -> int:
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        return len(doc)


def candidate_quality(raw: str) -> tuple[bool, str]:
    """Presentation-only heuristic; never alters or verifies source evidence."""
    text = raw.strip()
    if not text:
        return False, "empty"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False, "empty"
    # Chart markers (often single-letter G glyphs) are not useful equations.
    if all(re.fullmatch(r"(?:G\s*)+", line, flags=re.I) for line in lines):
        return False, "chart glyphs"
    if len(text) < 5 and not any(ch in text for ch in "=<>≤≥∑∫"):
        return False, "short fragment"
    # Candidate text should have an equality, an inequality, or a mathematical operator.
    if not re.search(r"[=≤≥<>∑∫]|\\(?:frac|sum|int)|[+−*/]", text):
        return False, "no recognizable equation operator"
    # Large mixed OCR/text blocks are safer in raw view than equation cards.
    if len(text) > 450 or len(lines) > 10:
        return False, "mixed or lengthy extraction"
    return True, "candidate"


def show_equation_candidates(pages: list[dict], pdf_available: bool) -> None:
    if not pages:
        st.info("No structured equation or table evidence returned.")
        return

    for item in pages:
        page = item.get("page_number")
        equations = item.get("equations") or []
        tables = item.get("tables") or []
        visible = []
        hidden = []
        for eq in equations:
            raw = str(eq.get("raw_text") or "")
            show, reason = candidate_quality(raw)
            (visible if show else hidden).append((eq, reason))

        with st.expander(
            f"Page {page} · {len(visible)} readable candidates · {len(hidden)} raw fragments",
            expanded=(page == st.session_state.current_page),
        ):
            if pdf_available and isinstance(page, int):
                if st.button(f"Open page {page} in reader", key=f"evidence_page_{page}"):
                    st.session_state.current_page = page
                    st.rerun()
            st.caption("These are unverified extraction candidates, not validated mathematical formulas.")
            if not visible:
                st.info("No clearly readable equation candidates. Inspect the original PDF or raw extraction.")
            for n, (eq, _) in enumerate(visible, 1):
                st.markdown(f"**Candidate {n} · Unverified**")
                # Preserve exact extraction: never guess missing fraction bars or denominators.
                st.code(str(eq.get("raw_text") or ""), language=None)
                if eq.get("verified") is True:
                    st.caption("Backend verified flag: true (review verification provenance)")
                else:
                    st.caption(f"Backend status: {eq.get('status', 'unverified')} · Human review required")
            if tables:
                with st.expander(f"Table candidates ({len(tables)}) · Unverified"):
                    for table in tables:
                        st.json(table.get("rows") or [])
            with st.expander(f"Raw extraction ({len(equations)} equation candidates)"):
                st.caption("Original extraction retained for debugging; may contain chart labels and broken fractions.")
                for n, eq in enumerate(equations, 1):
                    st.markdown(f"**Raw candidate {n}**")
                    st.code(str(eq.get("raw_text") or "(empty)"), language=None)
                if hidden:
                    st.caption("Hidden from readable view: " + ", ".join(f"#{equations.index(eq)+1} ({reason})" for eq, reason in hidden))


if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_page" not in st.session_state:
    st.session_state.current_page = 1
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "selected_document" not in st.session_state:
    st.session_state.selected_document = DEFAULT_DOCUMENT

st.title("📚 QuantBook AI")
st.caption("Local PDF research · Source navigation · Unverified evidence clearly marked")

with st.sidebar:
    st.header("Research settings")
    document_id = st.text_input("Document ID", value=DEFAULT_DOCUMENT).strip()
    if document_id != st.session_state.selected_document:
        st.session_state.selected_document = document_id
        st.session_state.messages = []
        st.session_state.last_result = None
        st.session_state.current_page = 1
    mode = st.selectbox("Research mode", ["retrieve", "answer"])
    top_k = st.slider("Number of sources", 1, 8, 5)
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.session_state.last_result = None
        st.rerun()
    st.caption("PDFs are read locally. Research requests go to FastAPI on localhost.")

pdf_path = local_pdf_path(document_id)
reader, assistant = st.columns([1.05, 1], gap="large")

with reader:
    st.subheader("PDF Reader")
    if pdf_path is None:
        st.info("No local original.pdf found for this document ID. Check backend/storage/<document-id>/original.pdf.")
    else:
        try:
            stamp = pdf_path.stat().st_mtime_ns
            total_pages = pdf_page_count(str(pdf_path), stamp)
            st.session_state.current_page = max(1, min(st.session_state.current_page, total_pages))
            st.number_input("Page", min_value=1, max_value=total_pages, key="current_page")
            png, _ = render_page(str(pdf_path), st.session_state.current_page, stamp)
            st.image(png, use_container_width=True)
            st.caption(f"Page {st.session_state.current_page} of {total_pages} · {pdf_path.name}")
        except (OSError, ValueError, RuntimeError, ImportError) as exc:
            st.error(f"PDF rendering failed: {exc}")

with assistant:
    st.subheader("Research Assistant")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("Ask a question about this document")
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.spinner("Retrieving evidence..."):
            try:
                response = requests.post(
                    f"{API_BASE}/api/v1/research/unified",
                    json={
                        "document_id": document_id,
                        "question": question,
                        "mode": mode,
                        "top_k": top_k,
                        "include_visual_evidence": False,
                    },
                    timeout=180,
                )
                response.raise_for_status()
                data = response.json()
                sources = data.get("sources") or []
                answer = data.get("answer") or f"Found {len(sources)} relevant source passages."
                st.session_state.last_result = data
                st.session_state.messages.append({"role": "assistant", "content": answer})
                st.rerun()
            except (requests.RequestException, ValueError) as exc:
                st.error(f"Research request failed: {exc}")

    result = st.session_state.last_result
    if result:
        sources_tab, evidence_tab = st.tabs(["Sources", "Evidence inspector"])
        with sources_tab:
            sources = result.get("sources") or []
            if not sources:
                st.info("No source passages returned.")
            for i, source in enumerate(sources):
                page = source.get("page_number")
                citation = source.get("citation_id", f"S{i + 1}")
                with st.expander(f"[{citation}] Page {page}", expanded=i == 0):
                    if isinstance(page, int) and pdf_path is not None:
                        if st.button(f"Open page {page} in reader", key=f"src_{i}_{page}"):
                            st.session_state.current_page = page
                            st.rerun()
                    with st.expander("Raw source passage"):
                        st.text(source.get("text") or "No excerpt available")
        with evidence_tab:
            validation = result.get("validation") or {}
            st.caption(f"Validation: {validation.get('status', 'unknown')}")
            for warning in validation.get("warnings") or []:
                st.warning(str(warning))
            for conflict in validation.get("possible_disagreements") or []:
                st.error("Possible formula disagreement — requires human review")
                st.json(conflict)
            structured = result.get("structured_evidence") or {}
            st.caption(f"Structured evidence: {structured.get('status', 'unavailable')}")
            show_equation_candidates(structured.get("pages") or [], pdf_path is not None)
