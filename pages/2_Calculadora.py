from __future__ import annotations
import os
import sys
import pandas as pd
import streamlit as st
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from calculadora.formulas import (
    calcular_iqe, calcular_ie, calcular_repasse_icms,
    calcular_coef_vaar, calcular_repasse_vaar,
)
from utils.formatters import fmt_moeda, fmt_numero, fmt_percentual
from utils.validators import validar_iqe
from utils.config import TOTAL_ICMS_EDUCACAO_MG, TOTAL_VAAR_MG

st.set_page_config(
    page_title="Calculadora — FUNDEB/ICMS MG",
    page_icon="🧮", layout="wide"
)
st.title("🧮 Calculadora de Indicadores")
st.caption("Calcule o IE, IQE e estimativa de repasse para qualquer município")


@st.cache_data(ttl=3600)
def carregar_fjp() -> pd.DataFrame:
    path = Path("data/processed/fjp_indices.parquet")
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_parquet(path)
    if "cod_ibge" in df.columns:
        df["cod_ibge"] = df["cod_ibge"].astype(str).str.strip()
        df = df[df["cod_ibge"].str.match(r"^\d{7}$", na=False)].copy()
    df = df[df["municipio"].astype(str).str.strip().ne("")].copy()
    return df


@st.cache_data(ttl=3600)
def carregar_parametros_ano(ano: int) -> dict:
    """Carrega Σ IQE real e totais estaduais para o ano."""
    df = carregar_fjp()
    soma_iqe = 1.0
    if not df.empty and "IQE" in df.columns:
        soma = df[df["ano"] == ano]["IQE"].sum()
        if soma > 0:
            soma_iqe = float(soma)
    return {
        "soma_iqe":   soma_iqe,
        "total_icms": float(TOTAL_ICMS_EDUCACAO_MG.get(ano, 5_500_000_000.0)),
        "total_vaar": float(TOTAL_VAAR_MG.get(ano, 1_600_000_000.0)),
    }


def buscar_indices_municipio(municipio: str, ano: int) -> dict | None:
    """Busca os índices reais do município na base FJP."""
    df = carregar_fjp()
    if df.empty:
        return None
    mask = (df["municipio"].str.upper() == municipio.strip().upper()) & (df["ano"] == ano)
    if not mask.any():
        return None
    row = df[mask].iloc[0]
    return {
        "IRAP": float(row.get("IRAP", 0)),
        "IRE":  float(row.get("IRE",  0)),
        "IAE":  float(row.get("IAE",  0)),
        "IGE":  float(row.get("IGE",  0)),
        "IQE":  float(row.get("IQE",  0)),
        "IE":   float(row.get("IE",   0)),
    }


# ── Seleção do ano e município FORA do formulário ─────────────────────────────
col_ano, col_mun = st.columns([1, 3])

with col_ano:
    ano = st.selectbox("Ano de referência", [2026, 2025, 2024])

with col_mun:
    df_fjp = carregar_fjp()
    municipios = sorted(df_fjp["municipio"].unique()) if not df_fjp.empty else []
    municipio_sel = st.selectbox(
        "Município (opcional — preenche os índices automaticamente)",
        [""] + municipios,
        format_func=lambda x: "Selecione para preencher automaticamente..." if x == "" else x
    )

# Carregar parâmetros do ano
params = carregar_parametros_ano(ano)

# Buscar índices do município selecionado
indices_auto = buscar_indices_municipio(municipio_sel, ano) if municipio_sel else None

if indices_auto:
    st.success(
        f"✅ Índices de **{municipio_sel}** ({ano}) carregados automaticamente da FJP — "
        f"IQE = `{indices_auto['IQE']:.8f}` | IE = `{indices_auto['IE']:.8f}`"
    )
else:
    st.info(
        f"📊 Parâmetros para **{ano}**: "
        f"Σ IQE = `{params['soma_iqe']:.8f}` | "
        f"Total ICMS = `{fmt_moeda(params['total_icms'])}` | "
        f"Total VAAR = `{fmt_moeda(params['total_vaar'])}`"
    )

# Valores padrão dos índices
def_irap = indices_auto["IRAP"] if indices_auto else 0.001000
def_ire  = indices_auto["IRE"]  if indices_auto else 0.001000
def_iae  = indices_auto["IAE"]  if indices_auto else 0.001000
def_ige  = indices_auto["IGE"]  if indices_auto else 0.001000

