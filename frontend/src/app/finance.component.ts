import { ChangeDetectionStrategy, Component, Input, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DailyFinance, ManagementService, PaymentMethod } from './management.service';
import { AuthService } from './auth.service';
import { apiError } from './api.service';

@Component({ changeDetection: ChangeDetectionStrategy.Eager, selector: 'app-finance', standalone: true, imports: [CommonModule, FormsModule], styleUrl: './management.css', template: `
  <section class="panel"><h2>Financeiro e caixa</h2><div class="toolbar"><label>Dia<input type="date" [(ngModel)]="day" [max]="today" (change)="load()"></label><button (click)="load()">Atualizar</button></div>
  @if (error) { <p role="alert" class="message error">{{ error }}</p> } @if (notice) { <p role="status" class="message">{{ notice }}</p> }
  @if (loading) { <p role="status">Consultando caixa…</p> }
  @if (data && !loading) {
    <div class="metrics"><div class="metric"><span>Recebido</span><strong>{{ data.received | currency:'BRL' }}</strong></div><div class="metric"><span>Despesas</span><strong>{{ data.expenses_total | currency:'BRL' }}</strong></div><div class="metric"><span>Comissões provisionadas</span><strong>{{ data.commissions | currency:'BRL' }}</strong></div><div class="metric"><span>Saldo de movimentos em dinheiro</span><strong>{{ data.cash_expected | currency:'BRL' }}</strong></div></div>
    <div class="row">@for (method of methods; track method.key) { <p>{{ method.label }}: {{ data.by_method[method.key] | currency:'BRL' }}</p> }</div>
    @if (data.close) { <p class="message">Caixa fechado. Contado: {{ data.close.counted | currency:'BRL' }} · Diferença: {{ data.close.difference | currency:'BRL' }}<br>{{ data.close.notes }}</p> }
    <h3>Atendimentos concluídos pendentes de pagamento</h3>
    <div class="table-wrap"><table><thead><tr><th>Reserva</th><th>Cliente / serviço</th><th>Valor</th><th>Ação</th></tr></thead><tbody>@for (item of data.pending; track item.id) { <tr><td>#{{ item.id }}</td><td>{{ item.customer_name }}<small>{{ item.service_name }}</small></td><td>{{ item.price | currency:'BRL' }}</td><td><button [disabled]="busy" (click)="paymentId = item.id">Receber</button></td></tr> } @empty { <tr><td colspan="4">Nenhum pagamento pendente para os atendimentos deste dia.</td></tr> }</tbody></table></div>
    @if (paymentId) { <form class="stack panel" (ngSubmit)="pay()"><h3>Receber reserva #{{ paymentId }}</h3><p>O recebimento será lançado no caixa de hoje.</p><div class="row"><label>Forma<select name="paymentMethod" [(ngModel)]="payment.method">@for (method of methods; track method.key) { <option [value]="method.key">{{ method.label }}</option> }</select></label><label>Desconto (R$)<input name="discount" type="number" min="0" step="0.01" required [(ngModel)]="payment.discount"></label><label>Comissão (%)<input name="commission" type="number" min="0" max="100" step="0.01" required [(ngModel)]="payment.commission_percent"></label></div><div class="row"><button [disabled]="busy">Registrar pagamento</button><button type="button" class="secondary" (click)="paymentId = 0">Cancelar</button></div></form> }
    <div class="columns">
      <div><h3>Recebimentos</h3>@for (item of data.payments; track item.id) { <p>#{{ item.appointment_id }} · {{ methodLabel(item.method) }} · {{ item.amount | currency:'BRL' }}<small>Desconto {{ item.discount | currency:'BRL' }} · Comissão {{ item.commission | currency:'BRL' }}</small></p> } @empty { <p>Sem recebimentos.</p> }</div>
      <div><h3>Despesas</h3>@for (item of data.expenses; track item.id) { <p>{{ item.description }} · {{ item.amount | currency:'BRL' }}<small>{{ methodLabel(item.method) }}</small></p> } @empty { <p>Sem despesas.</p> }</div>
    </div>
    @if (day === today && !data.close) { <form class="stack panel" (ngSubmit)="saveExpense()"><h3>Registrar despesa de hoje</h3><label>Descrição<input name="description" [(ngModel)]="expense.description" required minlength="2" maxlength="200"></label><div class="row"><label>Valor (R$)<input name="amount" type="number" min="0.01" step="0.01" [(ngModel)]="expense.amount" required></label><label>Forma<select name="expenseMethod" [(ngModel)]="expense.method">@for (method of methods; track method.key) { <option [value]="method.key">{{ method.label }}</option> }</select></label></div><button [disabled]="busy">Registrar despesa</button></form> }
    @if (auth.canManage && !data.close) { <form class="stack panel" (ngSubmit)="close()"><h3>Fechar caixa de {{ day }}</h3><p>O fechamento impede novos lançamentos neste dia. Conte apenas o dinheiro dos movimentos do sistema, sem o fundo de troco.</p><label>Dinheiro contado (R$)<input name="counted" type="number" min="0" step="0.01" required [(ngModel)]="cashCounted"></label><label>Observações<textarea name="notes" [(ngModel)]="closeNotes" maxlength="1000"></textarea></label><label><span><input type="checkbox" name="closeConfirm" [(ngModel)]="closeConfirmed" required> Conferi os valores e quero fechar o caixa.</span></label><button [disabled]="busy || !closeConfirmed">Fechar caixa</button></form> }
  }</section>` })
