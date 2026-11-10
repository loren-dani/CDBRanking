"""Séries históricas de TAEs das ofertas; não representa marcação a mercado."""
import numpy as np
import pandas as pd
from motor_tae import Config, calcular_ranking, normalizar, numero


def identificar(base):
    b = base.copy()
    def chave(r):
        codigo = normalizar(r.get('Codigo renda fixa'))
        if codigo:
            return 'COD:'+codigo
        # Sem identificador, só unem-se observações com MESMOS termos contratuais.
        venc = pd.to_datetime(r.get('Data Vencimento'), errors='coerce')
        campos = [normalizar(r.get(x)) for x in ('Produto', 'Emissor', 'Indexador', 'JUROS', 'AMORTIZACAO')]
        return 'TERMOS:'+'|'.join(campos+[str(venc), str(numero(r.get('Taxa')))])
    b['_chave_titulo'] = [chave(r) for r in b.to_dict('records')]
    return b


def cinco_primeiros(resultado):
    if resultado.empty or 'TAE_Liquida_Base' not in resultado:
        return resultado.iloc[:0].copy()
    validos = resultado[resultado.Status_Calculo.str.startswith('OK')].copy()
    if '_chave_titulo' not in validos:
        validos = identificar(validos)
    # Critérios do ranking, desempate de exibição determinístico; exatamente cinco títulos.
    return (validos.sort_values(['TAE_Liquida_Base', 'DC', '_chave_titulo'], ascending=[False, True, True])
            .drop_duplicates('_chave_titulo').head(5))


def historico_ofertas(btg, selic, ipca, data_base, estimar=False):
    """Calcula cada oferta com a informação elegível NAQUELA data, sem choques futuros.

    A Selic inicial vem da própria série histórica, não da âncora manual de hoje.
    Não usa taxas realizadas depois da data da oferta. Retém somente colunas de gráfico.
    """
    base = identificar(btg)
    limite = pd.Timestamp(data_base).normalize()
    base = base[base.Data_Emissao.le(limite)]
    colunas = ['Data_Emissao', '_chave_titulo', 'Produto', 'Emissor', 'Data Vencimento',
               'Taxa', 'Indexador', 'TAE_Liquida_Base', 'DC', 'Status_Calculo']
    partes = []
    for d, grupo in base.groupby('Data_Emissao', sort=True):
        config = Config(str(pd.Timestamp(d).date()), selic_inicial_pct=None,
                        permitir_estimativa_historica=estimar)
        try:
            r, _ = calcular_ranking(grupo, selic, ipca, config)
        except ValueError:
            continue
        ok = r.Status_Calculo.str.startswith('OK')
        if not ok.any():
            continue
        partes.append(r.loc[ok, [c for c in colunas if c in r]])
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=colunas)


def series_lideres(historico, lideres, data_base):
    """Mantém os cinco títulos escolhidos na Data Base; nunca troca os títulos."""
    if lideres.empty:
        return pd.DataFrame()
    lideres = identificar(lideres) if '_chave_titulo' not in lideres else lideres
    rows = []
    datas = sorted(set(historico.Data_Emissao.dropna()) | {pd.Timestamp(data_base)})
    for pos, (_, titulo) in enumerate(lideres.iterrows(), start=1):
        chave = titulo['_chave_titulo']
        h = historico.loc[historico._chave_titulo.eq(chave), ['Data_Emissao', 'TAE_Liquida_Base']].copy()
        # Endpoint usa a configuração efetivamente calculada na Data Base.
        h = h[~h.Data_Emissao.eq(pd.Timestamp(data_base))]
        h = h.sort_values('Data_Emissao').drop_duplicates('Data_Emissao')
        valores = h.set_index('Data_Emissao').TAE_Liquida_Base.copy()
        valores.loc[pd.Timestamp(data_base)] = titulo.TAE_Liquida_Base
        venc = pd.Timestamp(titulo['Data Vencimento']).strftime('%d/%m/%Y')
        label = f"{pos}º · {titulo.get('Produto','')} · {titulo.get('Emissor','')} · {venc}"
        # Datas ausentes recebem null: não se inventa histórico nem se liga através de lacunas.
        for d in datas:
            valor = valores.get(d, np.nan)
            rows.append({'Data': d, 'Serie': label, 'TAE_pct': valor*100 if pd.notna(valor) else np.nan})
    return pd.DataFrame(rows)


def series_top5_diario(historico):
    """Cinco posições ao longo do tempo; seus ocupantes podem mudar em cada data."""
    rows = []
    for d, grupo in historico.groupby('Data_Emissao', sort=True):
        for pos, (_, titulo) in enumerate(cinco_primeiros(grupo).iterrows(), start=1):
            rows.append({'Data': d, 'Serie': f'{pos}º colocado do dia',
                         'TAE_pct': titulo.TAE_Liquida_Base*100,
                         'Titulo': f"{titulo.get('Produto','')} · {titulo.get('Emissor','')}"})
    return pd.DataFrame(rows)
