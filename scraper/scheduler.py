"""
scraper/scheduler.py
Pipeline de consolidação de todos os dados.
"""
from __future__ import annotations
import pandas as pd
from loguru import logger

from utils.config import (
    ANOS_COLETA, COLUNAS_CONSOLIDADO,
    TOTAL_ICMS_EDUCACAO_MG, TOTAL_VAAR_MG,
    DATA_PROCESSED,
)
from utils.cache import salvar_parquet, carregar_parquet
from calculadora.calc_icms import calcular_icms_municipios
from calculadora.calc_vaar import calcular_vaar_municipios


def consolidar(anos: list[int] = ANOS_COLETA) -> pd.DataFrame:
    """
    Pipeline principal:
      1. Carrega FJP (IE, IRAP, IRE, IAE, IGE)
      2. Carrega receitas FNDE
      3. Carrega inabilitados FNDE
      4. Carrega INEP (fallback)
      5. Calcula IE e repasse ICMS por ano          ← PASSO CRÍTICO
      6. Mescla VAAR real (receitas + ajuste 2024)
      7. Mescla status de habilitação
      8. Salva consolidado.parquet
    """
    logger.info("=== Iniciando consolidação ===")

    # ── 1. FJP ───────────────────────────────────────────────────────────────
    df_fjp = carregar_parquet("fjp_indices")
    if df_fjp is None or df_fjp.empty:
        logger.warning("FJP indisponível — usando INEP como fallback.")
        df_fjp = pd.DataFrame()

    # ── 2. FNDE Receitas ──────────────────────────────────────────────────────
    df_receitas = carregar_parquet("fnde_receitas")
    if df_receitas is None:
        df_receitas = pd.DataFrame()
        logger.warning("Receitas FNDE não encontradas no cache.")

    # ── 3. FNDE Inabilitados ──────────────────────────────────────────────────
    df_inabilitados = carregar_parquet("fnde_inabilitados")
    if df_inabilitados is None:
        df_inabilitados = pd.DataFrame()
        logger.warning("Inabilitados FNDE não encontrados no cache.")

    # ── 4. INEP ───────────────────────────────────────────────────────────────
    df_inep = carregar_parquet("inep_indicadores")
    if df_inep is None:
        df_inep = pd.DataFrame()

    # ── 5. Montar base e calcular IE por ano ──────────────────────────────────
    if not df_fjp.empty:
        df_base = df_fjp.copy()
        logger.info(f"Base: FJP ({len(df_base)} registros)")
    elif not df_inep.empty:
        df_base = df_inep.copy()
        logger.info(f"Base: INEP fallback ({len(df_base)} registros)")
    else:
        logger.error("Nenhuma fonte de índices disponível.")
        return pd.DataFrame()

    dfs_calculados = []
    for ano in anos:
        df_ano = df_base[df_base["ano"] == ano].copy()
        if df_ano.empty:
            logger.warning(f"Sem dados de índices para {ano}.")
            continue
        for col in ["IRAP", "IRE", "IAE", "IGE"]:
            if col not in df_ano.columns:
                df_ano[col] = 0.5
        total_icms = TOTAL_ICMS_EDUCACAO_MG.get(ano, 5_000_000_000.0)
        df_calc = calcular_icms_municipios(df_ano, total_icms, ano)
        dfs_calculados.append(df_calc)

    if not dfs_calculados:
        logger.error("Nenhum cálculo realizado.")
        return pd.DataFrame()

    df_final = pd.concat(dfs_calculados, ignore_index=True)

    # ── 6. Mesclar VAAR real do FNDE ──────────────────────────────────────────
    # Fontes de VAAR:
    #   2024: fnde_inabilitados (XLSX ajuste) — habilitados com compl_vaar
    #   2025: fnde_receitas (PDF portaria)    — compl_vaar por município
    #   2026: fnde_receitas (CSV portaria)    — compl_vaar por município
    dfs_vaar = []

    # VAAR de fnde_receitas (2025 e 2026)
    if not df_receitas.empty and "compl_vaar" in df_receitas.columns:
        df_rec_vaar = df_receitas[["cod_ibge", "ano", "compl_vaar"]].copy()
        df_rec_vaar = df_rec_vaar[df_rec_vaar["compl_vaar"].notna()]
        dfs_vaar.append(df_rec_vaar)
        logger.info(f"VAAR de receitas: {len(df_rec_vaar)} registros")

    # VAAR de fnde_inabilitados (2024 — habilitados que receberam ajuste)
    if not df_inabilitados.empty and "compl_vaar" in df_inabilitados.columns:
        df_inab_vaar = df_inabilitados[
            df_inabilitados["habilitado_vaar"] == True
        ][["cod_ibge", "ano", "compl_vaar"]].copy()
        df_inab_vaar = df_inab_vaar[df_inab_vaar["compl_vaar"].notna()]
        dfs_vaar.append(df_inab_vaar)
        logger.info(f"VAAR de ajuste 2024: {len(df_inab_vaar)} registros")

    if dfs_vaar:
        df_vaar_total = pd.concat(dfs_vaar, ignore_index=True)
        df_vaar_total = df_vaar_total.drop_duplicates(
            subset=["cod_ibge", "ano"], keep="first"
        )
        df_final = df_final.merge(
            df_vaar_total.rename(columns={"compl_vaar": "repasse_vaar"}),
            on=["cod_ibge", "ano"], how="left"
        )
        n_com_vaar = df_final["repasse_vaar"].notna().sum()
        logger.info(f"VAAR mesclado: {n_com_vaar} municípios com valor.")
    else:
        # Fallback: calcular VAAR por fórmula
        logger.info("Calculando VAAR por fórmula (sem dados reais FNDE).")
        df_final = df_final.sort_values(["cod_ibge", "ano"])
        df_final["delta_indicador"] = (
            df_final.groupby("cod_ibge")["IE"].diff().fillna(0.0)
        )
        df_final["habilitado_vaar"] = True
        for ano in anos:
            mask = df_final["ano"] == ano
            total_vaar = TOTAL_VAAR_MG.get(ano, 1_000_000_000.0)
            df_vaar = calcular_vaar_municipios(df_final[mask].copy(), total_vaar)
            df_final.loc[mask, "repasse_vaar"] = df_vaar["repasse_vaar"].values
            df_final.loc[mask, "coef_vaar"]    = df_vaar["coef_vaar"].values

    # ── 7. Mesclar status de habilitação ──────────────────────────────────────
    if not df_inabilitados.empty:
        # Apenas inabilitados reais (habilitado_vaar == False)
        df_inab_status = df_inabilitados[
            df_inabilitados["habilitado_vaar"] == False
        ][[c for c in ["cod_ibge", "ano", "motivo_inabilitacao",
                        "condicionalidades_descumpridas"]
           if c in df_inabilitados.columns]].copy()
        df_inab_status["habilitado_vaar"] = False

        df_final = df_final.merge(
            df_inab_status, on=["cod_ibge", "ano"], how="left"
        )
        df_final["habilitado_vaar"] = (
            df_final["habilitado_vaar"]
            .infer_objects(copy=False)
            .fillna(True)
        )
        df_final["motivo_inabilitacao"] = (
            df_final["motivo_inabilitacao"].fillna("")
        )
        n_inab = (df_final["habilitado_vaar"] == False).sum()
        n_hab  = (df_final["habilitado_vaar"] == True).sum()
        logger.info(f"Status VAAR: {n_hab} habilitados | {n_inab} inabilitados")
    else:
        df_final["habilitado_vaar"]    = True
        df_final["motivo_inabilitacao"] = ""

    # ── 8. Garantir colunas e tipos ───────────────────────────────────────────
    for col in COLUNAS_CONSOLIDADO:
        if col not in df_final.columns:
            df_final[col] = None

    # Remover registros sem código IBGE válido para preservar a contagem
    # de municípios e o vínculo correto com o GeoJSON.
    if "cod_ibge" in df_final.columns:
        valid_cod = df_final["cod_ibge"].astype(str).str.match(r"^\d{7}$", na=False)
        if not valid_cod.all():
            logger.warning(
                f"Removendo {int((~valid_cod).sum())} registros sem cod_ibge válido"
            )
            df_final = df_final[valid_cod].copy()

    df_final["ano"] = df_final["ano"].astype(int)
    df_final = df_final.sort_values(["ano", "municipio"]).reset_index(drop=True)

    # ── 9. Salvar ─────────────────────────────────────────────────────────────
    salvar_parquet(df_final, "consolidado")
    logger.success(
        f"=== Consolidação concluída: {len(df_final)} registros | "
        f"{df_final['municipio'].nunique()} municípios | "
        f"Anos: {sorted(df_final['ano'].unique())} ==="
    )
    return df_final


