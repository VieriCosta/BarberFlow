import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';

export type PaymentMethod = 'cash' | 'pix' | 'credit' | 'debit';
export interface DailyFinance {
  day: string; received: string; expenses_total: string; commissions: string; balance: string;
  after_commissions: string; cash_expected: string; pending_total: string;
  by_method: Record<PaymentMethod, string>;
  payments: { id: number; appointment_id: number; amount: string; discount: string; commission: string; method: PaymentMethod; paid_at: string }[];
  expenses: { id: number; description: string; amount: string; method: PaymentMethod }[];
  pending: { id: number; customer_name: string; service_name: string; price: string }[];
  close: { id: number; counted: string; expected: string; difference: string; notes: string } | null;
}
export interface Dashboard extends DailyFinance {
  appointments_count: number; completed_count: number; no_shows_count: number;
  occupation: { professional_id: number; name: string; appointments: number; available_minutes: number; booked_minutes: number; occupancy_percent: number }[];
}
export interface ScheduleException { id: number; professional_id: number; day: string; reason: string; periods: { starts_at: string; ends_at: string }[]; }
export interface NotificationItem { id: number; appointment_id: number; kind: string; state: string; attempts: number; last_error: string; due_at: string; }

@Injectable({ providedIn: 'root' })
export class ManagementService {
  private readonly http = inject(HttpClient);
  daily(day: string) { return this.http.get<DailyFinance>('/api/finance/daily', { params: new HttpParams().set('day', day) }); }
  dashboard(day: string) { return this.http.get<Dashboard>('/api/dashboard', { params: new HttpParams().set('day', day) }); }
  pay(id: number, payload: { method: PaymentMethod; discount: string; commission_percent: string }) { return this.http.post(`/api/appointments/${id}/payment`, payload); }
  expense(payload: { description: string; amount: string; method: PaymentMethod }) { return this.http.post('/api/finance/expenses', payload); }
  close(payload: { day: string; cash_counted: string; notes: string }) { return this.http.post<DailyFinance>('/api/finance/close', payload); }
  exceptions() { return this.http.get<ScheduleException[]>('/api/schedule-exceptions'); }
  saveException(payload: Omit<ScheduleException, 'id'>) { return this.http.put<ScheduleException>('/api/schedule-exceptions', payload); }
  deleteException(id: number) { return this.http.delete(`/api/schedule-exceptions/${id}`); }
  notifications() { return this.http.get<{ configured: boolean; items: NotificationItem[] }>('/api/notifications'); }
  retry(id: number) { return this.http.post(`/api/notifications/${id}/retry`, {}); }
  audit() { return this.http.get<{ id: number; actor_id: number | null; action: string; entity_id: number | null; created_at: string }[]>('/api/auth/audit'); }
}
