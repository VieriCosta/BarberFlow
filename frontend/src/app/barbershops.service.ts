import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Barbershop, ShopRegistration } from './shop-context.service';
import { User } from './auth.service';

@Injectable({ providedIn: 'root' })
export class BarbershopsService {
  private readonly http = inject(HttpClient);
  list(q = '', offset = 0) { return this.http.get<{ items: Barbershop[]; has_more: boolean }>('/api/public/barbershops', { params: new HttpParams().set('q', q).set('offset', offset) }); }
  get(id: number) { return this.http.get<Barbershop>(`/api/public/barbershops/${id}`); }
  byCode(code: string) { return this.http.get<Barbershop>(`/api/public/barbershops/by-slug/${encodeURIComponent(code)}`); }
  register(payload: ShopRegistration) { return this.http.post<{ shop: Barbershop; token: string; user: User }>('/api/public/barbershops', payload); }
  profile() { return this.http.get<Barbershop>('/api/profile'); }
  saveProfile(payload: Omit<Barbershop, 'id' | 'slug'>) { return this.http.put<Barbershop>('/api/profile', payload); }
}
