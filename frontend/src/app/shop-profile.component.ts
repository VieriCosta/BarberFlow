import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BarbershopsService } from './barbershops.service';
import { ShopContext } from './shop-context.service';
import { apiError } from './api.service';

@Component({ selector: 'app-shop-profile', standalone: true, changeDetection: ChangeDetectionStrategy.Eager,
  imports: [FormsModule], styleUrl: './management.css', template: `
  <section class="panel"><h2>Sua barbearia no BarberFlow</h2><p>{{ form.published ? 'Sua barbearia aparece na lista dos clientes e pode receber agendamentos.' : 'Cadastre os serviços, os profissionais e uma jornada. Depois publique para aparecer na lista dos clientes.' }}</p>
    @if (error) { <p role="alert" class="message error">{{ error }}</p> } @if (notice) { <p role="status" class="message">{{ notice }}</p> }
    @if (loading) { <p role="status">Carregando dados da barbearia…</p> } @else {
      <form class="stack" (ngSubmit)="save()"><label>Nome da barbearia<input name="shopName" [(ngModel)]="form.name" required minlength="2" maxlength="120"></label><div class="row"><label>Cidade<input name="shopCity" [(ngModel)]="form.city" required minlength="2" maxlength="120"></label><label>Telefone com DDD<input name="shopPhone" type="tel" [(ngModel)]="form.phone" required></label></div><label>Endereço<input name="shopAddress" [(ngModel)]="form.address" required minlength="2" maxlength="200"></label><label>Sobre a barbearia<textarea name="shopDescription" [(ngModel)]="form.description" rows="3" maxlength="500"></textarea></label><label><span><input type="checkbox" name="published" [(ngModel)]="form.published"> Publicar minha barbearia na lista dos clientes</span></label><button [disabled]="busy">{{ busy ? 'Salvando…' : 'Salvar dados da barbearia' }}</button></form>
      <div class="message"><strong>Acesso da equipe</strong><p>Código da barbearia: <strong>{{ code }}</strong></p><a [href]="teamLink()">{{ teamLink() }}</a><small>Compartilhe esse código ou link com a sua equipe. Cada pessoa entra com o próprio usuário e senha.</small></div>
    }
  </section>` })
export class ShopProfileComponent implements OnInit {
  private readonly api = inject(BarbershopsService); readonly context = inject(ShopContext);
  loading = false; busy = false; error = ''; notice = ''; code = '';
  form = { name: '', city: '', address: '', phone: '', description: '', published: false };
  ngOnInit(): void { this.loading = true; this.api.profile().subscribe({ next: shop => { const { id, slug, ...form } = shop; this.form = form; this.code = slug; this.loading = false; }, error: error => { this.loading = false; this.error = apiError(error); } }); }
  teamLink(): string { return window.location.origin + window.location.pathname + '#shop=' + this.context.id + '&team=1'; }
  save(): void { if (this.busy) return; this.busy = true; this.error = ''; this.api.saveProfile(this.form).subscribe({ next: shop => { this.context.select(shop); this.busy = false; this.notice = shop.published ? 'Sua barbearia está no ar! Os clientes já podem encontrá-la e agendar.' : 'Dados salvos. Sua barbearia está em configuração.'; }, error: error => { this.busy = false; this.error = apiError(error); } }); }
}
