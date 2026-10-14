import { ChangeDetectionStrategy, Component, EventEmitter, OnInit, Output, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BarbershopsService } from './barbershops.service';
import { AuthService } from './auth.service';
import { Barbershop, ShopContext, ShopRegistration } from './shop-context.service';
import { apiError } from './api.service';

@Component({ selector: 'app-directory', standalone: true, changeDetection: ChangeDetectionStrategy.Eager,
  imports: [FormsModule], templateUrl: './directory.component.html', styleUrl: './directory.component.css' })
export class DirectoryComponent implements OnInit {
  private readonly api = inject(BarbershopsService);
  private readonly auth = inject(AuthService);
  private readonly context = inject(ShopContext);
  @Output() chosen = new EventEmitter<Barbershop>();
  @Output() registered = new EventEmitter<Barbershop>();
  @Output() teamChosen = new EventEmitter<Barbershop>();
  shops: Barbershop[] = []; query = ''; loading = false; error = ''; hasMore = false;
  registering = false; teamAccess = false; busy = false; code = ''; private request = 0;
  form: ShopRegistration = { name: '', description: '', city: '', address: '', phone: '', owner_name: '', username: '', password: '' };
  ngOnInit(): void { this.search(); }
  search(more = false): void {
    const request = ++this.request; this.loading = true; this.error = '';
    this.api.list(this.query, more ? this.shops.length : 0).subscribe({ next: result => {
      if (request !== this.request) return;
      this.shops = more ? [...this.shops, ...result.items] : result.items;
      this.hasMore = result.has_more; this.loading = false;
    }, error: error => { if (request === this.request) { this.loading = false; this.error = apiError(error); } } });
  }
  register(): void {
    if (this.busy) return; this.busy = true; this.error = '';
    this.api.register(this.form).subscribe({ next: result => {
      this.busy = false; this.form.password = ''; this.context.select(result.shop); this.auth.accept(result); this.registered.emit(result.shop);
    }, error: error => { this.busy = false; this.form.password = ''; this.error = apiError(error); } });
  }
  openTeam(): void {
    if (this.busy || !this.code.trim()) return;
    this.busy = true; this.error = '';
    this.api.byCode(this.code.trim()).subscribe({ next: shop => { this.busy = false; this.teamChosen.emit(shop); }, error: error => { this.busy = false; this.error = apiError(error); } });
  }
}
