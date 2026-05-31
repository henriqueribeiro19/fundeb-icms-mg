"""
pages/5_Ranking.py
Ranking e comparação entre municípios por indicador.
"""
from __future__ import annotations
import os
import sys
import streamlit as st
import plotly.express as px

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scraper.scheduler import carregar_consolidado
from calculadora.ranking import gerar_ranking, comparar_municipios
from utils.formatters import fmt_moeda, fmt_numero, fmt_percentual

st.set_page_config(page_title="Ranking — FUNDEB/ICMS MG", page_icon="🏆", layout="wide")
st.title("🏆 Ranking de Municípios")
st.caption("Compare e classifique os municípios de MG por qualquer indicador")

@st.cache_data(ttl=3600)
def carregar():
    return carregar_consolidado()

df = carregar()
if df.empty:
    st.error("Dados não disponíveis.")
    st.stop()

# ── Controles ─────────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
with col1:
    ano_sel = st.selectbox("Ano", sorted(df["ano"].unique(), reverse=True))
with col2:
    indicadores = {
        "IE — Índice de Educação":        "IE",
        "IRAP — Desempenho Escolar":      "IRAP",
        "IRE — Rendimento Escolar":       "IRE",
        "IAE — Atendimento Educacional":  "IAE",
        "IGE — Gestão Escolar":           "IGE",
        "Repasse ICMS (R$)":              "repasse_icms_educacao",
        "Repasse VAAR (R$)":              "repasse_vaar",
    }
    ind_nome = st.selectbox("Ordenar por", list(indicadores.keys()))
    ind_col  = indicadores[ind_nome]
with col3:
    top_n = st.slider("Top N municípios", 5, 100, 20)
with col4:
    ordem = st.radio("Ordem", ["Maiores", "Menores"], horizontal=True)

df_ano = df[df["ano"] == ano_sel]

# ── Ranking principal ─────────────────────────────────────────────────────────
st.subheader(f"Ranking — {ind_nome} ({ano_sel})")

df_rank = gerar_ranking(df_ano, coluna=ind_col, top_n=top_n, ascendente=(ordem == "Menores"))

# Gráfico de barras horizontal
fig = px.bar(
    df_rank.reset_index(),
    x=ind_col,
    y="municipio",
    orientation="h",
    color=ind_col,
    color_continuous_scale="Blues" if ordem == "Maiores" else "Reds",
    labels={"municipio": "Município", ind_col: ind_nome},
    height=max(400, top_n * 22),
)
fig.update_layout(
    yaxis={"categoryorder": "total ascending"},
    showlegend=False,
    margin=dict(l=0, r=0, t=20, b=0),
    coloraxis_showscale=False,
)
st.plotly_chart(fig, use_container_width=True)

# Tabela
colunas_tabela = ["municipio", "IE", "IRAP", "IRE", "IAE", "IGE",
                  "repasse_icms_educacao", "repasse_vaar"]
colunas_disp = [c for c in colunas_tabela if c in df_rank.columns]
st.dataframe(df_rank[colunas_disp], use_container_width=True)

# ── Comparação entre municípios ───────────────────────────────────────────────
st.divider()
st.subheader("Comparar Municípios")

municipios_todos = sorted(df_ano["municipio"].dropna().unique())
muns_sel = st.multiselect(
    "Selecione municípios para comparar",
    municipios_todos,
    default=municipios_todos[:3] if len(municipios_todos) >= 3 else municipios_todos,
    max_selections=10,
)

if muns_sel:
    df_comp = comparar_municipios(df_ano, muns_sel)
    if not df_comp.empty:
        # Radar chart
        indicadores_radar = ["IRAP", "IRE", "IAE", "IGE"]
        indicadores_disp  = [i for i in indicadores_radar if i in df_comp.columns]

        fig_radar = px.line_polar(
            df_comp.melt(id_vars="municipio", value_vars=indicadores_disp,
                         var_name="Indicador", value_name="Valor"),
            r="Valor", theta="Indicador", color="municipio",
            line_close=True,
            range_r=[0, 1],
            title="Comparação dos Componentes do IQE",
        )
        fig_radar.update_traces(fill="toself", opacity=0.3)
        st.plotly_chart(fig_radar, use_container_width=True)

        st.dataframe(df_comp.set_index("municipio"), use_container_width=True)
