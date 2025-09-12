import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import re
import numpy as np

# Configurar o layout do Streamlit
st.set_page_config(layout="wide")

# Função para formatar números no padrão brasileiro
def format_brazilian(num, prefix="", suffix="", decimals=2):
    if pd.isna(num) or not isinstance(num, (int, float)):
        default_zero = "0"
        if decimals > 0:
            default_zero += "," + "0" * decimals
        return f"{prefix}{default_zero}{suffix}"
        
    format_str = f"{{:,.{decimals}f}}"
    # Formata com separadores padrão e depois inverte para o padrão BR
    formatted_num = format_str.format(num).replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{prefix}{formatted_num}{suffix}"

# Função para extrair peso do nome do produto
def extract_weight_from_name(product_name):
    if not isinstance(product_name, str):
        return 0.0
    match = re.search(r'(\d[\d,.]*)\s*(KG|G)\b', product_name, re.IGNORECASE)
    weight_kg = 0.0
    if match:
        value_str = match.group(1).replace(',', '.')
        unit = match.group(2).upper()
        try:
            value = float(value_str)
            if unit == 'G':
                weight_kg = value / 1000.0
            elif unit == 'KG':
                weight_kg = value
        except ValueError:
            pass
    return weight_kg

# Função para carregar e processar os dados do arquivo Excel
@st.cache_data
def load_data(uploaded_file):
    if uploaded_file is None:
        return pd.DataFrame()
    try:
        xls = pd.ExcelFile(uploaded_file, engine='openpyxl')
        df_preview = pd.read_excel(xls, header=None, nrows=10, engine='openpyxl')
        header_row_index = -1
        for i, row in df_preview.iterrows():
            if 'PRODUTO' in row.astype(str).str.upper().values:
                header_row_index = i
                break
        if header_row_index == -1:
            st.error("Não foi possível encontrar um cabeçalho com a coluna 'PRODUTO'. Verifique o arquivo.")
            return pd.DataFrame()

        df = pd.read_excel(uploaded_file, header=header_row_index, engine='openpyxl')
        
        if 'PRODUTO' not in df.columns:
            st.error("A coluna 'PRODUTO' é obrigatória no arquivo.")
            return pd.DataFrame()
        df['PRODUTO'] = df['PRODUTO'].astype(str)

        df.columns = df.columns.str.strip().str.upper()
        column_mapping = { 'CAIXA': 'UNIDADE/EMBALAGEM', 'VALOR UNITÁRIO': 'VALOR UNITÁRIO', 'VALOR CAIXA': 'VALOR/EMBALAGEM' }
        df.rename(columns=column_mapping, inplace=True)
        df['KG da Unidade'] = df['PRODUTO'].apply(extract_weight_from_name)

        for col in ['VALOR UNITÁRIO', 'VALOR/EMBALAGEM']:
            if col in df.columns:
                s = df[col].astype(str)
                s = s.str.replace('R\\$', '', regex=True).str.strip().str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                df[col] = pd.to_numeric(s, errors='coerce').fillna(0.0)
        
        if 'UNIDADE/EMBALAGEM' in df.columns:
             df['UNIDADE/EMBALAGEM_NUM'] = df['UNIDADE/EMBALAGEM'].astype(str).str.extract(r'(\d+)').astype(float).fillna(1.0)

        if 'VALOR/EMBALAGEM' in df.columns and 'KG da Unidade' in df.columns and 'UNIDADE/EMBALAGEM_NUM' in df.columns:
             peso_total_embalagem = df['KG da Unidade'] * df['UNIDADE/EMBALAGEM_NUM']
             df['MÉDIA/KG'] = df.apply(lambda row: row['VALOR/EMBALAGEM'] / peso_total_embalagem[row.name] if peso_total_embalagem[row.name] > 0 else 0, axis=1)
             df['VALOR/TONELADA'] = df['MÉDIA/KG'] * 1000

        essential_columns = { 'FORNECEDOR': '', 'MARCA': '', 'Volume/m³': 0.0 }
        for col, default_value in essential_columns.items():
            if col not in df.columns:
                df[col] = default_value
        return df
    except Exception as e:
        st.error(f"Ocorreu um erro ao processar o arquivo: {e}")
        return pd.DataFrame()

