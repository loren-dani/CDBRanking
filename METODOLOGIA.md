# Motor de rentabilidade: histórico, manutenção e cenários

## Decisão central

Para uma aplicação iniciada em A, avaliada na referência R e com vencimento V:

    Fator total = Fator histórico [A, min(R,V)) × Fator futuro [max(A,R), V)
    Retorno bruto = Fator total − 1
    IR = máximo(Retorno bruto, 0) × alíquota do prazo total A→V
    Retorno líquido = Retorno bruto − IR
    TAE líquida = (1 + Retorno líquido)^(252 / DU total) − 1

Não se somam retornos dos dois trechos. Não se cobra IR na referência para
reaplicar o saldo líquido: não houve resgate. A data de referência representa
o início do dia. A remuneração desse dia integra o trecho futuro. A emissão
integra o período e o vencimento é excluído, como no código original.

O cenário Base é a nova medida de carregamento com taxas futuras constantes
na referência, incorporando o caminho histórico. A antiga TAE com taxa
congelada na emissão é uma simulação ex ante diferente. Seus valores não devem
ser apresentados como rendimento efetivamente acumulado.

## Três cenários e unidades

Base: nenhum movimento. Simulacao: movimentos informados. Choque: os mesmos
movimentos, nas mesmas datas, com sinais invertidos. Podem existir até três
movimentos; zero é permitido. Todos precisam ser múltiplos de 0,25 p.p.

Defaults de interface acordados: Selic 13,25% e movimentos +0,25, +0,25,
+0,50 p.p. Trajetórias finais: Base 13,25%; Simulacao 14,25%; Choque 12,25%.
Esses são parâmetros de simulação, não afirmações sobre a Selic vigente.

A configuração recebe datas de eficácia futuras, distintas e crescentes.
Não há datas de Copom inventadas ou fixadas automaticamente. O dia de anúncio
e o dia de início da nova taxa não precisam coincidir. Datas em
validar_anexos.py e trajetorias_teste.csv são exclusivamente testes sintéticos.
Depois do último movimento, a taxa permanece constante até o vencimento.
Um movimento posterior ao vencimento não afeta o título.

A regra escolhida para inflação é aplicada a cada movimento, separadamente:

    Selic nova = Selic anterior + movimento em p.p.
    IPCA anual novo = IPCA anual anterior × [1 + 2,5 × (Selic nova / Selic anterior − 1)]

Exemplo: 13,25%→13,50% é +0,25 p.p., ou +1,88679% relativo.
O IPCA anual aumenta 4,71698% relativamente. Um IPCA inicial de 4,50%
passaria a aproximadamente 4,71226%. Não é aumento de 0,625 p.p.

Esse ratio é uma premissa de sensibilidade adotada no projeto; não é relação
causal nem coeficiente estimado nessa direção. O motor aplica o ajuste na
data do movimento. Não antecipa inflação em meses já realizados. Qualquer
defasagem futura exigirá um parâmetro adicional, que não foi definido.

O nível anual projetado é convertido em fator diário geométrico por dias
corridos do respectivo ano (365/366). Trata-se de ritmo anual equivalente
projetado; não de reconstrução exata do IPCA acumulado móvel dos próximos
12 meses. Este último exigiria projetar a série mensal e recalcular o rolling.

## Cálculo por modalidade

| Modalidade | Histórico | Futuro |
|---|---|---|
| Prefixado | Fator contratado, por DU/252 | Mesmo fator contratado |
| %CDI ou CDI | Produto de `1 + percentual × [(1+CDI_d)^(1/252)−1]` em cada DU | Mesma fórmula, com trajetória do cenário |
| CDI + spread | CDI diário multiplicado pelo spread efetivo anual convertido por DU/252 | Mesma fórmula com CDI projetado |
| IPCA + spread | IPCA mensal realizado do mês anterior, pró-rata geométrico por dia corrido, multiplicado pelo spread por DU/252 | Ritmo anual de inflação do cenário e spread por DU/252 |
| Percentual do IPCA | Participação no retorno diário de inflação, se explicitamente selecionada | Mesma regra com inflação projetada |

Nesta versão de publicação, a defasagem M-1 vale para o IPCA spot e para a variação mensal usada na acumulação histórica. Durante outubro utiliza-se o IPCA 12m de setembro como âncora, e a variação mensal de setembro para o trecho histórico de outubro, rateada pelos dias de outubro. Isso é uma convenção simplificada do simulador, não uma reprodução de VNA contratual.

