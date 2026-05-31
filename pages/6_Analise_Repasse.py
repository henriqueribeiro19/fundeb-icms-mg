from __future__ import annotations
import os
import sys
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from utils.config import TOTAL_ICMS_EDUCACAO_MG, TOTAL_VAAR_MG
from utils.formatters import fmt_moeda, fmt_numero, fmt_percentual
from scraper.scheduler import carregar_consolidado

st.set_page_config(
    page_title="Análise de Repasse — FUNDEB/ICMS MG",
    page_icon="💰", layout="wide"
)
st.title("💰 Dinheiro que Ficou na Mesa")
st.caption(
    "Análise de quanto do ICMS Educacional e do VAAR efetivamente chegou "
    "aos municípios — e quanto foi perdido por inabilitações."
)


@st.cache_data(ttl=3600)
def carregar():
    return carregar_consolidado()


df = carregar()
if df.empty:
    st.error("Dados não disponíveis.")
    st.stop()

ano = st.selectbox("Ano de referência", sorted(df["ano"].unique(), reverse=True))
df_ano = df[df["ano"] == ano].copy()

total_icms = TOTAL_ICMS_EDUCACAO_MG.get(ano, 5_500_000_000.0)
total_vaar = TOTAL_VAAR_MG.get(ano, 1_600_000_000.0)

# ── Dados de habilitação (apenas inabilitados com motivo real) ─────────────
df_inab = df_ano[
    (df_ano["habilitado_vaar"] == False) &
    (df_ano["motivo_inabilitacao"].notna()) &
    (df_ano["motivo_inabilitacao"] != "")
].copy()

df_hab = df_ano[df_ano["habilitado_vaar"] == True].copy()

n_inab = len(df_inab)
n_hab  = len(df_hab)

# VAAR repassado real (apenas municípios com valor positivo)
vaar_repassado = df_ano["repasse_vaar"].fillna(0).sum()

# VAAR estimado perdido = soma do IE dos inabilitados × total VAAR
# (quanto eles receberiam proporcionalmente se fossem habilitados)
vaar_perdido = df_inab["IE"].sum() * total_vaar

# ICMS repassado real
icms_repassado = df_ano["repasse_icms_educacao"].fillna(0).sum()

st.divider()

# ═══════════════════════════════════════════════════════════════════════════
# SEÇÃO 1 — VISÃO GERAL
# ═══════════════════════════════════════════════════════════════════════════
st.header("📊 Visão Geral — Minas Gerais")

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    "ICMS Educação Previsto",
    fmt_moeda(total_icms),
    help="10% do ICMS total de MG (Lei 24.431/2023)"
)
col2.metric(
    "ICMS Educação Repassado",
    fmt_moeda(icms_repassado),
    help="Soma dos repasses calculados pelo IE de cada município"
)
col3.metric(
    "Municípios Inabilitados ao VAAR",
    f"{n_inab} de 853",
    delta=f"{n_inab/853*100:.1f}% sem VAAR",
    delta_color="inverse"
)
col4.metric(
    "VAAR Estimado Perdido",
    fmt_moeda(vaar_perdido),
    help="Valor que os municípios inabilitados deixaram de receber",
    delta=f"{vaar_perdido/total_vaar*100:.1f}% do total VAAR",
    delta_color="inverse"
)

st.divider()

# ── Gráfico comparativo ICMS + VAAR ───────────────────────────────────────
st.subheader("💵 Comparativo — Previsto vs Repassado vs Perdido")

fig_comp = go.Figure()

categorias = ["ICMS Educação", "VAAR"]
previsto   = [total_icms,    total_vaar]
repassado  = [icms_repassado, vaar_repassado]
perdido    = [max(0, total_icms - icms_repassado), vaar_perdido]

