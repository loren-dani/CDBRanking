from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st
from motor_tae import Config, calcular_ranking, normalizar
from analise_top5 import identificar, historico_ofertas, series_top5_diario

st.set_page_config(page_title='Ranking de renda fixa | BTG', layout='wide')
ROOT = Path(__file__).resolve().parent
ARQUIVOS = ['BTG_Consolidado.xlsx', 'IPCA_OUTPUT.xlsx', 'SELIC_OUTPUT.xlsx']

# Datas de início de vigência; não são datas de publicação da ata.
AGENDA_COPOM = {
    '2026-12-10': '08 e 09/12/2026',
    '2027-01-28': '26 e 27/01/2027',
    '2027-03-18': '16 e 17/03/2027',
    '2027-04-29': '27 e 28/04/2027',
    '2027-06-17': '15 e 16/06/2027',
    '2027-08-05': '03 e 04/08/2027',
    '2027-09-23': '21 e 22/09/2027',
    '2027-10-28': '26 e 27/10/2027',
    '2027-12-09': '07 e 08/12/2027',
}


def opcoes_copom(referencia, anterior=None, reservar=0):
    limite = max(pd.Timestamp(referencia), pd.Timestamp(anterior)) if anterior else pd.Timestamp(referencia)
    datas = [pd.Timestamp(d).date() for d in AGENDA_COPOM if pd.Timestamp(d) > limite]
    return datas[:-reservar] if reservar else datas


CENARIOS = {'Base':'Base', 'Simulacao':'Simulação', 'Choque':'Choque'}


def ordenar_ranking(resultado, cenario):
    if cenario not in CENARIOS:
        raise ValueError('Cenário inválido.')
    rank, tae = f'Ranking_{cenario}', f'TAE_Liquida_{cenario}'
    validos = resultado[resultado.Status_Calculo.str.startswith('OK')].copy()
    if validos.empty:
        return validos
    return validos.sort_values([rank, tae, 'DC'], ascending=[True, False, True], kind='stable')


def top5_cenario(resultado, cenario):
    ordenados = ordenar_ranking(resultado, cenario)
    if ordenados.empty:
        return ordenados
    return identificar(ordenados).drop_duplicates('_chave_titulo').head(5)


def tabela_comparativa(v, cenario):
    rank = f'Ranking_{cenario}'
    colunas = [rank, 'Produto', 'Emissor', 'Indexador', 'Taxa', 'Data Vencimento', 'IR',
               f'TAE_Liquida_{cenario}', f'TAE_Real_{cenario}']
    vista = v[[x for x in colunas if x in v]].copy()
    nomes = {rank:f'Posição — {CENARIOS[cenario]}', 'IR':'IR (%)'}
    for tipo, nome in [('Liquida', 'líquida'), ('Real', 'real')]:
        referencia = f'TAE_{tipo}_{cenario}'
        if referencia not in v:
            continue
        vista[referencia] *= 100
        nomes[referencia] = f'TAE {nome} — {CENARIOS[cenario]} (% a.a.)'
        for outro in CENARIOS:
            if outro == cenario or f'TAE_{tipo}_{outro}' not in v:
                continue
            delta = (v[f'TAE_{tipo}_{outro}']-v[referencia])*100
            if delta.notna().any() and not np.allclose(delta.dropna(), 0, atol=1e-10, rtol=0):
                vista[f'Δ TAE {nome} {CENARIOS[outro]} (p.p.)'] = delta
    if 'IR' in vista:
        vista['IR'] *= 100
    if 'Amplitude_TAE_pp' in v:
        vista['Amplitude_TAE'] = v['Amplitude_TAE_pp']
    return vista.rename(columns=nomes)


