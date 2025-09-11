import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import re
import numpy as np

# Configurar o layout do Streamlit
st.set_page_config(layout="wide")

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
        column_mapping = {
            'CAIXA': 'UNIDADE/EMBALAGEM',
            'VALOR UNITÁRIO': 'VALOR UNITÁRIO',
            'VALOR CAIXA': 'VALOR/EMBALAGEM'
        }
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

        essential_columns = {
            'FORNECEDOR': '', 'MARCA': '',
            'QUANTIDADE MÍNIMA (Embalagens)': 1.0, 'PREÇO DE VENDA': 0.0, 
            'Logística (R$)': 0.0, 'Impostos (R$)': 0.0, 'Aduaneiros (R$)': 0.0, 
            'Outros Custos (R$)': 0.0, 'Volume/m³': 0.0
        }
        for col, default_value in essential_columns.items():
            if col not in df.columns:
                df[col] = default_value
        return df
    except Exception as e:
        st.error(f"Ocorreu um erro ao processar o arquivo: {e}")
        return pd.DataFrame()

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
    st.info("Aguardando o carregamento de um arquivo Excel para iniciar a análise.")
    if 'df_edited' in st.session_state:
        st.session_state.clear()
else:
    if 'df_edited' not in st.session_state or st.session_state.get('current_file_name') != uploaded_file.name:
        st.session_state.df_edited = load_data(uploaded_file)
        st.session_state.current_file_name = uploaded_file.name
        st.session_state.market_scenarios = pd.DataFrame(columns=[
            "Produto", "Mercado Alvo", "Qtd. Mín.", "Venda (R$/kg)", 
            "Logística Add. (R$)", "Impostos Add. (R$)", "Aduaneiros Add. (R$)", "Outros Custos Add. (R$)", "Volume/m³"
        ])

