import { ChangeDetectionStrategy, Component, Input, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Dashboard, ManagementService } from './management.service';
import { apiError } from './api.service';

@Component({ changeDetection: ChangeDetectionStrategy.Eager, selector: 'app-dashboard', standalone: true, imports: [CommonModule, FormsModule], styleUrl: './management.css', template: `
  <section class="panel"><h2>Painel da barbearia</h2><div class="toolbar"><label>Dia<input type="date" [(ngModel)]="day" (change)="load()"></label><button (click)="load()">Atualizar</button></div>
  @if (loading) { <p role="status">Carregando indicadores…</p> }
  @if (error) { <p class="message error" role="alert">{{ error }}</p> }
  @if (data && !loading && !error) {
    <div class="metrics"><div class="metric"><span>Atendimentos</span><strong>{{ data.appointments_count }}</strong></div><div class="metric"><span>Concluídos</span><strong>{{ data.completed_count }}</strong></div><div class="metric"><span>Faltas</span><strong>{{ data.no_shows_count }}</strong></div><div class="metric"><span>Recebido no dia</span><strong>{{ data.received | currency:'BRL' }}</strong></div><div class="metric"><span>Pendente dos atendimentos do dia</span><strong>{{ data.pending_total | currency:'BRL' }}</strong></div><div class="metric"><span>Saldo após despesas e comissões</span><strong>{{ data.after_commissions | currency:'BRL' }}</strong></div></div>
    <h3>Ocupação da equipe</h3><div class="columns">@for (item of data.occupation; track item.professional_id) { <div class="metric"><strong>{{ item.name }}</strong><p>{{ item.appointments }} reservas · {{ item.occupancy_percent }}%</p><progress [value]="item.occupancy_percent" max="100" [attr.aria-label]="'Ocupação de ' + item.name"></progress><small>{{ item.booked_minutes }} min reservados / {{ item.available_minutes }} min de expediente</small></div> }</div>
    <p>Ocupação considera reservas pendentes, em andamento e concluídas dentro do expediente do dia. Receita considera a data do pagamento.</p>
  }</section>` })
export class DashboardComponent implements OnInit {
  private readonly api = inject(ManagementService);
  @Input() day = ''; data: Dashboard | null = null; loading = false; error = ''; private request = 0;
  ngOnInit(): void { this.load(); }
  load(): void {
    if (!this.day) return;
    const request = ++this.request; this.loading = true; this.error = '';
    this.api.dashboard(this.day).subscribe({ next: data => { if (request === this.request) { this.data = data; this.loading = false; } }, error: error => { if (request === this.request) { this.error = apiError(error); this.loading = false; } } });
  }
}
