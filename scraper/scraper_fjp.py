"""
scraper/scraper_fjp.py
Coleta os índices do ICMS Educacional (IE, IRAP, IRE, IAE, IGE)
do portal Robin Hood da FJP — robin-hood.fjp.mg.gov.br

O portal é uma SPA (Single Page Application) em React/JavaScript,
por isso requer Selenium com Chrome headless para renderizar a página
antes de extrair os dados.

Uso:
    python -m scraper.scraper_fjp
"""
from __future__ import annotations
import os
import time
import pandas as pd
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from utils.config import URLS, ANOS_COLETA, SELENIUM_WAIT, DATA_RAW
from utils.cache import salvar_parquet, cache_valido, DATA_PROCESSED


# ── Configuração do Chrome ───────────────────────────────────────────────────

def criar_driver() -> webdriver.Chrome:
    """Cria instância do Chrome headless configurada para scraping."""
    options = Options()

    # Headless: sem interface gráfica (obrigatório em servidores/CI)
    if os.getenv("HEADLESS", "true").lower() == "true":
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    # User-agent de browser real para evitar bloqueios
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(SELENIUM_WAIT)
    return driver


# ── Funções de extração ──────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=30))
def coletar_indices_ano(driver: webdriver.Chrome, ano: int) -> pd.DataFrame:
    """
    Navega no portal FJP e extrai os índices de todos os municípios
    para um ano específico.

    Args:
        driver: instância do Chrome já aberta
        ano:    ano de referência (ex: 2023)

    Returns:
        DataFrame com colunas [cod_ibge, municipio, IRAP, IRE, IAE, IGE, IE, ano]
    """
    wait = WebDriverWait(driver, SELENIUM_WAIT)
    url = URLS["fjp_portal"]

    logger.info(f"Acessando portal FJP para o ano {ano}...")
    driver.get(url)
    time.sleep(3)  # aguarda o React carregar

    # ── Selecionar o ano ────────────────────────────────────────────────────
    try:
        # Tenta localizar o seletor de ano (dropdown ou input)
        select_ano = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "select[name*='ano'], select#ano, select.ano-select"))
        )
        Select(select_ano).select_by_visible_text(str(ano))
        time.sleep(2)
        logger.debug(f"Ano {ano} selecionado no dropdown.")
    except Exception:
        # Alternativa: busca por input/botão de ano
        logger.warning(f"Dropdown de ano não encontrado — tentando URL com parâmetro de ano.")
        driver.get(f"{url}?ano={ano}")
        time.sleep(3)

    # ── Selecionar critério Educação ────────────────────────────────────────
    try:
        btn_educacao = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Educa')]"))
        )
        btn_educacao.click()
        time.sleep(2)
    except Exception:
        logger.warning("Botão de Educação não encontrado — continuando com a view atual.")

    # ── Extrair tabela de municípios ─────────────────────────────────────────
    # Aguarda a tabela principal carregar
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table, .tabela-municipios, [class*='table']")))
    time.sleep(1)

    registros = _extrair_tabela(driver, ano)

    if not registros:
        raise ValueError(f"Nenhum dado extraído para o ano {ano}.")

    df = pd.DataFrame(registros)
    logger.success(f"Ano {ano}: {len(df)} municípios coletados.")
    return df


def _extrair_tabela(driver: webdriver.Chrome, ano: int) -> list[dict]:
    """
    Extrai linhas da tabela HTML do portal FJP.
    Tenta múltiplas estratégias de localização.
    """
    registros = []

    # Estratégia 1: tabela HTML padrão
    try:
        tabela = driver.find_element(By.CSS_SELECTOR, "table")
        linhas = tabela.find_elements(By.TAG_NAME, "tr")

        # Identificar cabeçalho
        cabecalho = [th.text.strip().upper() for th in linhas[0].find_elements(By.TAG_NAME, "th")]
        logger.debug(f"Cabeçalho encontrado: {cabecalho}")

        # Mapear colunas
        mapa_colunas = _mapear_colunas(cabecalho)

        for linha in linhas[1:]:
            cels = [td.text.strip() for td in linha.find_elements(By.TAG_NAME, "td")]
            if len(cels) < 3:
                continue
            registro = _parsear_linha(cels, mapa_colunas, ano)
            if registro:
                registros.append(registro)

    except Exception as e:
        logger.warning(f"Estratégia 1 falhou: {e}")

    # Estratégia 2: divs com classe de linha
    if not registros:
        try:
            linhas = driver.find_elements(By.CSS_SELECTOR, "[class*='row'], [class*='linha'], [class*='municipio']")
            for linha in linhas:
                texto = linha.text.strip()
                if texto:
                    registros.append({"raw": texto, "ano": ano})
            logger.warning(f"Estratégia 2 (divs): {len(registros)} linhas brutas coletadas.")
        except Exception as e:
            logger.error(f"Estratégia 2 também falhou: {e}")

    return registros


