import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots  # Importação necessária
import re
import numpy as np
import datetime
from dateutil.relativedelta import relativedelta
import locale

# --- Configuração da Página e Localidade ---
st.set_page_config(layout="wide", page_title="Dashboard de Viabilidade")
try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
except locale.Error:
    locale.setlocale(locale.LC_TIME, '') # Fallback

# --- Constantes de Conversão (Commodities) ---
COMMODITY_FACTORS = {
    "Soja": {
        "bushel_kg": 27.2155,
        "libra_kg": 0.453592
    },
    "Milho": {
        "bushel_kg": 25.4012,
        "libra_kg": 0.453592
    },
    "Saca": {
        "saca_kg": 60.0
    }
}


# --- Funções Utilitárias ---

def format_brazilian(num, prefix="R$ ", suffix="", decimals=2):
    """Formata um número para o padrão brasileiro (ex: R$ 1.234,56)."""
    if pd.isna(num) or not isinstance(num, (int, float)):
        default_zero = "0," + "0" * decimals
        return f"{prefix}{default_zero}{suffix}"
    
    formatted_num = f"{num:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{prefix}{formatted_num}{suffix}"

def extract_weight_from_name(product_name):
    """Extrai o peso (em KG) do nome de um produto usando regex."""
    if not isinstance(product_name, str):
        return 0.0
    match = re.search(r'(\d[\d,.]*)\s*(KG|G|GR)\b', product_name, re.IGNORECASE)
    if not match:
        return 0.0
        
    try:
        value_str = match.group(1).replace(',', '.')
        value = float(value_str)
        unit = match.group(2).upper()
        
        if unit in ['G', 'GR']:
            return value / 1000.0
        if unit == 'KG':
            return value
    except (ValueError, IndexError):
        return 0.0
    return 0.0

# --- Funções de Processamento de Dados ---

@st.cache_data
def load_and_process_data(uploaded_file):
    """Carrega e processa o arquivo Excel, retornando um DataFrame limpo."""
    if uploaded_file is None:
        return pd.DataFrame()
    try:
        df_preview = pd.read_excel(uploaded_file, header=None, nrows=10, engine='openpyxl')
        header_row_index = -1
        for i, row in df_preview.iterrows():
            if 'PRODUTO' in row.astype(str).str.upper().values:
                header_row_index = i
                break
        
        if header_row_index == -1:
            st.error("Cabeçalho não encontrado. Verifique se a coluna 'PRODUTO' existe no arquivo.")
            return pd.DataFrame()

        df = pd.read_excel(uploaded_file, header=header_row_index, engine='openpyxl')
        
        df.columns = df.columns.str.strip().str.upper()
        column_mapping = { 'CAIXA': 'UNIDADE/EMBALAGEM', 'VALOR CAIXA': 'VALOR/EMBALAGEM' }
        df.rename(columns=column_mapping, inplace=True)

        if 'PRODUTO' not in df.columns:
            st.error("A coluna 'PRODUTO' é obrigatória no arquivo.")
            return pd.DataFrame()
        df['PRODUTO'] = df['PRODUTO'].astype(str)

        for col in ['VALOR UNITÁRIO', 'VALOR/EMBALAGEM']:
            if col in df.columns:
                s = df[col].astype(str).str.replace(r'[R$\s]', '', regex=True).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                df[col] = pd.to_numeric(s, errors='coerce').fillna(0.0)
        
        df['KG da Unidade'] = df['PRODUTO'].apply(extract_weight_from_name)
        
        if 'UNIDADE/EMBALAGEM' in df.columns:
            df['UNIDADE/EMBALAGEM_NUM'] = df['UNIDADE/EMBALAGEM'].astype(str).str.extract(r'(\d+)').astype(float).fillna(1.0)
        else:
             df['UNIDADE/EMBALAGEM_NUM'] = 1.0

        peso_total_embalagem = df['KG da Unidade'] * df['UNIDADE/EMBALAGEM_NUM']
        df['MÉDIA/KG'] = np.divide(df['VALOR/EMBALAGEM'], peso_total_embalagem, where=peso_total_embalagem!=0, out=np.zeros_like(df['VALOR/EMBALAGEM']))
        df['VALOR/TONELADA'] = df['MÉDIA/KG'] * 1000
        
        for col, default in {'FORNECEDOR': '', 'MARCA': '', 'Volume/m³': 0.0}.items():
            if col not in df.columns:
                df[col] = default
        
        return df

    except Exception as e:
        st.error(f"Ocorreu um erro ao processar o arquivo: {e}")
        return pd.DataFrame()

