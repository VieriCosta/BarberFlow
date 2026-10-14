# BarberFlow

Gestão de barbearia com Angular e FastAPI, PostgreSQL no Docker e SQLite para desenvolvimento local. Inclui agendamento online, área da equipe com login, financeiro, painel de gestão e acesso protegido do cliente à própria reserva.

## Primeira execução

Requisitos: Node.js 24.15.0+, Docker Compose ou Python 3.13.

1. Na raiz, execute `node scripts/configure-env.cjs`. O comando prepara o `.env`, gera os segredos que faltam e preserva credenciais existentes.
2. Execute `docker compose up --build -d`. A API, PostgreSQL e backup diário são iniciados.
3. Em `frontend`, execute `npm ci` e `npm start`.
4. Abra http://localhost:4200. No formulário da equipe, escolha **Primeiro acesso: configurar barbearia**.
5. Use o valor de `BARBERFLOW_BOOTSTRAP_KEY` do seu `.env` e crie o administrador com senha de pelo menos 12 caracteres. A configuração inicial só pode ser usada uma vez.
6. Em **Serviços**, cadastre o catálogo. Em **Profissionais**, cadastre os barbeiros e salve suas jornadas. Em **Configurações**, crie as contas da equipe.

A documentação da API fica em http://localhost:8000/docs. As rotas internas exigem o token retornado pelo login.

### Backend local com SQLite