export class FinanceComponent implements OnInit {
  private readonly api = inject(ManagementService); readonly auth = inject(AuthService);
  @Input() today = ''; @Input() day = ''; @Input() paymentId = 0;
  readonly methods: { key: PaymentMethod; label: string }[] = [{ key: 'cash', label: 'Dinheiro' }, { key: 'pix', label: 'Pix' }, { key: 'credit', label: 'Crédito' }, { key: 'debit', label: 'Débito' }];
  data: DailyFinance | null = null; loading = false; busy = false; error = ''; notice = ''; private request = 0;
  payment = { method: 'pix' as PaymentMethod, discount: '0', commission_percent: '0' };
  expense = { description: '', amount: '', method: 'cash' as PaymentMethod };
  cashCounted = '0'; closeNotes = ''; closeConfirmed = false;
  ngOnInit(): void { this.load(); }
  methodLabel(method: PaymentMethod): string { return this.methods.find(m => m.key === method)?.label ?? method; }
  load(): void {
    const request = ++this.request; this.loading = true; this.error = ''; this.data = null; this.closeConfirmed = false;
    this.api.daily(this.day).subscribe({ next: data => { if (request === this.request) { this.data = data; this.loading = false; } }, error: error => { if (request === this.request) { this.error = apiError(error); this.loading = false; } } });
  }
  pay(): void { if (this.busy) return; this.busy = true; this.error = ''; this.api.pay(this.paymentId, { ...this.payment, discount: String(this.payment.discount), commission_percent: String(this.payment.commission_percent) }).subscribe({ next: () => { this.busy = false; this.paymentId = 0; this.notice = 'Pagamento registrado no caixa de hoje.'; this.load(); }, error: error => this.failed(error) }); }
  saveExpense(): void { if (this.busy) return; this.busy = true; this.api.expense({ ...this.expense, amount: String(this.expense.amount) }).subscribe({ next: () => { this.busy = false; this.expense.description = ''; this.expense.amount = ''; this.notice = 'Despesa registrada.'; this.load(); }, error: error => this.failed(error) }); }
  close(): void { if (this.busy || !this.closeConfirmed) return; this.busy = true; this.api.close({ day: this.day, cash_counted: String(this.cashCounted), notes: this.closeNotes }).subscribe({ next: data => { this.busy = false; this.data = data; this.notice = 'Caixa fechado.'; }, error: error => this.failed(error) }); }
  private failed(error: unknown): void { this.busy = false; this.error = apiError(error); }
}