def calculate_financials_vectorized(df, tempo_meses, juros_anual, habilitar_cambio, cambio_compra, cambio_venda):
    """Aplica ajustes financeiros ao DataFrame de forma vetorizada (mais rápido)."""
    juros_mensal = juros_anual / 12.0 / 100.0
    
    custo_final_kg = df['Custo Final (R$/kg)']
    preco_venda_kg = df['Venda (R$/kg)']
    peso_total_kg = df['Peso Total (kg)']
    
    investimento_total = custo_final_kg * peso_total_kg
    venda_total = preco_venda_kg * peso_total_kg
    lucro_bruto = venda_total - investimento_total
    variacao_cambial = pd.Series(0.0, index=df.index)

    if habilitar_cambio and cambio_compra > 0 and cambio_venda > 0:
        investimento_total = custo_final_kg * cambio_compra * peso_total_kg
        venda_total = preco_venda_kg * cambio_venda * peso_total_kg
        lucro_bruto = (preco_venda_kg * cambio_venda - custo_final_kg * cambio_compra) * peso_total_kg
        variacao_cambial = custo_final_kg * (cambio_venda - cambio_compra) * peso_total_kg
    
    custo_capital = investimento_total * juros_mensal * tempo_meses
    lucro_final = lucro_bruto + variacao_cambial - custo_capital
    margem_final = np.divide(lucro_final, venda_total, where=venda_total!=0, out=np.zeros_like(lucro_final)) * 100

    df['Investimento Total (R$)'] = investimento_total
    df['Venda Total (R$)'] = venda_total
    df['Lucro Bruto (R$)'] = lucro_bruto
    df['Variação Cambial (R$)'] = variacao_cambial
    df['Custo Capital (R$)'] = custo_capital
    df['Lucro Final (R$)'] = lucro_final
    df['Margem Final (%)'] = margem_final
    
    return df

def process_all_scenarios(df_analysis_base, scenarios_data, financial_params):
    """Processa todos os cenários e retorna um DataFrame consolidado com os resultados."""
    all_results_dfs = []
    
    for scenario_name, scenario_data in scenarios_data.items():
        scenario_df = scenario_data['products_df']
        if scenario_df.empty:
            continue
            
        costs = scenario_data["costs"]
        total_scenario_costs = sum(costs.values())
        
        results = pd.merge(
            scenario_df,
            df_analysis_base[['PRODUTO', 'MÉDIA/KG', 'KG da Unidade', 'Volume/m³', 'UNIDADE/EMBALAGEM_NUM']],
            on='PRODUTO', how='left'
        )
        
        results['Custo Base (R$/kg)'] = results['MÉDIA/KG']
        results['Peso Total (kg)'] = results['Qtd. Mín.'] * results['KG da Unidade'] * results['UNIDADE/EMBALAGEM_NUM']
        results['Volume Total (m³)'] = results['Qtd. Mín.'] * results['Volume/m³']
        
        total_weight_in_scenario = results['Peso Total (kg)'].sum()
        cost_per_kg_scenario = np.divide(total_scenario_costs, total_weight_in_scenario) if total_weight_in_scenario else 0
        
        results['Custos do Cenário (R$)'] = total_scenario_costs
        results['Custo do Cenário por kg'] = cost_per_kg_scenario
        results['Custo Final (R$/kg)'] = results['Custo Base (R$/kg)'] + cost_per_kg_scenario
        
        results_final = calculate_financials_vectorized(results, **financial_params)
        results_final['Cenário'] = scenario_name
        all_results_dfs.append(results_final)
        
    if not all_results_dfs:
        return pd.DataFrame()
        
    consolidated_df = pd.concat(all_results_dfs, ignore_index=True)
    consolidated_df = pd.merge(consolidated_df, df_analysis_base[['PRODUTO', 'FORNECEDOR', 'MARCA']], on='PRODUTO', how='left')
    return consolidated_df

