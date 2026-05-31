from __future__ import annotations
import json
import os
import sys
import streamlit as st
import pandas as pd
import plotly.express as px

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scraper.scheduler import carregar_consolidado
from utils.formatters import fmt_numero, fmt_moeda

st.set_page_config(
    page_title="Mapa MG — FUNDEB/ICMS",
    page_icon="🗺️", layout="wide"
)
st.title("🗺️ Mapa de Indicadores — Minas Gerais")
st.caption("Visualização dos indicadores educacionais por município")

@st.cache_data(ttl=3600, show_spinner=False)
def carregar_dados():
    df = carregar_consolidado()
    with open('data/geo/municipios_mg.geojson', encoding='utf-8') as f:
        geojson = json.load(f)

    # Normaliza IDs do GeoJSON para corresponder ao cod_ibge do consolidado.
    for feature in geojson.get('features', []):
        props = feature.get('properties', {})
        if 'cod_ibge' in props:
            props['cod_ibge'] = str(props['cod_ibge'])

    return df, geojson

try:
    with st.spinner("Carregando dados e mapa..."):
        df, geojson = carregar_dados()
except Exception as e:
    st.error(f"Erro ao carregar dados: {str(e)}")
    st.stop()

if df is None or df.empty:
    st.error("Dados não disponíveis.")
    st.stop()

# ── Controles ─────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)

with col1:
    ano_sel = st.selectbox("Ano", sorted(df["ano"].unique(), reverse=True))

with col2:
    indicadores_disp = {
        "IE — Índice de Educação":        "IE",
        "IRAP — Desempenho Escolar":      "IRAP",
        "IRE — Rendimento Escolar":       "IRE",
        "IAE — Atendimento Educacional":  "IAE",
        "IGE — Gestão Escolar":           "IGE",
        "Repasse ICMS Educação (R$)":     "repasse_icms_educacao",
        "Repasse VAAR (R$)":              "repasse_vaar",
    }
    indicador_nome = st.selectbox("Indicador", list(indicadores_disp.keys()))
    indicador_col  = indicadores_disp[indicador_nome]

with col3:
    paletas = {
        "Amarelo → Vermelho": "YlOrRd",
        "Azul":               "Blues",
        "Verde":              "Greens",
        "Verde → Vermelho":   "RdYlGn",
        "Azul Púrpura":       "PuBu",
    }
    paleta_nome = st.selectbox("Paleta de cores", list(paletas.keys()))
    paleta      = paletas[paleta_nome]

# ── Preparar dados ────────────────────────────────────────────────────────────
df_ano = df[df["ano"] == ano_sel][["cod_ibge", "municipio", indicador_col]].copy()
df_ano["cod_ibge"] = df_ano["cod_ibge"].astype(str)

# Coluna de exibição formatada para o hover
df_ano["valor_fmt"] = df_ano[indicador_col].apply(
    lambda v: fmt_moeda(v) if "repasse" in indicador_col else fmt_numero(v, 4)
    if v == v else "—"
)

# ── Criar mapa Plotly ─────────────────────────────────────────────────────────
try:
    fig = px.choropleth_mapbox(
        df_ano,
        geojson=geojson,
        locations="cod_ibge",
        featureidkey="properties.cod_ibge",
        color=indicador_col,
        color_continuous_scale=paleta,
        mapbox_style="carto-positron",
        zoom=5.5,
        center={"lat": -18.5, "lon": -44.5},
        opacity=0.75,
        hover_name="municipio",
        hover_data={
            "cod_ibge":      False,
            indicador_col:   False,
            "valor_fmt":     True,
        },
        labels={"valor_fmt": indicador_nome},
        height=580,
    )

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        coloraxis_colorbar=dict(
            title=indicador_nome,
            thickness=15,
            len=0.6,
        ),
    )

    st.plotly_chart(fig, use_container_width=True)
except Exception as e:
    st.error(f"Erro ao renderizar mapa: {str(e)}")
    import traceback
    st.write(traceback.format_exc())

# ── Estatísticas ──────────────────────────────────────────────────────────────
st.divider()
st.subheader(f"Estatísticas — {indicador_nome} ({ano_sel})")
col_a, col_b, col_c, col_d = st.columns(4)
serie = df_ano[indicador_col].dropna()
col_a.metric("Média",   fmt_numero(serie.mean()))
col_b.metric("Mediana", fmt_numero(serie.median()))
col_c.metric("Mínimo",  fmt_numero(serie.min()))
col_d.metric("Máximo",  fmt_numero(serie.max()))