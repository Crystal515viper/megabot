import React, { useState, useMemo } from 'react';
import type { Trade } from '@/types';
import clsx from 'clsx';

interface TradeTableProps {
  trades: Trade[];
  loading?: boolean;
}

export function TradeTable({ trades, loading = false }: TradeTableProps) {
  const [sortField, setSortField] = useState<keyof Trade>('created_at');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [symbolFilter, setSymbolFilter] = useState<string>('all');

  const filteredAndSortedTrades = useMemo(() => {
    let result = [...trades];

    // Filter by status
    if (statusFilter !== 'all') {
      result = result.filter((t) => t.status === statusFilter);
    }

    // Filter by symbol
    if (symbolFilter !== 'all') {
      result = result.filter((t) => t.symbol === symbolFilter);
    }

    // Sort
    result.sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });

    return result;
  }, [trades, sortField, sortDirection, statusFilter, symbolFilter]);

  const handleSort = (field: keyof Trade) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const uniqueSymbols = useMemo(
    () => Array.from(new Set(trades.map((t) => t.symbol))),
    [trades]
  );

  if (loading) {
    return (
      <div className="bg-dark-800 rounded-xl p-6 border border-dark-700">
        <div className="animate-pulse space-y-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 bg-dark-700 rounded"></div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-dark-800 rounded-xl p-6 border border-dark-700">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <h2 className="text-xl font-bold">История сделок</h2>

        <div className="flex flex-wrap gap-3">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm"
          >
            <option value="all">Все статусы</option>
            <option value="OPEN">Открытые</option>
            <option value="CLOSED">Закрытые</option>
          </select>

          <select
            value={symbolFilter}
            onChange={(e) => setSymbolFilter(e.target.value)}
            className="bg-dark-700 border border-dark-600 rounded-lg px-3 py-2 text-sm"
          >
            <option value="all">Все символы</option>
            {uniqueSymbols.map((symbol) => (
              <option key={symbol} value={symbol}>
                {symbol}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-dark-700">
              <th
                className="text-left py-3 px-4 cursor-pointer hover:text-profit"
                onClick={() => handleSort('id')}
              >
                # {sortField === 'id' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th
                className="text-left py-3 px-4 cursor-pointer hover:text-profit"
                onClick={() => handleSort('symbol')}
              >
                Символ {sortField === 'symbol' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th
                className="text-left py-3 px-4 cursor-pointer hover:text-profit"
                onClick={() => handleSort('side')}
              >
                Сторона {sortField === 'side' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th
                className="text-left py-3 px-4 cursor-pointer hover:text-profit"
                onClick={() => handleSort('entry_price')}
              >
                Вход {sortField === 'entry_price' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th
                className="text-left py-3 px-4 cursor-pointer hover:text-profit"
                onClick={() => handleSort('exit_price')}
              >
                Выход {sortField === 'exit_price' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th
                className="text-left py-3 px-4 cursor-pointer hover:text-profit"
                onClick={() => handleSort('pnl')}
              >
                PnL {sortField === 'pnl' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th
                className="text-left py-3 px-4 cursor-pointer hover:text-profit"
                onClick={() => handleSort('pnl_percent')}
              >
                % {sortField === 'pnl_percent' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th className="text-left py-3 px-4">Статус</th>
              <th
                className="text-left py-3 px-4 cursor-pointer hover:text-profit"
                onClick={() => handleSort('created_at')}
              >
                Дата {sortField === 'created_at' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
            </tr>
          </thead>
          <tbody>
            {filteredAndSortedTrades.map((trade) => (
              <tr
                key={trade.id}
                className="border-b border-dark-700 hover:bg-dark-700 transition-colors"
              >
                <td className="py-3 px-4 text-gray-400">{trade.id}</td>
                <td className="py-3 px-4 font-medium">{trade.symbol}</td>
                <td
                  className={clsx(
                    'py-3 px-4',
                    trade.side === 'LONG' ? 'text-profit' : 'text-loss'
                  )}
                >
                  {trade.side}
                </td>
                <td className="py-3 px-4">
                  ${new Intl.NumberFormat('en-US').format(trade.entry_price)}
                </td>
                <td className="py-3 px-4">
                  {trade.exit_price
                    ? `$${new Intl.NumberFormat('en-US').format(trade.exit_price)}`
                    : '-'}
                </td>
                <td
                  className={clsx(
                    'py-3 px-4 font-medium',
                    trade.pnl >= 0 ? 'text-profit' : 'text-loss'
                  )}
                >
                  ${new Intl.NumberFormat('en-US').format(trade.pnl)}
                </td>
                <td
                  className={clsx(
                    'py-3 px-4 font-medium',
                    trade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'
                  )}
                >
                  {trade.pnl_percent.toFixed(2)}%
                </td>
                <td className="py-3 px-4">
                  <span
                    className={clsx(
                      'px-2 py-1 rounded text-xs',
                      trade.status === 'OPEN'
                        ? 'bg-green-900 text-green-300'
                        : 'bg-gray-700 text-gray-300'
                    )}
                  >
                    {trade.status}
                  </span>
                </td>
                <td className="py-3 px-4 text-gray-400 text-sm">
                  {new Date(trade.created_at).toLocaleString('ru-RU')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filteredAndSortedTrades.length === 0 && (
          <div className="text-center py-12 text-gray-500">
            Нет данных для отображения
          </div>
        )}
      </div>
    </div>
  );
}
