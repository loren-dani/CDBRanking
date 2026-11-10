"""Motor de simulação de carregamento até o vencimento (não marcação a mercado).

Unidades externas: taxas em %, choques em pontos percentuais.
Fatores e retornos internos: decimais. Intervalos [início, fim).
Leia METODOLOGIA.md antes de integrar à interface.
"""
from dataclasses import dataclass
from functools import lru_cache
import unicodedata
import re
import numpy as np
import pandas as pd


def normalizar(x):
    if pd.isna(x):
        return ''
    return ''.join(c for c in unicodedata.normalize('NFKD', str(x).strip().upper())
                   if not unicodedata.combining(c))


def numero(x):
    if isinstance(x, str):
        x = x.strip().replace('%', '')
        if ',' in x:
            x = x.replace('.', '').replace(',', '.')
    return float(pd.to_numeric(x, errors='coerce'))


def data(x):
    # ISO é inequívoco; dayfirst=True pode inverter mês/dia em certas versões.
    if isinstance(x, str) and re.match(r'^\d{4}-\d{2}-\d{2}', x):
        return pd.to_datetime(x, errors='coerce', yearfirst=True)
    return pd.to_datetime(x, errors='coerce', dayfirst=True)


@dataclass(frozen=True)
class Config:
    data_referencia: str
    # Datas de EFICÁCIA, não datas de anúncio. Até três; nunca inventadas.
    datas_alteracoes: tuple = ()
    alteracoes_pp: tuple = ()
    selic_inicial_pct: float | None = None
    # Preserva proxy do código anexado: CDI = taxa Selic anual da planilha.
    # Futuro: CDI = meta simulada menos este diferencial em p.p.
    diferencial_cdi_pp: float = 0.10
    sensibilidade_ipca: float = 2.5
    feriados: tuple = ()
    permitir_estimativa_historica: bool = False
    # Novo leiaute traz IPCA com Taxa ~7: interpretação explícita como spread.
    ipca_simples: str = 'spread'  # 'spread', 'percentual' ou 'bloquear'
    assumir_fluxo_unico_quando_ausente: bool = True


def modalidade(x, config):
    x = normalizar(x).replace(' ', '')
    if x in ('', 'PRE', 'PREFIXADO'):
        return 'PRE'
    if x in ('CDI', '%CDI'):
        return 'CDI_PCT'
    if x in ('CDI+', 'CDI+A.A.'):
        return 'CDI_MAIS'
    if x in ('IPCA+', 'IPCA+A.A.'):
        return 'IPCA_MAIS'
    if x == 'IPCA':
        return {'spread': 'IPCA_MAIS', 'percentual': 'IPCA_PCT',
                'bloquear': 'AMBIGUO'}.get(config.ipca_simples, 'AMBIGUO')
    return 'DESCONHECIDO'


def aliquota_ir(dias, produto):
    # Regra do projeto para PF. Outros produtos: regressiva por premissa,
    # sem afirmar que a classificação fiscal específica foi validada.
    if normalizar(produto) in ('LCI', 'LCA'):
        return 0.0
    return .225 if dias <= 180 else .20 if dias <= 360 else .175 if dias <= 720 else .15