# ── Formulário ────────────────────────────────────────────────────────────────
with st.form("calc_form"):
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Componentes do IQE")
        if indices_auto:
            st.caption("✅ Valores preenchidos automaticamente — edite se necessário")
        else:
            st.caption(
                "Valores na escala original da FJP — ex: 0,001422 | "
                "Selecione um município acima para preencher automaticamente"
            )

        irap = st.number_input("IRAP — Desempenho Escolar (peso 50%)",
                               min_value=0.0, max_value=1.0, value=def_irap,
                               step=0.000001, format="%.8f")
        ire  = st.number_input("IRE — Rendimento Escolar (peso 20%)",
                               min_value=0.0, max_value=1.0, value=def_ire,
                               step=0.000001, format="%.8f")
        iae  = st.number_input("IAE — Atendimento Educacional (peso 15%)",
                               min_value=0.0, max_value=1.0, value=def_iae,
                               step=0.000001, format="%.8f")
        ige  = st.number_input("IGE — Gestão Escolar (peso 15%)",
                               min_value=0.0, max_value=1.0, value=def_ige,
                               step=0.000001, format="%.8f")

    with col2:
        st.subheader("Parâmetros do Estado")
        st.caption(f"Carregados automaticamente para {ano} com dados reais da FJP/FNDE")

        total_icms = st.number_input(
            "Total ICMS Educação do Estado (R$)",
            value=params["total_icms"],
            step=1_000_000.0, format="%.2f"
        )
        soma_iqe = st.number_input(
            "Σ IQE de todos os municípios",
            value=params["soma_iqe"],
            step=0.000001, format="%.8f",
            help="Soma dos IQEs de todos os 853 municípios — carregado automaticamente da FJP"
        )
        total_vaar = st.number_input(
            "Total VAAR do Estado (R$)",
            value=params["total_vaar"],
            step=1_000_000.0, format="%.2f"
        )
        delta_mun = st.number_input(
            "ΔIndicador do município (variação)",
            value=0.000500, step=0.000001, format="%.6f",
            help="Melhoria do indicador educacional em relação ao ano anterior"
        )
        soma_delta = st.number_input(
            "Σ ΔIndicador de todos municípios habilitados",
            value=4.250000, step=0.000001, format="%.6f",
        )

    st.caption("💡 Parâmetros do estado atualizados automaticamente ao mudar o ano acima.")
    calcular = st.form_submit_button(
        "🧮 Calcular", use_container_width=True, type="primary"
    )

# ── Resultados ────────────────────────────────────────────────────────────────
if calcular:
    ok, erros = validar_iqe(irap, ire, iae, ige)
    if not ok:
        for e in erros:
            st.error(e)
        st.stop()

    iqe       = calcular_iqe(irap, ire, iae, ige)
    ie        = calcular_ie(iqe, soma_iqe)
    rep_icms  = calcular_repasse_icms(ie, total_icms)
    coef_vaar = calcular_coef_vaar(delta_mun, soma_delta)
    rep_vaar  = calcular_repasse_vaar(coef_vaar, total_vaar)

    nome_exib = municipio_sel or "Município"
    st.divider()
    st.subheader(f"📊 Resultado — {nome_exib} ({ano})")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("IQE",                   fmt_numero(iqe, 6))
    c2.metric("IE (participação)",     fmt_percentual(ie))
    c3.metric("Repasse ICMS Educação", fmt_moeda(rep_icms))
    c4.metric("Repasse VAAR",          fmt_moeda(rep_vaar))
    st.metric("💰 Total recebido (ICMS + VAAR)", fmt_moeda(rep_icms + rep_vaar))

    with st.expander("📐 Detalhamento dos cálculos"):
        st.markdown("**Fórmula IQE** (Anexo II — Lei 24.431/2023):")
        st.code(
            f"IQE = IRAP×0,50 + IRE×0,20 + IAE×0,15 + IGE×0,15\n"
            f"IQE = {irap:.8f}×0,50 + {ire:.8f}×0,20 "
            f"+ {iae:.8f}×0,15 + {ige:.8f}×0,15\n"
            f"IQE = {irap*0.50:.10f} + {ire*0.20:.10f} "
            f"+ {iae*0.15:.10f} + {ige*0.15:.10f}\n"
            f"IQE = {iqe:.10f}"
        )
        st.markdown("**Fórmula IE** (Anexo II — Lei 24.431/2023):")
        st.code(
            f"IE(i) = IQE(i) / Σ IQE(i)\n"
            f"IE    = {iqe:.10f} / {soma_iqe:.8f}\n"
            f"IE    = {ie:.10f}  ({fmt_percentual(ie)} do total)"
        )
        st.markdown("**Repasse ICMS Educação:**")
        st.code(
            f"Repasse = IE × Total_ICMS_Educação\n"
            f"Repasse = {ie:.10f} × {fmt_moeda(total_icms)}\n"
            f"Repasse = {fmt_moeda(rep_icms)}"
        )
        st.markdown("**Coeficiente VAAR** (Lei 14.113/2020):")
        st.code(
            f"CoefVAAR = ΔIndicador_mun / Σ ΔIndicador_rede\n"
            f"CoefVAAR = {delta_mun:.6f} / {soma_delta:.6f}\n"
            f"CoefVAAR = {coef_vaar:.10f}"
        )
        st.markdown("**Repasse VAAR:**")
        st.code(
            f"ValorVAAR = CoefVAAR × Total_VAAR_UF\n"
            f"ValorVAAR = {coef_vaar:.10f} × {fmt_moeda(total_vaar)}\n"
            f"ValorVAAR = {fmt_moeda(rep_vaar)}"
        )