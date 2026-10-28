
import os

import requests
import streamlit as st

API_BASE = os.getenv("QUANTBOOK_API_URL", "http://127.0.0.1:8000")
DOCUMENT_ID = "62539443-b7ef-46a6-b059-ff58a2706fda"

st.set_page_config(
    page_title="QuantBook AI",
    page_icon="📚",
    layout="wide",
)

st.title("📚 QuantBook AI")
st.caption("Local-first PDF research assistant")

with st.sidebar:
    st.header("Research settings")
    document_id = st.text_input("Document ID", value=DOCUMENT_ID)
    mode = st.selectbox("Research mode", ["retrieve", "answer"])
    top_k = st.slider("Number of sources", 1, 8, 5)

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("sources"):
            with st.expander("Sources"):
                for source in message["sources"]:
                    page = source.get("page_number", "Unknown")
                    st.write(f"Page {page}")

question = st.chat_input("Ask a question about your PDF...")

if question:
    st.session_state.messages.append(
        {"role": "user", "content": question}
    )

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Searching document..."):
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

                if mode == "retrieve":
                    answer = (
                        f"Found {len(data.get('sources', []))} "
                        "relevant source passages."
                    )
                else:
                    answer = data.get("answer") or "No answer generated."

                st.markdown(answer)

                sources = data.get("sources", [])
                if sources:
                    with st.expander("Sources"):
                        for source in sources:
                            page = source.get("page_number", "Unknown")
                            st.write(f"Page {page}")

                validation = data.get("validation") or {}
                if validation.get("possible_disagreements"):
                    st.warning("Evidence disagreement requires review.")

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "sources": sources,
                    }
                )

            except requests.RequestException as exc:
                st.error(f"Backend request failed: {exc}")

