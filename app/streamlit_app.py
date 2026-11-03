"""Interface com os dois chats.  Rode:  streamlit run app/streamlit_app.py"""

import streamlit as st

from lembra import memorias, rag
from lembra.config import get_settings
from lembra.store import VectorStore

st.set_page_config(page_title="Lembra", page_icon="🧠")
st.title("🧠 Lembra")

s = get_settings()
st.caption(
    f"Memórias: {len(memorias.listar(s))} · Chunks: {VectorStore(s.chroma_dir).total()} · "
    f"LLM: {s.llm_provider}"
)

aba_alimentar, aba_perguntar = st.tabs(["✍️ Alimentar", "💬 Perguntar"])

with aba_alimentar:
    st.write("Escreva uma memória, um fato ou uma história. Ela vira chunks e embeddings.")
    with st.form("nova_memoria", clear_on_submit=True):
        texto = st.text_area("Memória", height=200)
        col1, col2 = st.columns(2)
        categoria = col1.selectbox(
            "Categoria", ["geral", "família", "trabalho", "saúde", "viagens", "estudos", "gostos"]
        )
        data = col2.text_input("Quando aconteceu? (opcional)", placeholder="ex.: 2020")
        if st.form_submit_button("Salvar") and texto.strip():
            with st.spinner("Gerando chunks e embeddings…"):
                n = memorias.salvar(memorias.Memoria(texto=texto, categoria=categoria, data=data))
            st.success(f"Memória salva em {n} chunk(s).")

with aba_perguntar:
    if "historico" not in st.session_state:
        st.session_state.historico = []

    for msg in st.session_state.historico:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if pergunta := st.chat_input("Pergunte algo sobre a sua vida…"):
        st.session_state.historico.append({"role": "user", "content": pergunta})
        with st.chat_message("user"):
            st.markdown(pergunta)
        with st.chat_message("assistant"):
            with st.spinner("Buscando nas memórias…"):
                r = rag.perguntar(pergunta)
            st.markdown(r.texto)
            if r.fontes:
                with st.expander("Fontes usadas (o que o RAG recuperou)"):
                    for i, t in enumerate(r.fontes, start=1):
                        st.markdown(
                            f"**[{i}]** similaridade `{t.similaridade:.2f}` · "
                            f"{t.metadados.get('categoria')} · {t.metadados.get('data') or 's/ data'}"
                        )
                        st.text(t.texto)
        st.session_state.historico.append({"role": "assistant", "content": r.texto})
