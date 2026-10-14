# Operação e recuperação

## Entrada de clientes e cadastro de donos

A página inicial é um diretório de barbearias publicadas. Clientes escolhem o espaço e agendam sem entrar na área interna. Abaixo da lista, **Cadastrar minha barbearia** cria um espaço vazio e uma conta de administrador própria, em uma única transação. O novo espaço começa em configuração e aparece na lista após o dono cadastrar catálogo/jornada e publicar em **Configurações**.

A equipe entra por **Sou da equipe** dentro da barbearia escolhida, por link direto ou pelo código informado pelo administrador. Código e link ficam em **Configurações**. Cada conta pertence a uma barbearia, e a mesma identificação de usuário pode ser usada em espaços diferentes.

Os dados anteriores pertencem à barbearia inicial. Para assumir esse espaço quando ainda não houver administrador, use o formulário de primeiro acesso da equipe com a chave de `.env`. O cadastro público de um novo negócio não usa essa chave. `node scripts/configure-env.cjs` prepara as variáveis de infraestrutura sem mostrar segredos no terminal.

## Migrações

O histórico está em `schema_migrations`. As versões preservam os registros existentes:

| Versão | Alteração |
| --- | --- |
| 1 | Tabelas de acesso, financeiro, auditoria, expediente e notificações; vínculo por `customer_id` e preenchimento do histórico pelo telefone existente |
| 2 | Limites persistentes de login e recuperação de trabalhos interrompidos na fila |
| 3 | Geração de notificação para manter a mesma chave de idempotência durante tentativas de envio |
| 4 | Diretório de barbearias, vínculo dos registros por `shop_id` e unicidade de telefone/usuário/fechamento dentro de cada espaço |

SQLite cria uma cópia antes de mudar de versão. A versão 4 reconstrói tabelas com unicidade global antiga, preservando IDs, dados e relacionamentos. PostgreSQL aplica as alterações em transação, sob um bloqueio exclusivo de migração. O comando `python -m app.migrations` usa o mesmo banco configurado para a API. Uma falha impede a inicialização; verifique o erro e o backup antes de alterar o esquema manualmente.

## Backup PostgreSQL

O serviço `backup` gera dumps em formato custom e usa `pg_restore --list` para verificar o catálogo. Essa verificação não substitui um teste de restauração. Não use `docker compose down -v` se quiser preservar bancos e backups.

Liste os arquivos:

```powershell
docker compose exec backup ls -lh /backups
```

Para copiar um backup para fora do volume, substitua o nome pelo arquivo listado:

```powershell
docker compose cp backup:/backups/barberflow-AAAAMMDD-HHMMSS.dump ./barberflow-backup.dump
```

Restaure primeiro em um **novo banco**, mantendo o original disponível. Exemplo com um banco separado chamado `barberflow_restore`:

```powershell
docker compose exec db createdb -U barberflow barberflow_restore
docker compose cp ./barberflow-backup.dump db:/tmp/barberflow-restore.dump
docker compose exec db pg_restore -U barberflow --exit-on-error --dbname=barberflow_restore /tmp/barberflow-restore.dump
```

Confira cadastros, reservas, pagamentos e integridade antes de apontar a API para o banco restaurado. Faça também uma cópia periódica fora da máquina que hospeda o PostgreSQL.

## Backup SQLite

`python -m app.backup --output backups --keep 14` cria uma cópia consistente e verifica `PRAGMA integrity_check`. Para execução diária contínua, adicione `--interval 86400`. A retenção remove somente os arquivos `barberflow-*.db` no diretório informado.

Para recuperar, pare a API, preserve o banco atual e copie o backup validado para um novo caminho. Configure `DATABASE_URL=sqlite:///./barberflow-restored.db` para abrir a cópia, execute a API e verifique os dados. Mantenha o original até concluir a conferência.

## Notificações

O worker é opcional. Configure um webhook HTTPS ou SMTP e inicie `docker compose --profile notifications up --build -d`. SMTP usa STARTTLS; credenciais permanecem nas variáveis de ambiente.

Payload do webhook:

```json
{
  "notification_id": 1,
  "version": "identificador-da-geracao",
  "kind": "confirmation",
  "appointment_id": 10,
  "shop_id": 1,
  "shop_name": "Nome da barbearia",
  "phone": "telefone-do-cliente",
  "email": "cliente@example.com",
  "message": "Detalhes do atendimento"
}
```

O header `Idempotency-Key` identifica notificação e geração; o provedor deve respeitá-lo. `BARBERFLOW_NOTIFICATION_SECRET`, quando definido, é enviado como bearer token. O worker não segue redirecionamentos.

Os envios podem ficar pendentes, em processamento, enviados, com falha ou cancelados. Trabalhos em processamento há mais de 10 minutos podem ser recuperados. Após uma falha, há novas tentativas com espera crescente, até 5 tentativas. A tela **Configurações** permite repetir falhas de reservas ainda pendentes. Cancelamentos e mudanças de status removem as notificações pendentes; reagendamentos atualizam a geração e o lembrete.

O transporte SMTP pode entregar uma mensagem e falhar antes de confirmar o envio ao worker. Nesse caso, uma tentativa posterior pode duplicar a mensagem. Uma alteração de reserva ocorrida durante um envio já iniciado também pode exigir atualização posterior.

## Caixa

Recebimentos são lançados na data atual, mesmo quando o atendimento ocorreu em outro dia. Despesas seguem a mesma regra. O caixa fechado não recebe novos movimentos. O sistema mantém o fechamento como registro final; não há edição ou exclusão de pagamentos e despesas nesta versão. Comissões representam valores provisionados, sem integração bancária ou repasse automático.

Ao contar o caixa, informe o dinheiro dos movimentos registrados, sem o fundo de troco. Pix, crédito e débito aparecem separados. O painel distingue receita recebida e pendências dos atendimentos da data consultada.

## Revisão das alterações

A branch `feat/barberflow-management` parte do commit que preserva o projeto inicial em `main`. Os commits agrupam autenticação/migrações, agendamento/portal/notificações, financeiro, interface, infraestrutura e testes/documentação. O PR deve apontar para `main`; nenhum merge ou deploy é automático.

## Separação entre barbearias

As rotas internas ficam sob `/api/shops/{shop_id}`. A API valida a sessão nesse espaço e limita consultas, relacionamentos e alterações ao seu `shop_id`. Tokens de reserva também são limitados ao espaço do atendimento. O diretório público exibe apenas perfil e localização dos espaços publicados.

O worker de notificações é um processo de infraestrutura que atende a fila de todos os espaços; não é uma sessão de usuário. Os backups abrangem todo o banco, incluindo todas as barbearias. A carga Demo só atua no espaço inicial.