# --- Funções de Plotagem ---

def plot_summary_chart(summary_df):
    """Gera o gráfico de barras de Lucro Final por Cenário."""
    fig = go.Figure(data=[
        go.Bar(
            name='Lucro Final',
            x=summary_df['Cenário'],
            y=summary_df['Lucro Final (R$)'],
            text=summary_df['Lucro Final (R$)'].apply(lambda x: format_brazilian(x, prefix='')),
            textposition='auto'
        )
    ])
    fig.update_layout(
        title_text='<b>Lucro Final Total por Cenário de Mercado</b>',
        xaxis_title="Cenário",
        yaxis_title="Lucro Final Total (R$)",
        uniformtext_minsize=8, 
        uniformtext_mode='hide'
    )
    return fig

def plot_projection_chart(df_projecao, taxa_juros_anual):
    """Gera o gráfico de linhas com a projeção da margem ao longo do tempo."""
    fig = go.Figure()
    tempos_arr = np.arange(1, 25)
    taxa_juros_mensal = taxa_juros_anual / 12.0 / 100.0

    if not df_projecao.empty:
        lucro_antes_capital = (df_projecao['Lucro Bruto (R$)'] + df_projecao['Variação Cambial (R$)']).values
        investimento_total = df_projecao['Investimento Total (R$)'].values
        venda_total = df_projecao['Venda Total (R$)'].values
        
        custo_capital_proj = investimento_total[:, np.newaxis] * taxa_juros_mensal * tempos_arr[np.newaxis, :]
        lucro_final_proj = lucro_antes_capital[:, np.newaxis] - custo_capital_proj
        margens_proj = np.divide(lucro_final_proj, venda_total[:, np.newaxis], where=venda_total[:, np.newaxis]!=0, out=np.zeros_like(lucro_final_proj)) * 100
        
        df_projecao_reset = df_projecao.reset_index(drop=True)

        for i, row in df_projecao_reset.iterrows():
            label = f"{row['PRODUTO']} ({row['Cenário']})"
            fig.add_trace(go.Scatter(x=tempos_arr, y=margens_proj[i], mode='lines+markers', name=label))

            
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.add_hline(y=taxa_juros_anual, line_dash="dash", line_color="red", annotation_text=f"Taxa de Juros Anual ({taxa_juros_anual}%)")
    fig.update_layout(
        title_text='<b>Projeção da Margem Final vs. Tempo de Estoque</b>',
        xaxis_title="Tempo de Estoque (Meses)",
        yaxis_title="Margem Líquida Final (%)",
        height=500
    )
    return fig

