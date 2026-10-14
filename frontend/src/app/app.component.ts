import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { AgendaView, ApiService, Appointment, AppointmentStatus, Customer, Professional, ScheduleBlock, Service, Slot, WorkPeriod, apiError } from './api.service';

type Tab = 'entry' | 'booking' | 'agenda' | 'services' | 'professionals' | 'customers';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnInit {
  readonly api = inject(ApiService);
  readonly weekdays = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
  tab: Tab = sessionStorage.getItem('barberflow-professional-id') ? 'agenda' : 'entry';
  activeProfessionalId = Number(sessionStorage.getItem('barberflow-professional-id')) || 0;
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
  loadingCustomerHistory = false;
  customerHistoryError = '';
  customers: Customer[] = [];
  customerHistory: Appointment[] = [];
  private customerHistoryRequest = 0;
  customerSearch = '';
  slots: Slot[] = [];
  loadingSlots = false;
  slotsError = '';
  private availabilityRequest = 0;
  appointments: Appointment[] = [];
  timezone = 'America/Fortaleza';
  blocks: ScheduleBlock[] = [];
  agendaView: AgendaView = 'day';
  agendaProfessionalId = this.activeProfessionalId;
  private agendaRequest = 0;
  today = (() => {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Fortaleza', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    const get = (type: string): string => parts.find(part => part.type === type)?.value ?? '';
    return `${get('year')}-${get('month')}-${get('day')}`;
  })();
  booking = { service_id: 0, professional_id: 0, day: this.today, customer_name: '', customer_phone: '' };
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
  newService = { name: '', description: '', price: 0, duration_minutes: 30 };
  editingServiceId = 0;
  newProfessional = { name: '', service_ids: [] as number[] };
  editingProfessionalId = 0;
  editingCustomerId = 0;
  customerForm = { name: '', phone: '', email: '', notes: '' };
  selectedProfessionalId = this.activeProfessionalId;
  periods: WorkPeriod[] = [];

  ngOnInit(): void {
    sessionStorage.removeItem('barberflow-admin-key');
    this.api.publicConfig().subscribe({ next: config => {
      const previous = this.today;
      this.timezone = config.timezone;
      this.today = this.dateInZone(new Date(), this.timezone);
      if (this.booking.day === previous) this.booking.day = this.today;
      if (this.agendaDay === previous) this.agendaDay = this.today;
      if (this.blockForm.day === previous) this.blockForm.day = this.today;
      if (this.manualForm.day === previous) this.manualForm.day = this.today;
    }});
    this.loadPublic();
  }

  setTab(tab: Tab): void {
    this.tab = tab;
    this.clearMessages();
    if (tab !== 'booking' && tab !== 'entry' && this.activeProfessionalId) this.loadAdmin();
  }

  enterAsProfessional(): void {
    if (this.choiceProfessionalId === -1 && !this.professionals.some(p => p.active)) {
      this.activeProfessionalId = -1;
      sessionStorage.setItem('barberflow-professional-id', '-1');
      this.agendaProfessionalId = 0;
      this.tab = this.services.some(service => service.active) ? 'professionals' : 'services';
      this.notice = 'Cadastre o primeiro serviço e barbeiro para começar.';
      this.error = '';
      this.loadAdmin();
      return;
    }
    const professional = this.professionals.find(p => p.id === this.choiceProfessionalId && p.active);
    if (!professional) { this.error = 'Escolha um barbeiro ativo para entrar.'; return; }
    this.activeProfessionalId = professional.id;
    sessionStorage.setItem('barberflow-professional-id', String(professional.id));
    this.agendaProfessionalId = professional.id;
    this.blockForm.professional_id = professional.id;
    this.manualForm.professional_id = professional.id;
    this.selectProfessional(professional.id);
    this.tab = 'agenda';
    this.notice = `Você está vendo a barbearia como ${professional.name}.`;
    this.error = '';
    this.loadAdmin();
  }

  switchProfessional(): void {
    ++this.agendaRequest;
    ++this.manualRequest;
    ++this.customerHistoryRequest;
    this.loadingAgenda = false;
    this.loadingManualSlots = false;
    this.loadingCustomerHistory = false;
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
    this.api.publicServices().subscribe({
      next: services => { this.services = services; this.loadingServices = false; },
      error: error => { this.loadingServices = false; this.error = apiError(error); },
    });
    this.api.publicProfessionals().subscribe({
      next: professionals => {
        this.loadingProfessionals = false;
        this.professionals = professionals;
        if (this.activeProfessionalId > 0 && !professionals.some(p => p.id === this.activeProfessionalId))
          this.switchProfessional();
        else if (this.activeProfessionalId > 0) this.selectProfessional(this.activeProfessionalId);
        if (this.activeProfessionalId && this.tab !== 'entry' && this.tab !== 'booking') this.loadAdmin();
      },
      error: error => { this.loadingProfessionals = false; this.error = apiError(error); },
    });
  }

  loadAdmin(refreshPeriods = false): void {
    this.api.services().subscribe({
      next: services => this.services = services,
      error: error => this.error = apiError(error),
    });
    this.api.professionals().subscribe({
      next: professionals => {
        this.professionals = professionals;
        if (this.activeProfessionalId > 0 && !professionals.some(p => p.id === this.activeProfessionalId && p.active))
          this.switchProfessional();
        else if (this.selectedProfessionalId && (refreshPeriods || this.tab !== 'professionals')) this.selectProfessional(this.selectedProfessionalId);
      },
      error: error => this.error = apiError(error),
    });
    this.loadAppointments();
    this.loadCustomers();
  }

  loadCustomers(): void {
    this.api.customers().subscribe({
      next: customers => this.customers = customers,
      error: error => this.error = apiError(error),
    });
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
    }).subscribe({
      next: result => {
        if (request !== this.agendaRequest) return;
        this.appointments = result.appointments;
        this.blocks = result.blocks;
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
    this.saving = true;
    this.clearMessages();
    this.api.updateStatus(appointment.id, status).subscribe({
      next: updated => {
        this.saving = false;
        this.notice = `Atendimento #${updated.id}: ${this.statusLabel(updated.status).toLowerCase()}.`;
        this.loadAppointments();
        this.loadCustomers();
      },
      error: error => { this.saving = false; this.error = apiError(error); },
    });
  }

  openReschedule(appointment: Appointment): void {
    this.rescheduleId = appointment.id;
    this.rescheduleForm = { day: appointment.starts_at.slice(0, 10),
      time: appointment.starts_at.slice(11, 16), professional_id: appointment.professional_id };
    this.clearMessages();
  }

  saveReschedule(): void {
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
        this.saving = false;
        this.rescheduleId = 0;
        this.agendaDay = updated.starts_at.slice(0, 10);
        this.notice = `Agendamento #${updated.id} reagendado para ${this.formatDay(updated.starts_at)} às ${this.formatTime(updated.starts_at)}.`;
        this.loadAppointments();
      },
      error: error => { this.saving = false; this.error = apiError(error); },
    });
  }

  saveBlock(): void {
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
        this.saving = false;
        this.agendaDay = form.day;
        this.blockForm.reason = '';
        this.notice = 'Horário bloqueado.';
        this.loadAppointments();
      },
      error: error => { this.saving = false; this.error = apiError(error); },
    });
  }

  removeBlock(block: ScheduleBlock): void {
    this.saving = true;
    this.clearMessages();
    this.api.deleteBlock(block.id).subscribe({
      next: () => { this.saving = false; this.notice = 'Bloqueio removido.'; this.loadAppointments(); },
      error: error => { this.saving = false; this.error = apiError(error); },
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
        this.saving = false;
        this.agendaDay = updated.starts_at.slice(0, 10);
        this.manualForm.customer_name = '';
        this.manualForm.customer_phone = '';
        this.loadManualSlots();
        this.notice = `Agendamento #${updated.id} criado.`;
        this.loadAppointments();
        this.loadCustomers();
      },
      error: error => { this.saving = false; this.error = apiError(error); this.loadManualSlots(); this.error = apiError(error); },
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
    }).subscribe({
      next: appointment => {
        this.confirmed = appointment;
        this.selectedSlot = null;
        this.saving = false;
        ++this.availabilityRequest;
        this.slots = [];
        this.loadingSlots = false;
        this.notice = `Agendamento #${appointment.id} confirmado.`;
      },
      error: error => {
        this.saving = false;
        this.error = apiError(error);
        this.onBookingChange();
        this.error = apiError(error);
      },
    });
  }

  addService(): void {
    if (this.saving) return;
    if (this.newService.name.trim().length < 2 || !Number.isFinite(this.newService.price) || this.newService.price < 0
      || !Number.isInteger(this.newService.duration_minutes) || this.newService.duration_minutes < 1 || this.newService.duration_minutes > 480) {
      this.error = 'Informe um nome válido, preço a partir de R$ 0 e duração de 1 a 480 minutos.';
      return;
    }
    this.saving = true;
    this.clearMessages();
    const request = this.editingServiceId
      ? this.api.updateService(this.editingServiceId, this.newService)
      : this.api.createService(this.newService);
    request.subscribe({
      next: service => {
        this.saving = false;
        this.notice = `Serviço ${service.name} ${this.editingServiceId ? 'atualizado' : 'cadastrado'}.`;
        const firstSetupService = this.activeProfessionalId === -1 && !this.hasActiveProfessionals() && !this.editingServiceId;
        this.cancelServiceEdit();
        if (firstSetupService) {
          this.tab = 'professionals';
          this.notice = `Serviço ${service.name} cadastrado. Agora cadastre o primeiro barbeiro.`;
        }
        this.loadAdmin();
      },
      error: error => { this.saving = false; this.error = apiError(error); },
    });
  }

  editService(service: Service): void {
    this.editingServiceId = service.id;
    this.newService = { name: service.name, description: service.description,
      price: Number(service.price), duration_minutes: service.duration_minutes };
    this.clearMessages();
  }

  cancelServiceEdit(): void {
    this.editingServiceId = 0;
    this.newService = { name: '', description: '', price: 0, duration_minutes: 30 };
  }

  changeServiceActive(service: Service): void {
    this.clearMessages();
    this.api.updateService(service.id, { active: !service.active }).subscribe({
      next: updated => { this.notice = `${updated.name} ${updated.active ? 'reativado' : 'inativado'}.`; this.loadAdmin(); },
      error: error => this.error = apiError(error),
    });
  }

  toggleService(id: number, checked: boolean): void {
    this.newProfessional.service_ids = checked
      ? [...this.newProfessional.service_ids, id]
      : this.newProfessional.service_ids.filter(value => value !== id);
  }

  addProfessional(): void {
    if (this.saving) return;
    if (this.newProfessional.name.trim().length < 2) { this.error = 'Informe o nome do profissional com pelo menos 2 caracteres.'; return; }
    if (!this.newProfessional.service_ids.length) {
      this.error = 'Selecione pelo menos um serviço.';
      return;
    }
    this.saving = true;
    this.clearMessages();
    const request = this.editingProfessionalId
      ? this.api.updateProfessional(this.editingProfessionalId, this.newProfessional)
      : this.api.createProfessional(this.newProfessional);
    request.subscribe({
      next: professional => {
        this.saving = false;
        this.notice = `${professional.name} ${this.editingProfessionalId ? 'atualizado' : 'cadastrado'}.`;
        if (this.activeProfessionalId === -1) {
          this.activeProfessionalId = professional.id;
          this.choiceProfessionalId = professional.id;
          this.agendaProfessionalId = professional.id;
          this.blockForm.professional_id = professional.id;
          this.manualForm.professional_id = professional.id;
          sessionStorage.setItem('barberflow-professional-id', String(professional.id));
          this.notice = `${professional.name} cadastrado. Defina os horários na jornada de trabalho.`;
        }
        this.cancelProfessionalEdit();
        this.selectedProfessionalId = professional.id;
        this.loadAdmin(true);
      },
      error: error => { this.saving = false; this.error = apiError(error); },
    });
  }

  editProfessional(professional: Professional): void {
    this.editingProfessionalId = professional.id;
    this.newProfessional = { name: professional.name, service_ids: [...professional.service_ids] };
    this.clearMessages();
  }

  cancelProfessionalEdit(): void {
    this.editingProfessionalId = 0;
    this.newProfessional = { name: '', service_ids: [] };
  }

  changeProfessionalActive(professional: Professional): void {
    this.clearMessages();
    this.api.updateProfessional(professional.id, { active: !professional.active }).subscribe({
      next: updated => { this.notice = `${updated.name} ${updated.active ? 'reativado' : 'inativado'}.`; this.loadAdmin(); },
      error: error => this.error = apiError(error),
    });
  }

  filteredCustomers(): Customer[] {
    const query = this.customerSearch.trim().toLocaleLowerCase('pt-BR');
    const digits = query.replace(/\D/g, '');
    if (!query) return this.customers;
    return this.customers.filter(customer => customer.name.toLocaleLowerCase('pt-BR').includes(query)
      || (digits.length >= 3 && customer.phone.includes(digits)));
  }

  editCustomer(customer: Customer): void {
    const request = ++this.customerHistoryRequest;
    this.editingCustomerId = customer.id;
    this.customerForm = { name: customer.name, phone: customer.phone,
      email: customer.email ?? '', notes: customer.notes };
    this.customerHistory = [];
    this.loadingCustomerHistory = true;
    this.customerHistoryError = '';
    this.clearMessages();
    this.api.customerAppointments(customer.id).subscribe({
      next: appointments => { if (request === this.customerHistoryRequest) { this.customerHistory = appointments; this.loadingCustomerHistory = false; } },
      error: error => { if (request === this.customerHistoryRequest) { this.customerHistoryError = apiError(error); this.loadingCustomerHistory = false; } },
    });
  }

  newCustomer(): void {
    this.loadingCustomerHistory = false;
    ++this.customerHistoryRequest;
    this.editingCustomerId = 0;
    this.customerHistory = [];
    this.customerForm = { name: '', phone: '', email: '', notes: '' };
    this.clearMessages();
  }

  saveCustomer(): void {
    if (this.saving || !this.validCustomer(this.customerForm.name, this.customerForm.phone)) return;
    if (this.customerForm.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.customerForm.email.trim())) {
      this.error = 'Informe um e-mail válido ou deixe o campo vazio.';
      return;
    }
    this.saving = true;
    this.clearMessages();
    const payload = { ...this.customerForm, email: this.customerForm.email.trim() || null };
    const request = this.editingCustomerId
      ? this.api.updateCustomer(this.editingCustomerId, payload)
      : this.api.createCustomer(payload);
    request.subscribe({
      next: customer => {
        this.saving = false;
        const message = `Cliente ${customer.name} ${this.editingCustomerId ? 'atualizado' : 'cadastrado'}.`;
        this.editCustomer(customer);
        this.notice = message;
        this.loadCustomers();
      },
      error: error => { this.saving = false; this.error = apiError(error); },
    });
  }

  selectProfessional(id: number): void {
    this.selectedProfessionalId = id;
    this.periods = this.professionals.find(p => p.id === id)?.work_periods.map(period => ({ ...period })) ?? [];
  }

  addPeriod(): void { this.periods.push({ weekday: 0, starts_at: '09:00', ends_at: '18:00' }); }
  applyStandardPeriods(): void {
    this.periods = Array.from({ length: 6 }, (_, weekday) => [
      { weekday, starts_at: '09:00', ends_at: '12:00' },
      { weekday, starts_at: '13:00', ends_at: '18:00' },
    ]).flat();
  }
  removePeriod(index: number): void { this.periods.splice(index, 1); }

  savePeriods(): void {
    if (this.saving || !this.selectedProfessionalId) return;
    if (this.periods.some(period => !period.starts_at || !period.ends_at || period.ends_at <= period.starts_at)) {
      this.error = 'Em cada período, informe um fim depois do início.';
      return;
    }
    this.saving = true;
    this.clearMessages();
    this.api.savePeriods(this.selectedProfessionalId, this.periods).subscribe({
      next: professional => {
        this.saving = false;
        this.professionals = this.professionals.map(item => item.id === professional.id ? professional : item);
        this.selectProfessional(professional.id);
        this.notice = 'Jornada salva. Os horários já estão disponíveis para agendamento.';
        this.loadAdmin();
      },
      error: error => { this.saving = false; this.error = apiError(error); },
    });
  }

  serviceName(id: number): string { return this.services.find(service => service.id === id)?.name ?? 'Serviço'; }
  selectedService(): Service | undefined { return this.services.find(service => service.id === this.booking.service_id); }
  startNewBooking(): void {
    this.booking.customer_name = '';
    this.booking.customer_phone = '';
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
