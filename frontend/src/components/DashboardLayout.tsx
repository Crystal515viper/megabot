import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import clsx from 'clsx';

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

const navItems: NavItem[] = [
  { path: '/', label: 'Обзор', icon: '📊' },
  { path: '/trades', label: 'История', icon: '📜' },
  { path: '/analytics', label: 'Аналитика', icon: '📈' },
  { path: '/risk', label: 'Риски', icon: '⚠️' },
  { path: '/health', label: 'Здоровье', icon: '❤️' },
];

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-dark-900 text-white">
      {/* Mobile menu button */}
      <button
        className="lg:hidden fixed top-4 left-4 z-50 p-2 bg-dark-800 rounded-lg"
        onClick={() => setSidebarOpen(!sidebarOpen)}
      >
        ☰
      </button>

      {/* Sidebar */}
      <aside
        className={clsx(
          'fixed top-0 left-0 h-full w-64 bg-dark-800 transform transition-transform duration-300 ease-in-out z-40',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
          'lg:translate-x-0'
        )}
      >
        <div className="p-6">
          <h1 className="text-2xl font-bold text-profit">MegaBot</h1>
          <p className="text-sm text-gray-400 mt-1">Trading Dashboard</p>
        </div>

        <nav className="mt-6">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={clsx(
                'flex items-center px-6 py-3 text-left transition-colors',
                location.pathname === item.path
                  ? 'bg-dark-700 text-profit border-r-4 border-profit'
                  : 'text-gray-300 hover:bg-dark-700 hover:text-white'
              )}
              onClick={() => setSidebarOpen(false)}
            >
              <span className="mr-3">{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="absolute bottom-0 left-0 right-0 p-6">
          <div className="text-xs text-gray-500">
            <p>v0.1.0</p>
            <p className="mt-1">© 2024 MegaBot</p>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="lg:ml-64 min-h-screen">
        <div className="p-4 lg:p-8 pt-16 lg:pt-8">
          {children}
        </div>
      </main>
    </div>
  );
}
