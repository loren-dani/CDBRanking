from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
from motor_tae import Config, calcular_ranking, normalizar
from analise_top5 import identificar, cinco_primeiros, historico_ofertas, series_lideres, series_top5_diario

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


def tabela_comparativa(v):
    colunas = ['Ranking_Base', 'Produto', 'Emissor', 'Indexador', 'Taxa', 'Data Vencimento',
               'IR', 'TAE_Liquida_Base', 'TAE_Real_Base']
    vista = v[[x for x in colunas if x in v]].copy()
    for tipo in ('Liquida', 'Real'):
        base = f'TAE_{tipo}_Base'
        if base not in v:
            continue
        vista[base] *= 100
        for cenario in ('Simulacao', 'Choque'):
            col = f'TAE_{tipo}_{cenario}'
            if col not in v:
                continue
            delta = (v[col]-v[base])*100
            if delta.notna().any() and not np.allclose(delta.dropna(), 0, atol=1e-10, rtol=0):
                vista[f'Variação TAE {tipo.lower()} {cenario} (p.p.)'] = delta
    if 'IR' in vista:
        vista['IR'] *= 100
    if 'Amplitude_TAE_pp' in v:
        vista['Amplitude_TAE'] = v['Amplitude_TAE_pp']
    return vista.rename(columns={'TAE_Liquida_Base':'TAE líquida base (% a.a.)',
                                 'TAE_Real_Base':'TAE real base (% a.a.)', 'IR':'IR (%)'})


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
hoje = datetime.now(ZoneInfo('America/Sao_Paulo')).date()
ultima_selic = selic.Data.max().date()
ultimo_ipca = real.Data.max()
st.caption(f'Cobertura dos arquivos: Selic até {ultima_selic:%d/%m/%Y}; '
           f'IPCA realizado até {ultimo_ipca:%m/%Y}.')
with st.sidebar:
    st.header('Configuração')
    ref = st.date_input('Data Base', value=hoje, max_value=hoje,
                        help='Início do trecho futuro; o histórico permanece igual nos três cenários.')
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
if ok.any():
    v = resultado.loc[ok].sort_values('Ranking_Base').copy()
    vista = tabela_comparativa(v)
    st.dataframe(vista, hide_index=True, use_container_width=True)
    st.caption('TAE base em % a.a.; diferenças dos cenários e amplitude em p.p. Colunas sem variação são ocultadas. '
               'O IR é o mesmo nos três cenários; os rendimentos podem variar. O CSV completo usa retornos decimais: 0,12 = 12%.')
else:
    st.info('Nenhum título passou pelas verificações. Veja as pendências abaixo.')

with st.expander('Resumo das pendências', expanded=not bool(ok.any())):
    st.dataframe(resultado.Status_Calculo.value_counts().rename_axis('Status').reset_index(name='Quantidade'), hide_index=True)
st.download_button('Baixar cálculo completo (CSV)', resultado.to_csv(index=False).encode('utf-8-sig'),
                   file_name=f'ranking_{emissao}_{ref}.csv', mime='text/csv', on_click='ignore')
st.subheader('Evolução da TAE • Top 5 da Data Base')
ofertas_do_dia = btg[btg.Data_Emissao.eq(pd.Timestamp(ref))].copy()
lideres = pd.DataFrame()
if ofertas_do_dia.empty:
    st.info(f'Não há ofertas em {ref:%d/%m/%Y} no BTG Consolidado. '
            'Atualize a base para exibir o Top 5 do dia ou escolha uma Data Base histórica. '
            'A tabela acima pertence à Data da Oferta selecionada.')
else:
    if emissao == ref:
        ranking_dia = resultado
    else:
        ranking_dia, _ = simular(ofertas_do_dia, selic, ipca, config)
    lideres = cinco_primeiros(ranking_dia)
    if lideres.empty:
        st.info('Os títulos da Data Base estão pendentes de cálculo. Confira a cobertura das taxas.')

comparar_inicio = st.checkbox('Comparar com o Top 5 de cada dia desde o início da base', value=False)
if not lideres.empty or comparar_inicio:
    with st.spinner('Calculando as TAEs históricas por Data da Oferta...'):
        historico = carregar_historico(btg, selic, ipca, str(ref), estimar)
    if not ofertas_do_dia.empty:
        # A Data Base usa a configuração atual nos DOIS gráficos.
        hoje_validos = ranking_dia[ranking_dia.Status_Calculo.str.startswith('OK')]
        historico = historico[~historico.Data_Emissao.eq(pd.Timestamp(ref))].copy()
        if not hoje_validos.empty:
            atuais = identificar(hoje_validos)
            historico = pd.concat([historico, atuais.reindex(columns=historico.columns)], ignore_index=True)
    if not lideres.empty:
        serie = series_lideres(historico, lideres, str(ref))
        grafico_tae(serie)
        if serie.dropna(subset=['TAE_pct']).groupby('Serie').Data.nunique().lt(2).any():
            st.caption('Alguns líderes têm uma única observação identificável: aparecem como pontos, sem linha histórica artificial.')
        st.caption('Os mesmos cinco títulos líderes da Data Base são acompanhados no histórico. '
                   'Cada ponto anterior usa taxas disponíveis naquela Data da Oferta; o último usa '
                   'a configuração da Data Base. Datas sem observação ficam em branco.')
        if lideres['_chave_titulo'].str.startswith('TERMOS:').any():
            st.caption('Para títulos sem código, o vínculo histórico exige os mesmos termos: '
                       'emissor, produto, vencimento, indexador, taxa e fluxo de pagamentos.')
    if comparar_inicio:
        st.subheader('Top 5 de cada dia • Desde o início da base')
        serie_diaria = series_top5_diario(historico)
        if serie_diaria.empty:
            st.info('Não há histórico calculável para a seleção.')
        else:
            grafico_tae(serie_diaria)
            st.caption('Cada linha representa uma posição entre os cinco primeiros em cada Data da Oferta. '
                       'Os títulos que ocupam cada posição podem mudar. As TAEs históricas usam '
                       'a taxa spot elegível na própria data, sem antecipar taxas realizadas no futuro.')

with st.expander('Como interpretar'):
    st.markdown('O fator histórico é multiplicado pelo fator futuro. O IR é calculado sobre o '
                'rendimento total no vencimento. Juros mensais e fluxos intermediários ficam pendentes. '
                'A inflação spot usa o IPCA 12m do mês anterior; a acumulação histórica usa variações '
                'mensais com defasagem de um mês. A atualização é aproximada e não representa marcação a mercado. '
                'O ranking trata a data da oferta como aquisição hipotética. Consulte METODOLOGIA.md para as premissas.')
