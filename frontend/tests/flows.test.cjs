const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { Subject, of, forkJoin } = require('rxjs');
class AuthService {}

// Exercise the component's flow logic without a browser or live database.
function component(api = {}, kind = 'app') {
  api.agendaHours ??= () => of([]);
  const source = fs.readFileSync(path.join(__dirname, `../src/app/${kind}.component.ts`), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, experimentalDecorators: true },
  }).outputText;
  const context = {
    exports: {}, sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    Intl, Date, URLSearchParams, window: { location: { hash: '', origin: 'http://localhost:4200', pathname: '/' } },
    require(name) {
      if (name === '@angular/core') return { ChangeDetectionStrategy: { Eager: 1 }, Input: () => () => {}, Output: () => () => {}, EventEmitter: class { emit() {} }, HostListener: () => () => {}, Component: () => target => target, inject: token => token === AuthService ? { user: () => ({ role: 'admin' }), canFinance: true, canManage: true } : api };
      if (name === '@angular/common') return { CommonModule: {} };
      if (name === '@angular/forms') return { FormsModule: {} };
      if (name === 'rxjs') return { forkJoin: sources => forkJoin(Object.fromEntries(Object.entries(sources))) };
      if (name === './api.service') return { ApiService: {}, apiError: () => 'Falha na consulta' };
      if (name === './auth.service') return { AuthService };
      if (name.endsWith('.component')) return {};
      throw new Error(name);
    },
  };
  vm.runInNewContext(compiled, context);
  return new context.exports[kind === 'app' ? 'AppComponent' : 'CatalogComponent']();
}

test('agenda ignores an older response after the user changes the day', () => {
  const requests = [new Subject(), new Subject()];
  let index = 0;
  const app = component({ appointments: () => requests[index++], blocks: () => of([]) });
  app.activeProfessionalId = 1;
  app.loadAppointments();
  app.agendaDay = '2026-10-07';
  app.loadAppointments();
  requests[1].next([{ id: 2 }]); requests[1].complete();
  requests[0].next([{ id: 1 }]); requests[0].complete();
  assert.equal(app.appointments[0].id, 2);
  assert.equal(app.loadingAgenda, false);
});

test('switching professional prevents pending agenda data from reappearing', () => {
  const pending = new Subject();
  const app = component({ appointments: () => pending, blocks: () => of([]) });
  app.activeProfessionalId = 1;
  app.loadAppointments();
  app.switchProfessional();
  pending.next([{ id: 1 }]); pending.complete();
  assert.equal(app.appointments.length, 0);
  assert.equal(app.loadingAgenda, false);
});

test('confirmed booking stays confirmed and cannot submit twice', () => {
  let calls = 0;
  const app = component({ book: () => { calls++; return of({ id: 3 }); } });
  app.booking.customer_name = 'Ana';
  app.booking.customer_phone = '(85) 99999-9999';
  app.selectedSlot = { professional_id: 1, starts_at: '2026-10-07T10:00:00-03:00' };
  app.confirmBooking();
  app.confirmBooking();
  assert.equal(app.confirmed.id, 3);
  assert.equal(calls, 1);
  assert.equal(app.selectedSlot, null);
});

test('refreshing administrative data preserves the unsaved work periods', () => {
  const app = component({ services: () => of([]), professionals: () => of([{ id: 1, active: true, work_periods: [] }]) }, 'catalog');
  app.tab = 'professionals';
  app.activeProfessionalId = app.selectedProfessionalId = 1;
  app.periods = [{ weekday: 0, starts_at: '09:00', ends_at: '12:00' }];
  app.loadAppointments = app.loadCustomers = () => {};
  app.loadAdmin();
  assert.equal(app.periods.length, 1);
});

test('an empty work schedule can be saved', () => {
  let saved;
  const app = component({ savePeriods: (id, periods) => { saved = periods; return of({ id, work_periods: [] }); } }, 'catalog');
  app.selectedProfessionalId = 1;
  app.loadAdmin = () => {};
  app.savePeriods();
  assert.equal(saved.length, 0);
  assert.equal(app.saving, false);
});

test('invalid customer phone and inverted block interval do not reach the API', () => {
  const app = component();
  app.booking.customer_name = 'Ana'; app.booking.customer_phone = '123';
  app.selectedSlot = { professional_id: 1 };
  app.confirmBooking();
  assert.match(app.error, /DDD/);
  app.blockForm.professional_id = 1;
  app.blockForm.starts_at = '13:00'; app.blockForm.ends_at = '12:00';
  app.saveBlock();
  assert.match(app.error, /depois do início/);
});

test('agenda navigation moves by one day or one week across month boundaries', () => {
  const app = component(); app.loadAppointments = () => {};
  app.agendaDay = '2026-10-31';
  app.moveAgenda(1);
  assert.equal(app.agendaDay, '2026-11-01');
  app.agendaView = 'week'; app.moveAgenda(-1);
  assert.equal(app.agendaDay, '2026-10-25');
});
