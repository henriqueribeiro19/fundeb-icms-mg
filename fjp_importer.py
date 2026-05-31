"""
fjp_importer.py
Importa os índices reais de educação da FJP para o projeto.

Estrutura dos arquivos Excel da FJP:
  - Aba: 'Consolidado'
  - Cabeçalho: linha 10 (header=10)
  - Dados: a partir da linha 11
  - Colunas: IBGE | IBGE2 | MUNICÍPIO | Índice de Desempenho |
             Índice de Rendimento | Índice de Atendimento |
             Índice de Gestão Escolar | Índice de Educação Consolidado XXXX
"""
from __future__ import annotations
import requests
import pandas as pd
from pathlib import Path

ARQUIVOS_FJP = {
    2024: {
        "id":   "1LKuEVmxbw5Gg7HCNXEc_3urOyEznGOnC",
        "nome": "fjp_educacao_2024.xlsx",
    },
    2025: {
        "id":   "1zxWZa0qXUykiGFcCi4qB3UOJm0Mep56s",
        "nome": "fjp_educacao_2025.xlsx",
    },
    2026: {
        "id":   "1QZV1y7xAkIBLawyQk4cqv4yGZK_hP6Ff",
        "nome": "fjp_educacao_2026.xlsx",
    },
}

ABA_DADOS   = "Consolidado"
LINHA_HEADER = 10   # cabeçalho sempre na linha 10


def baixar_gdrive(file_id: str, nome_local: str, pasta: Path) -> Path | None:
    """Baixa arquivo do Google Drive."""
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / nome_local
    if caminho.exists():
        print(f"  Usando arquivo local: {caminho}")
        return caminho

    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    session = requests.Session()
    resp = session.get(url, timeout=60)

    if b"confirm" in resp.content[:2000]:
        import re
        token = re.search(r'confirm=([^&"]+)', resp.text)
        if token:
            resp = session.get(f"{url}&confirm={token.group(1)}", timeout=120)

    if resp.status_code != 200 or len(resp.content) < 5000:
        print(f"  ❌ Falha no download")
        return None

    caminho.write_bytes(resp.content)
    print(f"  ✅ Baixado: {caminho} ({len(resp.content)/1024:.1f} KB)")
    return caminho


def processar_excel(caminho: Path, ano: int) -> pd.DataFrame | None:
    """
    Lê a aba Consolidado com cabeçalho na linha 10.
    Mapeia as colunas para o padrão do projeto.
    """
    print(f"  Lendo aba '{ABA_DADOS}' (header={LINHA_HEADER})...")

    df = pd.read_excel(
        caminho,
        sheet_name=ABA_DADOS,
        header=LINHA_HEADER,
        dtype=str,
    )

    print(f"  Colunas brutas: {list(df.columns)}")

    # Renomear colunas pelo conteúdo (independente de variações entre anos)
    mapa = {}
    for col in df.columns:
        col_norm = str(col).strip().lower()
        if "ibge2" in col_norm or col_norm == "ibge2":
            mapa[col] = "cod_ibge"
        elif col_norm in ("ibge", "ibge "):
            mapa[col] = "cod_ibge_curto"   # ignorar depois
        elif "munic" in col_norm or "nome" in col_norm:
            mapa[col] = "municipio"
        elif "desempenho" in col_norm:
            mapa[col] = "IRAP"
        elif "rendimento" in col_norm:
            mapa[col] = "IRE"
        elif "atendimento" in col_norm:
            mapa[col] = "IAE"
        elif "gest" in col_norm:
            mapa[col] = "IGE"
        elif "educa" in col_norm or col_norm.startswith("ie") or "consolidado" in col_norm:
            mapa[col] = "IE"

    df = df.rename(columns=mapa)

    # Remover coluna auxiliar
    if "cod_ibge_curto" in df.columns:
        df = df.drop(columns=["cod_ibge_curto"])

    # Filtrar linhas válidas — deve ter município com nome real
    if "municipio" not in df.columns:
        print("  ❌ Coluna municipio não encontrada após mapeamento")
        return None

    df = df[df["municipio"].notna()].copy()
    df = df[df["municipio"].astype(str).str.strip() != ""].copy()
    df = df[df["municipio"].astype(str).str.strip() != "nan"].copy()
    # Remover linhas de totais/rodapé
    df = df[~df["municipio"].astype(str).str.lower()
            .str.contains(r"total|média|media|fonte|obs\.|nota|—", na=False, regex=True)].copy()

    # Converter índices para float
    for col in ["IRAP", "IRE", "IAE", "IGE", "IE"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", ".").str.strip(),
                errors="coerce"
            )

    # Padronizar cod_ibge para 7 dígitos
    if "cod_ibge" in df.columns:
        df["cod_ibge"] = (
            df["cod_ibge"].astype(str)
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
            .str.zfill(7)
        )
        # Remover entradas sem IBGE válido, que geralmente são notas de rodapé
        # ou metadados da planilha e não correspondem a municípios.
        valid_cod = df["cod_ibge"].str.match(r"^\d{7}$", na=False)
        if not valid_cod.all():
            invalid = len(valid_cod) - valid_cod.sum()
            print(f"  ⚠️ {invalid} linhas removidas por cod_ibge inválido")
            df = df[valid_cod].copy()

    # Calcular IQE a partir dos componentes
    pesos = {"IRAP": 0.50, "IRE": 0.20, "IAE": 0.15, "IGE": 0.15}
    if all(c in df.columns for c in pesos):
        df["IQE"] = sum(df[c] * p for c, p in pesos.items())

    df["ano"] = ano
    df = df.reset_index(drop=True)

    # Relatório
    colunas_finais = [c for c in ["cod_ibge", "municipio", "IRAP", "IRE", "IAE", "IGE", "IQE", "IE", "ano"]
                      if c in df.columns]
    print(f"  ✅ {len(df)} municípios | Colunas: {colunas_finais}")

    if "IE" in df.columns:
        ie = df["IE"].dropna()
        print(f"     IE: min={ie.min():.6f} | max={ie.max():.6f} | soma={ie.sum():.4f}")

    return df[colunas_finais]


def main():
    pasta_raw  = Path("data/raw")
    pasta_proc = Path("data/processed")
    pasta_proc.mkdir(parents=True, exist_ok=True)

    dfs = []

    for ano, info in ARQUIVOS_FJP.items():
        print(f"\n{'='*60}")
        print(f"Ano {ano}: {info['nome']}")
        print(f"{'='*60}")

        caminho = baixar_gdrive(info["id"], info["nome"], pasta_raw)
        if not caminho:
            continue

        df = processar_excel(caminho, ano)
        if df is None or df.empty:
            print(f"  ⚠️  Nenhum dado extraído para {ano}")
            continue

        dfs.append(df)

    if not dfs:
        print("\n❌ Nenhum dado processado.")
        return

    # Consolidar e salvar
    df_final = pd.concat(dfs, ignore_index=True)
    saida = pasta_proc / "fjp_indices.parquet"
    df_final.to_parquet(saida, index=False)

    print(f"\n{'='*60}")
    print(f"✅ CONCLUÍDO: {saida}")
    print(f"   Registros totais : {len(df_final)}")
    print(f"   Anos             : {sorted(df_final['ano'].unique())}")
    print(f"   Municípios únicos: {df_final['municipio'].nunique()}")
    print(f"\n▶  Próximo passo: python -m scraper.scheduler")
    print(f"   Depois         : streamlit run app.py")


if __name__ == "__main__":
    main()
