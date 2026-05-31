from __future__ import annotations
import os
import sys
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scraper.scheduler import carregar_consolidado
from calculadora.ranking import evolucao_historica, percentil_municipio
from utils.formatters import fmt_moeda, fmt_numero

st.set_page_config(
    page_title="Consulta — FUNDEB/ICMS MG",
    page_icon="🔍", layout="wide"
)
st.title("🔍 Consulta por Município")
st.caption("Painel detalhado com todos os indicadores, repasses e status VAAR")

@st.cache_data(ttl=3600)
def carregar():
    return carregar_consolidado()

df = carregar()
if df.empty:
    st.error("Dados não disponíveis.")
    st.stop()

# ── Seleção ───────────────────────────────────────────────────────────────────
municipios = sorted(df["municipio"].dropna().unique())
col1, col2 = st.columns([3, 1])
with col1:
    mun_sel = st.selectbox("Selecione o município", municipios)
with col2:
    ano_sel = st.selectbox("Ano", sorted(df["ano"].unique(), reverse=True))

df_mun = df[(df["municipio"] == mun_sel) & (df["ano"] == ano_sel)]
if df_mun.empty:
    st.warning(f"Sem dados para {mun_sel} em {ano_sel}.")
    st.stop()

row = df_mun.iloc[0]

# ── Extrair valores antecipadamente ──────────────────────────────────────────
habilitado = bool(row.get("habilitado_vaar", True))
motivo     = str(row.get("motivo_inabilitacao", "") or "")
rep_icms   = float(row.get("repasse_icms_educacao") or 0.0)
rep_vaar   = float(row.get("repasse_vaar") or 0.0)
conds      = str(row.get("condicionalidades_descumpridas", "") or "")

# ── Status VAAR ───────────────────────────────────────────────────────────────
st.divider()
if habilitado:
    st.success(f"✅ **{mun_sel}** está **HABILITADO** à complementação VAAR em {ano_sel}.")
else:
    st.error(f"❌ **{mun_sel}** está **INABILITADO** ao VAAR em {ano_sel}.")
    if rep_vaar > 0:
        st.warning(
            f"ℹ️ O valor de {fmt_moeda(rep_vaar)} exibido em Repasses refere-se "
            f"ao ano anterior (dados FNDE disponíveis). "
            f"Em {ano_sel} o município não receberá VAAR por estar inabilitado."
        )
    if motivo:
        with st.expander("Ver motivo da inabilitação"):
            st.markdown(f"**Motivo (FNDE):** {motivo}")
            if conds:
                st.markdown(f"**Condicionalidades descumpridas:** {conds}")
            st.caption(
                "Fonte: Lista de Redes Inabilitadas VAAR — FNDE | "
                "Lei 14.113/2020, Art. 14"
            )

# ── Percentil ─────────────────────────────────────────────────────────────────
st.subheader(f"📍 {mun_sel} — {ano_sel}")
pct_ie = percentil_municipio(df[df["ano"] == ano_sel], mun_sel, "IE")
st.caption(
    f"Está no percentil **{pct_ie:.0f}º** entre os municípios de MG "
    f"no Índice de Educação de {ano_sel}."
)

# ── Indicadores ───────────────────────────────────────────────────────────────
st.subheader("Componentes do IQE")
c1, c2, c3, c4, c5 = st.columns(5)
for col_st, campo, label in [
    (c1, "IRAP", "IRAP\nDesempenho (50%)"),
    (c2, "IRE",  "IRE\nRendimento (20%)"),
    (c3, "IAE",  "IAE\nAtendimento (15%)"),
    (c4, "IGE",  "IGE\nGestão (15%)"),
    (c5, "IQE",  "IQE\nQualidade Total"),
]:
    valor = row.get(campo)
    col_st.metric(label, fmt_numero(valor, 4) if valor is not None else "—")

st.metric(
    label=f"🎯 IE — Índice de Educação ({ano_sel})",
    value=fmt_numero(row.get("IE"), 6),
    help="IE = IQE_mun / Σ IQE — participação proporcional no rateio do ICMS Educação"
)

# ── Repasses ─────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Repasses Recebidos")
r1, r2, r3 = st.columns(3)
r1.metric("ICMS Educacional (MG)", fmt_moeda(rep_icms))
r2.metric(
    "Complementação VAAR (FNDE)",
    fmt_moeda(rep_vaar) if rep_vaar > 0 else "—",
    delta="Inabilitado" if not habilitado else None,
    delta_color="inverse",
)
r3.metric("Total (ICMS + VAAR)", fmt_moeda(rep_icms + rep_vaar))

# ── Evolução histórica ────────────────────────────────────────────────────────
st.divider()
st.subheader("Evolução Histórica")
df_hist = evolucao_historica(df, mun_sel)

if not df_hist.empty and len(df_hist) > 1:
    fig = go.Figure()
    cores = {
        "IRAP": "#1155A4", "IRE": "#0891B2",
        "IAE": "#6B3FA0",  "IGE": "#D97706", "IE": "#DC2626"
    }
    for ind, cor in cores.items():
        if ind in df_hist.columns:
            fig.add_trace(go.Scatter(
                x=df_hist["ano"], y=df_hist[ind],
                name=ind, mode="lines+markers",
                line=dict(color=cor, width=2),
                marker=dict(size=8),
            ))
    fig.update_layout(
        xaxis_title="Ano", yaxis_title="Índice",
        legend_title="Indicador", height=340,
        margin=dict(l=0, r=0, t=20, b=0),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Histórico disponível com dados de múltiplos anos.")

# ── Dados brutos ──────────────────────────────────────────────────────────────
with st.expander("📄 Dados completos"):
    df_exibir = df_mun.T.rename(columns={df_mun.index[0]: "Valor"})
    df_exibir["Valor"] = df_exibir["Valor"].astype(str)
    st.dataframe(df_exibir)
    