import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import time
import pytz
from datetime import datetime

# 1. CONFIGURAÇÃO DA PÁGINA STREAMLIT
st.set_page_config(
    page_title="⚡ QUANT CORE - MULTI SCANNER",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Estilização CSS profissional para tema Dark de trading
st.markdown("""
    <style>
        .main .block-container { padding-top: 1.5rem; max-width: 1250px; }
        table {
            width: 100% !important;
            border-collapse: collapse !important;
            color: #d1d4dc !important;
            font-size: 12.5px !important;
        }
        th {
            background-color: #1e222d !important;
            color: #787b86 !important;
            font-weight: bold !important;
            text-transform: uppercase !important;
            padding: 10px !important;
            border-bottom: 2px solid #2a2e39 !important;
            font-size: 11px !important;
        }
        td {
            padding: 10px 8px !important;
            border-bottom: 1px solid #2a2e39 !important;
            background-color: #131722 !important;
        }
        tr:hover td {
            background-color: #1e222d !important;
        }
        .metric-card {
            background-color: #1e222d;
            border: 1px solid #2a2e39;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
    </style>
""", unsafe_allow_html=True)

# =========================================================
# 🎯 PARÂMETROS E CÁLCULOS MATEMÁTICOS NATIVOS
# =========================================================
ATIVOS_SCANNER = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'LINK/USDT', 'AVAX/USDT', 'ADA/USDT']
fuso_br = pytz.timezone('America/Sao_Paulo')

def calcular_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def calcular_rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/length, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))

def calcular_bbl(series, length=20, std_dev=2):
    ma = series.rolling(window=length).mean()
    sd = series.rolling(window=length).std()
    return ma - (sd * std_dev)

@st.cache_resource
def obter_exchange():
    for ex_name in ['binance', 'bybit', 'kraken']:
        try:
            ex_class = getattr(ccxt, ex_name)
            ex = ex_class({'enableRateLimit': True})
            ex.fetch_ohlcv('BTC/USDT', '1d', limit=1)
            return ex
        except:
            continue
    return ccxt.binance({'enableRateLimit': True})

exchange = obter_exchange()

def obter_sentimento_midias():
    try:
        r = requests.get('https://api.alternative.me/fng/', timeout=5).json()
        return int(r['data'][0]['value'])
    except: return 50

def avaliar_dxy():
    try:
        dxy = yf.Ticker("DX-Y.NYB")
        hist = dxy.history(period="30d")
        if hist.empty: return 0
        mean_20 = hist['Close'].rolling(window=20).mean().iloc[-1]
        close_last = hist['Close'].iloc[-1]
        return ((close_last - mean_20) / mean_20) * 100
    except: return 0

def detectar_divergencia_rsi(df):
    try:
        if len(df) < 25: return "NENHUMA"
        bloco_recente = df.iloc[-5:]
        bloco_anterior = df.iloc[-25:-5]
        
        low_rec = bloco_recente['low'].min()
        rsi_low_rec = bloco_recente['RSI_14'].min()
        low_ant = bloco_anterior['low'].min()
        rsi_low_ant = bloco_anterior['RSI_14'].min()
        
        high_rec = bloco_recente['high'].max()
        rsi_high_rec = bloco_recente['RSI_14'].max()
        high_ant = bloco_anterior['high'].max()
        rsi_high_ant = bloco_anterior['RSI_14'].max()
        
        if low_rec < low_ant and rsi_low_rec > rsi_low_ant and rsi_low_rec < 40:
            return "ALTA"
        if high_rec > high_ant and rsi_high_rec < rsi_high_ant and rsi_high_rec > 60:
            return "BAIXA"
        return "NENHUMA"
    except:
        return "NENHUMA"