def dados_barras(lideres, cenario):
    r = lideres.copy().reset_index(drop=True)
    r['Ordem'] = np.arange(1,len(r)+1)
    r['TAE_pct'] = r[f'TAE_Liquida_{cenario}']*100
    r['Spread_lider_pp'] = r.TAE_pct-r.TAE_pct.max()
    r['Spread_anterior_pp'] = r.TAE_pct.diff().fillna(0)
    r['Titulo'] = [f"{k}º · {linha.get('Produto','')} · {linha.get('Emissor','')} · "
                   f"{pd.Timestamp(linha['Data Vencimento']):%d/%m/%Y}"
                   for k,linha in enumerate(r.to_dict('records'),start=1)]
    r['Rotulo'] = [f'{tae:.2f}% | {gap:+.3f} p.p.'.replace('.',',')
                    for tae,gap in zip(r.TAE_pct,r.Spread_lider_pp)]
    return r


def grafico_barras(lideres, cenario):
    dados = dados_barras(lideres, cenario)
    st.vega_lite_chart(dados, {
        'height': max(170,len(dados)*46), 'padding':{'right':160},
        'encoding': {
            'y':{'field':'Titulo','type':'nominal','sort':{'field':'Ordem','order':'ascending'},
                 'title':None,'axis':{'labelLimit':440}},
            'x':{'field':'TAE_pct','type':'quantitative','title':'TAE líquida (% a.a.)','scale':{'zero':True}},
            'tooltip':[{'field':'Titulo','type':'nominal','title':'Título'},
                       {'field':'TAE_pct','type':'quantitative','title':'TAE líquida (% a.a.)','format':'.4f'},
                       {'field':'Spread_lider_pp','type':'quantitative','title':'Diferença para o líder (p.p.)','format':'.4f'},
                       {'field':'Spread_anterior_pp','type':'quantitative','title':'Diferença para o anterior (p.p.)','format':'.4f'}]},
        'layer':[{'mark':{'type':'bar','color':'#1677C8','cornerRadiusEnd':3}},
                 {'mark':{'type':'text','align':'left','dx':6,'clip':False},
                  'encoding':{'text':{'field':'Rotulo','type':'nominal'}}}]
    }, use_container_width=True)
    st.caption('Rótulos: TAE líquida | diferença para o primeiro colocado, em p.p. '
               'O tooltip também mostra a diferença para o colocado anterior. '
               f'Distância entre o primeiro e o último exibido: {dados.TAE_pct.max()-dados.TAE_pct.min():.3f} p.p.')


@st.cache_data(show_spinner=False, max_entries=2)
def carregar_historico(base, selic, ipca, data_base, estimar):
    return historico_ofertas(base, selic, ipca, data_base, estimar)


def grafico_tae(dados):
    dados = dados.sort_values(['Serie', 'Data']).copy()
    lacunas = dados.groupby('Serie').TAE_pct.transform(lambda x: x.isna().cumsum())
    dados['Trecho'] = dados.Serie + '|' + lacunas.astype(str)
    dados = dados.dropna(subset=['TAE_pct'])
    st.vega_lite_chart(dados, {
        'mark': {'type':'line', 'point':True},
        'encoding': {'x':{'field':'Data','type':'temporal','title':'Data da Oferta'},
                     'y':{'field':'TAE_pct','type':'quantitative','title':'TAE líquida (% a.a.)', 'scale':{'zero':False}},
                     'color':{'field':'Serie','type':'nominal','title':'Série'},
                     'detail':{'field':'Trecho','type':'nominal'},
                     'tooltip':[{'field':'Data','type':'temporal'}, {'field':'Serie','type':'nominal'},
                                {'field':'TAE_pct','type':'quantitative','format':'.4f'}]}
    }, use_container_width=True)


@st.cache_data(show_spinner=False)
def carregar(assinatura):
    b = pd.read_excel(ROOT/ARQUIVOS[0], sheet_name='Base_Consolidada')
    i = pd.read_excel(ROOT/ARQUIVOS[1])
    s = pd.read_excel(ROOT/ARQUIVOS[2], sheet_name='Selic_Diaria')
    for df in (b, i, s):
        df.columns = df.columns.str.strip()
    for df, exigidas in [(b, {'Data_Emissao', 'Data Vencimento', 'Produto', 'Taxa', 'Indexador'}),
                          (i, {'Data', 'IPCA', 'IPCA_12m', 'Tipo'}),
                          (s, {'Data', 'Meta Selic', 'Taxa Selic anual'})]:
        if not exigidas.issubset(df.columns):
            raise ValueError(f'Colunas ausentes: {sorted(exigidas-set(df.columns))}')
    b['Data_Emissao'] = pd.to_datetime(b.Data_Emissao, errors='coerce').dt.normalize()
    b['Data Vencimento'] = pd.to_datetime(b['Data Vencimento'], errors='coerce').dt.normalize()
    for df in (i, s):
        df['Data'] = pd.to_datetime(df.Data, errors='coerce').dt.normalize()
    return b, i, s


