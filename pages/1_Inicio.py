"""
pages/1_Inicio.py
Página inicial — visão geral do projeto e indicadores consolidados.
"""
from __future__ import annotations
import os
import sys
import streamlit as st
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scraper.scheduler import carregar_consolidado
from utils.formatters import fmt_moeda, fmt_numero

st.set_page_config(page_title="Início — FUNDEB/ICMS MG", page_icon="🏠", layout="wide")
st.title("🏠 Visão Geral")
st.caption("Indicadores Educacionais dos Municípios de Minas Gerais")

@st.cache_data(ttl=3600)
def carregar():
    return carregar_consolidado()

df = carregar()

if df.empty:
    st.error("Dados não disponíveis. Execute o scraper primeiro.")
    st.stop()

ano_sel = st.selectbox("Ano de referência", sorted(df["ano"].unique(), reverse=True))
df_ano = df[df["ano"] == ano_sel]

# ── Métricas gerais ──────────────────────────────────────────────────────────
st.subheader(f"Resumo — {ano_sel}")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Municípios", f"{df_ano['municipio'].nunique():,}")
col2.metric("IE médio", fmt_numero(df_ano["IE"].mean(), 4))
col3.metric("Total ICMS Educação", fmt_moeda(df_ano["repasse_icms_educacao"].sum()))
col4.metric("Total VAAR", fmt_moeda(df_ano["repasse_vaar"].sum()))
col5.metric("Mun. com VAAR > 0", f"{(df_ano['repasse_vaar'] > 0).sum():,}")

st.divider()

# ── Distribuição dos indicadores ─────────────────────────────────────────────
st.subheader("Distribuição dos Indicadores")
col_a, col_b = st.columns(2)
with col_a:
    st.markdown("**IE — Índice de Educação do Município**")
    st.bar_chart(df_ano["IE"].dropna().sort_values().reset_index(drop=True))
with col_b:
    st.markdown("**Componentes médios do IQE**")
    medias = {
        "IRAP (50%)": df_ano["IRAP"].mean(),
        "IRE (20%)":  df_ano["IRE"].mean(),
        "IAE (15%)":  df_ano["IAE"].mean(),
        "IGE (15%)":  df_ano["IGE"].mean(),
    }
    st.bar_chart(pd.Series(medias))

st.divider()

# ── Top 10 municípios ────────────────────────────────────────────────────────
st.subheader("Top 10 Municípios por IE")
top10 = df_ano.nlargest(10, "IE")[["municipio", "IE", "IQE", "repasse_icms_educacao", "repasse_vaar"]]
top10.index = range(1, 11)
st.dataframe(top10, use_container_width=True)
