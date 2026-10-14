import { test, expect, Page } from '@playwright/test';

async function login(page: Page, username: string) {
  await page.goto('/');
  await page.getByLabel('Usuário', { exact: true }).fill(username);
  await page.getByLabel('Senha', { exact: true }).fill('e2e-password-123');
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Agenda em movimento' })).toBeVisible();
}

test('customer books and cancels through a protected link', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Agendar horário' }).first().click();
  const service = page.getByLabel('Serviço', { exact: true });
  await expect(service.locator('option').filter({ hasText: 'Corte clássico (Demo)' })).toHaveCount(1);
  await service.selectOption((await service.locator('option').filter({ hasText: 'Corte clássico (Demo)' }).getAttribute('value'))!);
  const day = new Date(); day.setDate(day.getDate()+3); if (day.getDay() === 0) day.setDate(day.getDate()+1);
  await page.getByLabel('Data do atendimento').fill(day.toISOString().slice(0,10));
  await expect(page.locator('.slot')).not.toHaveCount(0);
  await page.locator('.slot').first().click();
  await page.getByLabel('Seu nome', { exact: true }).fill('Browser Customer');
  await page.getByLabel('Telefone com DDD', { exact: true }).fill('85977776666');
  await page.getByLabel('E-mail para confirmação (opcional)').fill('browser@example.com');
  await page.getByRole('button', { name: 'Confirmar agendamento' }).click();
  await expect(page.getByRole('heading', { name: 'Seu horário está confirmado.' })).toBeVisible();
  const link = await page.getByRole('link', { name: 'Consultar, cancelar ou reagendar minha reserva' }).getAttribute('href');
  expect(link).toContain('#reservation=');
  await page.goto(link!);
  await expect(page.getByRole('heading', { name: 'Sua reserva' })).toBeVisible();
  await page.getByRole('button', { name: 'Escolher novo horário' }).click();
  day.setDate(day.getDate()+2); if (day.getDay() === 0) day.setDate(day.getDate()+1);
  await page.getByLabel('Nova data').fill(day.toISOString().slice(0,10));
  await page.getByRole('button', { name: /^\d{2}:\d{2} ·/ }).first().click();
  await page.getByRole('button', { name: 'Confirmar novo horário' }).click();
  await expect(page.getByText('Reserva reagendada.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Cancelar reserva', exact: true }).click();
  await page.getByRole('button', { name: 'Sim, cancelar reserva' }).click();
  await expect(page.getByText('Reserva cancelada.', { exact: true })).toBeVisible();
});