@st.cache_data(show_spinner=False, max_entries=8)
def simular(base, selic, ipca, config):
    return calcular_ranking(base, selic, ipca, config)


st.title('Ranking de renda fixa')
st.caption('BTG • Comparação de carregamento até o vencimento • Base, Simulação e Choque')
faltam = [n for n in ARQUIVOS if not (ROOT/n).is_file()]
if faltam:
    st.error('Arquivos ausentes na mesma pasta do app.py: '+', '.join(faltam))
    st.info('Confira nomes, letras maiúsculas e extensão .xlsx. Consulte CHECKLIST_PUBLICACAO.md.')
    st.stop()
try:
    assinatura = tuple((n, (ROOT/n).stat().st_mtime_ns, (ROOT/n).stat().st_size) for n in ARQUIVOS)
    with st.spinner('Lendo as bases...'):
        btg, ipca, selic = carregar(assinatura)
except Exception as exc:
    st.error(f'Não foi possível ler as bases: {exc}')
    st.stop()

real = ipca[ipca.Tipo.map(normalizar).eq('REALIZADO')].sort_values('Data')
if real.empty or selic.Data.dropna().empty:
    st.error('As bases precisam conter IPCA realizado e histórico de Selic.')
    st.stop()
ultima_selic = selic.Data.max().date()
ultimo_ipca = real.Data.max()
st.caption(f'Cobertura dos arquivos: Selic até {ultima_selic:%d/%m/%Y}; '
           f'IPCA realizado até {ultimo_ipca:%m/%Y}.')
with st.sidebar:
    st.header('Configuração')
    if btg.Data_Emissao.dropna().empty:
        st.error('A base não contém datas de emissão válidas.')
        st.stop()
    ref = btg.Data_Emissao.max().date()
    st.date_input('Data Base', value=ref, disabled=True,
                  help='Última data de emissão disponível no BTG Consolidado; atualizada ao substituir a base.')
    emissoes = sorted(btg.loc[btg.Data_Emissao.le(pd.Timestamp(ref)), 'Data_Emissao'].dropna().dt.date.unique(), reverse=True)
    if not emissoes:
        st.warning('Não há ofertas anteriores à referência escolhida.')
        st.stop()
    emissao = st.selectbox('Data da Oferta', emissoes, format_func=lambda d: d.strftime('%d/%m/%Y'))
    disponiveis = opcoes_copom(ref)
    limite_alteracoes = min(3, len(disponiveis))
    if limite_alteracoes < 3:
        st.warning('A agenda cadastrada precisa ser ampliada para oferecer três alterações após esta referência. '
                   'Não serão criadas datas de reuniões não publicadas.')
    quantidade = st.selectbox('Número de alterações', list(range(limite_alteracoes, -1, -1)))
    ds = []
    anterior = None
    st.caption('Vigência da nova taxa: datas futuras do calendário Copom 2026–2027.')
    for k in range(quantidade):
        opcoes = opcoes_copom(ref, anterior, reservar=quantidade-k-1)
        d = st.selectbox(f'{k+1}ª vigência da nova taxa', opcoes,
                         format_func=lambda d: f'{d:%d/%m/%Y} • reunião {AGENDA_COPOM[d.isoformat()]}',
                         key=f'copom_{k}_{ref}_{anterior}_{quantidade}')
        ds.append(d)
        anterior = d
    with st.form('parametros'):
        selic0 = st.number_input('Selic inicial simulada (% a.a.)', min_value=.25, max_value=40., value=13.25, step=.25)
        st.caption('Âncora manual. Não representa atualização automática da taxa vigente.')
        movimentos = []
        for k, padrao in enumerate((.25, .25, .5)[:quantidade], start=1):
            movimentos.append(st.number_input(f'{k}ª alteração (p.p.)', min_value=-5., max_value=5.,
                                              value=padrao, step=.25, key=f'choque_{k}'))
        estimar = st.checkbox('Permitir estimativas em lacunas históricas', value=False,
                              help='Resultados estimados recebem avisos e não são identificados como realizados.')
        enviar = st.form_submit_button('Calcular cenários', type='primary')