def plot_commodity_trends(df):
    """Gera gráficos de linha para as tendências de C. Futuro, Prêmio e Dólar."""
    st.markdown("---")
    st.subheader("Visualização da Perspectiva de Preços")

    col1, col2 = st.columns(2)

    with col1:
        # Cria a figura com um eixo Y secundário
        fig_futuro = make_subplots(specs=[[{"secondary_y": True}]])

        # Adiciona o C. Futuro ao eixo Y primário (esquerda)
        fig_futuro.add_trace(go.Scatter(
            x=df['Mês'],
            y=df['C. Futuro'],
            mode='lines+markers',
            name='C. Futuro'
        ), secondary_y=False)

        # Adiciona o Prêmio ao eixo Y secundário (direita)
        fig_futuro.add_trace(go.Scatter(
            x=df['Mês'],
            y=df['Prêmio'],
            mode='lines+markers',
            name='Prêmio'
        ), secondary_y=True)

        # Atualiza os títulos e o layout geral
        fig_futuro.update_layout(
            title_text='<b>Curva de Preço Futuro e Prêmio</b>',
            xaxis_title="Mês",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        # Define os títulos para cada eixo Y
        fig_futuro.update_yaxes(title_text="<b>C. Futuro (cents/bushel)</b>", secondary_y=False)
        fig_futuro.update_yaxes(title_text="<b>Prêmio (cents/bushel)</b>", secondary_y=True)
        
        st.plotly_chart(fig_futuro, use_container_width=True)


    with col2:
        fig_dolar = go.Figure()
        fig_dolar.add_trace(go.Scatter(
            x=df['Mês'],
            y=df['Dólar'],
            mode='lines+markers',
            name='Dólar',
            line=dict(color='green')
        ))
        fig_dolar.update_layout(
            title_text='<b>Curva do Dólar</b>',
            xaxis_title="Mês",
            yaxis_title="Taxa de Câmbio (R$)"
        )
        st.plotly_chart(fig_dolar, use_container_width=True)

# --- Novas Funções para Ferramentas de Commodities ---

def render_monthly_pricing_calculator():
    """Renderiza a calculadora de formação de preços mensal em uma única tabela interativa."""
    st.subheader("Formação de Preços Mensal")
    
    commodity = st.selectbox("Selecione a Commodity", options=["Soja", "Milho"], key="comm_select")
    bushel_kg = COMMODITY_FACTORS[commodity]["bushel_kg"]
    saca_kg = COMMODITY_FACTORS["Saca"]["saca_kg"]
    
    st.markdown(f"**Fatores de Conversão para {commodity}:** `1 Bushel = {bushel_kg:.4f} kg` | **Fator Saca:** `1 Saca = {saca_kg} kg`")
    
    col1, col2 = st.columns(2)
    with col1:
        fobbing = st.number_input("Fobbing (R$/tonelada)", value=45.0, step=1.0, format="%.2f", key="fobbing")
    with col2:
        rete_domestic = st.number_input("Rete Domestic EXW (R$/tonelada)", value=520.0, step=10.0, format="%.2f", key="rete_domestic")

    session_key = f"monthly_data_{commodity}"
    if session_key not in st.session_state:
        now = datetime.datetime.now()
        months = [(now + relativedelta(months=i)).strftime('%B/%Y').capitalize() for i in range(12)]
        st.session_state[session_key] = pd.DataFrame({
            "Mês": months,
            "C. Futuro": [1000.0] * 12,
            "Prêmio": [150.0] * 12,
            "Dólar": [5.10] * 12
        })

    input_df = st.session_state[session_key]
    
    # Realiza os cálculos para criar o dataframe completo
    calc_df = input_df.copy()
    calc_df['FOB (CS/BU)'] = calc_df['C. Futuro'] + calc_df['Prêmio']
    bushels_por_ton = 1000 / bushel_kg
    calc_df['FOB (US$/T)'] = (calc_df['FOB (CS/BU)'] / 100) * bushels_por_ton
    calc_df['FOB (R$/T)'] = calc_df['FOB (US$/T)'] * calc_df['Dólar']
    calc_df['FAS (SOBRE RODAS)'] = calc_df['FOB (R$/T)'] - fobbing
    calc_df['FOB (FAZENDA)'] = calc_df['FAS (SOBRE RODAS)'] - rete_domestic
    calc_df['PPE (R$/SACA)'] = calc_df['FOB (FAZENDA)'] / (1000 / saca_kg)
    
    st.markdown("##### Edite as colunas destacadas para recalcular os preços automaticamente:")

    disabled_columns = [col for col in calc_df.columns if col not in ["C. Futuro", "Prêmio", "Dólar"]]

    edited_df = st.data_editor(
        calc_df,
        disabled=disabled_columns,
        key=f"editor_{session_key}",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "C. Futuro": st.column_config.NumberColumn(format="%.2f"),
            "Prêmio": st.column_config.NumberColumn(format="%.2f"),
            "Dólar": st.column_config.NumberColumn(format="%.2f"),
            "FOB (CS/BU)": st.column_config.NumberColumn(format="%.2f"),
            "FOB (US$/T)": st.column_config.NumberColumn(format="$%.2f"),
            "FOB (R$/T)": st.column_config.NumberColumn(format="R$%.2f"),
            "FAS (SOBRE RODAS)": st.column_config.NumberColumn(format="R$%.2f"),
            "FOB (FAZENDA)": st.column_config.NumberColumn(format="R$%.2f"),
            "PPE (R$/SACA)": st.column_config.NumberColumn(format="R$%.2f"),
        }
    )
    
    plot_commodity_trends(edited_df)

    # Extrai apenas as colunas de input do dataframe editado
    new_input_df = edited_df[["Mês", "C. Futuro", "Prêmio", "Dólar"]]

    # Se o usuário fez uma alteração, atualiza o estado e executa novamente para recalcular
    if not new_input_df.equals(input_df):
        st.session_state[session_key] = new_input_df
        st.rerun()


