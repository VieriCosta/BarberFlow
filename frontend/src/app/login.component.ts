import { ChangeDetectionStrategy, Component, EventEmitter, Output, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from './auth.service';
import { apiError } from './api.service';

@Component({ changeDetection: ChangeDetectionStrategy.Eager,
  selector: 'app-login', standalone: true, imports: [FormsModule],
  template: `
    <form class="stack" (ngSubmit)="submit()">
      <h2>{{ setup ? 'Configurar administrador' : 'Entrar na barbearia' }}</h2>
      @if (error) { <p role="alert">{{ error }}</p> }
      @if (setup) {
        <label>Chave de configuração<input type="password" name="key" [(ngModel)]="key" required autocomplete="off"></label>
        <label>Seu nome<input name="name" [(ngModel)]="name" required minlength="2" maxlength="120" autocomplete="name"></label>
      }
      <label>Usuário<input name="username" [(ngModel)]="username" required minlength="3" maxlength="120" autocomplete="username"></label>
      <label>Senha<input type="password" name="password" [(ngModel)]="password" required [minlength]="setup ? 12 : 1" maxlength="128" [autocomplete]="setup ? 'new-password' : 'current-password'"></label>
      <button type="submit" [disabled]="busy">{{ busy ? 'Aguarde…' : setup ? 'Criar administrador' : 'Entrar' }}</button>
      <button type="button" (click)="setup = !setup; error = ''">{{ setup ? 'Voltar ao login' : 'Primeiro acesso: configurar barbearia' }}</button>
      @if (setup) { <p>A chave é definida por quem instalou a barbearia. A senha deve ter pelo menos 12 caracteres.</p> }
    </form>`,
  styles: [`.stack{display:grid;gap:16px}label{display:grid;gap:6px}input,button{font:inherit;padding:12px;border:1px solid #d0ccc3;border-radius:8px}button{cursor:pointer;background:#173a31;color:#fff}p{font-size:14px}`],
})
export class LoginComponent {
  readonly auth = inject(AuthService);
  @Output() signedIn = new EventEmitter<void>();
  setup = false; key = ''; name = ''; username = ''; password = ''; busy = false; error = '';
  submit(): void {
    if (this.busy) return;
    this.busy = true; this.error = '';
    if (this.setup) {
      this.auth.bootstrap({ username: this.username, name: this.name, password: this.password, role: 'admin', professional_id: null }, this.key).subscribe({
        next: () => { this.key = ''; this.setup = false; this.login(); },
        error: error => { this.busy = false; this.error = apiError(error); },
      });
    } else this.login();
  }
  private login(): void {
    this.auth.login(this.username, this.password).subscribe({
      next: () => { this.busy = false; this.password = ''; this.signedIn.emit(); },
      error: error => { this.busy = false; this.error = apiError(error); },
    });
  }
}