def processar_dados_ativo(simbolo, modalidade):
    try:
        timeframe_gatilho = '4h' if modalidade == "SWING" else '1h'
        bars_1w = exchange.fetch_ohlcv(simbolo, '1w', limit=20)
        bars_1d = exchange.fetch_ohlcv(simbolo, '1d', limit=100)
        bars_gatilho = exchange.fetch_ohlcv(simbolo, timeframe_gatilho, limit=200)
        
        if not bars_1w or not bars_1d or not bars_gatilho:
            return {}, False
            
        df_1w = pd.DataFrame(bars_1w, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_1d = pd.DataFrame(bars_1d, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_gat = pd.DataFrame(bars_gatilho, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        for df in [df_1w, df_1d, df_gat]:
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df_1d['EMA_50'] = calcular_ema(df_1d['close'], 50)
        tendencia_alta = df_1d['close'].iloc[-1] > df_1d['EMA_50'].iloc[-1]
        
        sup_1w = df_1w['low'].iloc[-12:].min()
        res_1w = df_1w['high'].iloc[-12:].max()
        
        topo_macro = df_1d['high'].iloc[-30:].max()
        fundo_macro = df_1d['low'].iloc[-30:].min()
        fib_618 = topo_macro - (topo_macro - fundo_macro) * 0.618
        
        df_gat['EMA_50'] = calcular_ema(df_gat['close'], 50)
        df_gat['EMA_200'] = calcular_ema(df_gat['close'], 200)
        df_gat['RSI_14'] = calcular_rsi(df_gat['close'], 14)
        df_gat['BBL_20_2.0'] = calcular_bbl(df_gat['close'], 20, 2)
        
        df_gat['EMA_50'] = df_gat['EMA_50'].ffill().bfill()
        df_gat['EMA_200'] = df_gat['EMA_200'].ffill().bfill()
        df_gat['RSI_14'] = df_gat['RSI_14'].ffill().bfill()
        df_gat['BBL_20_2.0'] = df_gat['BBL_20_2.0'].ffill().bfill()
        
        df_gat['vol_sma'] = df_gat['volume'].rolling(window=20).mean()
        
        last = df_gat.iloc[-1]
        preco = last['close']
        
        divergencia = detectar_divergencia_rsi(df_gat)
        bos = preco > df_gat['high'].iloc[-6:-1].max()
        
        absorcao = False
        spread = last['high'] - last['low']
        corpo = abs(last['close'] - last['open'])
        vol_sma_last = df_gat['vol_sma'].iloc[-1]
        if spread > 0 and (corpo/spread) < 0.35 and last['volume'] > (vol_sma_last * 1.5 if not pd.isna(vol_sma_last) else 0):
            absorcao = True
            
        return {
            'preco': preco, 'tendencia_alta': tendencia_alta, 'fib_618': fib_618,
            'ema50': last['EMA_50'], 'ema200': last['EMA_200'], 'rsi': last['RSI_14'],
            'rsi_prev': df_gat['RSI_14'].shift(1).iloc[-1] if len(df_gat) > 1 else 50.0,
            'divergencia': divergencia, 'bos': bos, 'absorcao': absorcao,
            'suporte_local': df_gat['low'].rolling(window=15).min().iloc[-1],
            'resistencia_local': df_gat['high'].rolling(window=15).max().iloc[-1],
            'res_1w': res_1w, 'bbl': last['BBL_20_2.0']
        }, True
    except:
        return {}, False

def calcular_score_e_direcao(dados, fng, dxy):
    votos_alta, votos_baixa, testes = 0, 0, 7
    
    if dados['tendencia_alta']: votos_alta += 1
    else: votos_baixa += 1
    
    if dados['preco'] > dados['ema50']: votos_alta += 1
    else: votos_baixa += 1
    
    if dados['preco'] >= dados['fib_618']: votos_alta += 1
    else: votos_baixa += 1
    
    if dados['rsi'] < 35: votos_alta += 1
    elif dados['rsi'] > 65: votos_baixa += 1
    else: testes -= 1
    
    if dados['divergencia'] == "ALTA": votos_alta += 2; testes += 1
    elif dados['divergencia'] == "BAIXA": votos_baixa += 2; testes += 1
    
    if dados['absorcao']: votos_alta += 1
    if dados['bos']: votos_alta += 1
    
    if dxy < 0 and fng > 45: votos_alta += 1
    elif dxy > 0 and fng < 40: votos_baixa += 1
    else: testes -= 1
    
    score_alta = (votos_alta / testes) * 100 if testes > 0 else 50.0
    score_baixa = (votos_baixa / testes) * 100 if testes > 0 else 50.0
    
    direcao = "LONG" if score_alta >= score_baixa else "SHORT"
    probabilidade = max(score_alta, score_baixa)
    
    return probabilidade, direcao

def escanear_mercado(modalidade):
    fng = obter_sentimento_midias()
    dxy = avaliar_dxy()
    oportunidades = []
    
    for ativo in ATIVOS_SCANNER:
        dados, ok = processar_dados_ativo(ativo, modalidade)
        if not ok: continue
        
        prob, direcao = calcular_score_e_direcao(dados, fng, dxy)
        preco = dados['preco']
        
        if direcao == "LONG":
            stop = min(dados['suporte_local'], dados['ema200'])
            if stop >= preco or stop == 0 or pd.isna(stop): stop = preco * 0.94
            alvo = dados['res_1w'] if modalidade == "SWING" else dados['resistencia_local']
            if alvo <= preco or pd.isna(alvo): alvo = preco * 1.08 if modalidade == "SWING" else preco * 1.03
        else:
            stop = max(dados['resistencia_local'], dados['ema200'])
            if stop <= preco or stop == 0 or pd.isna(stop): stop = preco * 1.06
            alvo = dados['suporte_local']
            if alvo >= preco or pd.isna(alvo): alvo = preco * 0.92 if modalidade == "SWING" else preco * 0.97
            
        distancia_stop_pct = abs(preco - stop) / preco
        
        teto_alavancagem = 6 if modalidade == "SWING" else 15
        if distancia_stop_pct > 0:
            alavancagem = int((1 / (distancia_stop_pct + 0.01)) * 0.80)
        else:
            alavancagem = 1
        alavancagem = max(1, min(alavancagem, teto_alavancagem))
        
        roi_estimado = (abs(alvo - preco) / preco) * alavancagem * 100
        
        oportunidades.append({
            'ativo': ativo, 'probabilidade': prob, 'direcao': direcao,
            'preco': preco, 'stop': stop, 'alvo': alvo, 'alavancagem': alavancagem,
            'roi': roi_estimado, 'dados': dados
        })
    
    return sorted(oportunidades, key=lambda x: x['probabilidade'], reverse=True)

def gerar_tabela_html(oportunidades):
    linhas_html = ""
    for op in oportunidades:
        cor_dir = "#089981" if op['direcao'] == "LONG" else "#f23645"
        fundo_dir = "rgba(8, 153, 129, 0.15)" if op['direcao'] == "LONG" else "rgba(242, 54, 69, 0.15)"
        cor_selo = "#089981" if op['probabilidade'] >= 80 else "#787b86"
        fundo_selo = "rgba(8, 153, 129, 0.2)" if op['probabilidade'] >= 80 else "rgba(120, 123, 134, 0.1)"
        selo_texto = "COPIAR" if op['probabilidade'] >= 80 else "AGUARDAR"
        
        linhas_html += f"""
        <tr>
            <td style="font-weight: bold; color: white;">{op['ativo']}</td>
            <td style="text-align: center;">
                <span style="background-color: {fundo_dir}; color: {cor_dir}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 10px;">{op['direcao']}</span>
            </td>
            <td style="text-align: right; font-weight: 500;">${op['preco']:,.4f}</td>
            <td style="text-align: center; color: #f3ba2f; font-weight: bold;">{op['alavancagem']}x</td>
            <td style="text-align: right; color: #f23645; font-weight: 500;">${op['stop']:,.4f}</td>
            <td style="text-align: right; color: #089981; font-weight: 500;">${op['alvo']:,.4f}</td>
            <td style="text-align: right; color: #089981; font-weight: bold;">+{op['roi']:.1f}%</td>
            <td style="text-align: center; font-weight: bold; color: {'#089981' if op['probabilidade'] >= 80 else '#f3ba2f'}">{op['probabilidade']:.0f}%</td>
            <td style="text-align: center;">
                <span style="background-color: {fundo_selo}; color: {cor_selo}; border: 1px solid {cor_selo}; padding: 3px 8px; border-radius: 4px; font-size: 9px; font-weight: bold;">
                    {selo_texto}
                </span>
            </td>
        </tr>
        """
    return linhas_html

# =========================================================
# 🖥️ RENDERIZAÇÃO DA INTERFACE WEB COM BOTÕES (ABAS)
# =========================================================
hora_atual = datetime.now(fuso_br).strftime("%H:%M:%S")

# Cabeçalho Fixo do Dashboard
st.write(f"""
    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #2a2e39; padding-bottom: 12px; margin-bottom: 20px;">
        <div>
            <h1 style="color: #f3ba2f; margin: 0; font-size: 22px; letter-spacing: 0.5px;">⚡ QUANT CORE SYSTEM (V5.0)</h1>
            <p style="margin: 3px 0 0 0; color: #787b86; font-size: 11px;">Scanner unificado e monitoramento avançado pelo celular</p>
        </div>
        <div style="text-align: right;">
            <span style="background-color: #2a2e39; padding: 5px 12px; border-radius: 5px; font-weight: bold; font-size: 12px; color: white;">🇧🇷 {hora_atual}</span>
        </div>
    </div>
""", unsafe_allow_html=True)

# Criação das Abas Interativas (Os botões que você pediu para separar as visões!)
aba_scanner, aba_solana = st.tabs(["📊 SCANNER COPIAR & COLAR", "🔥 MONITOR SOLANA DETALHADO"])

# --- ABA 1: SCANNER MULTI-ATIVOS ---
with aba_scanner:
    oportunidades_swing = escanear_mercado("SWING")
    oportunidades_day = escanear_mercado("DAY_TRADE")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"""
        <div style="background-color: #1e222d; border-radius: 8px; border: 1px solid #2a2e39; padding: 15px;">
            <h2 style="color: #2962ff; font-size: 14px; margin: 0 0 15px 0; border-left: 4px solid #2962ff; padding-left: 8px; text-transform: uppercase; font-weight: bold; letter-spacing: 0.5px;">
                🏆 QUADRO DE SWING TRADE (MÉDIO PRAZO)
            </h2>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th style="text-align: left;">ATIVO</th>
                            <th style="text-align: center;">DIREÇÃO</th>
                            <th style="text-align: right;">ENTRADA</th>
                            <th style="text-align: center;">ALAV.</th>
                            <th style="text-align: right;">STOP</th>
                            <th style="text-align: right;">ALVO</th>
                            <th style="text-align: right;">ROI</th>
                            <th style="text-align: center;">PROB.</th>
                            <th style="text-align: center;">AÇÃO</th>
                        </tr>
                    </thead>
                    <tbody>
                        {gerar_tabela_html(oportunidades_swing)}
                    </tbody>
                </table>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.write(f"""
        <div style="background-color: #1e222d; border-radius: 8px; border: 1px solid #2a2e39; padding: 15px;">
            <h2 style="color: #e5a93c; font-size: 14px; margin: 0 0 15px 0; border-left: 4px solid #e5a93c; padding-left: 8px; text-transform: uppercase; font-weight: bold; letter-spacing: 0.5px;">
                ⚡ QUADRO DE DAY TRADE (CURTO PRAZO)
            </h2>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th style="text-align: left;">ATIVO</th>
                            <th style="text-align: center;">DIREÇÃO</th>
                            <th style="text-align: right;">ENTRADA</th>
                            <th style="text-align: center;">ALAV.</th>
                            <th style="text-align: right;">STOP</th>
                            <th style="text-align: right;">ALVO</th>
                            <th style="text-align: right;">ROI</th>
                            <th style="text-align: center;">PROB.</th>
                            <th style="text-align: center;">AÇÃO</th>
                        </tr>
                    </thead>
                    <tbody>
                        {gerar_tabela_html(oportunidades_day)}
                    </tbody>
                </table>
            </div>
        </div>
        """, unsafe_allow_html=True)

# --- ABA 2: MONITOR ADVANCED SOLANA ---
with aba_solana:
    st.subheader("🔥 Central de Comando Solana (SOL)")
    
    # Processar dados estendidos exclusivamente para Solana
    dados_sol, ok_sol = processar_dados_ativo('SOL/USDT', 'DAY_TRADE')
    
    if ok_sol:
        fng = obter_sentimento_midias()
        dxy = avaliar_dxy()
        prob_sol, dir_sol = calcular_score_e_direcao(dados_sol, fng, dxy)
        
        # Grid de Métricas Principais da SOL
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(f"""<div class='metric-card'>
                <span style='color: #787b86; font-size:12px;'>PREÇO ATUAL SOL</span><br>
                <b style='font-size:22px; color:white;'>${dados_sol['preco']:,.2f}</b>
            </div>""", unsafe_allow_html=True)
        with m2:
            st.markdown(f"""<div class='metric-card'>
                <span style='color: #787b86; font-size:12px;'>FORÇA DO SINAL</span><br>
                <b style='font-size:22px; color:{"#089981" if prob_sol >= 75 else "#f3ba2f"};'>{prob_sol:.0f}% ({dir_sol})</b>
            </div>""", unsafe_allow_html=True)
        with m3:
            st.markdown(f"""<div class='metric-card'>
                <span style='color: #787b86; font-size:12px;'>RSI (14h)</span><br>
                <b style='font-size:22px; color:#d1d4dc;'>{dados_sol['rsi']:.1f}</b>
            </div>""", unsafe_allow_html=True)
        with m4:
            st.markdown(f"""<div class='metric-card'>
                <span style='color: #787b86; font-size:12px;'>DIVERGÊNCIA</span><br>
                <b style='font-size:22px; color:{"#089981" if "ALTA" in dados_sol['divergencia'] else "#f23645"};'>{dados_sol['divergencia']}</b>
            </div>""", unsafe_allow_html=True)
            
        # Detalhes Técnicos e Estruturais
        st.write("")
        st.markdown(f"""
        <div style="background-color: #1e222d; border-radius: 8px; border: 1px solid #2a2e39; padding: 20px;">
            <h3 style="color: white; font-size: 15px; margin-top: 0;">📋 MEMÓRIA DE CÁLCULO E ANÁLISE DE FLUXO (SOL)</h3>
            <ul style="color: #b2b5be; font-size: 13px; line-height: 1.8; padding-left: 20px;">
                <li><b>Tendência de Alta Primária (1D):</b> {"Confirmada acima da EMA50 🟢" if dados_sol['tendencia_alta'] else "Negada abaixo da EMA50 🔴"}</li>
                <li><b>Defesa de Compradores (FIB 0.618):</b> Preço está {"acima 🟢" if dados_sol['preco'] >= dados_sol['fib_618'] else "abaixo 🔴"} do suporte matemático em <b>${dados_sol['fib_618']:,.2f}</b></li>
                <li><b>Volume / VSA (Absorção):</b> {"Anomalia institucional de absorção detectada! 🟢" if dados_sol['absorcao'] else "Sem anomalias de volume identificadas ⚪"}</li>
                <li><b>Quebra de Estrutura (BOS):</b> {"Rompimento de pivô local confirmado (BOS)! 🟢" if dados_sol['bos'] else "Estrutura segue em consolidação local ⚪"}</li>
                <li><b>Alvo Corrente (Take Profit):</b> <b>${dados_sol['res_1w']:,.2f}</b> | <b>Stop Técnico:</b> <b>${dados_sol['suporte_local']:,.2f}</b></li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.warning("Aguardando carregamento de dados da exchange para a Solana...")

# Rodapé Técnico
st.write("""
    <div style="font-size: 10px; color: #787b86; text-align: center; border-top: 1px solid #2a2e39; padding-top: 15px; margin-top: 30px;">
        💡 *Os dados atualizam dinamicamente a cada ciclo. Os botões no topo alternam as visões de forma instantânea.*
  
