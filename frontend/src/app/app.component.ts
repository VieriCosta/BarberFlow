import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, HostListener, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { AgendaHours, AgendaView, ApiService, Appointment, AppointmentStatus, Customer, Professional, ScheduleBlock, Service, Slot, WorkPeriod, apiError } from './api.service';

import { AuthService } from './auth.service';
import { LoginComponent } from './login.component';
import { DashboardComponent } from './dashboard.component';
import { FinanceComponent } from './finance.component';
import { SettingsComponent } from './settings.component';
import { ReservationComponent } from './reservation.component';
import { AgendaGridComponent } from './agenda-grid.component';
import { CatalogComponent } from './catalog.component';
import { DirectoryComponent } from './directory.component';
import { Barbershop, ShopContext } from './shop-context.service';
import { BarbershopsService } from './barbershops.service';

type Tab = 'entry' | 'booking' | 'agenda' | 'services' | 'professionals' | 'customers' | 'dashboard' | 'finance' | 'settings' | 'reservation' | 'team';

@Component({ changeDetection: ChangeDetectionStrategy.Eager,
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule, LoginComponent, DashboardComponent, FinanceComponent, SettingsComponent, ReservationComponent, AgendaGridComponent, CatalogComponent, DirectoryComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnInit {
  readonly api = inject(ApiService);
  readonly auth = inject(AuthService);
  readonly shopContext = inject(ShopContext);
  private readonly shops = inject(BarbershopsService);
  loadingShop = false;
  shopError = '';
  private publicRequest = 0;
  private adminRequest = 0;
  readonly weekdays = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
  manageToken = new URLSearchParams(window.location.hash.slice(1)).get('reservation') ?? '';
  tab: Tab = this.manageToken ? 'reservation' : 'entry';
  agendaLayout: 'grid' | 'list' = 'grid';
  paymentAppointmentId = 0;
  activeProfessionalId = 0;
  choiceProfessionalId = this.activeProfessionalId;
  notice = '';
  error = '';
  saving = false;
  services: Service[] = [];
  professionals: Professional[] = [];
  loadingProfessionals = true;
  loadingServices = true;
  loadingAgenda = false;
  agendaError = '';
  loadingManualSlots = false;
  manualSlotsError = '';
  slots: Slot[] = [];
  loadingSlots = false;
  slotsError = '';
  private availabilityRequest = 0;
  appointments: Appointment[] = [];
  timezone = 'America/Fortaleza';
  blocks: ScheduleBlock[] = [];
  effectiveHours: AgendaHours[] = [];
  agendaView: AgendaView = 'day';
  agendaProfessionalId = this.activeProfessionalId;
  private agendaRequest = 0;
  today = (() => {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Fortaleza', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    const get = (type: string): string => parts.find(part => part.type === type)?.value ?? '';
    return `${get('year')}-${get('month')}-${get('day')}`;
  })();
  booking = { service_id: 0, professional_id: 0, day: this.today, customer_name: '', customer_phone: '', customer_email: '' };
  selectedSlot: Slot | null = null;
  confirmed: Appointment | null = null;
  agendaDay = this.today;
  rescheduleId = 0;
  rescheduleForm = { day: this.today, time: '10:00', professional_id: 0 };
  blockForm = { professional_id: this.activeProfessionalId, day: this.today, starts_at: '12:00', ends_at: '13:00', reason: '' };
  manualForm = { service_id: 0, professional_id: this.activeProfessionalId, day: this.today, customer_name: '', customer_phone: '' };
  manualSlots: Slot[] = [];
  manualSlot: Slot | null = null;
  private manualRequest = 0;

  @HostListener('window:hashchange')
  openReservationLink(): void {
    this.openLocation();
  }

  ngOnInit(): void {
    this.openLocation();
  }

  private openLocation(): void {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const id = Number(fragment.get('shop')) || (fragment.has('reservation') ? 1 : this.auth.token ? this.shopContext.id || 1 : 0);
    this.manageToken = fragment.get('reservation') ?? '';
    if (!id) { this.shopContext.clear(); this.loadingShop = false; return; }
    if (this.shopContext.shop()?.id === id) {
      this.tab = this.manageToken ? 'reservation' : fragment.get('team') ? 'team' : 'booking';
      this.clearMessages(); return;
    }
    if (this.auth.user() && this.auth.user()?.shop_id !== id) { this.auth.logout().subscribe({ error: () => {} }); this.auth.clear(); }
    this.resetShopData();
    this.manageToken = fragment.get('reservation') ?? '';
    this.loadingShop = true; this.shopError = '';
    this.shopContext.prepare(id);
    this.shops.get(id).subscribe({ next: shop => {
      if (this.shopContext.id !== id) return;
      this.shopContext.select(shop); this.loadingShop = false;
      this.tab = this.manageToken ? 'reservation' : fragment.get('team') ? 'team' : 'booking';
      this.initializeShop();
    }, error: error => { if (this.shopContext.id !== id) return; this.loadingShop = false; this.shopContext.clear(); this.shopError = apiError(error); } });
  }

  private initializeShop(restore = true): void {
    const shopId = this.shopContext.id;
    sessionStorage.removeItem('barberflow-admin-key');
    this.api.publicConfig().subscribe({ next: config => {
      if (this.shopContext.id !== shopId) return;
      const previous = this.today;
      this.timezone = config.timezone;
      this.today = this.dateInZone(new Date(), this.timezone);
      if (this.booking.day === previous) this.booking.day = this.today;
      if (this.agendaDay === previous) this.agendaDay = this.today;
      if (this.blockForm.day === previous) this.blockForm.day = this.today;
      if (this.manualForm.day === previous) this.manualForm.day = this.today;
    }});
    this.loadPublic();
    const token = this.auth.token;
    if (restore && token && !this.manageToken) this.auth.restore().subscribe({ next: () => { if (this.shopContext.id === shopId && this.auth.token === token) this.signedIn(); }, error: () => { if (this.shopContext.id === shopId && this.auth.token === token) this.auth.clear(); } });
  }

  chooseShop(shop: Barbershop, team = false): void {
    if (this.auth.user() && this.auth.user()?.shop_id !== shop.id) { this.auth.logout().subscribe({ error: () => {} }); this.auth.clear(); }
    this.resetShopData();
    this.shopContext.select(shop);
    history.replaceState(null, '', window.location.pathname + '#shop=' + shop.id + (team ? '&team=1' : ''));
    this.tab = team ? 'team' : 'booking';
    this.initializeShop();
  }

  shopRegistered(shop: Barbershop): void {
    this.resetShopData(); this.shopContext.select(shop);
    history.replaceState(null, '', window.location.pathname + '#shop=' + shop.id + '&team=1');
    this.initializeShop(false);
    this.signedIn(); this.tab = 'services';
    this.notice = 'Sua barbearia foi criada. Cadastre os serviços, os profissionais e a jornada; depois publique em Configurações.';
  }

  goDirectory(): void {
    if (this.auth.token) this.auth.logout().subscribe({ error: () => {} });
    this.auth.clear(); this.resetShopData(); this.shopContext.clear(); this.manageToken = '';
    this.loadingShop = false; this.shopError = '';
    this.tab = 'entry'; history.replaceState(null, '', window.location.pathname);
  }

  private resetShopData(): void {
    ++this.publicRequest; ++this.adminRequest; ++this.agendaRequest; ++this.manualRequest; ++this.availabilityRequest;
    this.services = []; this.professionals = []; this.appointments = []; this.blocks = []; this.effectiveHours = [];
    this.slots = []; this.manualSlots = []; this.manualSlot = null; this.selectedSlot = null; this.confirmed = null;
    this.activeProfessionalId = 0; this.agendaProfessionalId = 0; this.rescheduleId = 0; this.saving = false;
    this.loadingAgenda = false; this.loadingSlots = false; this.loadingServices = this.loadingProfessionals = true;
    this.booking = { service_id: 0, professional_id: 0, day: this.today, customer_name: '', customer_phone: '', customer_email: '' };
    this.manualForm = { service_id: 0, professional_id: 0, day: this.today, customer_name: '', customer_phone: '' };
    this.blockForm.professional_id = 0; this.manageToken = ''; this.clearMessages();
  }

  setTab(tab: Tab): void {
    if (tab !== 'entry' && tab !== 'booking' && tab !== 'reservation' && tab !== 'team' && !this.auth.user()) { this.tab = 'team'; this.error = 'Entre com seu usuário e senha para abrir a área interna.'; return; }
    if (['services', 'professionals', 'settings'].includes(tab) && !this.auth.canManage) return;
    if (['customers', 'dashboard', 'finance'].includes(tab) && !this.auth.canFinance) return;
    if (tab !== 'reservation' && this.manageToken) { this.manageToken = ''; history.replaceState(null, '', window.location.pathname + '#shop=' + this.shopContext.id); }
    this.tab = tab;
    this.clearMessages();
    if (tab !== 'booking' && tab !== 'entry' && tab !== 'team' && this.activeProfessionalId) this.loadAdmin();
  }

  signedIn(): void {
    const user = this.auth.user();
    if (!user) return;
    this.activeProfessionalId = user.professional_id ?? -1;
    this.agendaProfessionalId = user.professional_id ?? 0;
    this.manualForm.professional_id = user.professional_id ?? 0;
    this.blockForm.professional_id = user.professional_id ?? 0;
    this.tab = 'agenda';
    this.loadAdmin();
  }

  enterAsProfessional(): void { if (this.auth.user()) this.signedIn(); else this.tab = 'entry'; }

  logout(): void {
    this.auth.logout().subscribe({ next: () => {}, error: () => {} });
    this.auth.clear();
    this.switchProfessional();
    this.loadPublic();
  }

  switchProfessional(): void {
    ++this.agendaRequest;
    ++this.manualRequest;
    this.loadingAgenda = false;
    this.loadingManualSlots = false;
    this.rescheduleId = 0;
    this.manualSlot = null;
    this.manualSlots = [];
    this.manualForm.professional_id = 0;
    this.blockForm.professional_id = 0;
    this.activeProfessionalId = 0;
    this.choiceProfessionalId = 0;
    this.agendaProfessionalId = 0;
    this.appointments = [];
    this.blocks = [];
    this.tab = 'entry';
    sessionStorage.removeItem('barberflow-professional-id');
    this.clearMessages();
  }

  activeProfessional(): Professional | undefined {
    return this.professionals.find(p => p.id === this.activeProfessionalId);
  }

  hasActiveProfessionals(): boolean {
    return this.professionals.some(professional => professional.active);
  }

  hasActiveServices(): boolean { return this.services.some(service => service.active); }

  clearMessages(): void { this.notice = ''; this.error = ''; }

  loadPublic(): void {
    const request = ++this.publicRequest;
    this.api.publicServices().subscribe({
      next: services => { if (request !== this.publicRequest) return; this.services = services; this.loadingServices = false; },
      error: error => { this.loadingServices = false; this.error = apiError(error); },
    });
    this.api.publicProfessionals().subscribe({
      next: professionals => {
        if (request !== this.publicRequest) return;
        this.loadingProfessionals = false;
        this.professionals = professionals;
        if (this.activeProfessionalId > 0 && !professionals.some(p => p.id === this.activeProfessionalId))
          this.switchProfessional();
        if (this.activeProfessionalId && this.tab !== 'entry' && this.tab !== 'booking' && this.tab !== 'reservation') this.loadAdmin();
      },
      error: error => { this.loadingProfessionals = false; this.error = apiError(error); },
    });
  }

  loadAdmin(): void {
    const request = ++this.adminRequest;
    ++this.publicRequest;
    this.api.services().subscribe({
      next: services => { if (request === this.adminRequest) { this.services = services; this.loadingServices = false; } },
      error: error => this.error = apiError(error),
    });
    this.api.professionals().subscribe({
      next: professionals => {
        if (request !== this.adminRequest) return;
        this.loadingProfessionals = false;
        this.professionals = professionals;
        if (this.activeProfessionalId > 0 && !professionals.some(p => p.id === this.activeProfessionalId && p.active))
          this.switchProfessional();
      },
      error: error => this.error = apiError(error),
    });
    this.loadAppointments();
  }

  loadAppointments(): void {
    if (!this.activeProfessionalId || !this.agendaDay) return;
    const request = ++this.agendaRequest;
    this.loadingAgenda = true;
    this.agendaError = '';
    this.rescheduleId = 0;
    forkJoin({
      appointments: this.api.appointments(this.agendaDay, this.agendaView, this.agendaProfessionalId),
      blocks: this.api.blocks(this.agendaDay, this.agendaView, this.agendaProfessionalId),
      hours: this.api.agendaHours(this.agendaDay, this.agendaView, this.agendaProfessionalId),
    }).subscribe({
      next: result => {
        if (request !== this.agendaRequest) return;
        this.appointments = result.appointments;
        this.blocks = result.blocks;
        this.effectiveHours = result.hours;
        this.loadingAgenda = false;
      },
      error: error => {
        if (request !== this.agendaRequest) return;
        this.loadingAgenda = false;
        this.agendaError = apiError(error);
      },
    });
  }

  moveAgenda(direction: number): void {
    const day = new Date(`${this.agendaDay || this.today}T12:00:00Z`);
    day.setUTCDate(day.getUTCDate() + direction * (this.agendaView === 'week' ? 7 : 1));
    this.agendaDay = day.toISOString().slice(0, 10);
    this.loadAppointments();
  }

  private validCustomer(name: string, phone: string): boolean {
    if (name.trim().length < 2 || name.trim().length > 120) {
      this.error = 'Informe um nome com 2 a 120 caracteres.';
      return false;
    }
    if (![10, 11].includes(phone.replace(/\D/g, '').length)) {
      this.error = 'Informe um telefone com DDD e 10 ou 11 dígitos.';
      return false;
    }
    return true;
  }

  statusLabel(status: AppointmentStatus): string {
    return { scheduled: 'Agendado', in_progress: 'Em atendimento', completed: 'Concluído',
      cancelled: 'Cancelado', no_show: 'Faltou' }[status];
  }

  dailyHours(professional: Professional, day: string): string {
    const effective = this.effectiveHours.find(h => h.professional_id === professional.id && h.day === day);
    if (effective) return (effective.periods.length ? effective.periods.map(p => `${p.starts_at}–${p.ends_at}`).join(' · ') : 'Sem expediente') + (effective.reason ? ` (${effective.reason})` : '');
    const weekday = (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7;
    const periods = professional.work_periods.filter(period => period.weekday === weekday);
    return periods.length ? periods.map(period => `${period.starts_at}–${period.ends_at}`).join(' · ') : 'Sem expediente';
  }

  weeklyHours(professional: Professional): string {
    return professional.work_periods.length
      ? professional.work_periods.map(period => `${this.weekdays[period.weekday].slice(0, 3)} ${period.starts_at}–${period.ends_at}`).join(' · ')
      : 'Jornada ainda não definida';
  }

  serviceHours(service: Service): string {
    const team = this.professionals.filter(professional => professional.active && professional.service_ids.includes(service.id));
    if (!team.length) return 'Sem profissional disponível';
    const days = [...new Set(team.flatMap(professional => professional.work_periods.map(period => period.weekday)))].sort();
    return days.length ? days.map(day => {
      const ranges = [...new Set(team.flatMap(professional => professional.work_periods
        .filter(period => period.weekday === day).map(period => `${period.starts_at}–${period.ends_at}`)))].sort();
      return `${this.weekdays[day].slice(0, 3)} ${ranges.join(', ')}`;
    }).join(' · ') : 'Jornada ainda não definida';
  }

  agendaTeam(): Professional[] {
    return this.professionals.filter(professional => professional.active &&
      (!this.agendaProfessionalId || professional.id === this.agendaProfessionalId));
  }

  changeStatus(appointment: Appointment, status: AppointmentStatus): void {
    const shopId = this.shopContext.id;
    this.saving = true;
    this.clearMessages();
    this.api.updateStatus(appointment.id, status).subscribe({
      next: updated => {
        if (this.shopContext.id !== shopId) return;
        this.saving = false;
        this.notice = `Atendimento #${updated.id}: ${this.statusLabel(updated.status).toLowerCase()}.`;
        this.loadAppointments();
          },
      error: error => {
        if (this.shopContext.id !== shopId) return; this.saving = false; this.error = apiError(error); },
    });
  }

  openReschedule(appointment: Appointment): void {
    this.rescheduleId = appointment.id;
    this.rescheduleForm = { day: appointment.starts_at.slice(0, 10),
      time: appointment.starts_at.slice(11, 16), professional_id: appointment.professional_id };
    this.clearMessages();
  }

  saveReschedule(): void {
    const shopId = this.shopContext.id;
    if (this.saving) return;
    if (!this.rescheduleId || !this.rescheduleForm.professional_id || !this.rescheduleForm.day || !this.rescheduleForm.time) {
      this.error = 'Informe a nova data, o horário e o profissional.';
      return;
    }
    this.saving = true;
    this.clearMessages();
    this.api.reschedule(this.rescheduleId, {
      professional_id: this.rescheduleForm.professional_id,
      starts_at: this.localDateTime(this.rescheduleForm.day, this.rescheduleForm.time),
    }).subscribe({
      next: updated => {
        if (this.shopContext.id !== shopId) return;
        this.saving = false;
        this.rescheduleId = 0;
        this.agendaDay = updated.starts_at.slice(0, 10);
        this.notice = `Agendamento #${updated.id} reagendado para ${this.formatDay(updated.starts_at)} às ${this.formatTime(updated.starts_at)}.`;
        this.loadAppointments();
      },
      error: error => {
        if (this.shopContext.id !== shopId) return; this.saving = false; this.error = apiError(error); },
    });
  }

  saveBlock(): void {
    const shopId = this.shopContext.id;
    if (this.saving) return;
    const form = this.blockForm;
    if (!form.professional_id || !form.day || !form.starts_at || !form.ends_at) {
      this.error = 'Informe profissional, data e intervalo do bloqueio.';
      return;
    }
    if (form.ends_at <= form.starts_at) {
      this.error = 'O fim do bloqueio deve ser depois do início.';
      return;
    }
    this.saving = true;
    this.clearMessages();
    this.api.createBlock({ professional_id: form.professional_id,
      starts_at: this.localDateTime(form.day, form.starts_at),
      ends_at: this.localDateTime(form.day, form.ends_at), reason: form.reason }).subscribe({
      next: () => {
        if (this.shopContext.id !== shopId) return;
        this.saving = false;
        this.agendaDay = form.day;
        this.blockForm.reason = '';
        this.notice = 'Horário bloqueado.';
        this.loadAppointments();
      },
      error: error => {
        if (this.shopContext.id !== shopId) return; this.saving = false; this.error = apiError(error); },
    });
  }

  removeBlock(block: ScheduleBlock): void {
    const shopId = this.shopContext.id;
    this.saving = true;
    this.clearMessages();
    this.api.deleteBlock(block.id).subscribe({
      next: () => {
        if (this.shopContext.id !== shopId) return; this.saving = false; this.notice = 'Bloqueio removido.'; this.loadAppointments(); },
      error: error => {
        if (this.shopContext.id !== shopId) return; this.saving = false; this.error = apiError(error); },
    });
  }

  loadManualSlots(): void {
    const request = ++this.manualRequest;
    this.manualSlot = null;
    this.manualSlots = [];
    this.loadingManualSlots = false;
    this.manualSlotsError = '';
    if (!this.manualForm.service_id || !this.manualForm.day) return;
    if (this.manualForm.professional_id && !this.professionals.some(p => p.id === this.manualForm.professional_id
      && p.service_ids.includes(this.manualForm.service_id))) this.manualForm.professional_id = 0;
    this.loadingManualSlots = true;
    this.api.availability(this.manualForm.service_id, this.manualForm.day,
      this.manualForm.professional_id || undefined).subscribe({
      next: slots => { if (request === this.manualRequest) { this.manualSlots = slots; this.loadingManualSlots = false; } },
      error: error => { if (request === this.manualRequest) { this.manualSlotsError = apiError(error); this.loadingManualSlots = false; } },
    });
  }

  saveManualBooking(): void {
    const shopId = this.shopContext.id;
    if (this.saving) return;
    if (!this.manualSlot || !this.manualForm.customer_name.trim() || !this.manualForm.customer_phone.trim()) {
      this.error = 'Escolha um horário e informe nome e telefone.';
      return;
    }
    if (!this.validCustomer(this.manualForm.customer_name, this.manualForm.customer_phone)) return;
    this.saving = true;
    this.clearMessages();
    this.api.internalBooking({ service_id: this.manualForm.service_id, professional_id: this.manualSlot.professional_id,
      starts_at: this.manualSlot.starts_at, customer_name: this.manualForm.customer_name,
      customer_phone: this.manualForm.customer_phone }).subscribe({
      next: updated => {
        if (this.shopContext.id !== shopId) return;
        this.saving = false;
        this.agendaDay = updated.starts_at.slice(0, 10);
        this.manualForm.customer_name = '';
        this.manualForm.customer_phone = '';
        this.loadManualSlots();
        this.notice = `Agendamento #${updated.id} criado.`;
        this.loadAppointments();
      },
      error: error => {
        if (this.shopContext.id !== shopId) return; this.saving = false; this.error = apiError(error); this.loadManualSlots(); this.error = apiError(error); },
    });
  }

  private localDateTime(day: string, clock: string): string {
    const [year, month, date] = day.split('-').map(Number);
    const [hour, minute] = clock.split(':').map(Number);
    const desired = Date.UTC(year, month - 1, date, hour, minute);
    let instant = desired;
    for (let attempt = 0; attempt < 3; attempt++) {
      const parts = new Intl.DateTimeFormat('en-US', { timeZone: this.timezone, year: 'numeric',
        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
        .formatToParts(new Date(instant));
      const number = (type: string): number => Number(parts.find(part => part.type === type)?.value);
      const observed = Date.UTC(number('year'), number('month') - 1, number('day'), number('hour'), number('minute'));
      instant += desired - observed;
    }
    return new Date(instant).toISOString();
  }

  private dateInZone(instant: Date, zone: string): string {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: zone, year: 'numeric',
      month: '2-digit', day: '2-digit' }).formatToParts(instant);
    const value = (type: string): string => parts.find(part => part.type === type)?.value ?? '';
    return `${value('year')}-${value('month')}-${value('day')}`;
  }

  onBookingChange(): void {
    const request = ++this.availabilityRequest;
    this.selectedSlot = null;
    this.confirmed = null;
    this.slots = [];
    this.loadingSlots = false;
    this.slotsError = '';
    this.clearMessages();
    if (!this.booking.service_id || !this.booking.day) return;
    this.loadingSlots = true;
    this.api.availability(this.booking.service_id, this.booking.day, this.booking.professional_id || undefined).subscribe({
      next: slots => {
        if (request !== this.availabilityRequest) return;
        this.slots = slots;
        this.loadingSlots = false;
      },
      error: error => {
        if (request !== this.availabilityRequest) return;
        this.error = apiError(error);
        this.slotsError = apiError(error);
        this.loadingSlots = false;
      },
    });
  }

  onServiceChange(): void {
    if (this.booking.professional_id && !this.professionals.some(
      professional => professional.id === this.booking.professional_id && professional.service_ids.includes(this.booking.service_id))) {
      this.booking.professional_id = 0;
    }
    this.onBookingChange();
  }

  selectSlot(slot: Slot): void {
    if (this.saving) return;
    this.selectedSlot = slot;
    this.clearMessages();
  }

  confirmBooking(): void {
    const shopId = this.shopContext.id;
    if (this.saving || this.confirmed) return;
    if (!this.selectedSlot || !this.booking.customer_name.trim() || !this.booking.customer_phone.trim()) {
      this.error = 'Escolha um horário e informe nome e telefone.';
      return;
    }
    if (!this.validCustomer(this.booking.customer_name, this.booking.customer_phone)) return;
    this.saving = true;
    this.clearMessages();
    this.api.book({
      service_id: this.booking.service_id,
      professional_id: this.selectedSlot.professional_id,
      starts_at: this.selectedSlot.starts_at,
      customer_name: this.booking.customer_name,
      customer_phone: this.booking.customer_phone,
      customer_email: this.booking.customer_email.trim() || null,
    }).subscribe({
      next: appointment => {
        if (this.shopContext.id !== shopId) return;
        this.confirmed = appointment;
        this.selectedSlot = null;
        this.saving = false;
        ++this.availabilityRequest;
        this.slots = [];
        this.loadingSlots = false;
        this.notice = `Agendamento #${appointment.id} confirmado.`;
      },
      error: error => {
        if (this.shopContext.id !== shopId) return;
        this.saving = false;
        this.error = apiError(error);
        this.onBookingChange();
        this.error = apiError(error);
      },
    });
  }

  reservationLink(): string { return this.confirmed?.manage_token ? window.location.origin + window.location.pathname + '#shop=' + this.shopContext.id + '&reservation=' + encodeURIComponent(this.confirmed.manage_token) : ''; }
  openPayment(appointment: Appointment): void { this.paymentAppointmentId = appointment.id; this.setTab('finance'); }
  selectGridAppointment(appointment: Appointment): void {
    this.agendaLayout = 'list';
    if (appointment.status === 'scheduled') this.openReschedule(appointment);
    setTimeout(() => document.getElementById('appointment-' + appointment.id)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0);
  }

  serviceName(id: number): string { return this.services.find(service => service.id === id)?.name ?? 'Serviço'; }
  selectedService(): Service | undefined { return this.services.find(service => service.id === this.booking.service_id); }
  startNewBooking(): void {
    this.booking.customer_name = '';
    this.booking.customer_phone = '';
    this.booking.customer_email = '';
    this.onBookingChange();
  }
  get bookingStep(): number {
    if (this.confirmed) return 4;
    if (this.selectedSlot) return 3;
    if (this.booking.service_id) return 2;
    return 1;
  }
  formatDay(value: string): string {
    const [year, month, day] = value.slice(0, 10).split('-');
    return year && month && day ? `${day}/${month}/${year}` : value;
  }
  formatTime(value: string): string { return value.slice(11, 16); }
}
