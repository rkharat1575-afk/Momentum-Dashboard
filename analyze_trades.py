import pandas as pd

df = pd.read_csv('live_trade_journal.csv', header=None, names=['Entry Time','Direction','Strike','Type','Entry Price','Exit Time','Exit Price','Result','P/L %'], skiprows=1)
df['P/L %'] = pd.to_numeric(df['P/L %'], errors='coerce')
wins = df[df['Result'] == 'TARGET 1 HIT']
losses = df[df['Result'] == 'STOPPED OUT']
total_trades = len(df)
win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0

print(f'Total Trades: {total_trades}')
print(f'Wins: {len(wins)}')
print(f'Losses: {len(losses)}')
print(f'Win Rate: {win_rate:.2f}%')
print(f'Average Win: {wins["P/L %"].mean():.2f}%')
print(f'Average Loss: {losses["P/L %"].mean():.2f}%')
print(f'Max Win: {wins["P/L %"].max():.2f}%')
print(f'Max Loss: {losses["P/L %"].min():.2f}%')
print(f'Overall PnL % sum: {df["P/L %"].sum():.2f}%')