O IPCA_12m não é acumulado novamente a cada mês histórico. A coluna IPCA é
a variação mensal usada no histórico. IPCA_12m realizado serve apenas de
âncora para o ritmo anual projetado. Linhas Tipo=Projetado são excluídas da
base realizada, independentemente da data.

No novo leiaute, IPCA aparece com Taxa na faixa de 5 a 8. O default é
interpretar isso como spread real anual (IPCA + Taxa), com aviso em cada
registro afetado. Isso corrige a interpretação anterior de, por exemplo,
7,77 como 7,77% do IPCA, mas precisa corresponder à documentação comercial
da base. É possível escolher ipca_simples='bloquear' ou 'percentual'.

## Proxy CDI e âncora da Selic

Preserva-se a coluna Taxa Selic anual do código anexado como proxy histórica
do CDI. Não é a série DI efetivamente divulgada. A meta Selic é separada.
No futuro, o default é CDI = meta simulada − 0,10 p.p., coerente com o
diferencial observado no anexo; o diferencial é configurável. Isso é uma
premissa, não identidade financeira garantida.

selic_inicial_pct=None usa a última meta disponível até a referência.
13.25 usa a âncora manual acordada. Na referência 10/11/2026, o arquivo só
tem meta de 13,75% até 30/10. Portanto, 13,25% deve ser rotulada como
manual. O motor não cria uma decisão histórica para justificar a diferença.

## TAE real e comparabilidade

    TAE real = [(1 + retorno líquido total) / fator de inflação total]^(252/DU total) − 1

A inflação total usa o mesmo intervalo da aplicação. O prefixado não muda
sua rentabilidade nominal entre cenários; sua rentabilidade real pode mudar.
Na ausência de IPCA histórico, o motor pode calcular títulos CDI/prefixados
nominalmente, mas deixa a TAE real indisponível no modo estrito.

A TAE apresentada é da aplicação inteira, não apenas do período remanescente.
Fator_Historico e Fator_Futuro permitem inspecionar os trechos. Para decidir
uma compra hoje, é necessário usar condições de compra atuais e data de
aquisição atual; uma oferta histórica não se torna disponível hoje.

O campo Data_Emissao da consolidação foi extraído da data da oferta/arquivo.
Ele só representa o início da aplicação e a contagem do IR se a aquisição
hipotética ocorreu nessa data. Para carteira efetivamente adquirida em outra
data, fornecer a data real de aquisição. O motor não estima preço de mercado,
rentabilidade de venda antecipada ou reinvestimento de cupons.

Ranking por Data_Emissao: maior TAE líquida; em empate, menor prazo DC.
Mesma TAE (arredondada a 12 casas decimais) e mesmo prazo têm mesma posição.
A classificação é densa, como no código anterior. Mudança positiva indica
melhora de posição. Amplitude_TAE_pp está em p.p.; retornos e TAEs estão em
decimais (0,12 = 12%). Comparação de prazos não elimina diferenças de risco,
liquidez ou qualidade de crédito.

## Cobertura dos anexos e controles

Selic_Diaria: 09/05/2024 a 30/10/2026. IPCA realizado: até setembro/2026.
IPCA outubro a dezembro/2026 é projetado e não é realizado.

Modo padrão: permitir_estimativa_historica=False. Lacunas no passado impedem
o cálculo do indexador correspondente. Não há preenchimento silencioso.
Para CDI, são exigidas as datas úteis históricas conforme o calendário
configurado; finais de semana não precisam ter linha. Para IPCA, todo mês
histórico abrangido precisa ter variação realizada elegível na referência.

Modo opcional: permitir_estimativa_historica=True. CDI faltante é mantido
na última observação; IPCA faltante usa o ritmo anual da última âncora 12m.
Os registros recebem avisos de estimativa e não devem ser exibidos como
rentabilidade realizada. Não se estima CDI anterior à primeira observação.

A elegibilidade do IPCA usa primeiro dia do mês seguinte como aproximação,
herdada do código anterior. Isso não é o calendário efetivo de divulgação.
Backtests sem informação futura exigem adicionar datas reais de publicação.
O rateio mensal diário não reproduz necessariamente a defasagem do indexador,
data de aniversário, VNA ou regra de atualização monetária de cada contrato.
Assim, resultados IPCA são aproximações de simulação, não conciliação exata
com extrato bancário.

