import { Injectable, signal } from '@angular/core';

export interface Barbershop { id: number; name: string; slug: string; description: string; city: string; address: string; phone: string; published: boolean; }
export interface ShopRegistration { name: string; description: string; city: string; address: string; phone: string; owner_name: string; username: string; password: string; }

@Injectable({ providedIn: 'root' })
export class ShopContext {
  readonly shop = signal<Barbershop | null>(null);
  get id(): number { return this.shop()?.id ?? (Number(sessionStorage.getItem('barberflow-shop-id')) || 0); }
  select(shop: Barbershop): void { this.shop.set(shop); sessionStorage.setItem('barberflow-shop-id', String(shop.id)); }
  prepare(id: number): void { this.shop.set(null); sessionStorage.setItem('barberflow-shop-id', String(id)); }
  clear(): void { this.shop.set(null); sessionStorage.removeItem('barberflow-shop-id'); }
}
