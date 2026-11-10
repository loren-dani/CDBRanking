"""Testes independentes de fatores e fronteiras. Executar: python testar_motor.py"""
import unittest
import numpy as np
import pandas as pd
from motor_tae import Config, MotorTAE, calcular_ranking


class TestMotor(unittest.TestCase):
    def setUp(self):
        self.s = pd.DataFrame({'Data': pd.bdate_range('2025-01-01', '2025-12-31')})
        self.s['Meta Selic'] = np.where(self.s.Data < '2025-07-01', 10., 12.)
        self.s['Taxa Selic anual'] = self.s['Meta Selic']-.1
        self.i = pd.DataFrame({'Data': pd.date_range('2024-01-31', '2025-12-31', freq='ME'),
                               'IPCA': .5, 'IPCA_12m': (1.005**12-1)*100,
                               'Tipo': 'Realizado'})
        self.c = Config('2025-09-01', ('2025-10-01', '2025-11-03', '2025-12-01'), (.25, .25, .5), 13.25)
        self.m = MotorTAE(self.s, self.i, self.c, '2025-01-01', '2026-07-01')
        self.row = dict(Data_Emissao='2025-01-01', **{'Data Vencimento': '2026-07-01'},
                        Taxa=100, Produto='CDB', Indexador='%CDI', JUROS='SOMENTE_VENCIMENTO',
                        AMORTIZACAO='SOMENTE_VENCIMENTO')

    def test_historico_variavel_e_futuro(self):
        r = self.m.calcular(self.row)
        n1 = np.busday_count('2025-01-01', '2025-07-01')
        n2 = np.busday_count('2025-07-01', '2025-09-01')
        expected = 1.099**(n1/252)*1.119**(n2/252)
        self.assertAlmostEqual(r['Fator_Historico_Base'], expected, 12)
        for n in ('Simulacao', 'Choque'):
            self.assertAlmostEqual(r['Fator_Historico_'+n], expected, 12)
        nf = np.busday_count('2025-09-01', '2026-07-01')
        self.assertAlmostEqual(r['Fator_Futuro_Base'], 1.1315**(nf/252), 12)
        self.assertGreater(r['TAE_Liquida_Simulacao'], r['TAE_Liquida_Base'])
        self.assertGreater(r['TAE_Liquida_Base'], r['TAE_Liquida_Choque'])

    def test_prefixado_nao_muda_nominal(self):
        r = self.m.calcular({**self.row, 'Indexador': 'PRE', 'Taxa': 12})
        self.assertAlmostEqual(r['TAE_Bruta_Base'], .12, 12)
        self.assertAlmostEqual(r['TAE_Liquida_Base'], r['TAE_Liquida_Choque'], 12)
        self.assertNotEqual(r['TAE_Real_Base'], r['TAE_Real_Choque'])

    def test_vencimento_antes_do_choque(self):
        r = self.m.calcular({**self.row, 'Data Vencimento': '2025-09-30'})
        self.assertEqual(r['TAE_Liquida_Base'], r['TAE_Liquida_Simulacao'])
        self.assertEqual(r['TAE_Liquida_Base'], r['TAE_Liquida_Choque'])

    def test_vencido_e_imposto_unico(self):
        r = self.m.calcular({**self.row, 'Data Vencimento': '2025-08-01'})
        self.assertEqual(r['Situacao'], 'VENCIDO')
        self.assertEqual(r['Fator_Futuro_Base'], 1)
        self.assertAlmostEqual(r['IR_Valor_Base'], r['Retorno_Bruto_Base']*.20)

    def test_ipca_mensal_nao_12m_repetido(self):
        r = self.m.calcular({**self.row, 'Indexador': 'IPCA + a.a.', 'Taxa': 0,
                             'Data Vencimento': '2025-09-01'})
        self.assertAlmostEqual(r['Fator_Historico_Base'], 1.005**8, 12)

    def test_inflacao_futura_relativa(self):
        t = pd.DataFrame(self.m.trajetorias)
        a = t[t.Cenario.eq('Simulacao')].reset_index(drop=True)
        self.assertAlmostEqual(a.Selic_pct.iloc[-1], 14.25)
        self.assertAlmostEqual(a.IPCA_anual_pct.iloc[1], a.IPCA_anual_pct.iloc[0]*(1+2.5*(13.5/13.25-1)))

    def test_defasagem_mensal_menos_um(self):
        i = self.i.copy()
        i.loc[i.Data.eq('2025-07-31'), 'IPCA'] = 1.
        i.loc[i.Data.eq('2025-08-31'), 'IPCA'] = 9.
        m = MotorTAE(self.s, i, self.c, '2025-01-01', '2026-07-01')
        r = m.calcular({**self.row, 'Data_Emissao':'2025-08-01',
                       'Data Vencimento':'2025-09-01', 'Indexador':'IPCA+', 'Taxa':0})
        self.assertAlmostEqual(r['Fator_Historico_Base'], 1.01, 12)

    def test_fluxos_e_gaps(self):
        self.assertEqual(self.m.calcular({**self.row, 'JUROS': 'MENSAL'})['Status_Calculo'],
                         'FLUXO_INTERMEDIARIO_NAO_SUPORTADO')
        gap = self.s[self.s.Data < '2025-08-01']
        m = MotorTAE(gap, self.i, self.c, '2025-01-01', '2026-07-01')
        self.assertEqual(m.calcular(self.row)['Status_Calculo'], 'HISTORICO_CDI_INCOMPLETO')
        m = MotorTAE(self.s, self.i[self.i.Data < '2025-07-01'], self.c, '2025-01-01', '2026-07-01')
        self.assertEqual(m.calcular({**self.row, 'Indexador': 'IPCA+', 'Taxa': 5})['Status_Calculo'],
                         'IPCA_SPOT_MES_ANTERIOR_AUSENTE')

    def test_projecoes_do_anexo_excluidas(self):
        i = self.i.copy()
        i.loc[i.Data.eq('2025-08-31'), ['Tipo', 'IPCA', 'IPCA_12m']] = ['Projetado', 99., 99.]
        m = MotorTAE(self.s, i, self.c, '2025-01-01', '2026-07-01')
        self.assertEqual(m.calcular({**self.row, 'Indexador': 'IPCA+', 'Taxa': 5})['Status_Calculo'],
                         'IPCA_SPOT_MES_ANTERIOR_AUSENTE')

    def test_feriado_e_invalidos(self):
        c = Config('2025-09-01', feriados=('2025-01-01',))
        m = MotorTAE(self.s, self.i, c, '2025-01-01', '2026-07-01')
        self.assertEqual(m.cumdu[-1], self.m.cumdu[-1]-1)
        for changes in ((.1,), (.25, .25, .25, .25)):
            with self.assertRaises(ValueError):
                MotorTAE(self.s, self.i, Config('2025-09-01', ('2025-10-01',), changes), '2025-01-01', '2026-07-01')

    def test_ranking_empates(self):
        rows = [{**self.row, 'Taxa': 12, 'Indexador': 'PRE'}]*2
        r, _ = calcular_ranking(pd.DataFrame(rows), self.s, self.i, self.c)
        self.assertEqual(r.Ranking_Base.tolist(), [1, 1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
