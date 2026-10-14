import { Injectable, inject, signal } from '@angular/core';
import { HttpClient, HttpInterceptorFn } from '@angular/common/http';
import { tap, catchError, throwError } from 'rxjs';

export interface User { id: number; name: string; username: string; role: 'admin' | 'reception' | 'barber'; professional_id: number | null; active: boolean; }
export interface UserInput { username: string; name: string; password: string; role: User['role']; professional_id: number | null; }

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  readonly user = signal<User | null>(null);
  get token(): string { return sessionStorage.getItem('barberflow-session') ?? ''; }
  get canManage(): boolean { return this.user()?.role === 'admin'; }
  get canFinance(): boolean { return ['admin', 'reception'].includes(this.user()?.role ?? ''); }
  login(username: string, password: string) {
    return this.http.post<{ token: string; user: User }>('/api/auth/login', { username, password }).pipe(tap(result => {
      sessionStorage.setItem('barberflow-session', result.token);
      this.user.set(result.user);
    }));
  }
  restore() { return this.http.get<User>('/api/auth/me').pipe(tap(user => this.user.set(user))); }
  clear(): void { sessionStorage.removeItem('barberflow-session'); this.user.set(null); }
  logout() { return this.http.post<void>('/api/auth/logout', {}); }
  bootstrap(payload: UserInput, key: string) { return this.http.post<User>('/api/auth/bootstrap', payload, { headers: { 'Bootstrap-Key': key } }); }
  users() { return this.http.get<User[]>('/api/auth/users'); }
  createUser(payload: UserInput) { return this.http.post<User>('/api/auth/users', payload); }
  updateUser(id: number, payload: { active?: boolean; password?: string }) { return this.http.patch<User>(`/api/auth/users/${id}`, payload); }
}

export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  if (auth.token && request.url.startsWith('/api/') && !request.url.startsWith('/api/public/') && !request.headers.has('Authorization')) {
    request = request.clone({ setHeaders: { Authorization: `Bearer ${auth.token}` } });
  }
  return next(request).pipe(catchError(error => {
    if (error.status === 401 && request.url.startsWith('/api/') && !request.url.startsWith('/api/public/')) auth.clear();
    return throwError(() => error);
  }));
};