# Função para aplicar ajustes financeiros a UMA LINHA (row)
def apply_financial_adjustments_to_row(row, tempo_meses, juros_anual, habilitar_cambio, cambio_compra, cambio_venda):
    juros_mensal = juros_anual / 12.0 / 100.0

    custo_final_kg_original = row['Custo Final (R$/kg)']
    preco_venda_kg_original = row['Venda (R$/kg)']
    peso_total_kg = row['Peso Total (kg)']

    if habilitar_cambio and cambio_compra > 0 and cambio_venda > 0:
        investimento_total = custo_final_kg_original * cambio_compra * peso_total_kg
        venda_total = preco_venda_kg_original * cambio_venda * peso_total_kg
        
        lucro_bruto = (preco_venda_kg_original - custo_final_kg_original) * cambio_venda * peso_total_kg
        variacao_cambial = custo_final_kg_original * (cambio_venda - cambio_compra) * peso_total_kg
    else:
        investimento_total = custo_final_kg_original * peso_total_kg
        venda_total = preco_venda_kg_original * peso_total_kg
        lucro_bruto = (preco_venda_kg_original - custo_final_kg_original) * peso_total_kg
        variacao_cambial = 0.0

    custo_capital = investimento_total * juros_mensal * tempo_meses
    lucro_final = lucro_bruto + variacao_cambial - custo_capital
    margem_final = (lucro_final / venda_total * 100) if venda_total > 0 else 0

    row['Investimento Total (R$)'] = investimento_total
    row['Venda Total (R$)'] = venda_total
    row['Lucro Bruto (R$)'] = lucro_bruto
    row['Variação Cambial (R$)'] = variacao_cambial
    row['Custo Capital (R$)'] = custo_capital
    row['Lucro Final (R$)'] = lucro_final
    row['Margem Final (%)'] = margem_final
    
    return row

# --- Início da Interface do Streamlit ---
st.title("Dashboard de Viabilidade de Produtos e Mercados")

# --- Seção 1: Upload ---
st.subheader("1. Carregue seu arquivo de dados")
with st.expander("Clique para ver o formato da planilha de exemplo"):
    st.dataframe(pd.DataFrame({
        "PRODUTO": ["MEL 1.4 KG", "MEL SACHÊ 500G"],
        "CAIXA": ["12 UNIDADES", "20 UNIDADES"],
        "VALOR UNITÁRIO": ["R$ 30,94", "R$ 5,10"],
        "VALOR CAIXA": ["R$ 371,28", "R$ 102,00"]
    }), use_container_width=True, hide_index=True)

uploaded_file = st.file_uploader("Escolha um arquivo Excel (.xlsx ou .xls)", type=['xlsx', 'xls'])

# --- Inicialização do Estado ---
if uploaded_file is None:
    if 'df_edited' in st.session_state:
        st.session_state.clear()
    st.info("Aguardando o carregamento de um arquivo Excel para iniciar a análise.")
else:
    if 'df_edited' not in st.session_state or st.session_state.get('current_file_name') != uploaded_file.name:
        st.session_state.df_edited = load_data(uploaded_file)
        st.session_state.current_file_name = uploaded_file.name
        st.session_state.scenarios_data = {}