def render_unit_converter():
    """Renderiza um conversor de unidades para commodities."""
    st.subheader("Conversor de Unidades")
    
    units = ["Tonelada", "KG", "Saca", "Libra", "Bushel (Soja)", "Bushel (Milho)"]
    
    col1, col2, col3 = st.columns([2,1,2])
    
    with col1:
        from_unit = st.selectbox("De:", units, key="from_u")
        value = st.number_input("Valor", value=1.0, step=1.0, min_value=0.0)

    with col2:
        st.markdown("# ") # Spacer
        st.markdown("<h1 style='text-align: center; margin-top: 15px;'>→</h1>", unsafe_allow_html=True)
        
    with col3:
        to_unit = st.selectbox("Para:", units, key="to_u", index=1)
        
    # Fator de conversão para KG
    def to_kg(val, unit_name):
        if unit_name == "Tonelada": return val * 1000
        if unit_name == "KG": return val
        if unit_name == "Saca": return val * COMMODITY_FACTORS["Saca"]["saca_kg"]
        if unit_name == "Libra": return val * COMMODITY_FACTORS["Soja"]["libra_kg"]
        if unit_name == "Bushel (Soja)": return val * COMMODITY_FACTORS["Soja"]["bushel_kg"]
        if unit_name == "Bushel (Milho)": return val * COMMODITY_FACTORS["Milho"]["bushel_kg"]
        return 0

    # Fator de conversão de KG
    def from_kg(val_kg, unit_name):
        if unit_name == "Tonelada": return val_kg / 1000
        if unit_name == "KG": return val_kg
        if unit_name == "Saca": return val_kg / COMMODITY_FACTORS["Saca"]["saca_kg"]
        if unit_name == "Libra": return val_kg / COMMODITY_FACTORS["Soja"]["libra_kg"]
        if unit_name == "Bushel (Soja)": return val_kg / COMMODITY_FACTORS["Soja"]["bushel_kg"]
        if unit_name == "Bushel (Milho)": return val_kg / COMMODITY_FACTORS["Milho"]["bushel_kg"]
        return 0

    value_in_kg = to_kg(value, from_unit)
    result = from_kg(value_in_kg, to_unit)
    
    st.markdown(f"<h3 style='text-align: center; color: green;'>Resultado: {result:,.4f} {to_unit}</h3>", unsafe_allow_html=True)

# --- Interface Principal do Streamlit ---

