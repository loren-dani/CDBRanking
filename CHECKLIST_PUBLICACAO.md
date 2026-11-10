# Checklist de publicação

## 1. Preparar os arquivos

- [ ] Baixar e extrair ranking_btg_streamlit_pronto.zip no computador.
- [ ] Abrir a pasta extraída. Os arquivos devem aparecer diretamente nela.
- [ ] Confirmar os seis arquivos necessários na raiz:
  - app.py
  - motor_tae.py
  - requirements.txt
  - BTG_Consolidado.xlsx
  - IPCA_OUTPUT.xlsx
  - SELIC_OUTPUT.xlsx
- [ ] Manter também README.md, METODOLOGIA.md e este checklist para consulta.
- [ ] testar_motor.py é opcional no repositório e está incluído para validação.

Não enviar o ZIP como substituto dos arquivos extraídos. Não é necessário
enviar o notebook, taxas_macro.csv, motor_tae_revisado.zip, amostras,
trajetórias de teste ou relatórios de validação do pacote anterior.

## 2. GitHub — repositório que você já está usando

- [ ] Abrir o repositório do ranking.
- [ ] Selecionar a branch usada pelo aplicativo (normalmente main).
- [ ] Na página principal, clicar em Add file → Upload files.
- [ ] Arrastar os arquivos extraídos para a raiz, sem criar pasta data.
- [ ] Usar a nova versão de app.py e requirements.txt, substituindo as anteriores.
- [ ] Usar o motor_tae.py DESTE pacote: ele inclui o ajuste de defasagem M-1.
- [ ] Escrever uma mensagem de commit, por exemplo: “Integra ranking e três cenários”.
- [ ] Clicar em Commit changes e confirmar que os arquivos aparecem na página principal.
- [ ] Conferir maiúsculas e minúsculas dos nomes, especialmente BTG_Consolidado.xlsx,
      IPCA_OUTPUT.xlsx e SELIC_OUTPUT.xlsx (SELIC, não SELI).
- [ ] Se o site não aceitar sobrescrever um arquivo, abrir o arquivo existente e
      substituir sua versão, mantendo o mesmo nome. Não criar app(1).py.
- [ ] Se o repositório for público, confirmar que as bases comerciais podem ser
      publicadas. Usar repositório privado se elas não forem destinadas ao público.

## 3. Streamlit Community Cloud

- [ ] Entrar em https://share.streamlit.io/ com a conta vinculada ao GitHub.
- [ ] Se o aplicativo já existe, conferir se aponta para o mesmo repositório,
      branch e app.py; acompanhar a atualização e os logs após o commit.
- [ ] Para uma nova implantação, clicar em Create app e escolher o repositório.
- [ ] Informar a branch utilizada, por exemplo main.
- [ ] Informar Main file path: app.py.
- [ ] Nas opções avançadas, escolher Python 3.12, se disponível na conta.
- [ ] Clicar em Deploy e aguardar a instalação das dependências e inicialização.
- [ ] Se houver falha, abrir os logs em Manage app e copiar a mensagem completa.

Referências oficiais:
https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies

## 4. Primeiro teste na tela

- [ ] Confirmar referência inicial 30/10/2026 para os arquivos deste pacote.
- [ ] Confirmar a data da oferta selecionada (a mais recente até a referência).
- [ ] Confirmar Selic inicial manual de 13,25% a.a.
- [ ] Preencher três datas FUTURAS de eficácia, em ordem crescente.
- [ ] Manter os movimentos +0,25; +0,25; +0,50 p.p.
- [ ] Clicar em Calcular cenários.
- [ ] Conferir Selic final: Base 13,25%; Simulação 14,25%; Choque 12,25%.
- [ ] Conferir tabela com as três TAEs líquidas e reais, amplitude e mudança de posição.
- [ ] Verificar que prefixados mantêm a mesma TAE nominal nos três cenários.
- [ ] Verificar os avisos, os títulos pendentes e o calendário sem feriados.
- [ ] Baixar o CSV e conferir algumas linhas.

As datas precisam ser escolhidas conforme a vigência das decisões que você
pretende simular. O aplicativo não fornece automaticamente agenda do Copom.

## 5. Antes de compartilhar

- [ ] Atualizar as taxas caso queira usar referência posterior à cobertura atual.
- [ ] Para referência em novembro, incluir IPCA de outubro classificado como
      realizado e atualizar o histórico Selic até a referência.
- [ ] Confirmar a interpretação IPCA sem sinal + como spread real no novo leiaute.
- [ ] Informar feriados financeiros se precisar melhorar a contagem de dias úteis.
- [ ] Conferir a visibilidade do aplicativo e quem pode acessar os resultados.
- [ ] Compartilhar o endereço do aplicativo depois de observar seu funcionamento.

## Diagnóstico rápido

| Mensagem/sintoma | O que verificar |
|---|---|
| Arquivo ausente | Nome exato e presença na raiz, junto do app.py |
| ModuleNotFoundError | requirements.txt na raiz e dependências instaladas nos logs |
| Aba não encontrada | Base_Consolidada e Selic_Diaria com nomes originais |
| IPCA_SPOT_MES_ANTERIOR_AUSENTE | Atualizar o mês anterior realizado ou alterar referência |
| HISTORICO_CDI_INCOMPLETO | Estender a série diária realizada até a referência |
| HISTORICO_IPCA_INCOMPLETO | Conferir meses históricos necessários com defasagem M-1 |
| FLUXO_INTERMEDIARIO_NAO_SUPORTADO | Título exige cálculo por cupons; não é falha de instalação |
| Tela pede datas | Preencher as primeiras N datas, ou selecionar zero alterações |

Não inserir credenciais em app.py ou no GitHub. Esta aplicação não precisa delas.
