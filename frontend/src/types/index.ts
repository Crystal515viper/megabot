export interface Position {
  id: number;
  account_id: number;
  signal_id: number;
  side: 'LONG' | 'SHORT';
  symbol: string;
  entry_price: number;
  current_price: number;
  amount: number;
  leverage: number;
  pnl: number;
  pnl_percent: number;
  status: 'OPEN' | 'CLOSED' | 'STOPPED' | 'LIQUIDATED';
  trailing_stop_price?: number;
  created_at: string;
  updated_at: string;
}

export interface Trade {
  id: number;
  position_id: number;
  symbol: string;
  side: 'LONG' | 'SHORT';
  entry_price: number;
  exit_price?: number;
  amount: number;
  pnl: number;
  pnl_percent: number;
  status: 'OPEN' | 'CLOSED';
  created_at: string;
  closed_at?: string;
}

export interface SystemStatus {
  healthy: boolean;
  orchestrator_status: string;
  bot_long_status: string;
  bot_short_status: string;
  total_balance: number;
  free_balance: number;
  positions_count: number;
  last_update: string;
}

export interface Metrics {
  sharpe_ratio: number;
  win_rate: number;
  max_drawdown: number;
  profit_factor: number;
  total_trades: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
}

export interface SSEMessage {
  type: 'position_update' | 'pnl_update' | 'trailing_update' | 'system_status';
  data: Position | SystemStatus | number;
  timestamp: string;
}