def main():
    # Adiciona CSS para aumentar a fonte nas tabelas
    st.markdown("""
        <style>
            div[data-testid="stDataFrame"] table, 
            div[data-testid="stDataEditor"] table {
                font-size: 18px;
            }
        </style>
    """, unsafe_allow_html=True)

    st.title("Dashboard de Viabilidade de Produtos e Mercados")

    # --- Inicialização do Estado da Sessão ---
    if 'df_base' not in st.session_state: st.session_state.df_base = pd.DataFrame()
    if 'scenarios_data' not in st.session_state: st.session_state.scenarios_data = {}
    if 'current_file_name' not in st.session_state: st.session_state.current_file_name = None
    if 'results_df' not in st.session_state: st.session_state.results_df = pd.DataFrame()
    if 'summary_df' not in st.session_state: st.session_state.summary_df = pd.DataFrame()


    tab_analise, tab_ferramentas = st.tabs([
        "Análise de Viabilidade",
        "Ferramentas de Commodities"
    ])

    with tab_analise:
        # --- ETAPA 1: CARREGAR E EDITAR DADOS ---
        st.subheader("1. Carregue e Edite os Dados dos Produtos")
        
        with st.expander("Clique para ver o formato da planilha de exemplo"):
            st.dataframe(pd.DataFrame({
                "PRODUTO": ["MEL 1.4 KG", "MEL SACHÊ 500G"], "UNIDADE/EMBALAGEM": ["12 UNIDADES", "20 UNIDADES"],
                "VALOR UNITÁRIO": ["R$ 30,94", "R$ 5,10"], "VALOR/EMBALAGEM": ["R$ 371,28", "R$ 102,00"]
            }), use_container_width=True, hide_index=True)

        uploaded_file = st.file_uploader("Escolha um arquivo Excel (.xlsx ou .xls)", type=['xlsx', 'xls'])

        if uploaded_file:
            if st.session_state.current_file_name != uploaded_file.name:
                st.session_state.df_base = load_and_process_data(uploaded_file)
                st.session_state.current_file_name = uploaded_file.name
                st.session_state.scenarios_data = {}
                st.session_state.results_df = pd.DataFrame()
                st.session_state.summary_df = pd.DataFrame()
        elif not uploaded_file:
             st.info("Aguardando o carregamento de um arquivo Excel para iniciar a análise.")

        if not st.session_state.df_base.empty:
            st.markdown("**Dados dos Produtos Carregados**")
            st.markdown("Confira os dados carregados. Você pode adicionar/remover produtos e editar o **Fornecedor**, **Marca** e **Volume/m³**.")
            
            edited_df = st.data_editor(st.session_state.df_base,
                disabled=[col for col in st.session_state.df_base.columns if col not in ['FORNECEDOR', 'MARCA', 'Volume/m³']],
                key="main_editor", num_rows="dynamic", use_container_width=True)
            if not edited_df.equals(st.session_state.df_base):
                st.session_state.df_base = edited_df
                st.rerun()

        st.divider()

        # --- ETAPA 2: CENÁRIOS E SIMULAÇÃO ---
        df_analysis_base = st.session_state.df_base.copy()
        if not df_analysis_base.empty:
            st.subheader("2. Configure os Cenários de Simulação")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Ajustes Financeiros Globais**")
                tempo_estoque_meses = st.slider("Tempo de Estoque (Meses)", 1, 24, 1, 1)
                taxa_juros_anual = st.slider("Taxa de Juros Anual (%)", 0.0, 50.0, 12.0, 0.5)
            with col2:
                st.markdown("**Ajustes de Câmbio**")
                habilitar_cambio = st.checkbox("Habilitar Análise Cambial")
                cambio_compra = st.number_input("Taxa de Câmbio (Compra)", min_value=0.01, value=5.0, step=0.01, disabled=not habilitar_cambio)
                cambio_venda = st.number_input("Taxa de Câmbio (Venda)", min_value=0.01, value=5.1, step=0.01, disabled=not habilitar_cambio)
            
            st.markdown("**Cenários de Mercado**")
            with st.form("new_scenario_form"):
                new_scenario_name = st.text_input("Nome do Novo Cenário (ex: E-commerce SP)")
                if st.form_submit_button("Adicionar Cenário"):
                    if new_scenario_name and new_scenario_name not in st.session_state.scenarios_data:
                        st.session_state.scenarios_data[new_scenario_name] = {
                            "costs": {"Logística (R$)": 0.0, "Impostos (R$)": 0.0, "Aduaneiros (R$)": 0.0, "Outros Custos (R$)": 0.0},
                            "products_df": pd.DataFrame(columns=["PRODUTO", "Qtd. Mín.", "Venda (R$/kg)"])}
                        st.rerun()
                    else: st.warning(f"O cenário '{new_scenario_name}' já existe ou o nome está em branco.")
            
            scenarios_to_delete = []
            for scenario_name in list(st.session_state.scenarios_data.keys()):
                with st.expander(f"Cenário: {scenario_name}", expanded=True):
                    scenario_data = st.session_state.scenarios_data[scenario_name]
                    st.markdown(f"**Custos para o cenário '{scenario_name}'**")
                    costs = scenario_data["costs"]
                    cost_cols = st.columns(4)
                    costs["Logística (R$)"] = cost_cols[0].number_input("Logística", value=costs["Logística (R$)"], key=f"log_{scenario_name}", min_value=0.0, format="%.2f")
                    costs["Impostos (R$)"] = cost_cols[1].number_input("Impostos", value=costs["Impostos (R$)"], key=f"imp_{scenario_name}", min_value=0.0, format="%.2f")
                    costs["Aduaneiros (R$)"] = cost_cols[2].number_input("Aduaneiros", value=costs["Aduaneiros (R$)"], key=f"adu_{scenario_name}", min_value=0.0, format="%.2f")
                    costs["Outros Custos (R$)"] = cost_cols[3].number_input("Outros", value=costs["Outros Custos (R$)"], key=f"out_{scenario_name}", min_value=0.0, format="%.2f")
                    st.markdown("---")
                    all_products = list(df_analysis_base['PRODUTO'].unique())
                    products_in_scenario = list(scenario_data['products_df']['PRODUTO'])
                    selected_products = st.multiselect("Selecione os produtos", options=all_products, default=products_in_scenario, key=f"mselect_{scenario_name}")
                    current_df = scenario_data['products_df']
                    new_df = pd.DataFrame(
                        [row for _, row in current_df.iterrows() if row['PRODUTO'] in selected_products] + 
                        [{"PRODUTO": p, "Qtd. Mín.": 1, "Venda (R$/kg)": 0.0} for p in selected_products if p not in products_in_scenario],
                        columns=["PRODUTO", "Qtd. Mín.", "Venda (R$/kg)"])
                    if not new_df.equals(current_df):
                        st.session_state.scenarios_data[scenario_name]['products_df'] = new_df
                        st.rerun()
                    if not new_df.empty:
                        st.markdown(f"**Dados dos produtos para o cenário '{scenario_name}'**")
                        edited_scenario_df = st.data_editor(new_df, disabled=["PRODUTO"], key=f"editor_{scenario_name}",
                            num_rows="fixed", use_container_width=True)
                        if not edited_scenario_df.equals(new_df):
                            st.session_state.scenarios_data[scenario_name]['products_df'] = edited_scenario_df
                            st.rerun()
                    if st.button(f"Remover Cenário '{scenario_name}'", key=f"del_{scenario_name}"):
                        scenarios_to_delete.append(scenario_name)

            if scenarios_to_delete:
                for name in scenarios_to_delete: del st.session_state.scenarios_data[name]
                st.rerun()
            
            st.divider()
            
            if st.button("Analisar Cenários e Gerar Resultados", type="primary", use_container_width=True):
                financial_params = {"tempo_meses": tempo_estoque_meses, "juros_anual": taxa_juros_anual,
                                    "habilitar_cambio": habilitar_cambio, "cambio_compra": cambio_compra, "cambio_venda": cambio_venda}
                
                with st.spinner("Calculando resultados..."):
                    consolidated_df = process_all_scenarios(df_analysis_base, st.session_state.scenarios_data, financial_params)
                    
                    if not consolidated_df.empty:
                        st.session_state.results_df = consolidated_df
                        summary = consolidated_df.groupby('Cenário').agg({
                            'Investimento Total (R$)': 'sum',
                            'Venda Total (R$)': 'sum',
                            'Lucro Bruto (R$)': 'sum',
                            'Variação Cambial (R$)': 'sum',
                            'Custo Capital (R$)': 'sum',
                            'Lucro Final (R$)': 'sum',
                            'Custos do Cenário (R$)': 'first'
                        }).reset_index()
                        lucro = summary['Lucro Final (R$)']
                        venda = summary['Venda Total (R$)']
                        out_array = np.zeros(lucro.shape, dtype=float)
                        summary['Margem Final (%)'] = np.divide(lucro, venda, where=venda!=0, out=out_array) * 100
                        st.session_state.summary_df = summary
                        st.session_state.taxa_juros_anual_calculada = taxa_juros_anual
                        st.success("Resultados calculados com sucesso!")
                    else:
                        st.warning("Nenhum cenário com produtos foi configurado para análise.")
            
            st.divider()

        # --- ETAPA 3: RESULTADOS CONSOLIDADOS ---
        consolidated_df = st.session_state.results_df
        scenario_summary = st.session_state.summary_df
        
        if not consolidated_df.empty:
            st.subheader("3. Resultados Consolidados da Simulação")
            st.markdown("**Análise Detalhada por Produto**")
            
            df_display_details = consolidated_df.copy()
            
            detail_formatter = {
                "Qtd. Mín.": "{:,.0f}", "Venda (R$/kg)": "R$ {:,.2f}",
                "MÉDIA/KG": "R$ {:,.2f}", "KG da Unidade": "{:,.3f} kg",
                "Volume/m³": "{:,.4f} m³", "UNIDADE/EMBALAGEM_NUM": "{:,.0f}",
                "Custo Base (R$/kg)": "R$ {:,.2f}", "Peso Total (kg)": "{:,.2f} kg",
                "Volume Total (m³)": "{:,.3f} m³", "Custos do Cenário (R$)": "R$ {:,.2f}",
                "Custo do Cenário por kg": "R$ {:,.4f}", "Custo Final (R$/kg)": "R$ {:,.2f}",
                "Investimento Total (R$)": "R$ {:,.2f}", "Venda Total (R$)": "R$ {:,.2f}",
                "Lucro Bruto (R$)": "R$ {:,.2f}", "Variação Cambial (R$)": "R$ {:,.2f}",
                "Custo Capital (R$)": "R$ {:,.2f}", "Lucro Final (R$)": "R$ {:,.2f}",
                "Margem Final (%)": "{:,.2f}%"
            }
            
            st.dataframe(df_display_details.style.format(detail_formatter).applymap(
                lambda v: 'color: red;' if isinstance(v, (int, float)) and v < 0 else '', 
                subset=['Lucro Bruto (R$)', 'Variação Cambial (R$)', 'Lucro Final (R$)', 'Margem Final (%)']
            ), use_container_width=True)

            st.markdown("**Resumo por Cenário**")

            summary_formatter = {
                "Investimento Total (R$)": "R$ {:,.2f}", "Venda Total (R$)": "R$ {:,.2f}",
                "Lucro Bruto (R$)": "R$ {:,.2f}", "Variação Cambial (R$)": "R$ {:,.2f}",
                "Custo Capital (R$)": "R$ {:,.2f}", "Lucro Final (R$)": "R$ {:,.2f}",
                "Custos do Cenário (R$)": "R$ {:,.2f}", "Margem Final (%)": "{:,.2f}%"
            }

            st.dataframe(scenario_summary.style.format(formatter=summary_formatter).applymap(
                lambda v: 'color: red;' if isinstance(v, (int, float)) and v < 0 else '', 
                subset=['Lucro Bruto (R$)', 'Variação Cambial (R$)', 'Lucro Final (R$)', 'Margem Final (%)']
            ), use_container_width=True, hide_index=True)

            st.plotly_chart(plot_summary_chart(scenario_summary), use_container_width=True)
            taxa_juros_plot = st.session_state.get('taxa_juros_anual_calculada', 12.0)
            st.plotly_chart(plot_projection_chart(consolidated_df, taxa_juros_plot), use_container_width=True)
        elif st.session_state.df_base.empty:
            pass 
        else:
            st.info("Clique em 'Analisar Cenários e Gerar Resultados' acima para visualizar a análise.")


    with tab_ferramentas:
        st.header("Ferramentas de Análise para Commodities")
        render_monthly_pricing_calculator()
        st.divider()
        render_unit_converter()

if __name__ == "__main__":
    main()