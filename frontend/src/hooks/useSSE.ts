import { useEffect, useState, useCallback } from 'react';
import type { Position } from '@/types';

interface UseSSEOptions {
  url: string;
  reconnectDelay?: number;
  maxReconnectDelay?: number;
}

interface UseSSEResult<T> {
  data: T | null;
  connected: boolean;
  error: Error | null;
}

export function useSSE<T>({
  url,
  reconnectDelay = 1000,
  maxReconnectDelay = 30000,
}: UseSSEOptions): UseSSEResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let eventSource: EventSource | null = null;
    let currentDelay = reconnectDelay;
    let isMounted = true;

    const connect = () => {
      if (!isMounted) return;

      try {
        eventSource = new EventSource(url);
        setConnected(true);
        setError(null);
        currentDelay = reconnectDelay;

        eventSource.onopen = () => {
          console.log('SSE connection established');
        };

        eventSource.addEventListener('position_update', (event) => {
          try {
            const parsedData = JSON.parse(event.data) as T;
            setData(parsedData);
          } catch (e) {
            console.error('Failed to parse SSE message:', e);
          }
        });

        eventSource.onerror = () => {
          console.warn('SSE connection lost, reconnecting...');
          setConnected(false);
          eventSource?.close();
          
          // Exponential backoff
          setTimeout(() => {
            if (isMounted) {
              currentDelay = Math.min(currentDelay * 2, maxReconnectDelay);
              connect();
            }
          }, currentDelay);
        };
      } catch (e) {
        setError(e instanceof Error ? e : new Error('Unknown SSE error'));
        setConnected(false);
      }
    };

    connect();

    return () => {
      isMounted = false;
      eventSource?.close();
    };
  }, [url, reconnectDelay, maxReconnectDelay]);

  return { data, connected, error };
}

export default useSSE;
