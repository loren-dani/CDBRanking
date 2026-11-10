from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
from motor_tae import Config, calcular_ranking, normalizar

st.set_page_config(page_title='Ranking de renda fixa | BTG', layout='wide')
ROOT = Path(__file__).resolve().parent
ARQUIVOS = ['BTG_Consolidado.xlsx', 'IPCA_OUTPUT.xlsx', 'SELIC_OUTPUT.xlsx']


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
# Referência inicial compatível com cobertura M-1 dos anexos, explicitamente exibida.
limite_ipca = (ultimo_ipca+pd.offsets.MonthEnd(1)).date()
referencia_padrao = min(hoje, ultima_selic, limite_ipca)
st.caption(f'Cobertura dos arquivos: Selic até {ultima_selic:%d/%m/%Y}; '
           f'IPCA realizado até {ultimo_ipca:%m/%Y}.')
with st.sidebar:
    st.header('Configuração')
    ref = st.date_input('Data de referência', value=referencia_padrao, max_value=hoje,
                        help='Início do trecho futuro; o histórico permanece igual nos três cenários.')
    emissoes = sorted(btg.loc[btg.Data_Emissao.le(pd.Timestamp(ref)), 'Data_Emissao'].dropna().dt.date.unique(), reverse=True)
    if not emissoes:
        st.warning('Não há ofertas anteriores à referência escolhida.')
        st.stop()
    emissao = st.selectbox('Data da oferta / aquisição hipotética', emissoes, format_func=lambda d: d.strftime('%d/%m/%Y'))
    with st.form('parametros'):
        selic0 = st.number_input('Selic inicial simulada (% a.a.)', min_value=.25, max_value=40., value=13.25, step=.25)
        st.caption('Âncora manual. Não representa atualização automática da taxa vigente.')
        quantidade = st.selectbox('Número de alterações', [3, 2, 1, 0])
        # Os três campos sempre existem: mudanças dentro de formulário são aplicadas ao enviar.
        ds, movimentos = [], []
        st.caption('Preencha apenas as primeiras N datas. Informe o início da vigência da nova taxa.')
        for k, padrao in enumerate((.25, .25, .5), start=1):
            ds.append(st.date_input(f'{k}ª data de eficácia', value=None,
                                    min_value=ref+timedelta(days=1), key=f'data_{k}'))
            movimentos.append(st.number_input(f'{k}ª alteração (p.p.)', min_value=-5., max_value=5.,
                                              value=padrao, step=.25, key=f'choque_{k}'))
        estimar = st.checkbox('Permitir estimativas em lacunas históricas', value=False,
                              help='Resultados estimados recebem avisos e não são identificados como realizados.')
        ipca_modo = st.selectbox('Campo IPCA sem sinal +', ['spread', 'bloquear', 'percentual'],
                                 help='Spread interpreta Taxa como juros reais anuais adicionados ao IPCA.')
        feriados_txt = st.text_area('Feriados financeiros (opcional)', placeholder='2026-12-25\n2027-01-01',
                                   help='Uma data ISO por linha. Sem lista, o cálculo usa segunda a sexta.')
        enviar = st.form_submit_button('Calcular cenários', type='primary')

if not enviar:
    st.info('Escolha a data da oferta, preencha até três datas futuras e clique em Calcular cenários. '
            'Selecione zero alterações para comparar os três cenários em manutenção.')
    st.caption('Configuração inicial: Selic 13,25%; movimentos +0,25, +0,25 e +0,50 p.p. '
               'As datas devem ser escolhidas; não há calendário do Copom presumido.')
    st.stop()
if any(d is None for d in ds[:quantidade]):
    st.warning('Preencha as primeiras datas de eficácia correspondentes ao número de alterações.')
    st.stop()
try:
    feriados = tuple(pd.Timestamp(x.strip()).date().isoformat() for x in feriados_txt.splitlines() if x.strip())
    config = Config(str(ref), tuple(str(d) for d in ds[:quantidade]), tuple(movimentos[:quantidade]),
                    selic0, feriados=feriados, permitir_estimativa_historica=estimar, ipca_simples=ipca_modo)
    base = btg[btg.Data_Emissao.dt.date.eq(emissao)].copy()
    with st.spinner('Acumulando histórico e calculando os três cenários...'):
        resultado, trajetorias = simular(base, selic, ipca, config)