Em `backend`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --env-file ../.env
```

Sem `DATABASE_URL`, o banco é `backend/barberflow.db`. Dados e reservas existentes são preservados pelas migrações. Linux/macOS: use `.venv/bin/python`.

## Perfis e permissões

| Perfil | Acesso |
| --- | --- |
| Administrador | Agenda, cadastros, usuários, expediente especial, financeiro, fechamento, notificações e auditoria |
| Recepção | Agenda da equipe, clientes, pagamentos, despesas e painel; sem gestão de usuários, catálogo ou fechamento |
| Barbeiro | Própria agenda, reservas de balcão, bloqueios e ações dos próprios atendimentos |
| Cliente | Catálogo público, agendamento e gestão de uma reserva por link protegido |

As permissões são verificadas na API. Sessões duram 8 horas e são revogadas no logout, na troca de senha ou na desativação da conta. Login tem limite persistente de tentativas. Senhas usam scrypt e somente hashes dos tokens ficam no banco.

## Fluxos disponíveis

- **Agendamento:** serviço, profissional, data, horário, nome, telefone e e-mail opcional. A confirmação entrega um link para consultar, cancelar ou reagendar aquela reserva. O token fica no fragmento do link, fora dos parâmetros da URL enviados ao servidor.
- **Portal do cliente:** alteração até 2 horas antes do atendimento, configurável por `BARBERFLOW_CUSTOMER_CHANGE_HOURS`. Reagendamento mantém preço e duração da reserva e valida conflitos novamente.
- **Agenda:** dia ou semana, filtros, grade por horário/profissional e lista de ações. Clique em uma reserva na grade para abrir suas ações. Iniciar, concluir, cancelar, registrar falta, reagendar, reservar no balcão e bloquear intervalos.
- **Expediente:** jornada semanal e exceções por data para feriados, férias ou horários especiais. Uma data sem períodos significa fechado. Reservas existentes impedem alterações que as deixariam fora do expediente.
- **Clientes:** cadastro, busca, observações e histórico ligado por `customer_id`, preservado quando o telefone muda.
- **Financeiro:** recebimento de atendimentos concluídos, dinheiro/Pix/crédito/débito, descontos, comissão percentual e despesas. Atendimento concluído e pagamento recebido são estados distintos. Não é permitido receber a mesma reserva duas vezes.
- **Caixa:** consulta diária e fechamento pelo administrador, com dinheiro contado e diferença. O fechamento impede novos pagamentos ou despesas naquele dia. A contagem considera movimentos registrados, sem fundo de troco. Comissões são provisionadas separadamente das despesas.
- **Painel:** atendimentos, conclusões, faltas, receita recebida, valores pendentes e ocupação por profissional. Recebimentos usam a data do pagamento; pendências usam a data do atendimento.
- **Auditoria:** registra usuário, ação, registro e horário das alterações, incluindo ações do cliente.

A agenda usa `America/Fortaleza`, configurável por `BARBERFLOW_TIMEZONE`. Reservas, reagendamentos, pagamentos e fechamento usam transações e bloqueios compatíveis com PostgreSQL e SQLite.

## Confirmações e lembretes

As reservas criam uma fila persistente de confirmação e lembrete. O envio precisa de um provedor configurado; a aplicação não envia mensagens apenas por receber uma reserva.

Configure no `.env` um webhook HTTPS que receba o payload da fila **ou** SMTP com STARTTLS e remetente válido. Para SMTP, o cliente precisa informar e-mail. Para envio por telefone, o webhook deve integrar o provedor escolhido.

```powershell
docker compose --profile notifications up --build -d
```

Localmente: `python -m app.worker`, com as variáveis de ambiente carregadas. O worker registra tentativas e falhas, tenta novamente até 5 vezes e recupera trabalhos interrompidos. Webhooks recebem uma chave de idempotência estável durante as tentativas. SMTP não oferece essa garantia: uma falha após a entrega pode gerar duplicidade. **Configurações** mostra o estado e permite repetir falhas de reservas ainda pendentes.

## Backup e migrações

O Compose cria um backup PostgreSQL diariamente, mantém arquivos por aproximadamente 14 dias e verifica o catálogo do dump. Os arquivos ficam no volume `barberflow_backups`. Exportação e restauração estão em [docs/OPERATIONS.md](docs/OPERATIONS.md).

Para SQLite, execute em `backend`:

```powershell
.\.venv\Scripts\python.exe -m app.backup --output backups --keep 14 --interval 86400
```

O comando usa a API de backup do SQLite, verifica integridade e mantém os últimos 14 arquivos. Sem `--interval`, faz um único backup.

A API aplica migrações aditivas versionadas na inicialização. SQLite recebe backup antes de uma mudança de versão. PostgreSQL usa bloqueio para impedir migrações simultâneas. Para executar manualmente: `python -m app.migrations`. Não há downgrade destrutivo automático; restaure um backup em outro banco para recuperação.

## Dados fictícios

Execute `python -m app.seed_demo` em `backend`, ou `docker compose exec api python -m app.seed_demo`. A carga cria serviços, profissionais, clientes, reservas e bloqueios marcados como Demo, preservando os dados existentes. Ela não cria contas nem envia notificações para os contatos fictícios.

## Testes

```powershell
# Em backend
.\.venv\Scripts\python.exe -m pytest -q
# Em frontend
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Para PostgreSQL, defina `TEST_DATABASE_URL` para um banco de testes. Cada teste usa um schema isolado, removido ao terminar. Nunca use um banco de produção para testes.

O Playwright inicia API e frontend próprios, com banco temporário e contas exclusivas dos testes. Roda os fluxos em desktop e celular. Portas: 18001 e 14200. `E2E_PYTHON` permite indicar outro executável Python. O GitHub Actions verifica SQLite, PostgreSQL, testes do frontend, build e navegador.

## Organização e PR

- `backend/app`: autenticação, schemas, catálogo, agendamentos, financeiro, expediente, portal, notificações, migrações e backup.
- `frontend/src/app`: componentes de login, cadastros, grade de agenda, painel, financeiro, configurações e reserva do cliente.
- `main`: versão inicial preservada.
- `feat/barberflow-management`: melhorias em commits por etapa; destino do PR é `main`.

Para disponibilizar a aplicação fora da máquina local, configure um domínio com HTTPS e os endereços do frontend em `BARBERFLOW_CORS_ORIGINS`. Tokens de sessão e links de reserva precisam de transporte protegido.

Os componentes usam atualização explícita compatível com o estado atual da aplicação e Angular 22. Referência: [estratégias de detecção de mudanças](https://angular.dev/api/core/ChangeDetectionStrategy).