def executar_coleta_completa(anos: list[int] = ANOS_COLETA) -> pd.DataFrame:
    """Executa todo o pipeline de coleta do zero."""
    from scraper.scraper_fjp     import coletar_todos_anos as coletar_fjp
    from scraper.fnde_loader     import coletar_todos_anos as coletar_fnde
    from scraper.downloader_inep import coletar_todos_anos as coletar_inep
    from scraper.geo_loader      import carregar_geodados

    logger.info("=== Pipeline completo de coleta ===")
    for nome, fn in [("FJP", coletar_fjp), ("FNDE", coletar_fnde),
                     ("INEP", coletar_inep)]:
        try:
            fn(anos)
        except Exception as e:
            logger.error(f"{nome}: {e}")
    try:
        carregar_geodados()
    except Exception as e:
        logger.error(f"GEO: {e}")
    return consolidar(anos)


def carregar_consolidado() -> pd.DataFrame:
    """Carrega o consolidado do disco. Se não existir, executa o pipeline."""
    df = carregar_parquet("consolidado")
    if df is not None and not df.empty:
        return df
    logger.info("Consolidado não encontrado — executando pipeline completo...")
    return executar_coleta_completa()


if __name__ == "__main__":
    df = consolidar()
    print(df[[
        "municipio", "ano", "IE",
        "repasse_icms_educacao", "repasse_vaar",
        "habilitado_vaar", "motivo_inabilitacao"
    ]].head(20))
    print(f"\nShape: {df.shape}")
    print(f"Inabilitados: {(df['habilitado_vaar'] == False).sum()}")
    print(f"Com VAAR: {df['repasse_vaar'].notna().sum()}")