def _mapear_colunas(cabecalho: list[str]) -> dict[str, int]:
    """
    Mapeia nomes de colunas do portal para os nomes padronizados do projeto.
    O portal FJP pode usar nomes variados entre anos.
    """
    mapeamento = {
        # Código IBGE
        "COD": "cod_ibge", "CODIGO": "cod_ibge", "CÓD": "cod_ibge",
        "COD_IBGE": "cod_ibge", "CÓDIGO": "cod_ibge",
        # Município
        "MUNICIPIO": "municipio", "MUNICÍPIO": "municipio", "NOME": "municipio",
        # Índices
        "IRAP": "IRAP", "DESEMPENHO": "IRAP",
        "IRE": "IRE", "RENDIMENTO": "IRE",
        "IAE": "IAE", "ATENDIMENTO": "IAE",
        "IGE": "IGE", "GESTAO": "IGE", "GESTÃO": "IGE",
        "IQE": "IQE",
        "IE": "IE", "INDICE": "IE", "ÍNDICE": "IE",
    }
    resultado = {}
    for i, col in enumerate(cabecalho):
        col_upper = col.upper().replace(" ", "_").replace(".", "")
        for chave, nome_padrao in mapeamento.items():
            if chave in col_upper:
                resultado[nome_padrao] = i
                break
    return resultado


def _parsear_linha(celulas: list[str], mapa: dict[str, int], ano: int) -> dict | None:
    """Converte uma linha da tabela em dicionário padronizado."""
    try:
        registro = {"ano": ano}
        for campo, idx in mapa.items():
            if idx < len(celulas):
                valor = celulas[idx].replace(",", ".").strip()
                if campo in ("cod_ibge", "municipio"):
                    registro[campo] = valor
                else:
                    registro[campo] = float(valor) if valor else None
        return registro if "municipio" in registro else None
    except (ValueError, IndexError) as e:
        logger.debug(f"Linha ignorada: {e}")
        return None


# ── Execução principal ───────────────────────────────────────────────────────

def coletar_todos_anos(anos: list[int] = ANOS_COLETA) -> pd.DataFrame:
    """
    Coleta os índices FJP para todos os anos configurados.
    Reutiliza uma única instância do Chrome para eficiência.

    Returns:
        DataFrame consolidado com todos os anos
    """
    # Verificar cache
    caminho_cache = DATA_PROCESSED / "fjp_indices.parquet"
    if cache_valido(caminho_cache):
        logger.info("Cache FJP válido — carregando do disco.")
        return pd.read_parquet(caminho_cache)

    dfs = []
    driver = criar_driver()

    try:
        for ano in anos:
            logger.info(f"── Coletando FJP ano {ano} ──")
            try:
                df_ano = coletar_indices_ano(driver, ano)
                dfs.append(df_ano)

                # Salvar dados brutos por ano
                DATA_RAW.mkdir(parents=True, exist_ok=True)
                df_ano.to_csv(DATA_RAW / f"fjp_indices_{ano}.csv", index=False, encoding="utf-8-sig")

            except Exception as e:
                logger.error(f"Falha ao coletar ano {ano}: {e}")
                continue
    finally:
        driver.quit()
        logger.info("Chrome encerrado.")

    if not dfs:
        raise RuntimeError("Nenhum dado coletado do portal FJP.")

    df_total = pd.concat(dfs, ignore_index=True)

    # Garantir tipos corretos
    df_total["ano"] = df_total["ano"].astype(int)
    for col in ["IRAP", "IRE", "IAE", "IGE", "IQE", "IE"]:
        if col in df_total.columns:
            df_total[col] = pd.to_numeric(df_total[col], errors="coerce")

    if "cod_ibge" in df_total.columns:
        df_total["cod_ibge"] = df_total["cod_ibge"].astype(str).str.strip()
        valid_cod = df_total["cod_ibge"].str.match(r"^\d{7}$", na=False)
        if not valid_cod.all():
            invalid = int((~valid_cod).sum())
            logger.warning(f"Removendo {invalid} registros FJP sem cod_ibge válido")
            df_total = df_total[valid_cod].copy()

    salvar_parquet(df_total, "fjp_indices")
    logger.success(f"FJP: {len(df_total)} registros coletados ({len(anos)} anos).")
    return df_total


if __name__ == "__main__":
    anos_env = os.getenv("ANOS_COLETA", "")
    anos = [int(a) for a in anos_env.split(",") if a.strip()] if anos_env else ANOS_COLETA
    df = coletar_todos_anos(anos)
    print(df.head())
    print(f"\nTotal: {len(df)} registros | Anos: {df['ano'].unique()}")
