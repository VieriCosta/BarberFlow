import { ChangeDetectionStrategy, Component, Input, Output, EventEmitter, OnChanges, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService, Appointment, AppointmentStatus, Customer, Professional, Service, WorkPeriod, apiError } from './api.service';
import { AuthService } from './auth.service';

@Component({ selector: 'app-catalog', standalone: true, changeDetection: ChangeDetectionStrategy.Eager,
  imports: [CommonModule, FormsModule], templateUrl: './catalog.component.html', styleUrl: './app.component.css' })
export class CatalogComponent implements OnChanges {
  readonly api = inject(ApiService);
  readonly auth = inject(AuthService);
  @Input() services: Service[] = [];
  @Input() professionals: Professional[] = [];
  @Input() today = '';
  @Input() tab: 'services' | 'professionals' | 'customers' = 'services';
  @Output() changed = new EventEmitter<void>();
  saving = false; notice = ''; error = '';
  ngOnChanges(): void { if (this.tab === 'customers') this.loadCustomers(); }
  loadAdmin(refreshPeriods = false): void {
    this.api.services().subscribe({ next: rows => this.services = rows, error: error => this.error = apiError(error) });
    this.api.professionals().subscribe({ next: rows => { this.professionals = rows; if (refreshPeriods && this.selectedProfessionalId) this.selectProfessional(this.selectedProfessionalId); }, error: error => this.error = apiError(error) });
    this.changed.emit();
  }
  readonly weekdays = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];

  loadingCustomerHistory = false;

  customerHistoryError = '';

  customers: Customer[] = [];

  customerHistory: Appointment[] = [];

  private customerHistoryRequest = 0;

  customerSearch = '';

  newService = { name: '', description: '', price: 0, duration_minutes: 30 };

  editingServiceId = 0;

  newProfessional = { name: '', service_ids: [] as number[] };

  editingProfessionalId = 0;

  editingCustomerId = 0;

  customerForm = { name: '', phone: '', email: '', notes: '' };

  selectedProfessionalId = 0;

  periods: WorkPeriod[] = [];

  hasActiveProfessionals(): boolean {
    return this.professionals.some(professional => professional.active);
  }

  clearMessages(): void { this.notice = ''; this.error = ''; }

  loadCustomers(): void {
    this.api.customers().subscribe({
      next: customers => this.customers = customers,
      error: error => this.error = apiError(error),
    });
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
        this.cancelServiceEdit();
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

  formatDay(value: string): string {
    const [year, month, day] = value.slice(0, 10).split('-');
    return year && month && day ? `${day}/${month}/${year}` : value;
  }

  formatTime(value: string): string { return value.slice(11, 16); }
}