test('administrator accesses dashboard, finance and settings without layout overflow', async ({ page }) => {
  await login(page, 'admin');
  await page.getByRole('button', { name: 'Painel', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Painel da barbearia' })).toBeVisible();
  await expect(page.getByText('Carregando indicadores…')).not.toBeVisible();
  await page.getByRole('button', { name: 'Financeiro', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Financeiro e caixa' })).toBeVisible();
  await expect(page.getByText('Consultando caixa…')).not.toBeVisible();
  await page.getByRole('button', { name: 'Configurações', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Usuários e permissões' })).toBeVisible();
  await expect(page.getByRole('cell').filter({ hasText: 'E2E reception' }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth+1)).toBeTruthy();
  await page.screenshot({ path: test.info().outputPath('settings.png'), fullPage: true });
  await page.getByRole('button', { name: 'Sair', exact: true }).click();
  await expect(page.getByLabel('Senha', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Configurações', exact: true })).toHaveCount(0);
});

test('barber sees only own agenda and session survives a reload', async ({ page }) => {
  await login(page, 'barber');
  await expect(page.getByRole('button', { name: 'Financeiro', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Serviços', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Configurações', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Profissional', { exact: true }).first()).toHaveValue(/1$/);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Agenda em movimento' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Financeiro', exact: true })).toHaveCount(0);
});

test('reception records an expense and cannot close the cash register', async ({ page }) => {
  await login(page, 'reception');
  await page.getByRole('button', { name: 'Financeiro', exact: true }).click();
  await page.getByLabel('Descrição', { exact: true }).fill('Browser expense');
  await page.getByLabel('Valor (R$)', { exact: true }).fill('5.00');
  await page.getByRole('button', { name: 'Registrar despesa', exact: true }).click();
  await expect(page.getByText('Despesa registrada.', { exact: true })).toBeVisible();
  await expect(page.getByText('Browser expense ·').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Fechar caixa', exact: true })).toHaveCount(0);
});

test('administrator receives a completed appointment and closes a separate historical day', async ({ page }, info) => {
  await login(page, 'admin');
  const previous = new Date(); previous.setDate(previous.getDate()-1); if (previous.getDay() === 0) previous.setDate(previous.getDate()-1);
  await page.locator('.agenda-toolbar input[type=date]').fill(previous.toISOString().slice(0,10));
  await page.getByRole('button', { name: 'Registrar pagamento', exact: true }).first().click();
  await page.getByLabel('Desconto (R$)').fill('5.00');
  await page.getByLabel('Comissão (%)').fill('10');
  await page.getByRole('button', { name: 'Registrar pagamento', exact: true }).click();
  await expect(page.getByText('Pagamento registrado no caixa de hoje.', { exact: true })).toBeVisible();
  const closing = new Date(); closing.setDate(closing.getDate()-(info.project.name === 'mobile' ? 11 : 10));
  await page.locator('app-finance .toolbar input[type=date]').fill(closing.toISOString().slice(0,10));
  await page.getByLabel('Dinheiro contado (R$)').fill('0');
  await page.getByRole('checkbox', { name: 'Conferi os valores e quero fechar o caixa.' }).check();
  await page.getByRole('button', { name: 'Fechar caixa', exact: true }).click();
  await expect(page.getByText('Caixa fechado.', { exact: true })).toBeVisible();
});

test('administrator creates a barber account and a closed-day exception', async ({ page }, info) => {
  await login(page, 'admin');
  await page.getByRole('button', { name: 'Configurações', exact: true }).click();
  const username = 'browser-' + info.project.name;
  await page.getByLabel('Nome', { exact: true }).fill('Browser Barber');
  await page.getByLabel('Usuário', { exact: true }).fill(username);
  await page.getByLabel('Senha', { exact: true }).fill('browser-password-123');
  await page.getByLabel('Profissional associado').selectOption({ index: 1 });
  await page.getByRole('button', { name: 'Criar usuário', exact: true }).click();
  await expect(page.getByText('Usuário criado.', { exact: true })).toBeVisible();
  const section = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Feriados, férias e expediente especial' }) });
  await section.getByLabel('Profissional', { exact: true }).selectOption({ index: 1 });
  const date = new Date(); date.setDate(date.getDate()+(info.project.name === 'mobile' ? 11 : 10));
  await section.getByLabel('Data', { exact: true }).fill(date.toISOString().slice(0,10));
  await section.getByLabel('Motivo').fill('Browser holiday');
  await section.getByRole('button', { name: 'Salvar expediente da data' }).click();
  await expect(page.getByText('Expediente especial salvo.', { exact: true })).toBeVisible();
  await expect(section.getByRole('cell', { name: 'Fechado', exact: true }).first()).toBeVisible();
});

test('catalog component preserves service editing and customer history', async ({ page }, info) => {
  await login(page, 'admin');
  await page.locator('nav').getByRole('button', { name: /Serviços/ }).click();
  const section = page.locator('app-catalog');
  await section.getByLabel('Nome', { exact: true }).fill('Browser Service '+info.project.name);
  await section.getByLabel('Preço (R$)').fill('49.90');
  await section.getByRole('button', { name: 'Cadastrar serviço' }).click();
  await expect(section.getByText('Browser Service '+info.project.name, { exact: true })).toBeVisible();
  await page.locator('nav').getByRole('button', { name: /Clientes/ }).click();
  await section.getByRole('button').filter({ hasText: 'Pedro Lima (Demo)' }).click();
  await expect(section.getByText('HISTÓRICO / ATENDIMENTOS')).toBeVisible();
  await expect(section.locator('.appointment')).not.toHaveCount(0);
});