O calendário padrão considera segunda a sexta. Config.feriados recebe uma
lista de datas excluídas. Para produção, fornecer o calendário financeiro
adequado; o anexo Selic também inclui dias que podem ser feriados. Não há
pretensão de precisão contratual sem esse calendário e as convenções do papel.

## Tributação e fluxos intermediários

Mantém-se a regra do projeto: LCI/LCA isentas para PF; demais produtos com
regressiva 22,5/20/17,5/15%, pelo prazo em dias corridos desde a aquisição.
IR incide uma única vez sobre rendimento total positivo no vencimento.
Produtos diferentes de CDB/LF/LCI/LCA recebem aviso de classificação fiscal
por premissa. LCD/LIG e outros produtos podem ter regras específicas e não
devem receber selo de tributação validada a partir desse default.

Referência para tabela regressiva: Lei 11.033/2004, art. 1º:
https://www2.camara.leg.br/legin/fed/lei/2004/lei-11033-21-dezembro-2004-535177-normaatualizada-pl.html

Aplicações tributadas com prazo total inferior a 30 dias ficam bloqueadas,
pois IOF não foi implementado. Taxas, custos e eventos de crédito não entram.
Não há venda ou resgate na referência.

Foram encontrados 54 registros com JUROS=MENSAL. Eles ficam fora do ranking:
necessitam de agenda de pagamentos, base tributária por fluxo e hipótese de
reinvestimento ou taxa interna de retorno. Tratar esses títulos como bullet
produziria comparabilidade incorreta. Não há dados suficientes no consolidado
para reconstruir com exatidão todos esses fluxos.

JUROS/AMORTIZACAO ausentes no leiaute antigo: assume-se pagamento único, com
aviso explícito. Essa premissa pode ser desativada. Se informação contratual
posterior indicar cupons, corrigir a base antes de integrar os títulos.

## Uso no notebook, sem CSV obrigatório e sem escrita de arquivos

Dependências: pandas, numpy e openpyxl (leitura dos arquivos Excel).

```python
import pandas as pd
from motor_tae import Config, calcular_ranking

btg = pd.read_excel('BTG_Consolidado.xlsx', sheet_name='Base_Consolidada')
selic = pd.read_excel('SELIC_OUTPUT.xlsx', sheet_name='Selic_Diaria')
ipca = pd.read_excel('IPCA_OUTPUT.xlsx')

# Datas de eficácia selecionadas pelo investidor na interface:
config = Config(
    data_referencia=data_referencia,
    datas_alteracoes=tuple(datas_de_eficacia),
    alteracoes_pp=(0.25, 0.25, 0.50),
    selic_inicial_pct=13.25,
    feriados=tuple(feriados_financeiros),
    permitir_estimativa_historica=False,
)
ranking, trajetorias = calcular_ranking(btg, selic, ipca, config)
validos = ranking[ranking.Status_Calculo.str.startswith('OK')]
pendencias = ranking[~ranking.Status_Calculo.str.startswith('OK')]
display(validos)
display(pendencias.Status_Calculo.value_counts())
```

O motor recebe DataFrames e não acessa rede, não gera CSV e não grava arquivos.
O notebook e, depois, o Streamlit serão responsáveis pela leitura dos três
Excel. Não há dependência de taxas_macro.csv. O script validar_anexos.py
grava apenas evidências de auditoria para esta revisão, usando os nomes e
caminhos dos anexos deste ambiente; esses caminhos devem ser adaptados fora
dele. Nenhuma implantação no GitHub/Streamlit foi feita nesta etapa.

## Validação

Executar `python testar_motor.py`. Testes cobrem histórico CDI variável,
produto de fatores, prefixado nominal invariável, inflação mensal realizada,
regra relativa futura, exclusão de projeções do histórico, títulos vencidos,
vencimento antes do choque, cobrança única de IR, lacunas, juros mensais,
calendário com feriado, incrementos inválidos e empates no ranking.

Esta versão foi verificada com 11 testes automatizados e uma execução de integração
com os três Excel e a camada de interface simulada. A oferta de 30/10/2026
contém 712 títulos: 706 calculados e 6 com fluxos intermediários bloqueados.
O ambiente local não contém Streamlit instalado: a renderização e o funcionamento
na conta Community Cloud ainda precisam ser verificados após a implantação.
Não se realizou conciliação contra extratos oficiais de cada título.
