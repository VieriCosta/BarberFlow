import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { Appointment, Professional, ScheduleBlock } from './api.service';

@Component({ changeDetection: ChangeDetectionStrategy.Eager, selector: 'app-agenda-grid', standalone: true, template: `
  <div class="scroll" tabindex="0" aria-label="Agenda por horário e profissional">
    <div class="board" [style.grid-template-columns]="'64px repeat(' + team.length + ', minmax(170px, 1fr))'">
      <div class="heading">Hora</div>@for (professional of team; track professional.id) { <div class="heading">{{ professional.name }}</div> }
      <div class="times" [style.height.px]="height">@for (hour of hours; track hour) { <span [style.top.px]="(hour-startHour)*64">{{ hour.toString().padStart(2,'0') }}:00</span> }</div>
      @for (professional of team; track professional.id) {
        <div class="column" [style.height.px]="height">
          @for (appointment of dayAppointments(professional.id); track appointment.id) { <button class="booking" [class.completed]="appointment.status === 'completed'" [style.top.px]="top(appointment.starts_at)" [style.height.px]="duration(appointment.starts_at, appointment.ends_at)" (click)="selected.emit(appointment)" [attr.aria-label]="appointment.customer_name + ', ' + appointment.starts_at.slice(11,16) + ', ' + appointment.service_name"><strong>{{ appointment.starts_at.slice(11,16) }} · {{ appointment.customer_name }}</strong><small>{{ appointment.service_name }}</small></button> }
          @for (block of dayBlocks(professional.id); track block.id) { <div class="block" [style.top.px]="top(block.starts_at)" [style.height.px]="duration(block.starts_at, block.ends_at)" [title]="block.reason"><strong>{{ block.starts_at.slice(11,16) }} · Bloqueado</strong><small>{{ block.reason }}</small></div> }
        </div>
      }
    </div>
  </div><p class="hint">Clique em um atendimento para abrir suas ações na lista. Reservas canceladas e faltas aparecem apenas na lista.</p>`,
  styles: [`.scroll{overflow:auto;border:1px solid #dcd8cf;border-radius:12px;margin-top:20px;max-height:650px}.board{display:grid;min-width:460px}.heading{position:sticky;top:0;background:#173a31;color:#fff;z-index:2;padding:12px;border-right:1px solid #53675f}.column,.times{position:relative;background:repeating-linear-gradient(to bottom,#fffdf8 0px,#fffdf8 31px,#ece8df 32px,#fffdf8 33px,#fffdf8 63px,#d9d4c8 64px);border-right:1px solid #dcd8cf}.times span{position:absolute;font-size:12px;left:8px}.booking,.block{position:absolute;left:4px;right:4px;padding:5px 8px;overflow:hidden;border-radius:6px;text-align:left;font:inherit;min-height:16px}.booking{cursor:pointer;background:#ddebe1;border:1px solid #809d87;color:#173a31}.booking.completed{background:#e5e1cc;border-color:#b1a46c}.block{background:repeating-linear-gradient(45deg,#eee6e0,#eee6e0 6px,#ddd2c9 6px,#ddd2c9 12px);font-size:12px}.booking strong,.block strong{display:block;font-size:12px}.booking small,.block small{font-size:11px}.booking:focus-visible{outline:3px solid #ba8030;z-index:1}.hint{font-size:13px;margin:12px 0}`],
})
export class AgendaGridComponent {
  @Input() professionals: Professional[] = []; @Input() appointments: Appointment[] = []; @Input() blocks: ScheduleBlock[] = [];
  @Input() day = ''; @Input() professionalId = 0;
  @Output() selected = new EventEmitter<Appointment>();
  get team(): Professional[] { return this.professionals.filter(p => this.professionalId ? p.id === this.professionalId : p.active || this.appointments.some(a => a.professional_id === p.id)); }
  get startHour(): number { const entries = [...this.appointments, ...this.blocks].filter(a => a.starts_at.startsWith(this.day)); return Math.min(8, ...entries.map(a => Math.floor(this.minutes(a.starts_at)/60))); }
  get endHour(): number { const entries = [...this.appointments, ...this.blocks].filter(a => a.starts_at.startsWith(this.day)); return Math.max(20, ...entries.map(a => Math.ceil(this.minutes(a.ends_at)/60))); }
  get height(): number { return (this.endHour-this.startHour)*64; }
  get hours(): number[] { return Array.from({ length: this.endHour-this.startHour }, (_,i) => i+this.startHour); }
  dayAppointments(id: number): Appointment[] { return this.appointments.filter(a => a.professional_id === id && a.starts_at.startsWith(this.day) && !['cancelled','no_show'].includes(a.status)); }
  dayBlocks(id: number): ScheduleBlock[] { return this.blocks.filter(a => a.professional_id === id && a.starts_at.slice(0,10) <= this.day && a.ends_at.slice(0,10) >= this.day); }
  private minutes(value: string): number { return Number(value.slice(11,13))*60+Number(value.slice(14,16)); }
  top(value: string): number { return Math.max(0, ((value.slice(0,10) < this.day ? this.startHour*60 : this.minutes(value))-this.startHour*60)*64/60); }
  duration(start: string, end: string): number { const first = start.slice(0,10) < this.day ? this.startHour*60 : this.minutes(start); const last = end.slice(0,10) > this.day ? this.endHour*60 : this.minutes(end); return Math.max(16, (last-first)*64/60-2); }
}