if 'df_edited' in st.session_state and not st.session_state.df_edited.empty:
    df_base = st.session_state.df_edited

    # --- Seção 2: Edição Principal ---
    st.subheader("2. Dados dos Produtos Carregados")
    st.markdown("Confira os dados carregados do seu arquivo. Você pode adicionar/remover produtos e editar o **Fornecedor**, **Marca** e **Volume/m³**.")
    
    edited_data = st.data_editor(
        df_base,
        disabled=[col for col in df_base.columns if col not in ['FORNECEDOR', 'MARCA', 'Volume/m³']],
        key="main_editor", 
        num_rows="dynamic"
    )

    if not edited_data.equals(st.session_state.df_edited):
        st.session_state.df_edited = edited_data
        st.rerun()
    df_analysis_base = st.session_state.df_edited.copy()

    # --- Seção 3: Ajustes Financeiros Globais ---
    st.subheader("3. Ajustes Financeiros Globais (Opcional)")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Análise do Custo de Capital**")
        tempo_estoque_meses = st.slider("Tempo de Estoque (Meses)", 1, 24, 1, 1, help="Tempo médio em que o produto ficará em estoque antes da venda.")
        taxa_juros_anual = st.slider("Taxa de Juros Anual (%)", 0.0, 50.0, 12.0, 0.5, help="Taxa de juros anual para calcular o custo do capital empatado.")
    with col2:
        st.markdown("**Análise de Variação Cambial**")
        habilitar_cambio = st.checkbox("Habilitar Análise Cambial", help="Use para produtos com custos e/ou receitas em outra moeda.")
        cambio_compra = st.number_input("Taxa de Câmbio na Compra", min_value=0.01, value=1.0, step=0.01, disabled=not habilitar_cambio)
        cambio_venda = st.number_input("Taxa de Câmbio na Venda", min_value=0.01, value=1.0, step=0.01, disabled=not habilitar_cambio)

    # --- Seção 4: Simulação de Viabilidade por Cenário de Mercado ---
    st.subheader("4. Simulação de Viabilidade por Cenário de Mercado")
    
    new_scenario_name = st.text_input("Nome do Novo Cenário de Mercado (ex: E-commerce SP)", key="new_scenario_name_input")
    if st.button("Adicionar Cenário"):
        if new_scenario_name and new_scenario_name not in st.session_state.scenarios_data:
            st.session_state.scenarios_data[new_scenario_name] = {
                "costs": {"Logística (R$)": 0.0, "Impostos (R$)": 0.0, "Aduaneiros (R$)": 0.0, "Outros Custos (R$)": 0.0},
                "products_df": pd.DataFrame(columns=["PRODUTO", "Qtd. Mín.", "Venda (R$/kg)"])
            }
            st.rerun()
        elif not new_scenario_name:
            st.warning("Por favor, dê um nome ao cenário.")
        else:
            st.warning(f"O cenário '{new_scenario_name}' já existe.")

    all_results_dfs = []
    if 'scenarios_data' in st.session_state and st.session_state.scenarios_data:
        for scenario_name, scenario_data in st.session_state.scenarios_data.items():
            with st.expander(f"Cenário: {scenario_name}", expanded=True):
                st.markdown(f"**Custos para o cenário '{scenario_name}'**")
                costs = scenario_data["costs"]
                cost_cols = st.columns(4)
                costs["Logística (R$)"] = cost_cols[0].number_input("Logística (R$)", value=costs["Logística (R$)"], key=f"log_{scenario_name}")
                costs["Impostos (R$)"] = cost_cols[1].number_input("Impostos (R$)", value=costs["Impostos (R$)"], key=f"imp_{scenario_name}")
                costs["Aduaneiros (R$)"] = cost_cols[2].number_input("Aduaneiros (R$)", value=costs["Aduaneiros (R$)"], key=f"adu_{scenario_name}")
                costs["Outros Custos (R$)"] = cost_cols[3].number_input("Outros Custos (R$)", value=costs["Outros Custos (R$)"], key=f"out_{scenario_name}")
                st.markdown("---")
                all_products = list(df_analysis_base['PRODUTO'].unique())
                if not scenario_data['products_df'].empty:
                    products_in_scenario = list(scenario_data['products_df']['PRODUTO'].unique())
                else:
                    products_in_scenario = []
                valid_defaults = [p for p in products_in_scenario if p in all_products]
                selected_products_for_scenario = st.multiselect("Selecione os produtos para este cenário", options=all_products, default=valid_defaults, key=f"mselect_{scenario_name}")
                if set(selected_products_for_scenario) != set(products_in_scenario):
                    new_products_df = pd.DataFrame()
                    for product_name in selected_products_for_scenario:
                        if product_name in products_in_scenario:
                            new_products_df = pd.concat([new_products_df, scenario_data['products_df'][scenario_data['products_df']['PRODUTO'] == product_name]])
                        else:
                            new_row_data = {"PRODUTO": product_name, "Qtd. Mín.": 1, "Venda (R$/kg)": 0.0}
                            new_products_df = pd.concat([new_products_df, pd.DataFrame([new_row_data])], ignore_index=True)
                    st.session_state.scenarios_data[scenario_name]['products_df'] = new_products_df
                    st.rerun()
                scenario_df = scenario_data['products_df']
                if not scenario_df.empty and set(scenario_df['PRODUTO']).issubset(set(all_products)):
                    st.markdown(f"**Editando dados dos produtos para o cenário '{scenario_name}'**")
                    edited_scenario_df = st.data_editor(scenario_df, disabled=["PRODUTO"], key=f"editor_{scenario_name}", num_rows="dynamic")
                    if not edited_scenario_df.equals(scenario_df):
                        st.session_state.scenarios_data[scenario_name]['products_df'] = edited_scenario_df
                        st.rerun()
                    results = pd.merge(edited_scenario_df, df_analysis_base[['PRODUTO', 'MÉDIA/KG', 'KG da Unidade', 'Volume/m³', 'UNIDADE/EMBALAGEM_NUM']], on='PRODUTO', how='left')
                    results['Custo Base (R$/kg)'] = results['MÉDIA/KG']
                    results['Peso Total (kg)'] = results['Qtd. Mín.'] * results['KG da Unidade'] * results['UNIDADE/EMBALAGEM_NUM']
                    results['Volume Total (m³)'] = results['Qtd. Mín.'] * results['Volume/m³']
                    total_weight_in_scenario = results['Peso Total (kg)'].sum()
                    total_scenario_costs = sum(costs.values())
                    results['Custos do Cenário (R$)'] = total_scenario_costs
                    cost_per_kg_scenario = total_scenario_costs / total_weight_in_scenario if total_weight_in_scenario > 0 else 0
                    results['Custo do Cenário por kg'] = cost_per_kg_scenario
                    results['Custo Final (R$/kg)'] = results['Custo Base (R$/kg)'] + results['Custo do Cenário por kg']
                    results_final = results.apply(apply_financial_adjustments_to_row, axis=1, args=(tempo_estoque_meses, taxa_juros_anual, habilitar_cambio, cambio_compra, cambio_venda))
                    results_final['Cenário'] = scenario_name
                    all_results_dfs.append(results_final)

    # --- Seção 5: Resultados Consolidados ---
    st.subheader("5. Resultados Consolidados da Simulação")

    if all_results_dfs:
        consolidated_df = pd.concat(all_results_dfs, ignore_index=True)
        
        consolidated_df = pd.merge(consolidated_df, df_analysis_base[['PRODUTO', 'FORNECEDOR', 'MARCA']], on='PRODUTO', how='left')
        
        def highlight_negative(val):
            return 'color: red' if isinstance(val, (int, float)) and val < 0 else ''

        st.markdown("**Análise Detalhada por Produto**")
        df_display_details = consolidated_df.rename(columns={ "PRODUTO": "Produto", "FORNECEDOR": "Fornecedor", "MARCA": "Marca", "Peso Total (kg)": "Peso Total Vendido (kg)", "Custo Final com Câmbio (R$/kg)": "Custo Final (R$/kg)", "Venda com Câmbio (R$/kg)": "Venda (R$/kg)" })
        styler_details = df_display_details.style.apply(lambda s: s.map(highlight_negative), subset=['Variação Cambial (R$)', 'Lucro Final (R$)'])
        styler_details.format({
            "Peso Total Vendido (kg)": lambda x: format_brazilian(x, suffix=" kg"), "Custo Final (R$/kg)": lambda x: format_brazilian(x, prefix="R$ "),
            "Venda (R$/kg)": lambda x: format_brazilian(x, prefix="R$ "), "Investimento Total (R$)": lambda x: format_brazilian(x, prefix="R$ "),
            "Venda Total (R$)": lambda x: format_brazilian(x, prefix="R$ "), "Lucro Bruto (R$)": lambda x: format_brazilian(x, prefix="R$ "),
            "Variação Cambial (R$)": lambda x: format_brazilian(x, prefix="R$ "), "Custo Capital (R$)": lambda x: format_brazilian(x, prefix="R$ "),
            "Lucro Final (R$)": lambda x: format_brazilian(x, prefix="R$ "), "Custos do Cenário (R$)": lambda x: format_brazilian(x, prefix="R$ "),
            "Margem Final (%)": lambda x: format_brazilian(x, suffix="%"), "Volume Total (m³)": lambda x: format_brazilian(x, suffix=" m³", decimals=3)
        })
        st.dataframe(styler_details, use_container_width=True)

        st.markdown("**Resumo por Cenário**")
        scenario_summary = consolidated_df.groupby('Cenário').agg({
            'Investimento Total (R$)': 'sum', 'Venda Total (R$)': 'sum', 'Lucro Bruto (R$)': 'sum',
            'Variação Cambial (R$)': 'sum', 'Custo Capital (R$)': 'sum', 'Lucro Final (R$)': 'sum',
            'Custos do Cenário (R$)': 'first'
        }).reset_index()
        scenario_summary['Margem Final (%)'] = (scenario_summary['Lucro Final (R$)'] / scenario_summary['Venda Total (R$)'] * 100).fillna(0)
        
        styler_summary = scenario_summary.style.apply(lambda s: s.map(highlight_negative), subset=['Variação Cambial (R$)', 'Lucro Final (R$)'])
        styler_summary.format({
            "Investimento Total (R$)": lambda x: format_brazilian(x, prefix="R$ "), "Venda Total (R$)": lambda x: format_brazilian(x, prefix="R$ "),
            "Lucro Bruto (R$)": lambda x: format_brazilian(x, prefix="R$ "), "Variação Cambial (R$)": lambda x: format_brazilian(x, prefix="R$ "),
            "Custo Capital (R$)": lambda x: format_brazilian(x, prefix="R$ "), "Lucro Final (R$)": lambda x: format_brazilian(x, prefix="R$ "),
            "Custos do Cenário (R$)": lambda x: format_brazilian(x, prefix="R$ "), "Margem Final (%)": lambda x: format_brazilian(x, suffix="%"),
        })
        st.dataframe(styler_summary, use_container_width=True)


        st.markdown("**Gráfico Comparativo de Lucro Final por Cenário**")
        fig_summary = go.Figure(data=[go.Bar(name='Lucro Final', x=scenario_summary['Cenário'], y=scenario_summary['Lucro Final (R$)'])])
        fig_summary.update_layout(title_text='Lucro Final Total por Cenário de Mercado', xaxis_title="Cenário", yaxis_title="Lucro Final Total (R$)")
        st.plotly_chart(fig_summary, use_container_width=True)

        st.markdown("**Gráfico de Projeção da Margem Final ao Longo do Tempo**")
        fig_projecao = go.Figure()

        tempos_estoque_meses_arr = np.arange(1, 25)
        taxa_juros_mensal = taxa_juros_anual / 12.0 / 100.0

        df_projecao = consolidated_df[consolidated_df['Venda Total (R$)'] > 0]

        if not df_projecao.empty:
            for index, row in df_projecao.iterrows():
                # CORREÇÃO: Usar o lucro que já inclui a variação cambial como base
                lucro_antes_capital = row['Lucro Bruto (R$)']
                investimento_total = row['Investimento Total (R$)']
                venda_total = row['Venda Total (R$)']
                
                margens_projetadas = []
                for mes in tempos_estoque_meses_arr:
                    custo_capital_projetado = investimento_total * taxa_juros_mensal * mes
                    lucro_final_projetado = lucro_antes_capital - custo_capital_projetado
                    margem_projetada = (lucro_final_projetado / venda_total) * 100 if venda_total > 0 else 0
                    margens_projetadas.append(margem_projetada)
                
                fig_projecao.add_trace(go.Scatter(x=tempos_estoque_meses_arr, y=margens_projetadas, mode='lines+markers', name=f"{row['PRODUTO']} ({row['Cenário']})"))

        fig_projecao.add_hline(y=taxa_juros_anual, line_dash="dash", line_color="red", annotation_text=f"Taxa de Juros Anual ({taxa_juros_anual}%)", annotation_position="bottom right")
        fig_projecao.update_layout(title_text='Projeção da Margem Final ao Longo do Tempo', xaxis_title="Tempo de Estoque (Meses)", yaxis_title="Margem Líquida Final (%)", height=500)
        st.plotly_chart(fig_projecao, use_container_width=True)

    else:
        st.info("Adicione e configure cenários para ver os resultados consolidados.")