class MotorTAE:
    def __init__(self, selic, ipca, config, inicio, fim):
        self.config = config
        self.ref = pd.Timestamp(config.data_referencia).normalize()
        self.inicio = pd.Timestamp(inicio).normalize()
        self.fim = max(pd.Timestamp(fim).normalize(), self.ref)
        if self.inicio > self.ref:
            self.inicio = self.ref
        datas = tuple(pd.Timestamp(d).normalize() for d in config.datas_alteracoes)
        choques = tuple(float(x) for x in config.alteracoes_pp)
        if len(datas) != len(choques) or len(datas) > 3:
            raise ValueError('Configure de zero a três datas e alterações correspondentes.')
        if any(not np.isfinite(x) or abs(x/.25-round(x/.25)) > 1e-9 for x in choques):
            raise ValueError('As alterações devem ser múltiplas de 0,25 p.p.')
        if any(d <= self.ref for d in datas) or any(a >= b for a, b in zip(datas, datas[1:])):
            raise ValueError('Datas de eficácia devem ser futuras, distintas e crescentes.')
        if config.ipca_simples not in ('spread', 'percentual', 'bloquear'):
            raise ValueError('Interpretação de IPCA inválida.')
        if not np.isfinite(config.sensibilidade_ipca) or config.sensibilidade_ipca < 0:
            raise ValueError('Sensibilidade inválida.')
        cal = np.busdaycalendar(holidays=np.array(config.feriados, dtype='datetime64[D]'))
        self.dias = pd.date_range(self.inicio, self.fim, inclusive='left')
        self.du = np.is_busday(self.dias.values.astype('datetime64[D]'), busdaycal=cal)
        self.cumdu = np.r_[0, np.cumsum(self.du)]
        hist = self.dias < self.ref
        self.hist = hist
        s = selic.copy()
        s['Data'] = pd.to_datetime(s['Data']).dt.normalize()
        s = s.sort_values('Data')
        if s.Data.duplicated().any():
            raise ValueError('Datas duplicadas na série Selic.')
        # Nunca usar linhas posteriores à referência como histórico conhecido.
        s = s[s.Data <= self.ref].copy()
        if s.empty:
            raise ValueError('Não há Selic disponível até a referência.')
        s['taxa'] = s['Taxa Selic anual'].map(numero)/100
        s['meta'] = s['Meta Selic'].map(numero)/100
        if not np.isfinite(s[['taxa', 'meta']].to_numpy()).all():
            raise ValueError('Série Selic contém taxas inválidas.')
        alinhada = s.set_index('Data').reindex(self.dias, method='ffill')
        cdi_hist = alinhada.taxa.to_numpy(dtype=float)
        cobertura = self.dias.isin(s.Data)
        self.falta_cdi = hist & self.du & ~cobertura
        self.meta0 = (numero(config.selic_inicial_pct)/100
                      if config.selic_inicial_pct is not None else float(s.meta.iloc[-1]))
        self.ipca = ipca.copy()
        self.ipca['Data'] = pd.to_datetime(self.ipca['Data']).dt.normalize()
        self.ipca = self.ipca[self.ipca.Tipo.map(normalizar).eq('REALIZADO')].copy()
        # Sem calendário de publicação: elegibilidade mensal aproximada.
        self.ipca['Disponivel'] = self.ipca.Data + pd.offsets.MonthBegin(1)
        self.ipca = self.ipca[self.ipca.Disponivel <= self.ref]
        if self.ipca.Data.dt.to_period('M').duplicated().any():
            raise ValueError('Meses duplicados no IPCA realizado.')
        ult = self.ipca.sort_values('Data').dropna(subset=['IPCA_12m'])
        if ult.empty:
            raise ValueError('Não há IPCA 12m realizado elegível na referência.')
        self.ipca0 = numero(ult.IPCA_12m.iloc[-1])/100
        self.ancora_ipca_desatualizada = ult.Data.iloc[-1].to_period('M') != self.ref.to_period('M')-1
        mensal = self.ipca.set_index(self.ipca.Data.dt.to_period('M'))['IPCA'].map(numero)/100
        # Histórico remunerado com a variação mensal anterior (defasagem M-1).
        mm = mensal.reindex(self.dias.to_period('M')-1).to_numpy(dtype=float)
        self.falta_ipca = hist & self.du & ~np.isfinite(mm)
        # Rateio mensal por DU; fatores anuais e anualização usam 252 DU.
        meses = self.dias.to_period('M')
        inicio_mes = meses.to_timestamp().values.astype('datetime64[D]')
        fim_mes = (meses+1).to_timestamp().values.astype('datetime64[D]')
        du_mes = np.busday_count(inicio_mes, fim_mes, busdaycal=cal)
        infl_hist = np.where(self.du, np.log1p(mm)/du_mes, 0.)
        if config.permitir_estimativa_historica:
            infl_hist = np.where(self.falta_ipca,
                                 np.log1p(self.ipca0)/252, infl_hist)
        self.curvas = {}
        self.trajetorias = []
        for nome, sinal in [('Base', 0), ('Simulacao', 1), ('Choque', -1)]:
            meta, infl = self.meta0, self.ipca0
            cdi = cdi_hist.copy()
            logs_ipca = np.array(infl_hist, dtype=float)
            futuro = ~hist
            cdi[futuro] = meta - config.diferencial_cdi_pp/100
            logs_ipca[futuro] = np.where(self.du[futuro], np.log1p(infl)/252, 0.)
            self.trajetorias.append(dict(Cenario=nome, Data=self.ref, Selic_pct=meta*100, IPCA_anual_pct=infl*100))
            for d, delta in zip(datas, choques):
                nova = meta+sinal*delta/100
                if meta <= 0 or nova <= 0:
                    raise ValueError('Selic não positiva: razão relativa indefinida ou cenário inválido.')
                infl = infl*(1+config.sensibilidade_ipca*(nova/meta-1))
                meta = nova
                if infl <= -1 or meta-config.diferencial_cdi_pp/100 <= -1:
                    raise ValueError('Trajetória gera fator de capitalização inválido.')
                mask = self.dias >= d
                cdi[mask] = meta-config.diferencial_cdi_pp/100
                logs_ipca[mask] = np.where(self.du[mask], np.log1p(infl)/252, 0.)
                self.trajetorias.append(dict(Cenario=nome, Data=d, Selic_pct=meta*100, IPCA_anual_pct=infl*100))
            if not np.isfinite(meta) or meta <= 0:
                raise ValueError('Selic inicial inválida.')
            self.curvas[nome] = (cdi, logs_ipca)

    def pos(self, d):
        return int((pd.Timestamp(d).normalize()-self.inicio).days)

    @lru_cache(maxsize=4096)
    def acumuladores(self, nome, mod, taxa):
        cdi, logipca = self.curvas[nome]
        spread = np.log1p(taxa/100)/252
        if mod == 'PRE':
            log = np.where(self.du, spread, 0.)
        elif mod == 'CDI_PCT':
            fator = 1+np.expm1(np.log1p(cdi)/252)*(taxa/100)
            if np.any(fator[self.du] <= 0):
                raise ValueError('Percentual CDI produz fator inválido.')
            log = np.where(self.du, np.log(fator), 0.)
        elif mod == 'CDI_MAIS':
            log = np.where(self.du, np.log1p(cdi)/252+spread, 0.)
        elif mod == 'IPCA_MAIS':
            log = logipca + np.where(self.du, spread, 0.)
        elif mod == 'IPCA_PCT':
            # Participação no retorno diário, premissa distinta de spread.
            log = np.log1p(np.expm1(logipca)*(taxa/100))
        else:
            raise ValueError('INDEXADOR_NAO_CLASSIFICADO')
        # Gaps são sinalizados por título; não contaminam acumuladores posteriores.
        return np.r_[0., np.cumsum(np.nan_to_num(log))], np.r_[0., np.cumsum(np.nan_to_num(logipca))]

    def calcular(self, linha):
        out = {}
        try:
            a = data(linha['Data_Emissao'])
            b = data(linha['Data Vencimento'])
            if pd.isna(a) or pd.isna(b) or b <= a:
                raise ValueError('DATAS_INVALIDAS')
            a, b = a.normalize(), b.normalize()
            if a > self.ref:
                raise ValueError('EMISSAO_POSTERIOR_A_REFERENCIA')
            ia, ib = self.pos(a), self.pos(b)
            if ia < 0 or ib > len(self.dias):
                raise ValueError('FORA_DO_INTERVALO_DO_MOTOR')
            corte = min(ib, max(ia, self.pos(self.ref)))
            du = self.cumdu[ib]-self.cumdu[ia]
            dc = (b-a).days
            if du <= 0:
                raise ValueError('SEM_DIAS_UTEIS')
            if dc < 30 and normalizar(linha['Produto']) not in ('LCI', 'LCA'):
                raise ValueError('IOF_CURTO_PRAZO_NAO_IMPLEMENTADO')
            avisos = []
            for campo in ('JUROS', 'AMORTIZACAO'):
                fluxo = normalizar(linha.get(campo))
                if fluxo not in ('', 'SOMENTE_VENCIMENTO', 'NO VENCIMENTO', 'VENCIMENTO'):
                    raise ValueError('FLUXO_INTERMEDIARIO_NAO_SUPORTADO')
                if not fluxo:
                    if not self.config.assumir_fluxo_unico_quando_ausente:
                        raise ValueError('FLUXO_NAO_INFORMADO')
                    avisos.append('FLUXO_UNICO_ASSUMIDO')
            taxa = numero(linha['Taxa'])
            if not np.isfinite(taxa) or taxa <= -100:
                raise ValueError('TAXA_INVALIDA')
            mod = modalidade(linha.get('Indexador'), self.config)
            if mod in ('AMBIGUO', 'DESCONHECIDO'):
                raise ValueError('INDEXADOR_AMBIGUO_OU_DESCONHECIDO')
            if normalizar(linha.get('Indexador')) == 'IPCA':
                avisos.append('IPCA_INTERPRETADO_COMO_'+self.config.ipca_simples.upper())
            if mod.startswith('CDI') and self.falta_cdi[ia:corte].any():
                if not self.config.permitir_estimativa_historica:
                    raise ValueError('HISTORICO_CDI_INCOMPLETO')
                if not np.isfinite(self.curvas['Base'][0][ia:corte][self.du[ia:corte]]).all():
                    raise ValueError('HISTORICO_CDI_SEM_TAXA_INICIAL')
                avisos.append('CDI_HISTORICO_ESTIMADO_POR_MANUTENCAO')
            falta = self.falta_ipca[ia:corte].any()
            if b > self.ref and self.ancora_ipca_desatualizada:
                if mod.startswith('IPCA') and not self.config.permitir_estimativa_historica:
                    raise ValueError('IPCA_SPOT_MES_ANTERIOR_AUSENTE')
                avisos.append('IPCA_SPOT_DESATUALIZADO')
                if not self.config.permitir_estimativa_historica:
                    falta = True
            if falta:
                if not self.config.permitir_estimativa_historica and mod.startswith('IPCA'):
                    raise ValueError('HISTORICO_IPCA_INCOMPLETO')
                avisos.append('IPCA_HISTORICO_ESTIMADO' if self.config.permitir_estimativa_historica
                              else 'TAE_REAL_INDISPONIVEL_POR_FALTA_IPCA')
            produto = normalizar(linha['Produto'])
            if produto not in ('CDB', 'LF', 'LCI', 'LCA'):
                avisos.append('IR_REGRESSIVO_POR_PREMISSA_DO_PROJETO')
            ir = aliquota_ir(dc, produto)
            out.update(Modalidade=mod, DC=dc, DU=du, IR=ir,
                       Situacao='VENCIDO' if b <= self.ref else 'EM_CURSO')
            for nome in self.curvas:
                cum, cinf = self.acumuladores(nome, mod, taxa)
                fator_hist = np.exp(cum[corte]-cum[ia])
                fator_fut = np.exp(cum[ib]-cum[corte])
                bruto = fator_hist*fator_fut-1
                imposto = max(bruto, 0)*ir
                liquido = bruto-imposto
                fator_inflacao = np.exp(cinf[ib]-cinf[ia])
                out.update({f'Fator_Historico_{nome}': fator_hist,
                            f'Fator_Futuro_{nome}': fator_fut,
                            f'Retorno_Bruto_{nome}': bruto,
                            f'IR_Valor_{nome}': imposto,
                            f'Retorno_Liquido_{nome}': liquido,
                            f'TAE_Bruta_{nome}': np.expm1(np.log1p(bruto)*252/du),
                            f'TAE_Liquida_{nome}': np.expm1(np.log1p(liquido)*252/du),
                            f'TAE_Real_{nome}': np.expm1(np.log((1+liquido)/fator_inflacao)*252/du)
                            if not falta or self.config.permitir_estimativa_historica else np.nan})
            out['Status_Calculo'] = 'OK_COM_PREMISSAS' if avisos else 'OK'
            out['Avisos'] = ';'.join(sorted(set(avisos)))
        except (ValueError, TypeError, OverflowError) as e:
            out = {'Status_Calculo': str(e), 'Avisos': ''}
        return out