except Exception as exc:
    st.error(f'Não foi possível calcular: {exc}')
    st.stop()

st.subheader(f'Ofertas de {emissao:%d/%m/%Y}')
st.caption(f'Referência do cálculo: {ref:%d/%m/%Y}. As TAEs correspondem ao prazo completo da aplicação.')
if not feriados:
    st.warning('Calendário simplificado: segunda a sexta, sem exclusão de feriados financeiros.')
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
st.subheader('Trajetórias da Selic')
st.vega_lite_chart(trajetorias, {
    'mark': {'type':'line', 'interpolate':'step-after', 'point':True},
    'encoding': {'x':{'field':'Data','type':'temporal','title':'Data de eficácia'},
                 'y':{'field':'Selic_pct','type':'quantitative','title':'Selic (% a.a.)', 'scale':{'zero':False}},
                 'color':{'field':'Cenario','type':'nominal','title':'Cenário'}}
}, use_container_width=True)
st.caption('Pontos nas datas de eficácia; a taxa fica constante entre as datas. '
           'Base = manutenção; Choque = sinais invertidos. IPCA: sensibilidade relativa 2,5.')
st.dataframe(trajetorias.rename(columns={'Selic_pct':'Selic (% a.a.)', 'IPCA_anual_pct':'IPCA anual projetado (%)'}),
             hide_index=True, use_container_width=True)

st.subheader('Comparação por título')
if ok.any():
    v = resultado.loc[ok].sort_values('Ranking_Base').copy()
    colunas = ['Ranking_Base', 'Produto', 'Emissor', 'Indexador', 'Taxa', 'Data Vencimento',
               'TAE_Liquida_Base', 'TAE_Liquida_Simulacao', 'TAE_Liquida_Choque',
               'TAE_Real_Base', 'TAE_Real_Simulacao', 'TAE_Real_Choque', 'Amplitude_TAE_pp',
               'Mudanca_Ranking_Simulacao', 'Mudanca_Ranking_Choque', 'Situacao', 'Avisos']
    vista = v[[x for x in colunas if x in v]].copy()
    for x in vista.columns:
        if x.startswith('TAE_'):
            vista[x] = vista[x]*100
    st.dataframe(vista, hide_index=True, use_container_width=True)
    st.caption('TAEs exibidas em % a.a.; amplitude em p.p. Mudança positiva significa melhora no ranking. '
               'O CSV completo usa retornos decimais: 0,12 significa 12%.')
else:
    st.info('Nenhum título passou pelas verificações. Veja as pendências abaixo.')

with st.expander('Pendências e avisos', expanded=not bool(ok.any())):
    st.dataframe(resultado.Status_Calculo.value_counts().rename_axis('Status').reset_index(name='Quantidade'), hide_index=True)
    detalhes = [x for x in ['Produto', 'Emissor', 'Data Vencimento', 'Status_Calculo', 'Avisos'] if x in resultado]
    st.dataframe(resultado[detalhes], hide_index=True, use_container_width=True)
st.download_button('Baixar cálculo completo (CSV)', resultado.to_csv(index=False).encode('utf-8-sig'),
                   file_name=f'ranking_{emissao}_{ref}.csv', mime='text/csv', on_click='ignore')
with st.expander('Como interpretar'):
    st.markdown('O fator histórico é multiplicado pelo fator futuro. O IR é calculado sobre o '
                'rendimento total no vencimento. Juros mensais e fluxos intermediários ficam pendentes. '
                'A inflação spot usa o IPCA 12m do mês anterior; a acumulação histórica usa variações '
                'mensais com defasagem de um mês. A atualização é aproximada e não representa marcação a mercado. '
                'O ranking trata a data da oferta como aquisição hipotética. Consulte METODOLOGIA.md para as premissas.')