token = (str(ref), str(emissao), tuple(ds), tuple(movimentos), selic0, estimar)
if enviar:
    st.session_state['calculo_solicitado'] = token
if st.session_state.get('calculo_solicitado') != token:
    st.info('Escolha a data da oferta, preencha até três datas futuras e clique em Calcular cenários. '
            'Selecione zero alterações para comparar os três cenários em manutenção.')
    st.caption('Configuração inicial: Selic 13,25%; movimentos +0,25, +0,25 e +0,50 p.p. '
               'As listas usam as datas de vigência da agenda cadastrada do Copom.')
    st.stop()
if any(d is None for d in ds[:quantidade]):
    st.warning('Preencha as primeiras datas de eficácia correspondentes ao número de alterações.')
    st.stop()
try:
    config = Config(str(ref), tuple(str(d) for d in ds[:quantidade]), tuple(movimentos[:quantidade]),
                    selic0, permitir_estimativa_historica=estimar)
    base = btg[btg.Data_Emissao.dt.date.eq(emissao)].copy()
    with st.spinner('Acumulando histórico e calculando os três cenários...'):
        resultado, trajetorias = simular(base, selic, ipca, config)
except Exception as exc:
    st.error(f'Não foi possível calcular: {exc}')
    st.stop()

st.subheader(f'Ofertas de {emissao:%d/%m/%Y}')
st.caption(f'Data Base: {ref:%d/%m/%Y}. TAEs do prazo completo da aplicação, em base anual de 252 DU.')
if estimar:
    st.warning('Estimativas históricas habilitadas. Confira os avisos antes de interpretar os resultados.')
mes_necessario = pd.Timestamp(ref).to_period('M')-1
meses = real.Data.dt.to_period('M')
if not meses.eq(mes_necessario).any():
    st.warning(f'IPCA realizado de {mes_necessario} ausente: é o mês necessário à referência escolhida. '
               'Atualize o Excel ou escolha uma referência anterior.')
if ref > ultima_selic:
    st.warning('A referência ultrapassa o último dia da série Selic. Atualize a série para calcular '
               'integralmente o histórico de aplicações ainda em curso.')

ok = resultado.Status_Calculo.str.startswith('OK')
a, b, c = st.columns(3)
a.metric('Títulos da data', len(resultado))
b.metric('Calculados', int(ok.sum()))
c.metric('Pendentes', int((~ok).sum()))
st.subheader('Comparação por título')
cenario_ordenacao = st.selectbox('Ordenar ranking por cenário', list(CENARIOS),
                                format_func=lambda x:CENARIOS[x], key='cenario_ordenacao')
if ok.any():
    v = ordenar_ranking(resultado, cenario_ordenacao)
    vista = tabela_comparativa(v, cenario_ordenacao)
    st.dataframe(vista, hide_index=True, use_container_width=True)
    st.caption(f'Ordenação e TAEs principais: {CENARIOS[cenario_ordenacao]}. As diferenças dos outros cenários são relativas a ele, em p.p. '
               'O IR é o mesmo nos três cenários; os rendimentos podem variar. O CSV completo usa retornos decimais: 0,12 = 12%.')
else:
    st.info('Nenhum título passou pelas verificações. Veja as pendências abaixo.')

with st.expander('Resumo das pendências', expanded=not bool(ok.any())):
    st.dataframe(resultado.Status_Calculo.value_counts().rename_axis('Status').reset_index(name='Quantidade'), hide_index=True)
