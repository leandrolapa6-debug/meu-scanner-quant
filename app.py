import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import pytz
from datetime import datetime

# 1. CONFIGURAÇÃO DA PÁGINA STREAMLIT
st.set_page_config(
    page_title="⚡ QUANT CORE SYSTEM",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Estilização CSS Dark de Alta Performance
st.markdown("""
    <style>
        .main .block-container { padding-top: 1rem; max-width: 100%; }
        .metric-card { background-color: #1e222d; border: 1px solid #2a2e39; padding: 12px; border-radius: 6px; text-align: center; }
        div.stTabs [data-baseweb="tab"] { font-size: 13px !important; font-weight: bold !important; color: #787b86 !important; }
        div.stTabs [data-baseweb="tab"][aria-selected="true"] { color: #f3ba2f !important; border-bottom-color: #f3ba2f !important; }
    </style>
""", unsafe_allow_html=True)

# =========================================================
# 📊 DADOS DO NOSSO INVESTIMENTO ATIVO (RASTREABILIDADE SOL)
# =========================================================
SOL_ENTRADA = 77.54       # Seu preço de entrada real
SOL_STOP_REAL = 74.20     # Seu Stop Loss definido
SOL_ALVO_REAL = 92.50     # Seu Alvo (Take Profit) definido
SOL_ALAVANCAGEM = 10      # Alavancagem utilizada na operação

# =========================================================
# 🎯 PARÂMETROS E MATEMÁTICA PURA
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

@st.cache_resource
def obter_exchange():
    for ex_name in ['binance', 'bybit', 'kraken']:
        try:
            ex_class = getattr(ccxt, ex_name)
            ex = ex_class({'enableRateLimit': True})
            ex.fetch_ohlcv('BTC/USDT', '1d', limit=1)
            return ex
        except: continue
    return ccxt.binance({'enableRateLimit': True})

exchange = obter_exchange()

# Cache de segurança de dados lentos para evitar bloqueio (BAN) de IPs
@st.cache_data(ttl=300)
def obter_dados_macro():
    fng = 50
    try:
        r = requests.get('https://api.alternative.me/fng/', timeout=2).json()
        fng = int(r['data'][0]['value'])
    except: pass
    
    dxy_pct = 0.0
    try:
        dxy = yf.Ticker("DX-Y.NYB")
        hist = dxy.history(period="5d")
        if not hist.empty:
            mean_20 = hist['Close'].mean()
            close_last = hist['Close'].iloc[-1]
            dxy_pct = ((close_last - mean_20) / mean_20) * 100
    except: pass
    return fng, dxy_pct

@st.cache_data(ttl=120)
def obter_dados_historicos(simbolo):
    try:
        b_1w = exchange.fetch_ohlcv(simbolo, '1w', limit=15)
        b_1d = exchange.fetch_ohlcv(simbolo, '1d', limit=60)
        df_w = pd.DataFrame(b_1w, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_d = pd.DataFrame(b_1d, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        for c in ['open', 'high', 'low', 'close', 'volume']:
            df_w[c] = pd.to_numeric(df_w[c])
            df_d[c] = pd.to_numeric(df_d[c])
        return df_w, df_d
    except:
        return pd.DataFrame(), pd.DataFrame()

def detectar_divergencia_rsi(df):
    try:
        if len(df) < 25: return "NENHUMA"
        bloco_rec, bloco_ant = df.iloc[-5:], df.iloc[-25:-5]
        if bloco_rec['low'].min() < bloco_ant['low'].min() and bloco_rec['RSI_14'].min() > bloco_ant['RSI_14'].min() and bloco_rec['RSI_14'].min() < 40: return "ALTA"
        if bloco_rec['high'].max() > bloco_ant['high'].max() and bloco_rec['RSI_14'].max() < bloco_ant['RSI_14'].max() and bloco_rec['RSI_14'].max() > 60: return "BAIXA"
    except: pass
    return "NENHUMA"

def processar_estrategia(simbolo, fng, dxy, modalidade, df_w, df_d):
    try:
        if df_w.empty or df_d.empty: return {}, False
        tf = '4h' if modalidade == "SWING" else '1h'
        
        bars_gat = exchange.fetch_ohlcv(simbolo, tf, limit=100)
        df_gat = pd.DataFrame(bars_gat, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        for col in ['open', 'high', 'low', 'close', 'volume']: 
            df_gat[col] = pd.to_numeric(df_gat[col])
        
        df_d['EMA_50'] = calcular_ema(df_d['close'], 50)
        tendencia_alta = df_d['close'].iloc[-1] > df_d['EMA_50'].iloc[-1]
        res_1w = df_w['high'].iloc[-12:].max()
        
        topo_macro, fundo_macro = df_d['high'].iloc[-30:].max(), df_d['low'].iloc[-30:].min()
        fib_618 = topo_macro - (topo_macro - fundo_macro) * 0.618
        
        df_gat['EMA_50'] = calcular_ema(df_gat['close'], 50)
        df_gat['EMA_200'] = calcular_ema(df_gat['close'], 200)
        df_gat['RSI_14'] = calcular_rsi(df_gat['close'], 14)
        df_gat['vol_sma'] = df_gat['volume'].rolling(window=20).mean()
        
        last = df_gat.iloc[-1]
        preco = last['close']
        
        divergencia = detectar_divergencia_rsi(df_gat)
        bos = preco > df_gat['high'].iloc[-6:-1].max()
        
        spread, corpo = last['high'] - last['low'], abs(last['close'] - last['open'])
        absorcao = spread > 0 and (corpo/spread) < 0.35 and last['volume'] > (df_gat['vol_sma'].iloc[-1] * 1.5)
        
        dados_calc = {
            'preco': preco, 'tendencia_alta': tendencia_alta, 'fib_618': fib_618,
            'ema50': last['EMA_50'], 'ema200': last['EMA_200'], 'rsi': last['RSI_14'],
            'divergencia': divergencia, 'bos': bos, 'absorcao': absorcao,
            'suporte_local': df_gat['low'].rolling(window=15).min().iloc[-1],
            'resistencia_local': df_gat['high'].rolling(window=15).max().iloc[-1],
            'res_1w': res_1w
        }
        
        # Votação Algorítmica Original
        v_alta, v_baixa, testes = 0, 0, 7
        if dados_calc['tendencia_alta']: v_alta += 1
        else: v_baixa += 1
        if preco > dados_calc['ema50']: v_alta += 1
        else: v_baixa += 1
        if preco >= fib_618: v_alta += 1
        else: v_baixa += 1
        if dados_calc['rsi'] < 35: v_alta += 1
        elif dados_calc['rsi'] > 65: v_baixa += 1
        else: testes -= 1
        if divergencia == "ALTA": v_alta += 2; testes += 1
        elif divergencia == "BAIXA": v_baixa += 2; testes += 1
        if absorcao: v_alta += 1
        if bos: v_alta += 1
        if dxy < 0 and fng > 45: v_alta += 1
        elif dxy > 0 and fng < 40: v_baixa += 1
        else: testes -= 1
        
        score_alta = (v_alta / testes) * 100 if testes > 0 else 50.0
        score_baixa = (v_baixa / testes) * 100 if testes > 0 else 50.0
        direcao = "LONG" if score_alta >= score_baixa else "SHORT"
        prob = max(score_alta, score_baixa)
        
        # Gerenciamento de Risco Padrão do Scanner
        if direcao == "LONG":
            stop = min(dados_calc['suporte_local'], dados_calc['ema200'])
            if stop >= preco or pd.isna(stop) or stop == 0: stop = preco * 0.94
            alvo = res_1w if modalidade == "SWING" else dados_calc['resistencia_local']
            if alvo <= preco or pd.isna(alvo): alvo = preco * 1.08 if modalidade == "SWING" else preco * 1.03
        else:
            stop = max(dados_calc['resistencia_local'], dados_calc['ema200'])
            if stop <= preco or pd.isna(stop) or stop == 0: stop = preco * 1.06
            alvo = dados_calc['suporte_local']
            if alvo >= preco or pd.isna(alvo): alvo = preco * 0.92 if modalidade == "SWING" else preco * 0.97
            
        dist_stop = abs(preco - stop) / preco
        teto = 6 if modalidade == "SWING" else 15
        alav = max(1, min(int((1 / (dist_stop + 0.01)) * 0.80) if dist_stop > 0 else 1, teto))
        roi = (abs(alvo - preco) / preco) * alav * 100
        
        return {
            'ATIVO': simbolo, 'PROB.': f"{prob:.0f}%", 'DIR.': direcao,
            'PREÇO': f"${preco:,.3f}", 'ALAV.': f"{alav}x", 'STOP': f"${stop:,.3f}", 
            'ALVO': f"${alvo:,.3f}", 'ROI EST.': f"+{roi:.1f}%", 'AÇÃO': "COPIAR" if prob >= 80 else "AGUARDAR",
            'prob_num': prob, 'dados_brutos': dados_calc
        }, True
    except: return {}, False

# =========================================================
# 🖥️ CONTAINER NATIVO AUTO-ATUALIZÁVEL ("ONLINE")
# =========================================================
# Executa esta função nativamente a cada 15 segundos em background
@st.fragment(run_every=15)
def renderizar_painel_online():
    fng, dxy = obter_dados_macro()
    hora_atual = datetime.now(fuso_br).strftime("%H:%M:%S")

    st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #2a2e39; padding-bottom: 8px; margin-bottom: 15px;">
            <div><h1 style="color: #f3ba2f; margin: 0; font-size: 18px;">⚡ QUANT CORE SYSTEM (V5.3)</h1></div>
            <div><span style="background-color: #2a2e39; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 12px; color: white;">🟢 ONLINE • {hora_atual}</span></div>
        </div>
    """, unsafe_allow_html=True)

    list_day, list_swing = [], []
    dados_solana_atualizados = None

    for ativo in ATIVOS_SCANNER:
        try:
            df_w, df_d = obter_dados_historicos(ativo)
            if df_w.empty or df_d.empty: continue
            
            op_d, ok_d = processar_estrategia(ativo, fng, dxy, "DAY_TRADE", df_w, df_d)
            op_s, ok_s = processar_estrategia(ativo, fng, dxy, "SWING", df_w, df_d)
            
            if ok_d: list_day.append(op_d)
            if ok_s: list_swing.append(op_s)
            if ativo == 'SOL/USDT' and ok_d: 
                dados_solana_atualizados = op_d
        except: continue

    # Classificação e Filtro rígido do Top 5 por probabilidade
    top_day = sorted(list_day, key=lambda x: x['prob_num'], reverse=True)[:5]
    top_swing = sorted(list_swing, key=lambda x: x['prob_num'], reverse=True)[:5]

    df_day_display = pd.DataFrame(top_day).drop(columns=['prob_num', 'dados_brutos'], errors='ignore') if top_day else pd.DataFrame()
    df_swing_display = pd.DataFrame(top_swing).drop(columns=['prob_num', 'dados_brutos'], errors='ignore') if top_swing else pd.DataFrame()

    # ABAS INTERATIVAS
    aba_scanner, aba_solana = st.tabs(["📊 SCANNER COPIAR & COLAR", "🔥 MONITOR SOLANA DETALHADO"])

    with aba_scanner:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<h2 style='color:#2962ff; font-size:13px; border-left:3px solid #2962ff; padding-left:5px; margin-bottom:10px;'>🏆 SWING TRADE (TOP 5 MÉDIO PRAZO)</h2>", unsafe_allow_html=True)
            if not df_swing_display.empty:
                st.dataframe(df_swing_display, use_container_width=True, hide_index=True)
            else:
                st.warning("A carregar...")
                
        with c2:
            st.markdown("<h2 style='color:#e5a93c; font-size:13px; border-left:3px solid #e5a93c; padding-left:5px; margin-bottom:10px;'>⚡ DAY TRADE (TOP 5 CURTO PRAZO)</h2>", unsafe_allow_html=True)
            if not df_day_display.empty:
                st.dataframe(df_day_display, use_container_width=True, hide_index=True)
            else:
                st.warning("A carregar...")

    with aba_solana:
        st.markdown("<h3 style='font-size:14px; margin-bottom:10px;'>🔥 CENTRAL DE RASTREAMENTO: OPERAÇÃO ATIVA SOLANA</h3>", unsafe_allow_html=True)
        
        if dados_solana_atualizados:
            preco_mercado = float(dados_solana_atualizados['PREÇO'].replace('$', '').replace(',', ''))
            
            # Cálculo de Lucro e Perda (P&L) Realizado com Alavancagem do nosso Trade Ativo
            variacao_pct = ((preco_mercado - SOL_ENTRADA) / SOL_ENTRADA) * 100
            pnl_real = variacao_pct * SOL_ALAVANCAGEM
            cor_pnl = "#089981" if pnl_real >= 0 else "#f23645"
            sinal_pnl = "+" if pnl_real >= 0 else ""
            
            # Grid do Investimento
            m1, m2, m3, m4 = st.columns(4)
            with m1: 
                st.markdown(f"<div class='metric-card'><span style='color:#787b86; font-size:11px;'>PREÇO DE ENTRADA</span><br><b style='font-size:18px; color:white;'>${SOL_ENTRADA:.2f}</b></div>", unsafe_allow_html=True)
            with m2: 
                st.markdown(f"<div class='metric-card'><span style='color:#787b86; font-size:11px;'>PREÇO DE MERCADO</span><br><b style='font-size:18px; color:#f3ba2f;'>${preco_mercado:.4f}</b></div>", unsafe_allow_html=True)
            with m3: 
                st.markdown(f"<div class='metric-card'><span style='color:#787b86; font-size:11px;'>P&L ATUAL ({SOL_ALAVANCAGEM}x)</span><br><b style='font-size:18px; color:{cor_pnl};'>{sinal_pnl}{pnl_real:.2f}%</b></div>", unsafe_allow_html=True)
            with m4: 
                st.markdown(f"<div class='metric-card'><span style='color:#787b86; font-size:11px;'>ALVO / STOP DEFINIDOS</span><br><b style='font-size:15px; color:white;'>🎯 ${SOL_ALVO_REAL:.2f} | 🛡️ ${SOL_STOP_REAL:.2f}</b></div>", unsafe_allow_html=True)
            
            # Estatísticas técnicas e fluxo da SOL
            ds = dados_solana_atualizados['dados_brutos']
            st.markdown(f"""
            <div style="background-color: #1e222d; border-radius: 6px; border: 1px solid #2a2e39; padding: 12px; margin-top:15px;">
                <span style="color: white; font-size: 12px; font-weight:bold;">📋 METRICAS DE FLUXO E SUPORTE DINÂMICOS</span><br>
                <span style="color: #b2b5be; font-size: 11px; line-height: 1.6;">
                • <b>RSI do Período:</b> {ds['rsi']:.2f} ({"Sobrevendido 🟢" if ds['rsi'] < 30 else "Sobrecomprado 🔴" if ds['rsi'] > 70 else "Neutro ⚪"})<br>
                • <b>Tendência Macro (1D):</b> {"Compradora (Acima da EMA 50) 🟢" if ds['tendencia_alta'] else "Vendedora (Abaixo da EMA 50) 🔴"}<br>
                • <b>Zona Fibonacci 0.618:</b> Preço está {"Acima da Região Compradora 🟢" if preco_mercado >= ds['fib_618'] else "Abaixo da Região Compradora 🔴"} de <b>${ds['fib_618']:,.2f}</b><br>
                • <b>Divergência de Força:</b> {ds['divergencia']}<br>
                • <b>Volume Institutional (VSA) / Absorção:</b> {"Sinal Crítico de Absorção de Venda! 🟢" if ds['absorcao'] else "Fluxo normal de ordens ⚪"}
                </span>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("Sincronizando dados de fluxo da Solana em tempo real...")

    st.markdown("""
        <div style="font-size: 10px; color: #787b86; text-align: center; border-top: 1px solid #2a2e39; padding-top: 15px; margin-top: 20px;">
            💡 *Atualizações em tempo real a cada 15 segundos sem recarregar a página inteira.*
        </div>
    """, unsafe_allow_html=True)

# Executa a renderização dinâmica
renderizar_painel_online()
