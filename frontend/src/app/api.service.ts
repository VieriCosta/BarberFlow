import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface Service {
  id: number;
  name: string;
  description: string;
  price: string;
  duration_minutes: number;
  active: boolean;
}
export interface WorkPeriod { weekday: number; starts_at: string; ends_at: string; }
export interface Professional {
  id: number;
  name: string;
  active: boolean;
  service_ids: number[];
  work_periods: WorkPeriod[];
}
export interface Customer {
  id: number;
  name: string;
  phone: string;
  email: string | null;
  notes: string;
  appointments_count: number;
  no_shows_count: number;
}
export interface Slot { starts_at: string; professional_id: number; professional_name: string; }
export interface Appointment {
  id: number;
  service_id: number;
  service_name: string;
  professional_id: number;
  professional_name: string;
  customer_name: string;
  customer_phone: string;
  starts_at: string;
  ends_at: string;
  price: string;
  status: AppointmentStatus;
  customer_id?: number;
  manage_token?: string;
  paid?: boolean;
}
export type AppointmentStatus = 'scheduled' | 'in_progress' | 'completed' | 'cancelled' | 'no_show';
export type AgendaView = 'day' | 'week';
export interface ScheduleBlock {
  id: number;
  professional_id: number;
  professional_name: string;
  starts_at: string;
  ends_at: string;
  reason: string;
}
export interface AgendaHours { professional_id: number; day: string; reason: string; periods: { starts_at: string; ends_at: string }[]; }
export interface BookingPayload {
  service_id: number;
  professional_id: number | null;
  starts_at: string;
  customer_name: string;
  customer_phone: string;
  customer_email?: string | null;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  publicServices(): Observable<Service[]> { return this.http.get<Service[]>('/api/public/services'); }
  publicConfig(): Observable<{ timezone: string }> { return this.http.get<{ timezone: string }>('/api/public/config'); }
  publicProfessionals(serviceId?: number): Observable<Professional[]> {
    const params = serviceId ? new HttpParams().set('service_id', serviceId) : undefined;
    return this.http.get<Professional[]>('/api/public/professionals', { params });
  }
  availability(serviceId: number, day: string, professionalId?: number): Observable<Slot[]> {
    let params = new HttpParams().set('service_id', serviceId).set('day', day);
    if (professionalId) params = params.set('professional_id', professionalId);
    return this.http.get<Slot[]>('/api/public/availability', { params });
  }
  book(payload: BookingPayload): Observable<Appointment> {
    return this.http.post<Appointment>('/api/public/appointments', payload);
  }
  services(): Observable<Service[]> { return this.http.get<Service[]>('/api/services'); }
  createService(payload: { name: string; description: string; price: number; duration_minutes: number }): Observable<Service> {
    return this.http.post<Service>('/api/services', payload);
  }
  updateService(id: number, payload: { name?: string; description?: string; price?: number | string; duration_minutes?: number; active?: boolean }): Observable<Service> {
    return this.http.patch<Service>(`/api/services/${id}`, payload);
  }
  professionals(): Observable<Professional[]> {
    return this.http.get<Professional[]>('/api/professionals');
  }
  createProfessional(payload: { name: string; service_ids: number[] }): Observable<Professional> {
    return this.http.post<Professional>('/api/professionals', payload);
  }
  updateProfessional(id: number, payload: Partial<Pick<Professional, 'name' | 'service_ids' | 'active'>>): Observable<Professional> {
    return this.http.patch<Professional>(`/api/professionals/${id}`, payload);
  }
  customers(): Observable<Customer[]> {
    return this.http.get<Customer[]>('/api/customers');
  }
  createCustomer(payload: { name: string; phone: string; email: string | null; notes: string }): Observable<Customer> {
    return this.http.post<Customer>('/api/customers', payload);
  }
  updateCustomer(id: number, payload: { name: string; phone: string; email: string | null; notes: string }): Observable<Customer> {
    return this.http.patch<Customer>(`/api/customers/${id}`, payload);
  }
  customerAppointments(id: number): Observable<Appointment[]> {
    return this.http.get<Appointment[]>(`/api/customers/${id}/appointments`);
  }
  savePeriods(id: number, periods: WorkPeriod[]): Observable<Professional> {
    return this.http.put<Professional>(`/api/professionals/${id}/work-periods`, periods);
  }
  appointments(day: string, view: AgendaView = 'day', professionalId = 0): Observable<Appointment[]> {
    let params = new HttpParams().set('day', day).set('view', view);
    if (professionalId) params = params.set('professional_id', professionalId);
    return this.http.get<Appointment[]>('/api/appointments', { params });
  }
  blocks(day: string, view: AgendaView = 'day', professionalId = 0): Observable<ScheduleBlock[]> {
    let params = new HttpParams().set('day', day).set('view', view);
    if (professionalId) params = params.set('professional_id', professionalId);
    return this.http.get<ScheduleBlock[]>('/api/blocks', { params });
  }
  agendaHours(day: string, view: AgendaView = 'day', professionalId = 0): Observable<AgendaHours[]> {
    let params = new HttpParams().set('day', day).set('view', view);
    if (professionalId) params = params.set('professional_id', professionalId);
    return this.http.get<AgendaHours[]>('/api/agenda-hours', { params });
  }
  createBlock(payload: { professional_id: number; starts_at: string; ends_at: string; reason: string }): Observable<ScheduleBlock> {
    return this.http.post<ScheduleBlock>('/api/blocks', payload);
  }
  deleteBlock(id: number): Observable<void> {
    return this.http.delete<void>(`/api/blocks/${id}`);
  }
  reschedule(id: number, payload: { starts_at: string; professional_id: number }): Observable<Appointment> {
    return this.http.post<Appointment>(`/api/appointments/${id}/reschedule`, payload);
  }
  updateStatus(id: number, status: AppointmentStatus): Observable<Appointment> {
    return this.http.patch<Appointment>(`/api/appointments/${id}/status`, { status });
  }
  internalBooking(payload: BookingPayload): Observable<Appointment> {
    return this.http.post<Appointment>('/api/appointments', payload);
  }
}

export function apiError(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    const detail = error.error?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map(item => item.msg).join('; ');
    if (error.status === 0) return 'Não foi possível conectar à API. Confira se o backend está em execução.';
  }
  return 'Não foi possível concluir a operação. Tente novamente.';
}