if 'df_edited' in st.session_state and not st.session_state.df_edited.empty:
    df_base = st.session_state.df_edited

    # --- Seção 2: Edição Principal ---
    st.subheader("2. Edite os custos e o preço de venda base")
    
    st.markdown("##### Opcional: Definir Preço de Venda por Margem de Lucro")
    col1, col2 = st.columns([1, 2])
    with col1:
        target_margin = st.number_input(
            label="Margem de Lucro Desejada (%)",
            min_value=0.0, value=None, step=1.0, placeholder="Ex: 30",
            help="Calcula o preço de venda para todos os itens com base no custo de compra e na margem desejada."
        )
    with col2:
        st.write("")
        st.write("")
        if st.button("Aplicar Margem a Todos os Itens"):
            if target_margin is not None and target_margin > 0:
                df_to_update = df_base.copy()
                custo_base_kg = pd.to_numeric(df_to_update['MÉDIA/KG'], errors='coerce').fillna(0)
                margem_decimal = target_margin / 100.0
                df_to_update['PREÇO DE VENDA'] = custo_base_kg / (1 - margem_decimal) if margem_decimal < 1 else custo_base_kg * 100
                st.session_state.df_edited = df_to_update
                st.rerun()
            else:
                st.warning("Por favor, insira um valor válido para a margem de lucro.")
    st.markdown("---")

    # Correção para o bug de edição: detectar mudança e forçar rerun
    edited_data = st.data_editor(df_base, key="main_editor", num_rows="dynamic")
    if not edited_data.equals(st.session_state.df_edited):
        st.session_state.df_edited = edited_data
        st.rerun()

    df_analysis = st.session_state.df_edited.copy()

    # --- Seção 3: Análise Principal ---
    st.subheader("3. Análise de Custos e Lucratividade (Base)")
    
    for col in ['MÉDIA/KG', 'PREÇO DE VENDA', 'QUANTIDADE MÍNIMA (Embalagens)', 'Logística (R$)', 'Impostos (R$)', 'Aduaneiros (R$)', 'Outros Custos (R$)', 'Volume/m³', 'KG da Unidade']:
        if col in df_analysis.columns:
            df_analysis[col] = pd.to_numeric(df_analysis[col], errors='coerce').fillna(0.0)

    df_analysis['Peso Total (kg)'] = df_analysis['QUANTIDADE MÍNIMA (Embalagens)'] * df_analysis['KG da Unidade']
    df_analysis['Custo Total (R$)'] = df_analysis['Logística (R$)'] + df_analysis['Impostos (R$)'] + df_analysis['Aduaneiros (R$)'] + df_analysis['Outros Custos (R$)']
    df_analysis['Custo Total por kg (R$/kg)'] = df_analysis.apply(lambda r: r['Custo Total (R$)'] / r['Peso Total (kg)'] if r['Peso Total (kg)'] > 0 else 0, axis=1)
    df_analysis['Custo Final por kg (R$/kg)'] = df_analysis['MÉDIA/KG'] + df_analysis['Custo Total por kg (R$/kg)']
    df_analysis['Lucro Líquido por kg (R$/kg)'] = df_analysis['PREÇO DE VENDA'] - df_analysis['Custo Final por kg (R$/kg)']
    df_analysis['Margem de Lucro (%)'] = df_analysis.apply(lambda r: (r['Lucro Líquido por kg (R$/kg)'] / r['PREÇO DE VENDA'] * 100) if r['PREÇO DE VENDA'] > 0 else 0, axis=1)
    df_analysis['Valor Total da Venda (R$)'] = df_analysis['PREÇO DE VENDA'] * df_analysis['Peso Total (kg)']
    df_analysis['Lucro Líquido Total (R$)'] = df_analysis['Lucro Líquido por kg (R$/kg)'] * df_analysis['Peso Total (kg)']
    df_analysis['Margem Líquida (%)'] = df_analysis.apply(lambda r: (r['Lucro Líquido Total (R$)'] / r['Valor Total da Venda (R$)'] * 100) if r['Valor Total da Venda (R$)'] > 0 else 0, axis=1)

    st.dataframe(df_analysis[['PRODUTO', 'FORNECEDOR', 'MÉDIA/KG', 'PREÇO DE VENDA', 'Custo Final por kg (R$/kg)', 'Lucro Líquido por kg (R$/kg)', 'Margem de Lucro (%)']], use_container_width=True)
    
    st.subheader("Gráfico de Margem de Lucro (%) por Produto")
    fig_lucro = go.Figure()
    if not df_analysis.empty:
        fig_lucro.add_trace(go.Bar(
            x=df_analysis['PRODUTO'] + " (" + df_analysis['FORNECEDOR'].fillna('') + ")",
            y=df_analysis['Margem de Lucro (%)'],
            text=df_analysis['Margem de Lucro (%)'].round(2).astype(str) + '%', textposition='auto',
            hovertemplate="<b>%{x}</b><br>Margem de Lucro: %{y:.2f}%"
        ))
    fig_lucro.update_layout(xaxis_title="Produto (Fornecedor)", yaxis_title="Margem de Lucro (%)", height=400, xaxis_tickangle=-45)
    st.plotly_chart(fig_lucro, use_container_width=True)

    # --- Seção 4: Análise Financeira (slider de tempo) ---
    st.subheader("4. Análise de Viabilidade Financeira ao Longo do Tempo")
    tempo_estoque_meses = st.slider("Tempo de Estoque (Meses)", 1, 24, 12, 1)
    taxa_juros_anual = st.slider("Taxa de Juros Anual (%)", 0.0, 50.0, 12.0, 0.5)
    taxa_juros_mensal = taxa_juros_anual / 12.0

    # Tabela de Resultados da Análise de Tempo
    st.markdown("**Resultado da Análise de Tempo e Juros**")
    results_data = []
    for index, row in df_analysis.iterrows():
        margem_liquida_inicial = row['Margem Líquida (%)']
        custo_capital = taxa_juros_mensal * tempo_estoque_meses
        margem_liquida_ajustada = margem_liquida_inicial - custo_capital
        
        viavel = "Sim" if margem_liquida_ajustada > taxa_juros_anual else "Não"

        results_data.append({
            "Produto": f"{row['PRODUTO']} ({row['FORNECEDOR']})",
            "Margem Líquida Inicial (%)": margem_liquida_inicial,
            "Margem Líquida Ajustada (%)": margem_liquida_ajustada,
            "Viável?": viavel
        })
    st.dataframe(pd.DataFrame(results_data).round(2), use_container_width=True)
    
    st.subheader("Projeção da Margem Líquida ao Longo do Tempo")
    fig_margem_liquida = go.Figure()
    tempos_estoque_meses_arr = np.arange(1, 25)
    
    df_projecao = df_analysis[df_analysis['Margem Líquida (%)'].notna() & (df_analysis['Margem Líquida (%)'] > 0)]

    if not df_projecao.empty:
        for _, row in df_projecao.iterrows():
            margem_inicial = row['Margem Líquida (%)']
            margens_projetadas = margem_inicial - (taxa_juros_mensal * (tempos_estoque_meses_arr - 1))
            margens_projetadas[margens_projetadas < 0] = 0
            fig_margem_liquida.add_trace(go.Scatter(x=tempos_estoque_meses_arr, y=margens_projetadas, mode='lines+markers', name=f"{row['PRODUTO']} ({row['FORNECEDOR']})"))
    
    fig_margem_liquida.add_hline(y=taxa_juros_anual, line_dash="dash", line_color="red", annotation_text=f"Taxa de Juros Anual ({taxa_juros_anual}%)", annotation_position="bottom right")
    fig_margem_liquida.update_layout(xaxis_title="Tempo de Estoque (Meses)", yaxis_title="Margem Líquida Ajustada (%)", height=500)
    st.plotly_chart(fig_margem_liquida, use_container_width=True)

    # --- Seção 5: Simulação de Mercados Alvo ---
    st.subheader("5. Simulação de Viabilidade por Mercado Alvo")
    st.markdown("Selecione um produto e adicione os **custos adicionais** para diferentes cenários de mercado.")

    product_list = [""] + list(df_analysis['PRODUTO'].unique())
    selected_product = st.selectbox("Selecione um produto para simular", product_list, key="product_selector")

    if selected_product:
        base_product_info = df_analysis[df_analysis['PRODUTO'] == selected_product].iloc[0]
        base_cost_kg = base_product_info['MÉDIA/KG']
        st.info(f"Custo de Compra Base (R$/kg) para '{selected_product}': **R$ {base_cost_kg:.2f}**")

        col1, col2 = st.columns([2, 1])
        with col1:
            new_market_name = st.text_input("Nome do Novo Mercado Alvo (ex: E-commerce SP)", key="new_market_name")
        with col2:
            st.write("")
            if st.button("Adicionar Cenário de Mercado"):
                if new_market_name:
                    new_scenario_data = {
                        "Produto": selected_product, "Mercado Alvo": new_market_name, "Qtd. Mín.": 1, "Venda (R$/kg)": 0.0,
                        "Logística Add. (R$)": 0.0, "Impostos Add. (R$)": 0.0, "Aduaneiros Add. (R$)": 0.0, 
                        "Outros Custos Add. (R$)": 0.0, "Volume/m³": 0.0
                    }
                    new_scenario = pd.DataFrame([new_scenario_data])
                    st.session_state.market_scenarios = pd.concat([st.session_state.market_scenarios, new_scenario], ignore_index=True)
                    st.rerun()
                else:
                    st.warning("Por favor, dê um nome ao mercado alvo.")
        
        scenarios_for_product = pd.DataFrame()
        if not st.session_state.market_scenarios.empty:
            scenarios_for_product = st.session_state.market_scenarios[st.session_state.market_scenarios['Produto'] == selected_product]
        
        if not scenarios_for_product.empty:
            st.markdown(f"**Editando Cenários para: {selected_product}**")
            edited_scenarios = st.data_editor(scenarios_for_product, disabled=["Produto"], key=f"editor_{selected_product}", num_rows="dynamic")
            st.session_state.market_scenarios.update(edited_scenarios)
            
            st.markdown("**Resultados da Simulação**")
            results = edited_scenarios.copy()
            for col in results.columns:
                if col not in ["Produto", "Mercado Alvo"]:
                    results[col] = pd.to_numeric(results[col], errors='coerce').fillna(0)
            
            results['Custo Base (R$/kg)'] = base_cost_kg
            results['Peso Unitário (kg)'] = base_product_info['KG da Unidade']
            results['Peso Total (kg)'] = results['Qtd. Mín.'] * results['Peso Unitário (kg)']
            results['Custo Total Add. (R$)'] = results['Logística Add. (R$)'] + results['Impostos Add. (R$)'] + results['Aduaneiros Add. (R$)'] + results['Outros Custos Add. (R$)']
            results['Custo Add. por kg'] = results.apply(lambda r: r['Custo Total Add. (R$)'] / r['Peso Total (kg)'] if r['Peso Total (kg)'] > 0 else 0, axis=1)
            results['Custo Final (R$/kg)'] = results['Custo Base (R$/kg)'] + results['Custo Add. por kg']
            results['Lucro Líquido (R$/kg)'] = results['Venda (R$/kg)'] - results['Custo Final (R$/kg)']
            results['Lucro Líquido Total (R$)'] = results['Lucro Líquido (R$/kg)'] * results['Peso Total (kg)']
            results['Margem de Lucro (%)'] = results.apply(lambda r: (r['Lucro Líquido (R$/kg)'] / r['Venda (R$/kg)'] * 100) if r['Venda (R$/kg)'] > 0 else 0, axis=1)

            st.dataframe(results[['Mercado Alvo', 'Custo Base (R$/kg)', 'Custo Add. por kg', 'Custo Final (R$/kg)', 'Venda (R$/kg)', 'Lucro Líquido Total (R$)', 'Margem de Lucro (%)']], use_container_width=True)

            fig_sim = go.Figure()
            fig_sim.add_trace(go.Bar(x=results['Mercado Alvo'], y=results['Lucro Líquido Total (R$)'], name='Lucro Líquido Total (R$)'))
            fig_sim.update_layout(title_text=f'Comparativo de Lucro Líquido Total por Mercado para "{selected_product}"', xaxis_title="Mercado Alvo", yaxis_title="Lucro Líquido Total (R$)")
            st.plotly_chart(fig_sim, use_container_width=True)

