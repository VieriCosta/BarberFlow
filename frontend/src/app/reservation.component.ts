import { ChangeDetectionStrategy, Component, Input, OnInit, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService, Appointment, Slot, apiError } from './api.service';

@Component({ changeDetection: ChangeDetectionStrategy.Eager, selector: 'app-reservation', standalone: true, imports: [CommonModule, FormsModule], styleUrl: './management.css', template: `
  <section class="panel"><h2>Sua reserva</h2>@if (error) { <p class="message error" role="alert">{{ error }}</p> } @if (notice) { <p class="message" role="status">{{ notice }}</p> }
  @if (loading) { <p role="status">Consultando reserva…</p> }
  @if (appointment) {
    <h3>{{ appointment.service_name }}</h3><p>{{ appointment.professional_name }} · {{ appointment.starts_at.slice(0,10).split('-').reverse().join('/') }} às {{ appointment.starts_at.slice(11,16) }}<br>{{ appointment.price | currency:'BRL' }}</p><p>Situação: {{ statusLabel(appointment.status) }}</p>
    @if (appointment.status === 'scheduled') {
      <p>Você pode cancelar ou reagendar até {{ appointment.change_hours }} hora(s) antes. Após esse prazo, entre em contato com a barbearia.</p>
      <div class="row"><button [disabled]="busy" (click)="editing = !editing">Escolher novo horário</button><button class="secondary" [disabled]="busy" (click)="cancelling = !cancelling">Cancelar reserva</button></div>
      @if (cancelling) { <div class="message"><p>Confirma o cancelamento desta reserva?</p><button [disabled]="busy" (click)="cancel()">Sim, cancelar reserva</button><button class="secondary" (click)="cancelling = false">Manter reserva</button></div> }
      @if (editing) { <div class="stack panel"><label>Nova data<input type="date" [(ngModel)]="day" [min]="today" (change)="loadSlots()"></label><button [disabled]="busy || loadingSlots" (click)="loadSlots()">Consultar horários</button>@if (loadingSlots) { <p role="status">Consultando horários…</p> }<div class="row">@for (slot of slots; track slot.starts_at + slot.professional_id) { <button [disabled]="busy" [class.secondary]="selected !== slot" [attr.aria-pressed]="selected === slot" (click)="selected = slot">{{ slot.starts_at.slice(11,16) }} · {{ slot.professional_name }}</button> } @empty { @if (searched && !loadingSlots) { <p>Nenhum horário disponível. Escolha outra data.</p> } }</div>@if (selected) { <button [disabled]="busy" (click)="reschedule()">Confirmar novo horário</button> }</div> }
    }
  } @else if (!loading) { <p>Abra o link recebido na confirmação para acessar sua reserva.</p> }
  <p>Guarde este link com cuidado: quem tiver acesso a ele poderá gerenciar esta reserva.</p></section>` })
export class ReservationComponent implements OnInit {
  private readonly http = inject(HttpClient); private readonly api = inject(ApiService);
  @Input() token = ''; @Input() today = ''; day = '';
  appointment: (Appointment & { change_hours: number }) | null = null;
  slots: Slot[] = []; selected: Slot | null = null; error = ''; notice = ''; loading = false; busy = false;
  editing = false; cancelling = false; loadingSlots = false; searched = false; private request = 0;
  private get options() { return { headers: new HttpHeaders({ Authorization: `Bearer ${this.token}` }) }; }
  ngOnInit(): void { this.day = this.today; this.loading = true; this.http.get<Appointment & { change_hours: number }>('/api/public/reservation', this.options).subscribe({ next: result => { this.appointment = result; this.loading = false; }, error: error => { this.loading = false; this.error = apiError(error); } }); }
  statusLabel(status: string): string { return ({ scheduled: 'Confirmada', in_progress: 'Em atendimento', completed: 'Concluída', cancelled: 'Cancelada', no_show: 'Falta registrada' } as Record<string,string>)[status] ?? status; }
  loadSlots(): void {
    if (!this.appointment || !this.day) return;
    const request = ++this.request; this.loadingSlots = true; this.error = ''; this.slots = []; this.selected = null; this.searched = true;
    this.api.availability(this.appointment.service_id, this.day).subscribe({ next: slots => { if (request === this.request) { this.slots = slots; this.loadingSlots = false; } }, error: error => { if (request === this.request) { this.loadingSlots = false; this.error = apiError(error); } } });
  }
  cancel(): void { this.mutate('cancel', {}); }
  reschedule(): void { if (this.selected) this.mutate('reschedule', { starts_at: this.selected.starts_at, professional_id: this.selected.professional_id }); }
  private mutate(action: string, payload: unknown): void {
    if (this.busy) return; this.busy = true; this.error = '';
    this.http.post<Appointment>(`/api/public/reservation/${action}`, payload, this.options).subscribe({ next: result => { this.appointment = { ...result, change_hours: this.appointment!.change_hours }; this.busy = false; this.editing = this.cancelling = false; this.slots = []; this.selected = null; this.notice = action === 'cancel' ? 'Reserva cancelada.' : 'Reserva reagendada.'; }, error: error => { this.busy = false; this.error = apiError(error); } });
  }
}
