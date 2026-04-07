import React from 'react';
import clsx from 'clsx';

interface LivePnLCardProps {
  title: string;
  value: number;
  prefix?: string;
  suffix?: string;
  isPercentage?: boolean;
  className?: string;
}

export function LivePnLCard({
  title,
  value,
  prefix = '',
  suffix = '',
  isPercentage = false,
  className,
}: LivePnLCardProps) {
  const isPositive = value >= 0;
  const formattedValue = new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);

  return (
    <div
      className={clsx(
        'bg-dark-800 rounded-xl p-6 border border-dark-700',
        className
      )}
    >
      <h3 className="text-sm font-medium text-gray-400 mb-2">{title}</h3>
      <div
        className={clsx(
          'text-3xl font-bold',
          isPositive ? 'text-profit' : 'text-loss'
        )}
      >
        {prefix}
        {formattedValue}
        {isPercentage ? '%' : ''}
        {suffix}
      </div>
      <div className="mt-2 flex items-center text-xs text-gray-500">
        <span className="flex items-center">
          <span className="w-2 h-2 bg-green-500 rounded-full mr-2 animate-pulse"></span>
          Real-time
        </span>
      </div>
    </div>
  );
}
