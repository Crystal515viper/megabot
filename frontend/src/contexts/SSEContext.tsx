import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import type { Position, SystemStatus } from '@/types';
import { subscribeToPositions } from '@/apiClient';

interface SSEContextType {
  positions: Position[];
  status: SystemStatus | null;
  connected: boolean;
  error: Error | null;
}

const SSEContext = createContext<SSEContextType | undefined>(undefined);

export function SSEProvider({ children }: { children: ReactNode }) {
  const [positions, setPositions] = useState<Position[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let eventSource: EventSource | null = null;

    try {
      eventSource = subscribeToPositions(
        (data) => {
          setPositions((prev) => {
            const existingIndex = prev.findIndex((p) => p.id === data.id);
            if (existingIndex >= 0) {
              const updated = [...prev];
              updated[existingIndex] = data;
              return updated;
            }
            return [...prev, data];
          });
          setConnected(true);
        },
        (err) => {
          setError(new Error('SSE connection failed'));
          setConnected(false);
        }
      );
    } catch (e) {
      setError(e instanceof Error ? e : new Error('Failed to initialize SSE'));
    }

    // Fetch initial status
    fetch('/api/v1/status')
      .then((res) => res.json())
      .then(setStatus)
      .catch(console.error);

    return () => {
      eventSource?.close();
    };
  }, []);

  return (
    <SSEContext.Provider value={{ positions, status, connected, error }}>
      {children}
    </SSEContext.Provider>
  );
}

export function useSSEContext() {
  const context = useContext(SSEContext);
  if (context === undefined) {
    throw new Error('useSSEContext must be used within an SSEProvider');
  }
  return context;
}