def calcular_ranking(btg, selic, ipca, config):
    """Retorna (resultados por título, trajetórias). Não lê nem grava arquivos."""
    base = btg.copy().reset_index(drop=True)
    base.columns = base.columns.str.strip()
    base['Data_Emissao'] = base['Data_Emissao'].map(data)
    base['Data Vencimento'] = base['Data Vencimento'].map(data)
    inicio = base.Data_Emissao.min()
    fim = base['Data Vencimento'].max()
    if pd.isna(inicio) or pd.isna(fim):
        raise ValueError('Base sem datas válidas.')
    motor = MotorTAE(selic, ipca, config, inicio, fim)
    saida = pd.DataFrame([motor.calcular(linha) for linha in base.to_dict('records')])
    # Evita reter curvas de diferentes datas ao construir o histórico inteiro.
    motor.acumuladores.cache_clear()
    # Evita colisão com resultados de uma execução anterior.
    resultado = pd.concat([base.drop(columns=base.columns.intersection(saida.columns)), saida], axis=1)
    valido = resultado.Status_Calculo.str.startswith('OK')
    for nome in motor.curvas:
        col = f'TAE_Liquida_{nome}'
        resultado[f'Ranking_{nome}'] = np.nan
        if col not in resultado:
            continue
        rank = resultado.loc[valido].copy()
        rank['_tae'] = rank[col].round(12)
        rank = rank.sort_values(['Data_Emissao', '_tae', 'DC'], ascending=[True, False, True])
        novo = rank.Data_Emissao.ne(rank.Data_Emissao.shift()) | rank._tae.ne(rank._tae.shift()) | rank.DC.ne(rank.DC.shift())
        resultado.loc[rank.index, f'Ranking_{nome}'] = novo.groupby(rank.Data_Emissao).cumsum().to_numpy()
    cols = [f'TAE_Liquida_{n}' for n in motor.curvas]
    if all(c in resultado for c in cols):
        resultado['Amplitude_TAE_pp'] = (resultado[cols].max(axis=1)-resultado[cols].min(axis=1))*100
        for n in ('Simulacao', 'Choque'):
            resultado[f'Mudanca_Ranking_{n}'] = resultado.Ranking_Base-resultado[f'Ranking_{n}']
    return resultado, pd.DataFrame(motor.trajetorias)