fig_comp.add_trace(go.Bar(
    name="Previsto / Disponível",
    x=categorias, y=previsto,
    marker_color="#93C5FD",
    text=[fmt_moeda(v) for v in previsto],
    textposition="outside",
))
fig_comp.add_trace(go.Bar(
    name="Efetivamente Repassado",
    x=categorias, y=repassado,
    marker_color="#1155A4",
    text=[fmt_moeda(v) for v in repassado],
    textposition="outside",
))
fig_comp.add_trace(go.Bar(
    name="Estimado Não Recebido (inabilitações)",
    x=["VAAR"],
    y=[vaar_perdido],
    marker_color="#DC2626",
    text=[fmt_moeda(vaar_perdido)],
    textposition="outside",
))
fig_comp.update_layout(
    barmode="group",
    height=380,
    margin=dict(l=0, r=0, t=30, b=0),
    yaxis_title="R$",
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig_comp, use_container_width=True)

# ── Pizza habilitados vs inabilitados ─────────────────────────────────────
st.subheader("🔒 VAAR — Habilitados vs Inabilitados")
col_a, col_b = st.columns([1, 1])

with col_a:
    fig_pizza = px.pie(
        values=[n_hab, n_inab],
        names=[f"Habilitados ({n_hab})", f"Inabilitados ({n_inab})"],
        color_discrete_sequence=["#DC2626", "#047857"],
        hole=0.5,
    )
    fig_pizza.update_traces(
        textinfo="percent+label",
        textfont_size=13,
    )
    fig_pizza.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=True,
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig_pizza, use_container_width=True)

with col_b:
    st.markdown("#### O que significa estar inabilitado?")
    st.markdown(
        "Municípios inabilitados **não recebem a complementação VAAR** "
        "do governo federal. O valor que seria destinado a eles "
        "retorna ao fundo e é **redistribuído entre os habilitados**."
    )
    st.markdown("**Condicionalidades (Lei 14.113/2020, Art. 14):**")
    for cond in [
        "I — Gestores por mérito/desempenho",
        "II — ≥ 80% de participação no SAEB",
        "III — Redução de desigualdades socioeconômicas",
        "IV — Lei estadual ICMS Educação vigente",
        "V — Currículo alinhado à BNCC",
    ]:
        st.markdown(f"- {cond}")
    st.caption("Todas as 5 são cumulativas — uma falha = inabilitado.")

st.divider()

# ═══════════════════════════════════════════════════════════════════════════
# SEÇÃO 2 — ANÁLISE POR MUNICÍPIO
# ═══════════════════════════════════════════════════════════════════════════
st.header("🏙️ Análise por Município")

municipios = sorted(df_ano["municipio"].dropna().unique())
mun_sel = st.selectbox("Selecione o município", municipios)
row = df_ano[df_ano["municipio"] == mun_sel].iloc[0]

habilitado    = bool(row.get("habilitado_vaar", True))
motivo        = str(row.get("motivo_inabilitacao", "") or "")
ie            = float(row.get("IE", 0) or 0)
icms_rec      = float(row.get("repasse_icms_educacao", 0) or 0)
vaar_rec      = float(row.get("repasse_vaar", 0) or 0)
vaar_pot      = ie * total_vaar
na_mesa       = vaar_pot if not habilitado else 0.0
total_rec     = icms_rec + (vaar_rec if habilitado else 0)
total_pot     = icms_rec + vaar_pot

# Badge
if habilitado:
    st.success(f"✅ **{mun_sel}** está HABILITADO ao VAAR em {ano}")
else:
    st.error(f"❌ **{mun_sel}** está INABILITADO ao VAAR em {ano}")
    if motivo:
        with st.expander("Ver motivo da inabilitação"):
            st.markdown(f"**Motivo:** {motivo}")

# Métricas
m1, m2, m3, m4 = st.columns(4)
m1.metric("IE (participação)", fmt_percentual(ie))
m2.metric("ICMS Educação", fmt_moeda(icms_rec))
m3.metric(
    "VAAR recebido",
    fmt_moeda(vaar_rec) if habilitado else "R$ 0,00",
    delta="Inabilitado — não recebeu VAAR" if not habilitado else None,
    delta_color="inverse"
)
m4.metric(
    "VAAR estimado perdido",
    fmt_moeda(na_mesa) if na_mesa > 0 else "R$ 0,00",
    delta=f"{na_mesa/total_pot*100:.1f}% do potencial" if na_mesa > 0 else None,
    delta_color="inverse" if na_mesa > 0 else "normal"
)

