Dashboard de Viabilidade de Produto

Este é um dashboard interativo construído com Streamlit para analisar a viabilidade financeira de produtos, comparando diferentes fornecedores e simulando cenários de venda em diversos mercados-alvo.
Funcionalidades

    Carregamento Inteligente de Planilhas: Faça o upload de um arquivo Excel (.xlsx, .xls) com os dados do produto. O sistema identifica automaticamente o cabeçalho e extrai informações essenciais, como o peso do produto, diretamente do nome.

    Análise de Custo e Lucro: Edite custos (logística, impostos, etc.) e preços de venda para calcular dinamicamente a margem de lucro, o custo final por kg e outras métricas importantes.

    Simulação de Preço de Venda: Calcule automaticamente o preço de venda para todos os produtos com base em uma margem de lucro desejada.

    Análise Temporal: Simule o impacto do tempo de estoque e do custo de capital (juros) na lucratividade do seu produto ao longo dos meses.

    Simulação de Mercados-Alvo: Para um mesmo produto, crie e compare diferentes cenários de venda, adicionando custos específicos para cada mercado e visualizando qual oferece o maior retorno financeiro.

Tecnologias Utilizadas

    Python

    Streamlit: Para a criação da interface web interativa.

    Pandas: Para manipulação e análise dos dados.

    Plotly: Para a criação dos gráficos interativos.

    Openpyxl: Para a leitura de arquivos Excel.

Como Executar o Projeto

Siga os passos abaixo para configurar e rodar o dashboard no seu ambiente local.
1. Pré-requisitos

    Ter o Python (versão 3.8 ou superior) instalado no seu sistema.

    Ter o Git instalado no seu sistema.

2. Clone o Repositório (Para outros usuários)

git clone [https://github.com/Oliveirabrl/Viabilidadeproduto.git](https://github.com/Oliveirabrl/Viabilidadeproduto.git)
cd Viabilidadeproduto

3. Instale as Dependências

É uma boa prática criar um ambiente virtual. Após ativá-lo, instale as dependências:

pip install -r requirements.txt

4. Execute o Dashboard

streamlit run dashboard.py

O dashboard será aberto automaticamente no seu navegador.