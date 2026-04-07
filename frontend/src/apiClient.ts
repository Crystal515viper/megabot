import axios from 'axios';
import type { SystemStatus, Trade, Metrics, Position } from '@/types';

const API_BASE = '/api/v1';

const apiClient = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const fetchStatus = async (): Promise<SystemStatus> => {
  const response = await apiClient.get('/status');
  return response.data;
};

export const fetchTrades = async (
  page: number = 1,
  limit: number = 20,
  status?: string,
  symbol?: string
): Promise<{ trades: Trade[]; total: number }> => {
  const params = new URLSearchParams({
    page: page.toString(),
    limit: limit.toString(),
  });
  
  if (status) params.append('status', status);
  if (symbol) params.append('symbol', symbol);
  
  const response = await apiClient.get(`/trades?${params}`);
  return response.data;
};

export const fetchMetrics = async (): Promise<Metrics> => {
  const response = await apiClient.get('/metrics');
  return response.data;
};

export const subscribeToPositions = (
  onMessage: (data: Position) => void,
  onError?: (error: Event) => void
): EventSource => {
  const eventSource = new EventSource(`${API_BASE}/stream/positions`);
  
  eventSource.addEventListener('position_update', (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch (e) {
      console.error('Failed to parse SSE message:', e);
    }
  });
  
  eventSource.onerror = (error) => {
    console.error('SSE connection error:', error);
    onError?.(error);
  };
  
  return eventSource;
};

export default apiClient;