# Gráfico comparativo do município
st.subheader(f"Recebido vs Potencial — {mun_sel}")
fig_mun = go.Figure()
cats = ["ICMS Educação", "VAAR"]
rec  = [icms_rec, vaar_rec if habilitado else 0]
pot  = [icms_rec, vaar_pot]

fig_mun.add_trace(go.Bar(
    name="Potencial",
    x=cats, y=pot,
    marker_color="#93C5FD",
    text=[fmt_moeda(v) for v in pot],
    textposition="outside",
))
fig_mun.add_trace(go.Bar(
    name="Recebido",
    x=cats, y=rec,
    marker_color="#1155A4",
    text=[fmt_moeda(v) for v in rec],
    textposition="outside",
))
fig_mun.update_layout(
    barmode="group", height=320,
    margin=dict(l=0, r=0, t=20, b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig_mun, use_container_width=True)

if na_mesa > 0:
    st.error(
        f"🚨 **{mun_sel}** deixou **{fmt_moeda(na_mesa)}** na mesa em {ano} "
        f"por estar inabilitado ao VAAR — "
        f"**{na_mesa/total_pot*100:.1f}%** do seu potencial total de repasse."
    )
else:
    st.success(
        f"✅ **{mun_sel}** recebeu o repasse completo em {ano}."
    )

st.divider()

# ═══════════════════════════════════════════════════════════════════════════
# SEÇÃO 3 — TOP 20 QUE MAIS PERDERAM
# ═══════════════════════════════════════════════════════════════════════════
st.header("📉 Municípios que Mais Perderam com a Inabilitação")
st.caption(
    "Apenas municípios com motivo de inabilitação confirmado pelo FNDE, "
    "ordenados pelo VAAR estimado não recebido."
)

df_rank = df_inab.copy()
df_rank["vaar_perdido"] = df_rank["IE"] * total_vaar
df_rank = df_rank.nlargest(20, "vaar_perdido")

fig_rank = px.bar(
    df_rank,
    x="vaar_perdido", y="municipio",
    orientation="h",
    color="vaar_perdido",
    color_continuous_scale="Reds",
    text=df_rank["vaar_perdido"].apply(fmt_moeda),
    labels={"vaar_perdido": "VAAR não recebido (R$)", "municipio": "Município"},
    height=520,
)
fig_rank.update_traces(textposition="outside")
fig_rank.update_layout(
    yaxis={"categoryorder": "total ascending"},
    coloraxis_showscale=False,
    margin=dict(l=0, r=150, t=20, b=0),
)
st.plotly_chart(fig_rank, use_container_width=True)

# Tabela
tabela = df_rank[[
    "municipio", "IE",
    "repasse_icms_educacao", "vaar_perdido",
    "motivo_inabilitacao"
]].copy()
tabela.columns = [
    "Município", "IE",
    "ICMS Recebido (R$)", "VAAR Perdido Estimado (R$)",
    "Motivo Inabilitação"
]
tabela.index = range(1, len(tabela) + 1)
st.dataframe(tabela, use_container_width=True)

with st.expander("📖 Nota metodológica"):
    st.markdown(f"""
    **Como é calculado o VAAR estimado perdido:**

    ```
    VAAR potencial do município = IE × Total VAAR do Estado
    VAAR perdido = VAAR potencial (municípios inabilitados)
    ```

    - O **IE** (Índice de Educação) representa a participação proporcional
      do município no rateio — calculado a partir dos índices da FJP
    - O **Total VAAR de MG** em {ano} é de **{fmt_moeda(total_vaar)}**
      (fonte: FNDE — Portaria Interministerial)
    - Municípios inabilitados têm seus valores redistribuídos entre
      os habilitados — **o dinheiro não some, mas não chega para quem
      mais precisa de apoio educacional**

    **Fonte dos dados:** FJP (índices) | FNDE (repasses e inabilitados)
    **Legislação:** Lei 14.113/2020 (VAAR) | Lei 24.431/2023 (ICMS Educação)
    """)

st.info(
    f"ℹ️ **Nota sobre o VAAR {ano}:** O valor de {fmt_moeda(total_vaar)} "
    f"representa o **acumulado de todas as portarias** publicadas até a "
    f"última atualização — não o valor de uma única portaria."
    if ano == 2025 else ""
)