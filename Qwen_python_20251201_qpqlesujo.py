# app.py
import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta
import vectorbt as vbt
import pandas_ta as ta
import numpy as np

st.set_page_config(page_title="PST V2 Analyzer", layout="wide")
st.title("📊 Pivot SuperTrend V2 — Backtest Futuros")
st.caption("Baseado na sua estratégia Pine Script. Dados: Yahoo Finance (delayed)")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configurações")
    symbol = st.selectbox("Ativo", ["ES=F", "NQ=F", "RTY=F", "YM=F", "^BVSP"], index=0)
    timeframe = st.selectbox("Timeframe", ["15m", "1h", "1d"], index=0)
    days = st.slider("Dias atrás", 7, 60, 30)
    atr_mult = st.slider("ATR Multiplicador", 1.0, 5.0, 3.0, 0.5)
    rr = st.slider("Risco/Retorno", 1.0, 3.0, 1.5, 0.1)
    run = st.button("▶️ Executar")

def calculate_supertrend(df, period=10, multiplier=3.0):
    hl2 = (df['high'] + df['low']) / 2
    atr = ta.atr(df['high'], df['low'], df['close'], length=period)
    up = hl2 + multiplier * atr
    dn = hl2 - multiplier * atr

    st_line = pd.Series(np.nan, index=df.index)
    trend = pd.Series(True, index=df.index)

    upper = up.copy()
    lower = dn.copy()

    for i in range(1, len(df)):
        if i == 1:
            upper.iat[i] = up.iat[i]
            lower.iat[i] = dn.iat[i]
            st_line.iat[i] = lower.iat[i]
        else:
            upper.iat[i] = up.iat[i] if (up.iat[i] < upper.iat[i-1] or df['close'].iat[i-1] > upper.iat[i-1]) else upper.iat[i-1]
            lower.iat[i] = dn.iat[i] if (dn.iat[i] > lower.iat[i-1] or df['close'].iat[i-1] < lower.iat[i-1]) else lower.iat[i-1]

            if trend.iat[i-1]:
                if df['close'].iat[i] <= lower.iat[i]:
                    trend.iat[i] = False
                    st_line.iat[i] = upper.iat[i]
                else:
                    st_line.iat[i] = max(st_line.iat[i-1], lower.iat[i])
            else:
                if df['close'].iat[i] >= upper.iat[i]:
                    trend.iat[i] = True
                    st_line.iat[i] = lower.iat[i]
                else:
                    st_line.iat[i] = min(st_line.iat[i-1], upper.iat[i])
    return st_line, trend

if run:
    try:
        end = datetime.now()
        start = end - timedelta(days=days + 7)
        data = yf.download(symbol, start=start, end=end, interval=timeframe, progress=False)
        if data.empty:
            st.error("Sem dados. Tente outro ativo ou timeframe.")
            st.stop()
        df = data.rename(columns=str.lower)

        # Indicadores
        df['rsi'] = ta.rsi(df['close'], 14)
        macd = ta.macd(df['close'], 12, 26, 9)
        df['macd'] = macd['MACD_12_26_9']
        df['macd_signal'] = macd['MACDs_12_26_9']
        df['st_line'], df['is_up'] = calculate_supertrend(df, 10, atr_mult)

        # Sinais
        df['rsi_oversold'] = (df['rsi'].shift(1) < 30)
        df['rsi_overbought'] = (df['rsi'].shift(1) > 70)
        df['cross_up'] = (df['close'] > df['st_line']) & (df['close'].shift(1) <= df['st_line'].shift(1))
        df['cross_down'] = (df['close'] < df['st_line']) & (df['close'].shift(1) >= df['st_line'].shift(1))
        df['macd_cross_up'] = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
        df['macd_cross_down'] = (df['macd'] < df['macd_signal']) & (df['macd'].shift(1) >= df['macd_signal'].shift(1))

        df['buy'] = df['cross_up'] & df['rsi_oversold'] & df['macd_cross_up']
        df['sell'] = df['cross_down'] & df['rsi_overbought'] & df['macd_cross_down']

        # Stop & TP
        df['long_sl'] = df['st_line']
        df['long_tp'] = df['close'] + (df['close'] - df['long_sl']) * rr
        df['short_sl'] = df['st_line']
        df['short_tp'] = df['close'] - (df['short_sl'] - df['close']) * rr

        # Filtrar janela
        cutoff = end - timedelta(days=days)
        df = df[df.index >= cutoff]

        # Backtest
        pf_long = vbt.Portfolio.from_signals(
            df['close'], df['buy'], None,
            sl_stop=df['long_sl'], tp_stop=df['long_tp'],
            freq=timeframe, init_cash=10000, fees=0.001
        )
        pf_short = vbt.Portfolio.from_signals(
            df['close'], df['sell'], None,
            sl_stop=df['short_sl'], tp_stop=df['short_tp'],
            freq=timeframe, init_cash=10000, fees=0.001, direction='shortonly'
        )
        pf = pf_long + pf_short

        # Métricas
        stats = pf.stats()
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Lucro", f"${stats['Total Return [$]']:.1f}")
        col2.metric("Win Rate", f"{stats['Win Rate [%]']:.1f}%")
        col3.metric("Profit Factor", f"{stats['Profit Factor']:.2f}")
        col4.metric("Max DD", f"{stats['Max Drawdown [%]']:.1f}%")

        # Gráfico
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Preço'))
        fig.add_trace(go.Scatter(x=df.index, y=df['st_line'], mode='lines', name='SuperTrend', line=dict(color='cyan', width=1)))

        buys = df[df['buy']]
        sells = df[df['sell']]
        fig.add_trace(go.Scatter(x=buys.index, y=buys['low']*0.995, mode='markers', marker=dict(color='green', size=8, symbol='triangle-up'), name='Compra'))
        fig.add_trace(go.Scatter(x=sells.index, y=sells['high']*1.005, mode='markers', marker=dict(color='red', size=8, symbol='triangle-down'), name='Venda'))

        fig.update_layout(height=500, xaxis_rangeslider_visible=False, title=f"{symbol} — {timeframe} — últimos {days} dias")
        st.plotly_chart(fig, use_container_width=True)

        # Tabela
        trades = pf.trades.records_readable
        if not trades.empty:
            trades = trades[['Entry Timestamp', 'Exit Timestamp', 'Direction', 'PnL [$]', 'Return [%]']].sort_values('Entry Timestamp', ascending=False)
            st.dataframe(trades.style.format({'PnL [$]': '${:.2f}', 'Return [%]': '{:.2f}%'}), use_container_width=True)
        else:
            st.info("Nenhuma operação no período.")

    except Exception as e:
        st.error(f"Erro: {e}")

else:
    st.info("👆 Configure e clique em **Executar** para iniciar o backtest.")
    st.markdown("""
    ### 📌 Notas:
    - Dados de futuros são **delayed** pelo Yahoo Finance;
    - Para *WIN$* (B3), use dados próprios via CSV;
    - Recomendado: `ES=F` ou `NQ=F` em `15m` ou `1h`.
    """)