exportacao = resultado.sort_values(f'Ranking_{cenario_ordenacao}', na_position='last', kind='stable')
st.download_button('Baixar cálculo completo (CSV)', exportacao.to_csv(index=False).encode('utf-8-sig'),
                   file_name=f'ranking_{emissao}_{ref}.csv', mime='text/csv', on_click='ignore')
st.subheader(f'Top 5 da Data Base • {CENARIOS[cenario_ordenacao]}')
st.caption(f'Data Base: {ref:%d/%m/%Y}. As barras usam o mesmo cenário selecionado para ordenar a tabela.')
ofertas_do_dia = btg[btg.Data_Emissao.eq(pd.Timestamp(ref))].copy()
ranking_dia = pd.DataFrame()
if ofertas_do_dia.empty:
    st.info('Não há ofertas da Data Base disponíveis.')
else:
    if emissao == ref:
        ranking_dia = resultado
    else:
        ranking_dia, _ = simular(ofertas_do_dia, selic, ipca, config)
    lideres = top5_cenario(ranking_dia, cenario_ordenacao)
    if lideres.empty:
        st.info('Os títulos da Data Base estão pendentes de cálculo. Confira a cobertura das taxas.')
    else:
        grafico_barras(lideres, cenario_ordenacao)

comparar_inicio = st.checkbox('Comparar com o Top 5 de cada dia no período', value=False)
if comparar_inicio:
    st.subheader('Top 5 de cada dia • Histórico')
    primeira_emissao = btg.Data_Emissao.min().date()
    modo_periodo = st.radio('Período do histórico', ['Desde o início da base', 'Escolher período'], horizontal=True)
    inicio_grafico, fim_grafico = primeira_emissao, ref
    if modo_periodo == 'Escolher período':
        esquerda, direita = st.columns(2)
        with esquerda:
            inicio_grafico = st.date_input('Início do gráfico', value=primeira_emissao,
                                           min_value=primeira_emissao, max_value=ref)
        with direita:
            fim_grafico = st.date_input('Fim do gráfico', value=ref,
                                        min_value=primeira_emissao, max_value=ref)
        if inicio_grafico > fim_grafico:
            st.warning('O início do gráfico deve ser anterior ou igual ao fim.')
            st.stop()
    with st.spinner('Calculando as TAEs históricas por Data da Oferta...'):
        historico = carregar_historico(btg, selic, ipca, str(ref), estimar)
    if not ranking_dia.empty:
        atuais = ordenar_ranking(ranking_dia, cenario_ordenacao)
        historico = historico[~historico.Data_Emissao.eq(pd.Timestamp(ref))].copy()
        if not atuais.empty:
            atuais = identificar(atuais)
            atuais['TAE_Liquida_Base'] = atuais[f'TAE_Liquida_{cenario_ordenacao}']
            historico = pd.concat([historico, atuais.reindex(columns=historico.columns)], ignore_index=True)
    historico_periodo = historico[historico.Data_Emissao.between(pd.Timestamp(inicio_grafico), pd.Timestamp(fim_grafico))]
    serie_diaria = series_top5_diario(historico_periodo)
    if serie_diaria.empty:
        st.info('Não há histórico calculável para a seleção.')
    else:
        grafico_tae(serie_diaria)
        st.caption('Cada linha representa uma posição entre os cinco primeiros em cada Data da Oferta. '
                   'Os ocupantes podem mudar. Datas anteriores usam o cenário spot da própria data; '
                   f'a Data Base usa {CENARIOS[cenario_ordenacao]}. Os choques futuros não são aplicados retroativamente.')

with st.expander('Como interpretar'):
    st.markdown('O fator histórico é multiplicado pelo fator futuro. O IR é calculado sobre o '
                'rendimento total no vencimento. Juros mensais e fluxos intermediários ficam pendentes. '
                'A inflação spot usa o IPCA 12m do mês anterior; a acumulação histórica usa variações '
                'mensais com defasagem de um mês. A atualização é aproximada e não representa marcação a mercado. '
                'O ranking trata a data da oferta como aquisição hipotética. Consulte METODOLOGIA.md para as premissas.')
