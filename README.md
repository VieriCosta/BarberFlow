# BarberFlow

Sistema de gestão para barbearia com cadastro de serviços, profissionais e clientes, jornada de trabalho, consulta de horários e agendamento online sem conflitos. O front-end é Angular; a API é Python com FastAPI. O banco usado com Docker é PostgreSQL.

## Requisitos

- Node.js compatível com Angular 22 (22.22.3+, 24.15.0+ ou 26+)
- Docker Compose para API + PostgreSQL **ou** Python 3.13 para desenvolvimento local com SQLite

## Executar

1. Copie `.env.example` para `.env` e defina a senha do PostgreSQL.
2. Na raiz, execute `docker compose up --build -d` para subir API e PostgreSQL.
3. Em `frontend`, execute `npm install` e `npm start`.
4. Abra `http://localhost:4200`. Na tela inicial, escolha **Agendar horário** como cliente ou selecione um barbeiro para entrar na área interna. Se ainda não houver equipe, use **Configurar barbearia**.

A documentação interativa da API fica em `http://localhost:8000/docs`.

Para rodar só a API localmente, instale `backend/requirements.txt`, entre em `backend` e execute `uvicorn app.main:app --reload`. Sem `DATABASE_URL`, ela cria `barberflow.db` em SQLite.

## Fluxo disponível

1. Na primeira entrada, clique em **Configurar barbearia** e cadastre um serviço com preço e duração.
2. O sistema abre **Profissionais** para cadastrar o primeiro barbeiro e associar o serviço. Depois disso, cada barbeiro pode ser escolhido na entrada.
3. Ainda em **Profissionais**, adicione os períodos da jornada ou use **Usar horário padrão** e ajuste antes de salvar. Os horários aparecem no cadastro, na agenda e junto aos serviços atendidos.
4. Em **Agendar horário**, escolha serviço, profissional, data e horário. Informe nome e telefone e confirme.
5. Em **Agenda**, consulte reservas e bloqueios por dia ou semana, com filtro por profissional e resumo do expediente. Inicie, conclua, cancele, marque falta ou reagende um atendimento. Crie reservas no balcão e bloqueie intervalos indisponíveis.
6. Em **Serviços**, veja duração e horários da equipe que realiza cada serviço; em **Profissionais**, veja os horários semanais. Edite ou inative os registros. O sistema impede a inativação quando há reservas futuras.
7. Em **Clientes**, cadastre ou edite uma pessoa e consulte seu histórico. Clientes que agendam online entram automaticamente no cadastro pelo telefone normalizado.

A API valida novamente o horário dentro da transação de reserva ou reagendamento. No PostgreSQL, bloqueia a linha do profissional enquanto verifica conflitos; no SQLite, serializa as escritas. Bloqueios também impedem reservas e desaparecem da disponibilidade pública quando removidos. As reservas guardam preço, duração implícita no horário final e nome do serviço no momento da criação. Todas as datas são tratadas no fuso `America/Fortaleza`, configurável pela variável `BARBERFLOW_TIMEZONE`; o front-end consulta o fuso da API.

## Dados fictícios

Para popular o banco local, execute em `backend`:

```powershell
.\.venv\Scripts\python.exe -m app.seed_demo
```

Com Python e dependências disponíveis no ambiente, também pode usar `python -m app.seed_demo`. No Docker, após atualizar a imagem da API, use `docker compose exec api python -m app.seed_demo` para popular o PostgreSQL.

A carga adiciona 5 serviços, 3 profissionais com jornada de segunda a sábado, 8 clientes, até 10 agendamentos e 3 bloqueios. Os nomes recebem `(Demo)`; os telefones são ilustrativos e os e-mails usam `example.com`. As reservas ativas ficam no próximo dia útil, e o histórico no dia útil anterior. A carga respeita conflitos e preserva cadastros e jornadas existentes. Repetir no mesmo dia não duplica os registros; executar em outro dia pode adicionar exemplos para novas datas. No SQLite, o comando cria um backup antes de alterar o banco. Os dados são inseridos apenas no banco configurado para a execução, sem sincronizar SQLite e PostgreSQL.

## Ajustes de interface e fluxo

O agendamento mostra o horário no resumo e, após reservar, uma confirmação dedicada com data, profissional e valor. Use **Fazer outro agendamento** para iniciar uma nova reserva. A agenda permite navegar pelo dia ou semana anterior/próximo e voltar para **Hoje**. Consultas de agenda, disponibilidade e histórico diferenciam carregamento, falha e resultado vazio. Os cadastros validam os dados antes do envio, e a jornada em edição é preservada durante a atualização dos cadastros. Para retirar todo o expediente de um profissional, remova os períodos e salve a jornada.

## Testes

Em `frontend`, execute `npm test` para verificar os fluxos da interface e `npm run build` para compilar. Em `backend`, execute `pytest -q`. Se o Python local não estiver disponível, na raiz execute `docker build -f backend/Dockerfile.test -t barberflow-test backend` e `docker run --rm barberflow-test`. Os testes cobrem reservas simultâneas, limites da jornada, cadastros, bloqueios, reagendamento, filtros da agenda e transições de status.

## Escopo atual

A escolha de barbeiro identifica apenas o contexto da interface. Não há autenticação: quem acessar a API pode alterar cadastros e agendamentos. O Docker publica a API somente em `127.0.0.1`. Antes de disponibilizar o sistema na internet ou na rede local, implemente login e permissões reais. Pagamentos e relatórios fazem parte das próximas etapas. A tabela de bloqueios é criada automaticamente ao iniciar a API; mudanças futuras de esquema ainda precisam de migrações formais.

Referências de compatibilidade do Angular: [versões suportadas](https://angular.dev/reference/versions) e [estrutura do CLI](https://angular.dev/tools/cli/setup-local).
